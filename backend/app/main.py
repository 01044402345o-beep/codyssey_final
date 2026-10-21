"""Codyssey Final — 최소 백엔드.

문장 생성과 말하기는 Render 의 이 프로세스에 둔다.
POST /itinerary 는 장소 수집만 한다. 문장 팩은 만들지 않는다.
ITINERARY_ENABLED 의 기본값은 꺼짐이고, 공개 배포에서 켜지 않는다.
플래그가 꺼지면 /itinerary 는 바로 itinerary_disabled 를 돌려준다.
/generate 의 itinerary 형제는 그대로다.

로그인은 Firebase Authentication 이다. 화면이 받은 ID 토큰만 확인한다.
로그인한 계정의 진도·복습 목록·말하기 동의와 여행 입력(나라·도시·날짜·학습 시작일)은 /user/state 에 둔다.
장소·문장 본문은 브라우저가 그 입력으로 규칙을 다시 돌려 만든다. Cloud Functions 로 생성 경로를 옮기지 않는다.

  GET  /health       배포·콜드스타트 확인용
  GET  /auth/config  Firebase 웹 설정. 없으면 enabled=false
  GET  /auth/me      Authorization: Bearer <Firebase ID 토큰>
  GET  /user/state   그 토큰 uid 의 진도·복습·동의·여행 입력. 없으면 빈 기록
  PUT  /user/state   같은 기록을 갈아 끼운다. 본문의 uid 는 받지 않는다
  DELETE /user/state 그 기록을 지운다(탈퇴). 계정 삭제는 화면이 deleteUser 로 한다
  POST /account/erase 탈퇴(관리자). 토큰 취소 + 기록 삭제 + 계정 삭제. 서비스 계정 키가 있어야 함
  POST /generate     카테고리 문장 생성 (+ 스키마·규칙 검증 후 재생성). 토큰 불필요
  POST /itinerary    도시 하나의 장소 수집. category_id 없음. 토큰 불필요
  POST /speak-check  발음 오디오 → 피드백 (멀티모달). 토큰 불필요

모델은 고정하지 않고 호출 시점의 사용 가능 목록에서 고르며, AI API 호출은
하나당 최소 30회 시도한다 (app/gemini.py).

GEMINI_API_KEY 가 없으면 목업으로 응답한다. 그래서 키 없이도 배포·시연이 된다.
목업·검증실패 결과는 usable 로 구분되므로, 프론트가 학습 화면에 넣지 않게 막을 수 있다.
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import re
import threading
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, StringConstraints
from starlette.concurrency import run_in_threadpool

from . import firebase_admin
from . import firebase_auth
from . import user_state
from . import evidence
from . import gemini as ai
from . import speech_compare as compare
from . import speech_vad as vad
from . import stt_providers as stt
from . import stt_selftest as selftest
from . import interp
from .agents.facts import (
    FACT_SOURCES_READY,
    collect_facts,
    facts_clause,
    kakao_configured,
)
from .agents.itinerary import (
    collect_itinerary,
    google_maps_configured,
    itinerary_enabled,
)

from .validators import (
    SCHEMA_CHECKER_AVAILABLE,
    has_blocking,
    validate_pack,
)

# main.py 는 backend/app/ 에 있다. 저장소 루트의 agent_contract/ 를 본다.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
CONTRACT_DIR = Path(os.getenv("CONTRACT_DIR") or (REPO_ROOT / "agent_contract"))
CATEGORY_DIR = CONTRACT_DIR / "categories"
SCHEMA_PATH = CONTRACT_DIR / "schema.json"

MAX_AUDIO_BYTES = 8 * 1024 * 1024
MAX_AUDIO_SECONDS = 30

# 호출 제한 (단일 인스턴스 기준)
RATE_LIMIT = int(os.getenv("RATE_LIMIT", "20"))          # 창당 최대 요청 수
RATE_WINDOW = int(os.getenv("RATE_WINDOW", "60"))        # 초
# 앞단 프록시 수. Render 처럼 프록시 뒤에서는 연결 상대(request.client)가 프록시라
# 모든 사용자가 한 IP 로 묶인다. N 이면 X-Forwarded-For 의 뒤에서 N 번째를 사용자 IP 로 본다.
# 앞쪽 값은 사용자가 마음대로 넣을 수 있으므로 쓰지 않는다. 0(기본)은 연결 상대 그대로.
TRUSTED_PROXY_HOPS = max(0, int(os.getenv("TRUSTED_PROXY_HOPS", "0")))

# 1이면 설정 누락(schema.json·jsonschema·카테고리) 상태에서 /generate 를 거부한다.
# 기본 0은 '일단 돌아가게' 두되, /health 가 degraded 로 알린다.
CONFIG_STRICT = os.getenv("CONFIG_STRICT", "0") == "1"

# 시도별 실패 로그(app.gemini)가 Render 로그에 시각과 함께 남도록 한다.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)   # Gemini 요청마다 찍히는 INFO 는 끈다

PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")

@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Silero VAD(onnx)를 미리 불러 첫 녹음이 모델 로드를 기다리지 않게 한다. 실패해도 요청 때 다시 시도.
    def warm() -> None:
        try:
            vad.warmup()
        except Exception:  # noqa: BLE001
            logging.getLogger("app.vad").exception("VAD warmup 실패")
    threading.Thread(target=warm, name="vad-warmup", daemon=True).start()
    selftest.start()
    evidence.install_log_ring()      # 탈퇴 실패 증거에 최근 로그를 담기 위해(설정이 있을 때만)
    yield


app = FastAPI(title="Codyssey Final API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=(os.getenv("ALLOW_ORIGINS") or "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

_hits: dict[str, deque[float]] = defaultdict(deque)
_hits_lock = threading.Lock()



def _masked(ip: str) -> str:
    """로그용. 마지막 자리를 가리고 사설·공인만 붙인다(IP 는 개인정보)."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return "?"
    kind = "공인" if addr.is_global else "사설"
    head = ".".join(ip.split(".")[:3]) + ".x" if addr.version == 4 else ":".join(ip.split(":")[:3]) + ":…"
    return f"{head}({kind})"


_proxy_logged = False


