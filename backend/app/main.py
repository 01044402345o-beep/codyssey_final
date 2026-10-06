"""Codyssey Final — 최소 백엔드.

엔드포인트는 3개가 상한. 기능을 더 붙이지 마세요.
Firebase를 걷어낸 이유가 그대로 재발합니다.

  GET  /health       배포·콜드스타트 확인용
  POST /generate     카테고리 문장 생성 (+ 스키마·규칙 검증 후 재생성)
  POST /speak-check  발음 오디오 → 피드백 (멀티모달)

모델은 고정하지 않고 호출 시점의 사용 가능 목록에서 고르며, AI API 호출은
하나당 최소 30회 시도한다 (app/gemini.py).

GEMINI_API_KEY 가 없으면 목업으로 응답한다. 그래서 키 없이도 배포·시연이 된다.
목업·검증실패 결과는 usable 로 구분되므로, 프론트가 학습 화면에 넣지 않게 막을 수 있다.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from . import gemini as ai
from . import speech_compare as compare
from . import speech_vad as vad
from . import stt_providers as stt
from . import stt_selftest as selftest

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
    yield


app = FastAPI(title="Codyssey Final API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=(os.getenv("ALLOW_ORIGINS") or "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

_hits: dict[str, deque[float]] = defaultdict(deque)



def rate_limit(request: Request) -> None:
    """IP 기준 슬라이딩 윈도. 프로세스 메모리라 인스턴스가 늘면 약해진다 — 임시 방어."""
    ip = (request.client.host if request.client else "unknown")
    now = time.time()
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


class GenerateRequest(BaseModel):
    category_id: str = Field(min_length=1, max_length=40)
    city: str = Field(default="New York", min_length=1, max_length=80)
    places: list[Place] = Field(default_factory=list, max_length=20)
    weak_expressions: list[str] = Field(default_factory=list, max_length=20)


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


def build_prompt(cfg: dict[str, Any], req: GenerateRequest) -> str:
    """system_prompt 의 {키} 를 rules 의 같은 키 값으로 치환한다."""
    rules = cfg.get("rules", {})
    body = PLACEHOLDER.sub(
        lambda m: str(rules[m.group(1)]) if m.group(1) in rules else m.group(0),
        cfg.get("system_prompt", ""),
    )
    mapping = {s.get("situation_id"): s for s in cfg.get("situations", []) if isinstance(s, dict)}
    weak_spec = [
        {"situation_id": w, "situation": (mapping.get(w) or {}).get("situation"),
         "required_keywords": (mapping.get(w) or {}).get("required_keywords")}
        for w in req.weak_expressions
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
    )


def mock_pack(cfg: dict[str, Any], req: GenerateRequest) -> dict[str, Any]:
    """키 없이도 시연되도록 설정의 good_examples 를 그대로 돌려준다.

    주의: 여기서 취약 표현 태그를 임의로 붙이지 않는다. 태그를 조작하면
    '반영됐다'는 증거를 위조하는 것이 된다. 반영 여부는 검증기가
    weak_expressions.json 의 상황·키워드로 판단한다.
    """
    default_type = (cfg.get("place_types") or [None])[0]
    sentences = []
    for ex in cfg.get("good_examples", []):
        s = dict(ex)
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
        "stt_models": stt.cached_models(),
        "stt_selftest": selftest.status(),
        "has_api_key": bool(os.getenv("GEMINI_API_KEY")),
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


@app.post("/generate")
def generate(req: GenerateRequest, request: Request) -> dict[str, Any]:
    rate_limit(request)
    if CONFIG_STRICT and config_problems():
        raise HTTPException(
            status_code=503,
            detail={"message": "설정이 갖춰지지 않아 생성을 거부했습니다.", "problems": config_problems()},
        )
    cfg = load_category(req.category_id)
    schema = load_schema()

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
        }

    prompt = build_prompt(cfg, req)
    state: dict[str, Any] = {"last_error": "", "last_pack": None, "last_issues": []}

    def once(client: Any, model: str, attempt: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        src = prompt if attempt == 1 else (
            prompt + f"\n\nPrevious attempt was rejected: {state['last_error']}\nFix it and return JSON only."
        )
        try:
            raw = ai.generate_text(client, model, src, temperature=0.7, max_output_tokens=8192)
            pack = parse_json_object(raw)
        except Exception as exc:
            state["last_error"] = f"{type(exc).__name__}: {exc}"
            raise

        # 검증기 호출도 시도 안에 둔다. 검증기 버그가 500 을 내면 재시도가 무의미해진다.
        try:
            issues = validate_pack(pack, cfg, req.weak_expressions, schema)
        except Exception as exc:
            state["last_error"] = f"validator error: {type(exc).__name__}: {exc}"
            raise

        state["last_pack"], state["last_issues"] = pack, issues
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
        }

    pack, issues = res.value
    return {
        "pack": pack, "issues": issues, "attempts": res.attempts, "model": res.model,
        "failures": res.failures,   # 성공 전에 실패한 시도들 (원인 진단용)
        "mock": False, "usable": "ok",
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
    "A learner practiced saying the TARGET sentence in the given SITUATION. A speech recognizer "
    "(not you) transcribed what they said as HEARD, and code compared the two word by word (DIFF). "
    "The SCORE was computed by code; you cannot change it and must not output a score.\n"
    "Base your feedback ONLY on the TARGET, HEARD and DIFF below. You did not hear the audio, so do not "
    "comment on accent, intonation or sounds that are not visible in the DIFF.\n"
    "Write in Korean:\n"
    '- "fix_one": the single most useful thing to fix next time (one sentence). If nothing differs, '
    "praise briefly and suggest one natural variation useful in this situation.\n"
    '- "tip": one short practical tip for using this sentence in this situation.\n'
    'Return JSON only: {"fix_one": "...", "tip": "..."}\n\n'
)


def feedback_input(situation: str, target: str, heard: str, diff: dict[str, Any]) -> str:
    facts = {
        "SITUATION": situation or "(unknown)",
        "TARGET": target,
        "HEARD": heard,
        "SCORE": diff["score"],
        "DIFF": {k: diff[k] for k in ("missing", "extra", "replaced")},
    }
    return FEEDBACK_PROMPT + json.dumps(facts, ensure_ascii=False, indent=2)


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
    rate_limit(request)

    audio = await file.read()
    if not audio:
        raise HTTPException(status_code=400, detail="빈 오디오입니다. 다시 녹음해 주세요.")
    if len(audio) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="오디오가 너무 큽니다 (최대 8MB).")

    # 형식 검사는 목업 응답보다 먼저 한다. 키가 없어도 잘못된 입력은 잘못된 입력이다.
    mime = (file.content_type or "audio/webm").split(";")[0].strip() or "audio/webm"
    if not mime.startswith("audio/"):
        raise HTTPException(status_code=415, detail=f"지원하지 않는 형식입니다: {mime}")

    # 1) 말소리 검출 — 키가 없어도 동작한다. 말이 없으면 여기서 끝(외부 API 0회).
    try:
        samples = vad.decode(audio)
    except vad.AudioDecodeError:
        raise HTTPException(status_code=400, detail="녹음 파일을 읽을 수 없습니다. 다시 녹음해 주세요.")
    speech = await run_in_threadpool(vad.detect, samples)
    if not speech.has_speech:
        return no_speech("음성이 인식되지 않았습니다. 다시 녹음해 주세요.", vad=speech.summary())

    if not stt.configured():
        return {
            "usable": False,
            "reason": "전사 API 키가 없어 목업으로 응답했습니다.",
            "score": None, "heard": "", "issues": [], "fix_one": "", "tip": "",
            "mock": True, "vad": speech.summary(),
        }

    # 2) 전사 — 말소리 구간만, 목표 문장 없이. 공급자 체인(최소 30회씩).
    wav = vad.speech_only_wav(samples, speech)
    try:
        tr = await run_in_threadpool(stt.transcribe, wav)
    except stt.SttChainExhausted as exc:
        # 평가 실패는 점수·약점으로 저장되면 안 된다.
        return no_speech(
            "채점 중 오류가 발생했습니다. 다시 시도해 주세요.",
            error=exc.last_error, attempts=exc.attempts, failed_at="stt",
            failures=exc.failures, vad=speech.summary(),
        )
    meta = {"attempts": tr.attempts, "model": tr.model, "failures": tr.failures,
            "stt": tr.meta(), "vad": speech.summary()}

    # 3) 환각 세그먼트 제거와 무음 판정 — 코드가 한다.
    heard, dropped = compare.filter_segments(tr.text, tr.segments)
    meta["dropped_segments"] = dropped
    if compare.is_placeholder(heard):
        return no_speech("음성이 인식되지 않았습니다. 다시 녹음해 주세요.", heard_raw=tr.text, **meta)
    diff = compare.compare(target, heard)
    issues = [{"word": w, "note": "빠짐"} for w in diff["missing"]] + \
             [{"word": a, "note": f"'{b}'(으)로 들림"} for a, b in diff["replaced"]] + \
             [{"word": w, "note": "목표 문장에 없음"} for w in diff["extra"]]

    # 3) 피드백 문장 — 오디오 없이 비교 결과만 준다. 응답의 다른 키(score 등)는 버린다.
    prompt = feedback_input(situation, target, heard, diff)

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

    return {
        "usable": True,
        "score": diff["score"],
        "score_kind": "word_match",      # 발음 점수가 아니라 단어 일치율
        "heard": heard,
        "issues": issues,
        "diff": diff,
        "fix_one": fix_one,
        "tip": tip,
        "feedback": feedback,
        **meta,
    }


# 화면(목업)을 같은 서비스에서 서빙한다. 반드시 모든 API 라우트 등록 뒤에 마운트한다.
WEB_DIR = REPO_ROOT / "mockup"
if WEB_DIR.is_dir():
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
