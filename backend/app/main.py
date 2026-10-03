"""Codyssey Final — 최소 백엔드.

엔드포인트는 3개가 상한. 기능을 더 붙이지 마세요.
Firebase를 걷어낸 이유가 그대로 재발합니다.

  GET  /health       배포·콜드스타트 확인용
  POST /generate     카테고리 문장 생성 (+ 스키마·규칙 검증 후 재생성)
  POST /speak-check  발음 오디오 → 피드백 (멀티모달)

GEMINI_API_KEY 가 없으면 목업으로 응답한다. 그래서 키 없이도 배포·시연이 된다.
"""
from __future__ import annotations

import json
import logging
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .validators import has_blocking, require_schema_support, validate_pack

log = logging.getLogger("codyssey")

# main.py 는 backend/app/ 에 있다. 저장소 루트의 agent_contract/ 를 본다.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
CONTRACT_DIR = Path(os.getenv("CONTRACT_DIR") or (REPO_ROOT / "agent_contract"))
CATEGORY_DIR = CONTRACT_DIR / "categories"
SCHEMA_PATH = CONTRACT_DIR / "schema.json"

MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "2"))
MAX_AUDIO_BYTES = 8 * 1024 * 1024

PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")
CATEGORY_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")

app = FastAPI(title="Codyssey Final API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=(os.getenv("ALLOW_ORIGINS") or "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------- 요청 모델

class Place(BaseModel):
    name: str
    place_type: str | None = None


class GenerateRequest(BaseModel):
    category_id: str
    city: str = "New York"
    places: list[Place] = Field(default_factory=list)
    weak_expressions: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------- 설정 로드

@lru_cache(maxsize=32)
def load_category(category_id: str) -> dict[str, Any]:
    """없는 카테고리(404)와 서버 설정 파일 불량(500)을 구분한다."""
    if not CATEGORY_ID_RE.match(category_id):
        raise HTTPException(status_code=404, detail=f"unknown category: {category_id!r}")
    path = CATEGORY_DIR / f"{category_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"unknown category: {category_id}")
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.error("category config unreadable: %s: %s", path, exc)
        raise HTTPException(status_code=500, detail=f"category config {category_id!r} is unreadable: {exc}") from exc
    problems = []
    if not isinstance(cfg, dict) or cfg.get("category_id") != category_id:
        problems.append("category_id missing or different from file name")
    elif not isinstance(cfg.get("situations"), list) or not all(
        isinstance(x, dict) and "situation_id" in x for x in cfg["situations"]
    ):
        problems.append("situations must be a list of objects with situation_id")
    if problems:
        log.error("category config invalid: %s: %s", path, problems)
        raise HTTPException(status_code=500, detail=f"category config {category_id!r} is invalid: {'; '.join(problems)}")
    return cfg


@lru_cache(maxsize=1)
def load_schema() -> dict[str, Any] | None:
    try:
        return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


# 스키마 파일·jsonschema 가 없으면 서버가 뜨지 않는다 (조용히 검증을 건너뛰지 않는다).
require_schema_support(load_schema())


def list_categories() -> list[str]:
    return sorted(p.stem for p in CATEGORY_DIR.glob("*.json"))


def build_prompt(cfg: dict[str, Any], req: GenerateRequest) -> str:
    """system_prompt 의 {키} 를 rules 의 같은 키 값으로 치환한다."""
    rules = cfg.get("rules", {})
    body = PLACEHOLDER.sub(
        lambda m: str(rules[m.group(1)]) if m.group(1) in rules else m.group(0),
        cfg.get("system_prompt", ""),
    )
    payload = {
        "category_id": cfg["category_id"],
        "city": req.city,
        "places": [p.model_dump() for p in req.places],
        "situations": cfg.get("situations", []),
        "weak_expressions": req.weak_expressions,
        "rules": rules,
    }
    return (
        f"{body}\n\nINPUT:\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
        f"\n\nOUTPUT JSON SCHEMA:\n{json.dumps(load_schema(), ensure_ascii=False)}"
        f"\n\nReturn JSON only."
    )


def mock_pack(cfg: dict[str, Any], req: GenerateRequest) -> dict[str, Any]:
    """키 없이도 시연되도록 설정의 good_examples 를 그대로 돌려준다."""
    default_type = (cfg.get("place_types") or [None])[0]
    sentences = []
    for ex in cfg.get("good_examples", []):
        s = dict(ex)
        s.setdefault("place_type", default_type)
        # 샘플은 개인화되지 않았다. 예시에 적힌 취약 표시도 그대로 내보내지 않는다.
        s.pop("targets_weak", None)
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


# ---------------------------------------------------------------- 엔드포인트

@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "model": MODEL,
        "has_api_key": bool(os.getenv("GEMINI_API_KEY")),
        "contract_dir": str(CONTRACT_DIR),
        "categories": list_categories(),
    }