def _log_proxy_chain_once(peer: str, xff: str) -> None:
    """TRUSTED_PROXY_HOPS 를 정할 근거. 프로세스마다 X-Forwarded-For 가 붙은 첫 요청 한 번만 남긴다.

    내 공인 IP 가 체인 끝에서 몇 번째인지가 TRUSTED_PROXY_HOPS 값이다 (docs/deploy/DEPLOY_RUNBOOK.md F14).
    연결 상대는 uvicorn 이 이미 바꾼 값일 수 있다(연결이 127.0.0.1 에서 오면 X-Forwarded-For 를 반영).
    """
    global _proxy_logged
    if _proxy_logged or not xff:
        return
    _proxy_logged = True
    chain = [_masked(h.strip()) for h in xff.split(",") if h.strip()]
    logging.getLogger("app.ratelimit").info(
        "프록시 확인: 연결 상대=%s, X-Forwarded-For=%s, TRUSTED_PROXY_HOPS=%d",
        _masked(peer), " , ".join(chain) or "(없음)", TRUSTED_PROXY_HOPS)


def client_ip(request: Request) -> str:
    """속도 제한용 사용자 IP. TRUSTED_PROXY_HOPS 설명 참고.

    X-Forwarded-For 가 프록시 수보다 짧으면 연결 상대를 쓴다(여러 사용자가 묶여 더 엄격해지는 쪽).
    """
    peer = request.client.host if request.client else "unknown"
    if TRUSTED_PROXY_HOPS == 0:
        return peer
    chain = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
    return chain[-TRUSTED_PROXY_HOPS] if len(chain) >= TRUSTED_PROXY_HOPS else peer


@app.middleware("http")
async def proxy_chain_probe(request: Request, call_next: Any) -> Any:
    """/health 나 첫 화면만 열어도 프록시 구성이 로그에 남게 모든 요청에서 본다(기록은 한 번)."""
    if not _proxy_logged:
        _log_proxy_chain_once(request.client.host if request.client else "unknown",
                              request.headers.get("x-forwarded-for", ""))
    return await call_next(request)


def rate_limit(request: Request) -> None:
    """IP 기준 슬라이딩 윈도. 프로세스 메모리라 인스턴스가 늘면 약해진다 — 임시 방어."""
    ip = client_ip(request)
    # /generate 는 동기 함수라 스레드풀에서 동시에 들어온다. 정리 중 순회와 추가가 겹치지 않게 잠근다.
    with _hits_lock:
        now = time.time()
        if len(_hits) > 10_000:         # IP 별로 나뉘면 키가 쌓인다. 창이 지난 IP 는 버린다.
            for k in [k for k, v in _hits.items() if not v or now - v[-1] > RATE_WINDOW]:
                del _hits[k]
        q = _hits[ip]
        while q and now - q[0] > RATE_WINDOW:
            q.popleft()
        if len(q) >= RATE_LIMIT:
            raise HTTPException(status_code=429, detail="요청이 너무 많습니다. 잠시 후 다시 시도해 주세요.")
        q.append(now)


# ---------------------------------------------------------------- 요청 모델

