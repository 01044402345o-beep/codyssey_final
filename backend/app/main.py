"""Codyssey Final — 최소 백엔드.

엔드포인트는 3개가 상한. 기능을 더 붙이지 마세요.
Firebase를 걷어낸 이유가 그대로 재발합니다.

  GET  /health       배포·콜드스타트 확인용
  POST /generate     카테고리 문장 생성 (+ 스키마·규칙 검증 후 재생성)
  POST /speak-check  발음 오디오 → 피드백 (멀티모달)

GEMINI_API_KEY 가 없으면 목업으로 응답한다. 그래서 키 없이도 배포·시연이 된다.
목업·검증실패 결과는 usable 로 구분되므로, 프론트가 학습 화면에 넣지 않게 막을 수 있다.
"""
from __future__ import annotations

import json
import os
import re
import time
from collections import defaultdict, deque
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .validators import has_blocking, validate_pack, validate_speak_result

# main.py 는 backend/app/ 에 있다. 저장소 루트의 agent_contract/ 를 본다.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
CONTRACT_DIR = Path(os.getenv("CONTRACT_DIR") or (REPO_ROOT / "agent_contract"))
CATEGORY_DIR = CONTRACT_DIR / "categories"
SCHEMA_PATH = CONTRACT_DIR / "schema.json"
WEAK_MAP_PATH = CONTRACT_DIR / "weak_expressions.json"

MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "2"))
MAX_AUDIO_BYTES = 8 * 1024 * 1024
MAX_AUDIO_SECONDS = 30

# 호출 제한 (단일 인스턴스 기준). 진짜 비용 상한은 Google Cloud 예산 알림으로 잡는다.
RATE_LIMIT = int(os.getenv("RATE_LIMIT", "20"))          # 창당 최대 요청 수
RATE_WINDOW = int(os.getenv("RATE_WINDOW", "60"))        # 초

PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")

app = FastAPI(title="Codyssey Final API", version="0.1.0")
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


@lru_cache(maxsize=1)
def load_weak_map() -> dict[str, Any]:
    try:
        return json.loads(WEAK_MAP_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"mapping": {}}


def list_categories() -> list[str]:
    return sorted(p.stem for p in CATEGORY_DIR.glob("*.json"))


def build_prompt(cfg: dict[str, Any], req: GenerateRequest) -> str:
    """system_prompt 의 {키} 를 rules 의 같은 키 값으로 치환한다."""
    rules = cfg.get("rules", {})
    body = PLACEHOLDER.sub(
        lambda m: str(rules[m.group(1)]) if m.group(1) in rules else m.group(0),
        cfg.get("system_prompt", ""),
    )
    mapping = load_weak_map().get("mapping") or {}
    weak_spec = [
        {"id": w, **(mapping.get(w) or {})} for w in req.weak_expressions
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


def call_gemini(prompt: str) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    resp = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.7,
            max_output_tokens=8192,
        ),
    )
    return resp.text or ""


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
    return {
        "status": "ok",
        "model": MODEL,
        "has_api_key": bool(os.getenv("GEMINI_API_KEY")),
        "contract_dir": str(CONTRACT_DIR),
        "categories": list_categories(),
        "weak_expressions": sorted((load_weak_map().get("mapping") or {}).keys()),
        "rate_limit": f"{RATE_LIMIT}/{RATE_WINDOW}s",
    }


@app.post("/generate")
def generate(req: GenerateRequest, request: Request) -> dict[str, Any]:
    rate_limit(request)
    cfg = load_category(req.category_id)
    schema = load_schema()
    weak_map = load_weak_map()

    if not os.getenv("GEMINI_API_KEY"):
        pack = mock_pack(cfg, req)
        issues = validate_pack(pack, cfg, req.weak_expressions, schema, weak_map)
        return {
            "pack": pack,
            "issues": issues,
            "attempts": 0,
            "mock": True,
            "usable": usability(issues, True, False),
        }

    prompt = build_prompt(cfg, req)
    last_error = ""
    last_pack: dict[str, Any] | None = None
    last_issues: list[dict[str, Any]] = []

    for attempt in range(1, MAX_RETRIES + 2):
        try:
            src = prompt if attempt == 1 else (
                prompt + f"\n\nPrevious attempt was rejected: {last_error}\nFix it and return JSON only."
            )
            raw = call_gemini(src)
            pack = parse_json_object(raw)
        except Exception as exc:  # noqa: BLE001
            last_error = f"{type(exc).__name__}: {exc}"
            continue

        issues = validate_pack(pack, cfg, req.weak_expressions, schema, weak_map)
        last_pack, last_issues = pack, issues
        if not has_blocking(issues):
            return {
                "pack": pack, "issues": issues, "attempts": attempt,
                "mock": False, "usable": "ok",
            }

        last_error = json.dumps(
            [i for i in issues if i["severity"] == "block"], ensure_ascii=False
        )

    # 재시도에도 block 이 남으면 목업으로 대체한다. 다만 usable="rejected" 이므로
    # 프론트는 이 결과를 학습 화면에 넣으면 안 된다는 것을 알 수 있다.
    fallback = mock_pack(cfg, req)
    final_issues = last_issues or validate_pack(fallback, cfg, req.weak_expressions, schema, weak_map)
    return {
        "pack": last_pack or fallback,
        "issues": final_issues,
        "attempts": MAX_RETRIES + 1,
        "mock": last_pack is None,
        "degraded": True,
        "usable": "rejected",
        "error": last_error,
    }


SPEAK_PROMPT = (
    "You are an English pronunciation and speaking coach for Korean travelers. "
    "Listen to the audio and compare it to the target.\n"
    'Return JSON only: {"heard": "what you actually heard", '
    '"fix_one": "the single most important thing to fix, in Korean", '
    '"issues": [{"word": "...", "note": "..."}], '
    '"tip": "one short Korean tip", "score": optional 0-100}.\n'
    "If the audio is silent or unintelligible, set heard to \"\" and leave score out.\n"
    "TARGET: "
)


@app.post("/speak-check")
async def speak_check(
    request: Request,
    target: str = Form(..., max_length=200),
    file: UploadFile = File(...),
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

    if not os.getenv("GEMINI_API_KEY"):
        return {
            "usable": False,
            "reason": "API 키가 없어 목업으로 응답했습니다.",
            "score": None, "heard": "", "issues": [], "fix_one": "", "tip": "",
            "mock": True,
        }

    from google import genai
    from google.genai import types

    try:
        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        resp = client.models.generate_content(
            model=MODEL,
            contents=[
                types.Part.from_bytes(data=audio, mime_type=mime),
                SPEAK_PROMPT + target,
            ],
            config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.2),
        )
        parsed = parse_json_object(resp.text or "")
    except Exception as exc:  # noqa: BLE001
        # 평가 실패는 점수·약점으로 저장되면 안 된다.
        return {
            "usable": False,
            "reason": "채점 중 오류가 발생했습니다. 다시 시도해 주세요.",
            "error": f"{type(exc).__name__}: {exc}",
            "score": None, "heard": "", "issues": [], "fix_one": "", "tip": "",
        }

    norm, usable, reason = validate_speak_result(parsed)
    norm["usable"] = usable
    if reason:
        norm["reason"] = reason
    return norm