@app.post("/generate")
def generate(req: GenerateRequest) -> dict[str, Any]:
    cfg = load_category(req.category_id)
    schema = load_schema()
    # 이 카테고리의 현재 유효한 상황 id 만 취약 상황으로 인정한다.
    valid_ids = {x["situation_id"] for x in cfg["situations"]}
    req.weak_expressions = [w for w in dict.fromkeys(req.weak_expressions) if w in valid_ids]

    if not os.getenv("GEMINI_API_KEY"):
        pack = mock_pack(cfg, req)
        return {
            "pack": pack,
            "issues": validate_pack(pack, cfg, req.weak_expressions, schema),
            "attempts": 0,
            "mock": True,
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

        try:
            issues = validate_pack(pack, cfg, req.weak_expressions, schema)
        except Exception as exc:  # noqa: BLE001
            # 검증기 자체의 버그는 모델 출력 문제가 아니다. 재호출하지 않고 안전하게 실패한다.
            log.exception("validator crashed for category %s", req.category_id)
            return {
                "pack": mock_pack(cfg, req),
                "issues": [{"severity": "block", "code": "validator_error", "detail": f"{type(exc).__name__}: {exc}"}],
                "attempts": attempt,
                "mock": True,
                "degraded": True,
                "error": f"validator_error: {type(exc).__name__}",
            }
        last_pack, last_issues = pack, issues
        if not has_blocking(issues):
            return {"pack": pack, "issues": issues, "attempts": attempt, "mock": False}

        last_error = json.dumps(
            [i for i in issues if i["severity"] == "block"], ensure_ascii=False
        )

    # 재시도에도 block 이 남으면 목업으로 대체 (화면이 비지 않게)
    return {
        "pack": last_pack or mock_pack(cfg, req),
        "issues": last_issues or validate_pack(mock_pack(cfg, req), cfg, req.weak_expressions, schema),
        "attempts": MAX_RETRIES + 1,
        "mock": last_pack is None,
        "degraded": True,
        "error": last_error,
    }


SPEAK_PROMPT = (
    "You are an English pronunciation coach for Korean travelers. "
    "Listen to the audio and compare it to the target sentence. "
    'Return JSON only: {"score": 0-100, "heard": "what you heard", '
    '"issues": [{"word": "...", "note": "..."}], "tip": "one short Korean tip"}.\n'
    "TARGET: "
)


@app.post("/speak-check")
async def speak_check(
    target: str = Form(...),
    file: UploadFile = File(...),
) -> dict[str, Any]:
    audio = await file.read()
    if len(audio) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="audio too large (max 8MB)")

    if not os.getenv("GEMINI_API_KEY"):
        return {
            "score": None,
            "heard": "",
            "issues": [],
            "tip": "API 키가 없어 목업으로 응답했습니다.",
            "mock": True,
        }

    # 브라우저는 'audio/webm;codecs=opus' 처럼 파라미터를 붙여 보낸다. 떼어낸다.
    mime = (file.content_type or "audio/webm").split(";")[0].strip() or "audio/webm"

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    resp = client.models.generate_content(
        model=MODEL,
        contents=[
            types.Part.from_bytes(data=audio, mime_type=mime),
            SPEAK_PROMPT + target,
        ],
        config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.2),
    )
    try:
        return parse_json_object(resp.text or "")
    except Exception:  # noqa: BLE001
        return {
            "score": None,
            "heard": "",
            "issues": [],
            "tip": "채점 결과를 해석하지 못했습니다.",
            "raw": resp.text,
        }


# 화면(목업)을 같은 서비스에서 서빙한다. 반드시 모든 API 라우트 등록 뒤에 마운트한다.
WEB_DIR = REPO_ROOT / "mockup"
if WEB_DIR.is_dir():
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