class Place(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    place_type: str | None = Field(default=None, max_length=40)


# 계약의 id 형식(schema.json 의 situation_id 와 같다). category_id 는 파일 경로가 되므로 '../' 같은 값을 막는다.
ContractId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$", max_length=64)]


class GenerateRequest(BaseModel):
    category_id: ContractId = Field(max_length=40)
    city: str = Field(default="New York", min_length=1, max_length=80)
    places: list[Place] = Field(default_factory=list, max_length=20)
    # 항목마다 형식·길이를 제한한다. 프롬프트에 들어가고 Gemini 호출은 최소 30회라 긴 문자열은 비용이 된다.
    weak_expressions: list[ContractId] = Field(default_factory=list, max_length=20)
    # 플래그가 꺼지면 읽지 않는다. 문장 프롬프트에 넣지 않는다.
    # 범위가 틀려도 요청 전체를 422로 죽이지 않고, 일정 형제만 bad_date 가 된다.
    days: int | None = None
    start_date: str | None = Field(default=None, max_length=10)
    itinerary_kinds: list[str] = Field(default_factory=list, max_length=4)


class ItineraryRequest(BaseModel):
    """문장 팩 없이 도시 하나의 장소만 묻는다. 날짜가 범위를 벗어나도 422로 죽이지 않는다."""

    city: str = Field(min_length=1, max_length=80)
    days: int | None = None
    start_date: str | None = Field(default=None, max_length=10)
    itinerary_kinds: list[str] = Field(default_factory=list, max_length=4)


class WithdrawReport(BaseModel):
    """화면이 보내는 탈퇴 불일치 보고. 개인정보·토큰은 담지 않는다(상태 코드만)."""

    reason: str = Field(default="", max_length=200)
    screen: str = Field(default="", max_length=40)
    has_account: bool = False
    server_said_erased: bool = False
    note: str = Field(default="", max_length=500)


# ---------------------------------------------------------------- 설정 로드

@lru_cache(maxsize=32)
def load_category(category_id: str) -> dict[str, Any]:
    path = CATEGORY_DIR / f"{category_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"unknown category: {category_id}")
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_schema() -> dict[str, Any] | None:
    try:
        return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def list_categories() -> list[str]:
    return sorted(p.stem for p in CATEGORY_DIR.glob("*.json"))


def situation_index() -> dict[str, list[str]]:
    """카테고리 -> situation_id 목록. 프론트가 유효한 weak id 를 알 수 있게 노출한다."""
    out: dict[str, list[str]] = {}
    for cid in list_categories():
        try:
            out[cid] = [
                s.get("situation_id")
                for s in load_category(cid).get("situations", [])
                if isinstance(s, dict)
            ]
        except Exception:  # noqa: BLE001
            out[cid] = []
    return out


def config_problems() -> list[str]:
    """설정 누락을 조용히 넘기지 않는다. 구조 검증이 꺼진 채 돌면 '검증했다'고 말할 수 없다."""
    problems: list[str] = []
    if not SCHEMA_PATH.exists():
        problems.append("agent_contract/schema.json 이 없습니다 — 구조 검증이 비활성입니다.")
    if not SCHEMA_CHECKER_AVAILABLE:
        problems.append("jsonschema 가 설치되지 않았습니다 — 구조 검증이 비활성입니다.")
    if not list_categories():
        problems.append("categories/*.json 이 없습니다 — 생성할 카테고리가 없습니다.")
    return problems


def check_place_types(cfg: dict[str, Any], req: GenerateRequest) -> None:
    """장소 종류는 계약의 place_types 중 하나여야 한다(생략은 허용).

    맛집 카테고리에 hotel 을 보내는 식의 잘못된 짝을 조용히 생성하지 않는다.
    place_type 은 프롬프트에 그대로 들어가므로 허용 목록 밖의 문자열을 받지 않는다.
    """
    allowed = {str(t).strip().lower() for t in cfg.get("place_types") or []}
    bad = sorted({p.place_type for p in req.places
                  if p.place_type is not None and p.place_type.strip().lower() not in allowed})
    if bad:
        raise HTTPException(
            status_code=422,
            detail={"message": f"{cfg['category_id']} 카테고리에서 쓸 수 없는 장소 종류입니다.",
                    "place_types": bad, "allowed": sorted(allowed)},
        )


def build_prompt(cfg: dict[str, Any], req: GenerateRequest, facts: dict[str, Any] | None = None) -> str:
    """system_prompt 의 {키} 를 rules 의 같은 키 값으로 치환한다."""
    rules = cfg.get("rules", {})
    body = PLACEHOLDER.sub(
        lambda m: str(rules[m.group(1)]) if m.group(1) in rules else m.group(0),
        cfg.get("system_prompt", ""),
    )
    mapping = {s.get("situation_id"): s for s in cfg.get("situations", []) if isinstance(s, dict)}
    # 계약에 없는 id 는 프롬프트에 넣지 않는다(검증기가 weak_unknown_situation 경고로 따로 알린다).
    weak_spec = [
        {"situation_id": w, "situation": mapping[w].get("situation"),
         "required_keywords": mapping[w].get("required_keywords")}
        for w in req.weak_expressions if w in mapping
    ]
    payload = {
        "category_id": cfg["category_id"],
        "city": req.city,
        "places": [p.model_dump() for p in req.places],
        "situations": cfg.get("situations", []),
        "weak_expressions": weak_spec,
        "rules": rules,
    }
    return (
        f"{body}\n\nINPUT:\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
        f"\n\nOUTPUT JSON SCHEMA:\n{json.dumps(load_schema(), ensure_ascii=False)}"
        f"\n\nReturn JSON only."
        + (facts_clause(facts) if facts is not None else "")
    )


def mock_pack(cfg: dict[str, Any], req: GenerateRequest) -> dict[str, Any]:
    """키 없이도 시연되도록 설정의 good_examples 를 그대로 돌려준다.

    주의: 여기서 취약 표현 태그를 임의로 붙이지 않는다. 태그를 조작하면
    '반영됐다'는 증거를 위조하는 것이 된다. 반영 여부는 검증기가
    weak_expressions.json 의 상황·키워드로 판단한다.

    예시의 place 는 빼고 보낸다. 예시는 사용자가 고른 장소와 무관한데, 화면(buildPools)은 place 가
    고른 장소 이름과 다르면 문장을 버린다. place 가 없으면 도시 공통 문장으로 쓴다.
    (예시 place 를 'Katz's Delicatessen' → 'A local restaurant' 로 바꾼 ae4f9a9 뒤 샘플이 0개가 됐다.)
    """
    default_type = (cfg.get("place_types") or [None])[0]
    sentences = []
    for ex in cfg.get("good_examples", []):
        s = dict(ex)
        s.pop("place", None)
        s.setdefault("place_type", default_type)
        sentences.append(s)
    return {"category_id": cfg["category_id"], "city": req.city, "sentences": sentences}


def parse_json_object(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in model output")
    return json.loads(text[start : end + 1])


class BlockedResult(Exception):
    """응답은 왔지만 block 이슈가 남음 — 실패한 시도로 세고 다시 생성한다."""


def usability(issues: list[dict[str, Any]], mock: bool, degraded: bool) -> str:
    """프론트가 이 결과를 학습 화면에 넣어도 되는지 한 값으로 알려준다.

    ok       — 검증 통과한 실제 AI 결과. 정상 표시
    sample   — 검수된 샘플(목업). '샘플' 표시하고 제공
    rejected — 검증 실패. 학습 화면에 넣지 않는다
    """
    if has_blocking(issues):
        return "rejected"
    if degraded:
        return "rejected"
    if mock:
        return "sample"
    return "ok"


# ---------------------------------------------------------------- 엔드포인트

@app.get("/health")
def health() -> dict[str, Any]:
    problems = config_problems()
    return {
        # 설정이 덜 갖춰지면 degraded — 배포 직후 이 값을 먼저 보게 된다
        "status": "ok" if not problems else "degraded",
        "config_problems": problems,
        "config_strict": CONFIG_STRICT,
        "schema_checker": SCHEMA_CHECKER_AVAILABLE,
        # 모델은 고정하지 않는다. 마지막으로 받은 목록(첫 AI 호출 전에는 null)만 보여준다.
        "model_selection": "dynamic",
        "models": ai.cached_models(),
        "preferred_model": os.getenv("GEMINI_MODEL") or None,
        "min_attempts": ai.min_attempts(),
        "model_health": ai.model_health(),
        "vad": "silero (faster-whisper), min_silence 500ms, pad 200ms",
        "stt_providers": {pid: bool(stt.api_key(pid)) for pid in stt.ORDER},
        "speech_detectors": ["silero (faster-whisper)", "pyannote segmentation-3.0 (local onnx)"],
        "cross_validation_ready": bool(stt.configured_primary() and stt.api_key(stt.CHECKER)),
        "stt_models": stt.cached_models(),
        "stt_selftest": selftest.status(),
        "has_api_key": bool(os.getenv("GEMINI_API_KEY")),
        "firebase_auth": firebase_auth.configured(),
        # 탈퇴 관리자 경로(서비스 계정)를 쓸 수 있는지만 알린다. 키 값은 노출하지 않는다.
        "admin_erase": firebase_admin.configured(),
        # 증거 봉인 공개키의 지문·세대(공개 정보). 핀 검증(.github/workflows/verify-key-pin.yml)이 이 값을 본다.
        "evidence": evidence.health_block(),
        # 사실 경로의 구글 장소 검색은 붙이지 않았다. google_places 는 그 의미로 남긴다.
        # 일정 플래그와 키는 호출 때마다 읽는다. 임포트 때 고정하지 않는다.
        "itinerary_enabled": itinerary_enabled(),
        "fact_agents": {
            "kakao": kakao_configured(),
            "osm": "no-key",
            "google_places": False,
            # False 면 키가 있어도 사실 경로의 외부 호출이 0회다. facts.py 의 FACT_SOURCES_READY.
            "sources_ready": FACT_SOURCES_READY,
            "google_places_configured": google_maps_configured(),
            "itinerary_calling": itinerary_enabled() and google_maps_configured(),
        },
        # 배포된 코드가 어느 커밋인지 응답 한 번으로 알 수 있게 한다. Render 가 빌드·런타임에 주는 기본 환경변수이고,
        # 로컬 실행처럼 값이 없으면 null 이다. (SHA 는 비밀이 아니다.)
        "deploy": {
            "commit": os.getenv("RENDER_GIT_COMMIT") or None,
            "branch": os.getenv("RENDER_GIT_BRANCH") or None,
            "repo": os.getenv("RENDER_GIT_REPO_SLUG") or None,
        },
        "contract_dir": str(CONTRACT_DIR),
        "categories": list_categories(),
        "situations": situation_index(),
        "rate_limit": f"{RATE_LIMIT}/{RATE_WINDOW}s",
    }


class _Timer:
    """요청 한 건의 단계별 소요 시간(ms). 응답의 timing_ms 로 내보낸다 — 어디서 시간이 쓰이는지 숫자로 보려는 것이다.
    mark(name) 은 직전 mark(또는 시작) 이후 경과 시간을 name 에 기록한다."""

    def __init__(self) -> None:
        self.t0 = self.last = time.perf_counter()
        self.stages: dict[str, int] = {}

    def mark(self, name: str) -> None:
        now = time.perf_counter()
        self.stages[name] = round((now - self.last) * 1000)
        self.last = now

    def result(self) -> dict[str, int]:
        return {**self.stages, "total": round((time.perf_counter() - self.t0) * 1000)}


@app.post("/generate")
def generate(req: GenerateRequest, request: Request) -> dict[str, Any]:
    """처리 시간과 생각 예산 설정을 붙인다 — 속도 개선 전후를 같은 응답으로 비교하려고.
    elapsed_ms: 전체(ms). timing_ms.attempt_ms: 시도별 {model 호출 ms, 검증 ms, 통과 여부} — 재시도가 지연의 주범인지 본다."""
    t = _Timer()
    res = _generate(req, request)
    res["timing_ms"] = {**t.result(), "attempt_ms": res.pop("attempt_ms", [])}
    res["elapsed_ms"] = res["timing_ms"]["total"]
    res["thinking_budget"] = (os.getenv("GEMINI_THINKING_BUDGET") or "").strip() or None
    return res


@app.post("/itinerary")
def post_itinerary(req: ItineraryRequest, request: Request) -> dict[str, Any]:
    """장소 수집만 한다. 문장 생성은 호출하지 않는다.

    플래그가 꺼져 있으면 collect_itinerary 가 Places 와 Gemini 를 부르기 전에 돌아온다.
    """
    rate_limit(request)
    try:
        return collect_itinerary(req)
    except Exception as exc:  # noqa: BLE001 — 수집 실패는 화면이 예시로 돌아갈 수 있게 unavailable
        logging.getLogger("app.itinerary").warning("itinerary error %s", type(exc).__name__)
        return {"status": "unavailable", "reason": "itinerary_error"}


def _generate(req: GenerateRequest, request: Request) -> dict[str, Any]:
    rate_limit(request)
    if CONFIG_STRICT and config_problems():
        raise HTTPException(
            status_code=503,
            detail={"message": "설정이 갖춰지지 않아 생성을 거부했습니다.", "problems": config_problems()},
        )
    cfg = load_category(req.category_id)
    check_place_types(cfg, req)
    schema = load_schema()
    facts = collect_facts(
        category_id=req.category_id,
        city=req.city,
        places=[p.model_dump() for p in req.places],
        situation_ids=[
            s.get("situation_id")
            for s in cfg.get("situations", [])
            if isinstance(s, dict) and isinstance(s.get("situation_id"), str)
        ],
    )
    # 일정은 문장 팩 결과에 의존하지 않는다. 겹치면 벽시계는 합이 아니라 큰 쪽이다.
    box: dict[str, Any] = {}

    def _itinerary_side() -> None:
        try:
            box["itinerary"] = collect_itinerary(req)
        except Exception as exc:  # noqa: BLE001 — 일정 실패가 문장 응답을 지우면 안 된다
            logging.getLogger("app.itinerary").warning("itinerary error %s", type(exc).__name__)
            box["itinerary"] = {"status": "unavailable", "reason": "itinerary_error"}

    th = threading.Thread(target=_itinerary_side, name="itinerary")
    th.start()
    try:
        body = _generate_sentences(req, cfg, schema, facts)
    finally:
        th.join()
    body["itinerary"] = box.get("itinerary") or {"status": "unavailable", "reason": "itinerary_error"}
    return body


def _generate_sentences(
    req: GenerateRequest,
    cfg: dict[str, Any],
    schema: dict[str, Any] | None,
    facts: dict[str, Any],
) -> dict[str, Any]:
    if not os.getenv("GEMINI_API_KEY"):
        pack = mock_pack(cfg, req)
        try:
            issues = validate_pack(pack, cfg, req.weak_expressions, schema)
        except Exception as exc:  # noqa: BLE001 — 검증기 버그가 요청을 죽이지 않게
            issues = [{"severity": "warn", "code": "validator_error",
                       "detail": f"{type(exc).__name__}: {exc}"}]
        return {
            "pack": pack,
            "issues": issues,
            "attempts": 0,
            "mock": True,
            "usable": usability(issues, True, False),
            "facts": facts,
        }

    prompt = build_prompt(cfg, req, facts)
    state: dict[str, Any] = {"last_error": "", "last_pack": None, "last_issues": [], "attempt_ms": []}

    def once(client: Any, model: str, attempt: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        src = prompt if attempt == 1 else (
            prompt + f"\n\nPrevious attempt was rejected: {state['last_error']}\nFix it and return JSON only."
        )
        t_call = time.perf_counter()
        rec: dict[str, Any] = {"model": model, "call_ms": None, "validate_ms": None, "ok": False}
        state["attempt_ms"].append(rec)
        try:
            raw = ai.generate_text(client, model, src, temperature=0.7, max_output_tokens=8192)
            rec["call_ms"] = round((time.perf_counter() - t_call) * 1000)
            pack = parse_json_object(raw)
        except Exception as exc:
            if rec["call_ms"] is None:
                rec["call_ms"] = round((time.perf_counter() - t_call) * 1000)   # 실패(타임아웃 등)까지 걸린 시간
            state["last_error"] = f"{type(exc).__name__}: {exc}"
            raise

        # 검증기 호출도 시도 안에 둔다. 검증기 버그가 500 을 내면 재시도가 무의미해진다.
        t_val = time.perf_counter()
        try:
            issues = validate_pack(pack, cfg, req.weak_expressions, schema)
            rec["validate_ms"] = round((time.perf_counter() - t_val) * 1000)
        except Exception as exc:
            state["last_error"] = f"validator error: {type(exc).__name__}: {exc}"
            raise

        state["last_pack"], state["last_issues"] = pack, issues
        rec["ok"] = not has_blocking(issues)
        if has_blocking(issues):
            state["last_error"] = json.dumps(
                [i for i in issues if i["severity"] == "block"], ensure_ascii=False
            )
            raise BlockedResult(state["last_error"])
        return pack, issues

    try:
        res = ai.run("generate", once)
    except ai.AttemptsExhausted as exc:
        # 최소 시도 횟수를 다 채워도 block 이 남으면 목업으로 대체한다. usable="rejected" 이므로
        # 프론트는 이 결과를 학습 화면에 넣으면 안 된다는 것을 알 수 있다.
        last_pack, last_issues = state["last_pack"], state["last_issues"]
        fallback = mock_pack(cfg, req)
        if last_issues:
            final_issues = last_issues
        else:
            try:
                final_issues = validate_pack(fallback, cfg, req.weak_expressions, schema)
            except Exception as vexc:  # noqa: BLE001
                final_issues = [{"severity": "block", "code": "validator_error",
                                 "detail": f"{type(vexc).__name__}: {vexc}"}]
        return {
            "pack": last_pack or fallback,
            "issues": final_issues,
            # 모델 목록 조회에서 실패했으면 생성 호출은 0회다. failed_at 으로 구분한다.
            "attempts": exc.attempts if exc.what == "generate" else 0,
            "failed_at": exc.what,
            "failures": exc.failures,
            "mock": last_pack is None,
            "degraded": True,
            "usable": "rejected",
            "error": state["last_error"] or exc.last_error,
            "attempt_ms": state["attempt_ms"],
            "facts": facts,
        }

    pack, issues = res.value
    return {
        "pack": pack, "issues": issues, "attempts": res.attempts, "model": res.model,
        "failures": res.failures,   # 성공 전에 실패한 시도들 (원인 진단용)
        "mock": False, "usable": "ok",
        "attempt_ms": state["attempt_ms"],
        "facts": facts,
    }


# ---------------------------------------------------------------- 말하기 판정
# 원칙: AI 에게는 최소 권한만 준다 (docs/research/speak-hallucination.md).
#   1) 말소리 여부는 Silero 신경망 VAD 가 정한다(데시벨 아님). 말이 없으면 외부 API 를 부르지 않는다.
#   2) 전사는 전용 STT(Groq Whisper 등, app/stt_providers.py)가 하고, 목표 문장을 모른다.
#      목표 문장을 함께 준 LLM 은 무음에도 목표 문장을 들었다고 지어냈다(배포 실측 10/10, 95~100점).
#   3) 환각 세그먼트 제거·점수·빠진 단어는 코드가 정한다 (app/speech_compare.py).
#   4) 피드백 AI 는 오디오 없이 코드가 낸 비교 결과만 받아 문장을 쓴다. 점수는 바꿀 수 없다.

FEEDBACK_PROMPT = (
    "You are a friendly English speaking coach for Korean travelers.\n"
    "A learner practiced saying the TARGET sentence in the given SITUATION. Two independent speech recognizers "
    "(not you) transcribed what they said as HEARD and HEARD_BY_SECOND_RECOGNIZER, and code compared them with "
    "the TARGET word by word (DIFF). Only words that BOTH recognizers heard count as correct. "
    "The SCORE was computed by code; you cannot change it and must not output a score.\n"
    "Base your feedback ONLY on the TARGET, the two HEARD texts and DIFF below. You did not hear the audio, so do not "
    "comment on accent, intonation or sounds that are not visible in the DIFF.\n"
    "Write in Korean:\n"
    '- "fix_one": the single most useful thing to fix next time (one sentence). If nothing differs, '
    "praise briefly and suggest one natural variation useful in this situation.\n"
    '- "tip": one short practical tip for using this sentence in this situation.\n'
    'Return JSON only: {"fix_one": "...", "tip": "..."}\n\n'
)


def feedback_input(situation: str, target: str, heard: str, diff: dict[str, Any], second_heard: str = "") -> str:
    facts = {
        "SITUATION": situation or "(unknown)",
        "TARGET": target,
        "HEARD": heard,
        "HEARD_BY_SECOND_RECOGNIZER": second_heard,
        "SCORE": diff["score"],
        "DIFF": {k: diff[k] for k in ("missing", "extra", "replaced")},
    }
    return FEEDBACK_PROMPT + json.dumps(facts, ensure_ascii=False, indent=2)


def _run_parallel(tasks: dict[str, Any]) -> dict[str, Any]:
    """여러 외부 AI 호출을 동시에 돌린다. 예외도 값으로 돌려준다(어느 쪽이 실패했는지 판정에 쓴다)."""
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=len(tasks)) as ex:
        futures = {k: ex.submit(fn) for k, fn in tasks.items()}
        out: dict[str, Any] = {}
        for k, f in futures.items():
            try:
                out[k] = f.result()
            except Exception as exc:  # noqa: BLE001
                out[k] = exc
        return out


LIMITED_REASON = "음성 확인이 제한되어 점수와 자동 복습 저장을 제공하지 않습니다. 다시 녹음해 보세요."


def limited(heard: str, **extra: Any) -> dict[str, Any]:
    """교차검증을 못 했지만 1차 전사문은 있는 경우(사용자 결정, 2026-10-10).

    서비스는 계속 쓰게 하되, 검증하지 못한 결과를 검증된 평가처럼 주지 않는다.
    들린 문장만 보여 주고 점수·피드백은 만들지 않는다. score 가 null 이라 화면은 자동 저장하지 않고
    사용자에게 저장할지 묻는다(mockup/ai.js weakDecision → 'ask').
    """
    return {"usable": True, "limited": True, "cross_validated": False, "reason": LIMITED_REASON,
            "score": None, "heard": heard, "issues": [], "fix_one": "", "tip": "",
            "failed_at": "cross_validation", **extra}


def no_speech(reason: str, **extra: Any) -> dict[str, Any]:
    """말이 없거나 받아쓰기에 실패한 경우. 점수·피드백을 만들지 않는다."""
    return {"usable": False, "reason": reason, "score": None, "heard": "", "issues": [],
            "fix_one": "", "tip": "", **extra}


@app.post("/speak-check")
async def speak_check(
    request: Request,
    target: str = Form(..., max_length=200),
    file: UploadFile = File(...),
    situation: str = Form("", max_length=120),
) -> dict[str, Any]:
    t = _Timer()
    res = await _speak_check(request, target, file, situation, t)
    res["timing_ms"] = t.result()   # read·decode·silero·pyannote·stt(병렬 중 느린 쪽)·feedback·total. 거부 응답에도 들어간다
    return res


async def _speak_check(request: Request, target: str, file: UploadFile, situation: str, t: _Timer) -> dict[str, Any]:
    rate_limit(request)

    # 상한 + 1 바이트까지만 읽는다. 큰 업로드를 통째로 메모리에 올리지 않는다.
    audio = await file.read(MAX_AUDIO_BYTES + 1)
    t.mark("read")
    if not audio:
        raise HTTPException(status_code=400, detail="빈 오디오입니다. 다시 녹음해 주세요.")
    if len(audio) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="오디오가 너무 큽니다 (최대 8MB).")

    # 형식 검사는 목업 응답보다 먼저 한다. 키가 없어도 잘못된 입력은 잘못된 입력이다.
    mime = (file.content_type or "audio/webm").split(";")[0].strip() or "audio/webm"
    if not mime.startswith("audio/"):
        raise HTTPException(status_code=415, detail=f"지원하지 않는 형식입니다: {mime}")

    # 1) 말소리 검출 — 키가 없어도 동작한다. 말이 없으면 여기서 끝(외부 API 0회).
    # 디코딩은 CPU 작업이라 스레드풀에서 한다. 이벤트 루프에서 하면 그동안 다른 요청(/health 포함)이 멈춘다.
    try:
        samples = await run_in_threadpool(vad.decode, audio)
    except vad.AudioDecodeError:
        raise HTTPException(status_code=400, detail="녹음 파일을 읽을 수 없습니다. 다시 녹음해 주세요.")
    t.mark("decode")
    # 8MB 는 압축 녹음이면 30분이 넘는다. 길이로 다시 막는다(화면은 15초에서 멈춘다).
    # 전사 비용은 오디오 길이에 비례하므로 외부 AI 를 부르기 전에 거절한다.
    if len(samples) > MAX_AUDIO_SECONDS * vad.SAMPLE_RATE:
        raise HTTPException(status_code=413, detail=f"녹음이 너무 깁니다 (최대 {MAX_AUDIO_SECONDS}초).")
    speech = await run_in_threadpool(vad.detect, samples)
    t.mark("silero")
    if not speech.has_speech:
        return no_speech("음성이 인식되지 않았습니다. 다시 녹음해 주세요.", vad=speech.summary())
    # 두 번째 말소리 검출기(로컬 pyannote, Silero 와 다른 신경망). 둘 다 말소리를 찾아야 외부 AI 를 부른다.
    speech2 = await run_in_threadpool(vad.detect_pyannote, samples)
    t.mark("pyannote")
    detector = speech2.summary("pyannote segmentation-3.0 (local onnx)")
    if not speech2.has_speech:
        return no_speech("음성이 인식되지 않았습니다. 다시 녹음해 주세요. (두 번째 말소리 검출기가 말소리를 찾지 못함)",
                         vad=speech.summary(), cross_validation={"detector": detector})

    if not stt.configured():
        return {
            "usable": False,
            "reason": "전사 API 키가 없어 목업으로 응답했습니다.",
            "score": None, "heard": "", "issues": [], "fix_one": "", "tip": "",
            "mock": True, "vad": speech.summary(),
        }

    # 2) 말소리 구간만, 목표 문장 없이 두 전사 AI 에 동시에 보낸다(지연 시간 = 느린 쪽).
    #    1차 전사(Whisper 계열 체인) · 교차검증 전사(AssemblyAI). 각각 최소 30회.
    #    교차검증 키가 없으면 1차 전사만 하고 제한 모드로 답한다(점수 없음).
    wav = vad.speech_only_wav(samples, speech)
    tasks: dict[str, Any] = {"primary": lambda: stt.transcribe(wav)}
    if stt.api_key(stt.CHECKER):
        tasks["checker"] = lambda: stt.transcribe_with(stt.CHECKER, wav)
    jobs = await run_in_threadpool(_run_parallel, tasks)
    t.mark("stt")   # 두 전사는 병렬이라 느린 쪽 시간이다
    base = {"vad": speech.summary()}
    if isinstance(jobs["primary"], Exception):
        exc = jobs["primary"]
        # 평가 실패는 점수·약점으로 저장되면 안 된다.
        return no_speech("채점 중 오류가 발생했습니다. 다시 시도해 주세요.", failed_at="stt",
                         error=getattr(exc, "last_error", str(exc)), attempts=getattr(exc, "attempts", 0),
                         failures=getattr(exc, "failures", []), **base)
    tr = jobs["primary"]
    base.update(attempts=tr.attempts, model=tr.model, failures=tr.failures, stt=tr.meta())
    ck = jobs.get("checker")
    if ck is None or isinstance(ck, Exception):
        # 교차검증 불가 → 제한 모드. 1차 전사도 환각 세그먼트를 걸러 비면 '말소리 없음'과 같게 다룬다.
        heard, dropped = compare.filter_segments(tr.text, tr.segments)
        base["dropped_segments"] = dropped
        cv: dict[str, Any] = {"detector": detector}
        if ck is None:
            cv.update(required=[stt.CHECKER], missing_keys=[stt.CHECKER])
        else:
            cv["checker"] = {"error": getattr(ck, "last_error", str(ck)), "attempts": getattr(ck, "attempts", 0)}
        if compare.is_placeholder(heard):
            return no_speech("음성이 인식되지 않았습니다. 다시 녹음해 주세요.", failed_at="cross_validation",
                             heard_raw=tr.text, cross_validation=cv, **base)
        return limited(heard, cross_validation=cv, **base)
    base["cross_validation"] = {"checker": ck.meta(), "detector": detector}

    # 3) 판정 — 모두 코드가 한다. 두 전사(Whisper 계열·AssemblyAI) 모두 환각 세그먼트 제거 뒤 비어 있지 않아야 한다.
    heard, dropped = compare.filter_segments(tr.text, tr.segments)
    heard_ck, dropped_ck = compare.filter_segments(ck.text, ck.segments)
    base["dropped_segments"] = dropped + [dict(d, provider=stt.CHECKER) for d in dropped_ck]
    if compare.is_placeholder(heard) or compare.is_placeholder(heard_ck):
        return no_speech("음성이 인식되지 않았습니다. 다시 녹음해 주세요.",
                         heard_raw=tr.text, heard_checker_raw=ck.text, **base)
    meta = base
    # 두 전사 모두에서 들린 목표 단어만 점수가 된다.
    diff = compare.compare_consensus(target, heard, heard_ck)
    t.mark("compare")
    issues = [{"word": w, "note": "빠짐"} for w in diff["missing"]] + \
             [{"word": a, "note": f"'{b}'(으)로 들림"} for a, b in diff["replaced"]] + \
             [{"word": w, "note": "목표 문장에 없음"} for w in diff["extra"]]

    # 3) 피드백 문장 — 오디오 없이 비교 결과만 준다. 응답의 다른 키(score 등)는 버린다.
    prompt = feedback_input(situation, target, heard, diff, heard_ck)

    def write_feedback(client: Any, model: str, attempt: int) -> tuple[str, str]:
        data = parse_json_object(ai.generate_text(client, model, prompt, temperature=0.4))
        fix_one, tip = data.get("fix_one"), data.get("tip")
        if not (isinstance(fix_one, str) and fix_one.strip() and isinstance(tip, str)):
            raise ValueError("fix_one/tip 형식 오류")
        return fix_one.strip(), tip.strip()

    if not os.getenv("GEMINI_API_KEY"):
        fix_one, tip = compare.template_feedback(diff)
        feedback = {"source": "template", "attempts": 0, "error": "GEMINI_API_KEY 없음"}
    else:
        try:
            fb = await run_in_threadpool(ai.run, "speak-feedback", write_feedback)
            (fix_one, tip), feedback = fb.value, {"source": "ai", "attempts": fb.attempts, "model": fb.model}
        except ai.AttemptsExhausted as exc:
            # 점수는 코드가 이미 정했으므로 결과는 쓸 수 있다. 문구만 사실 기반 문장 틀로 대신한다.
            fix_one, tip = compare.template_feedback(diff)
            feedback = {"source": "template", "attempts": exc.attempts, "error": exc.last_error}
    t.mark("feedback")

    return {
        "usable": True,
        "cross_validated": True,
        "score": diff["score"],
        "score_kind": "word_match_consensus",   # 발음 점수가 아니라, 두 전사 모두에서 들린 단어 일치율
        "heard": heard,
        "heard_checker": heard_ck,
        "issues": issues,
        "diff": diff,
        "fix_one": fix_one,
        "tip": tip,
        "feedback": feedback,
        **meta,
    }


@app.websocket("/interp/stream")
async def interp_stream(ws: WebSocket) -> None:
    """실시간 통역: 브라우저 마이크 PCM 을 제공자에게 중계하고 자막·음성을 돌려준다(서버는 저장하지 않는다)."""
    await interp.serve(ws)


@app.get("/auth/config")
def auth_config() -> dict[str, Any]:
    """브라우저용 Firebase 공개 설정. 비밀이 아니다. 값이 없으면 화면은 데모 로그인을 쓴다."""
    return firebase_auth.public_config()


@app.get("/auth/me")
def auth_me(request: Request) -> dict[str, str]:
    """Firebase ID 토큰의 계정. 생성·말하기는 이 확인을 요구하지 않는다."""
    try:
        return firebase_auth.verify_bearer(request.headers.get("authorization") or "")
    except firebase_auth.AuthError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.code) from exc


def _bearer_token(request: Request) -> str:
    scheme, _, token = (request.headers.get("authorization") or "").partition(" ")
    if scheme.lower() != "bearer":
        return ""
    return token.strip()


async def _account_token(request: Request) -> tuple[dict[str, str], str]:
    """토큰의 uid. 익명 로그인은 계정 기록을 만들지 않는다."""
    try:
        account = await run_in_threadpool(
            firebase_auth.verify_bearer, request.headers.get("authorization") or "",
        )
    except firebase_auth.AuthError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.code) from exc
    if account.get("provider") == "anonymous":
        raise HTTPException(status_code=403, detail="anonymous_rejected")
    return account, _bearer_token(request)


@app.get("/user/state")
async def user_state_get(request: Request) -> dict[str, Any]:
    """이 계정의 진도·복습·동의·여행 입력. 문서가 없으면 빈 기록. 생성·말하기는 이 경로를 타지 않는다.

    탈퇴한 uid 는 403 account_deleted 다 — 화면이 '기록이 비어 있다'로 오인해 다시 올리지 않게.
    """
    account, token = await _account_token(request)
    await _reject_if_erased(account["uid"])
    try:
        found = await run_in_threadpool(user_state.read_for, account["uid"], token)
    except user_state.StoreError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.code) from exc
    return found if found is not None else user_state.EMPTY_STATE


async def _reject_if_erased(uid: str) -> None:
    """탈퇴 흔적이 있는 uid 의 읽기·쓰기를 거부한다.

    관리자 삭제 뒤에도 남은 미만료 ID 토큰(≤1h)이 `users/{uid}` 를 다시 만드는 것을 막는다.
    흔적 조회는 저장소로 나가는 **동기** HTTP 이므로 스레드풀에서 돌린다 —
    이벤트 루프를 막으면 다른 요청(생성·음성)까지 멈춘다.
    """
    if await run_in_threadpool(firebase_admin.is_erased, uid):
        raise HTTPException(status_code=403, detail="account_deleted")


@app.put("/user/state")
async def user_state_put(request: Request) -> dict[str, Any]:
    """진도·복습·동의·여행 입력만 갈아 끼운다. uid 는 토큰에서 나오고 본문에서는 받지 않는다.

    탈퇴한 uid 는 거부한다(403 account_deleted).
    """
    account, token = await _account_token(request)
    await _reject_if_erased(account["uid"])
    raw = await request.body()
    if len(raw) > user_state.MAX_STATE_BYTES:
        raise HTTPException(status_code=413, detail="state_too_large")
    try:
        state = user_state.parse_state(json.loads(raw))
        await run_in_threadpool(user_state.write_for, account["uid"], token, state)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid_state") from exc
    except user_state.StoreError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.code) from exc
    return state


@app.delete("/user/state")
async def user_state_delete(request: Request) -> dict[str, Any]:
    """탈퇴: 이 계정의 기록 문서를 지운다. uid 는 토큰에서 나온다. 없는 문서도 성공이다.

    Firebase 계정 자체(로그인)는 여기서 지우지 않는다 — 서비스 계정 키 없이 ID 토큰만 쓰는
    구조라서다. 화면이 이 호출 뒤에 deleteUser 로 계정을 지운다.
    """
    account, token = await _account_token(request)
    try:
        await run_in_threadpool(user_state.delete_for, account["uid"], token)
    except user_state.StoreError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.code) from exc
    return {"deleted": True}


@app.post("/account/erase")
async def account_erase(request: Request) -> dict[str, Any]:
    """탈퇴(관리자): 흔적 → 토큰 취소 → 기록 삭제 → 계정 삭제. uid 는 검증된 토큰에서 온다.

    서비스 계정 키(FIREBASE_SERVICE_ACCOUNT_JSON)가 없으면 503 admin_unavailable 을 돌려주고,
    화면은 규칙 삭제 + 클라이언트 deleteUser 경로로 되돌아간다.

    실패하면 **단계 원장**과 함께 증거를 봉인해 둔다(누가 어디까지 갔는지 남긴다). 성공해도
    사후 검증으로 "남아 있는" 경우를 잡는다 — 응답이 성공이어도 실제로 지워졌는지는 별개다.
    """
    account, _token = await _account_token(request)
    if not firebase_admin.configured():
        raise HTTPException(status_code=503, detail="admin_unavailable")
    rate_limit(request)
    challenge = _challenge_from(request)                 # 클라이언트가 요청 **전에** 만든 값(없으면 서버가 만든다)
    attempt = {}
    if evidence.configured():
        # 시도 기록은 반드시 남아야 한다 — 남기지 못하면 아무것도 지우지 않고 멈춘다(재시도 후).
        # 예전에는 이 예외가 그대로 새어 500 이 됐다. 이제 원인이 드러나는 503 으로 답한다.
        try:
            attempt = await _chain_write(evidence.record_attempt, challenge, account["uid"])
        except Exception as exc:  # noqa: BLE001
            logging.getLogger("app.evidence").exception("시도 기록 실패 — 탈퇴를 시작하지 않는다")
            # 이 실패도 봉인한다. 예전에는 계정 삭제 **전** 실패가 봉인 코드(아래 except)에 닿지 못해
            # 10/18~19 탈퇴 실패 10건의 증거가 하나도 남지 않았다(관리자 GUI 아카이브 목록이 빔).
            _seal_in_background("attempt_unrecorded", account["uid"], [],
                                {"challenge": challenge, "stage": "record_attempt"}, exc)
            raise HTTPException(status_code=503, detail="evidence_unavailable") from exc
    ledger: list[dict[str, Any]] = []
    try:
        await run_in_threadpool(firebase_admin.erase_account, account["uid"], ledger)
    except (firebase_admin.AdminError, Exception) as exc:   # noqa: BLE001 — 아래에서 상태로 나눈다
        await _chain_outcome(challenge, "failed", account["uid"], note=getattr(exc, "code", "") or "")
        _seal_in_background("erase_failed", account["uid"], ledger, None, exc)
        if isinstance(exc, firebase_admin.AdminError):
            raise HTTPException(status_code=exc.status, detail=exc.code) from exc
        raise HTTPException(status_code=503, detail="admin_failed") from exc

    check = await run_in_threadpool(firebase_admin.verify_erased, account["uid"])
    outcome = "ok" if check.get("ok", True) else "verify_mismatch"
    await _chain_outcome(challenge, outcome, account["uid"])
    if check.get("ok") is False:
        _seal_in_background("verify_mismatch", account["uid"], ledger, check, None)
    return {"erased": True, "receipt": evidence.receipt_for(challenge, attempt, outcome)}


CHAIN_RETRY_DELAYS = (0.5, 1.5)   # 증거 체인 쓰기: 첫 시도 + 재시도 2회(일시적 Firestore 오류 대비)


async def _chain_write(fn: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
    """증거 체인에 한 항목을 쓴다. 실패하면 잠깐 쉬고 다시 쓴다 — 끝내 실패하면 마지막 예외를 그대로 던진다."""
    for delay in (*CHAIN_RETRY_DELAYS, None):
        try:
            return await run_in_threadpool(fn, *args, **kwargs)
        except Exception:  # noqa: BLE001 — 마지막 시도에서만 밖으로 던진다
            if delay is None:
                raise
            logging.getLogger("app.evidence").warning("증거 체인 쓰기 실패 — %.1fs 뒤 다시 시도", delay)
            await asyncio.sleep(delay)
    return {}


async def _chain_outcome(challenge: str, outcome: str, uid: str, note: str = "") -> None:
    """결과 기록(성공·실패 모두). 재시도해도 남기지 못하면 증거로 봉인하고 오류 로그를 남긴다.

    여기까지 왔으면 시도 기록은 이미 체인에 있다. 계정 삭제가 끝난 뒤라면 되돌릴 수 없으므로
    응답을 '실패'로 바꾸지 않는다 — 지워졌는데 화면이 실패로 안내하는 것이 더 나쁘다.
    """
    if not evidence.configured():
        return
    try:
        await _chain_write(evidence.record_outcome, challenge, outcome, uid=uid, note=note)
    except Exception as exc:  # noqa: BLE001
        logging.getLogger("app.evidence").error("결과 기록 실패(%s) — 시도 기록만 체인에 남았다", outcome)
        _seal_in_background("outcome_unrecorded", uid, [], {"challenge": challenge, "outcome": outcome}, exc)


def _challenge_from(request: Request) -> str:
    """요청의 챌린지(헤더 또는 본문). 클라이언트가 보내지 않으면 서버가 만든다.

    서버가 만든 챌린지는 **사전 커밋 효과가 없다**(앱이 그 순간에 만들기 때문) — 그래서 화면이
    챌린지를 보내고, 영수증이 없으면 "상태 불명"을 보여야 한다. 여기서는 최소한 값을 남긴다.
    """
    raw = (request.headers.get("x-withdraw-challenge") or "").strip().lower()
    if re.fullmatch(r"[0-9a-f]{16,128}", raw or ""):
        return raw
    return uuid.uuid4().hex


def _seal_in_background(trigger: str, uid: str, ledger: list[dict[str, Any]],
                        verification: dict[str, Any] | None,
                        error: BaseException | None) -> None:
    """증거 봉인을 백그라운드 스레드로 넘긴다 — 응답을 늦추지 않고, 실패해도 조용히 로그만 남긴다."""
    if not evidence.configured():
        return
    threading.Thread(
        target=evidence.seal_and_report,
        kwargs={"trigger": trigger, "uid": uid, "ledger": ledger, "verification": verification,
                "error": error, "source_root": str(REPO_ROOT / "backend" / "app")},
        name="evidence-seal", daemon=True).start()


@app.post("/diagnostics/withdraw")
async def diagnostics_withdraw(request: Request, payload: WithdrawReport) -> dict[str, Any]:
    """화면이 "탈퇴가 예상 밖 상태로 끝났다"고 보고하는 경로(다른 기기 탈퇴·부분 실패 등).

    서버가 성공으로 응답했는데 화면이 불일치를 봤다면 그것도 증거다. 인증된 사용자만 보낼 수 있고
    스로틀이 걸려 있다(같은 uid 는 1시간에 한 번).
    """
    account, _token = await _account_token(request)
    rate_limit(request)
    _seal_in_background("client_report", account["uid"], [], {"client": payload.model_dump()}, None)
    return {"received": True}


# 화면(목업)을 같은 서비스에서 서빙한다. 반드시 모든 API 라우트 등록 뒤에 마운트한다.
WEB_DIR = REPO_ROOT / "mockup"
if WEB_DIR.is_dir():
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
