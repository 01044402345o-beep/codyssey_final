"""발음기호 안내를 이미 물었는지 — 사용자(계정) 또는 IP 기준으로 서버가 기억한다.

왜 서버인가: 화면 저장소(localStorage)만 쓰면 기기를 바꾸거나 시크릿 창을 열 때마다 다시 묻는다.
'한 번만 묻는다'는 브라우저의 성질이 아니라 사람의 성질이어야 해서 계정 → IP 순서로 본다.

저장 방식과 한계
  · 원본 IP 는 저장하지 않는다. 소금(IPA_GATE_SALT) + sha256 앞 32자만 남긴다.
  · 파일 하나(JSON)에 담는다. Render 무료 플랜은 재시작 시 디스크가 비므로 배포 뒤에는
    한 번 더 물을 수 있다. 이 한계를 없애려면 Firestore 를 써야 하지만, 그러려면 게스트에게도
    토큰이 필요해 인증 구조를 바꿔야 한다 — 마감 전에 바꿀 변경이 아니다.
  · 180일이 지난 항목은 읽을 때 버린다.
  · 프록시 뒤인데 실제 사용자 IP 를 모를 때(Render + TRUSTED_PROXY_HOPS=0)는 모든 게스트가 프록시 IP
    하나로 보인다. 그때 IP 로 기억하면 한 사람이 답한 뒤 아무에게도 묻지 않으므로, 게스트는 서버에
    기억하지 않고 브라우저 칸(localStorage)만 쓴다. 계정은 그대로 기억한다.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()

STORE_PATH = Path(os.getenv("IPA_GATE_STORE") or (Path(tempfile.gettempdir()) / "ipa-gate.json"))
TTL_SECONDS = 180 * 24 * 3600
MAX_KEYS = 20_000
# 소금은 프로세스마다 새로 만들 수 있다 — 그러면 재시작 시 기억이 사라질 뿐 유출 위험은 없다.
SALT = os.getenv("IPA_GATE_SALT") or os.urandom(16).hex()
_UID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_VALUES = {"known", "course"}
_lock = threading.Lock()


def _key(uid: str, ip: str) -> str:
    """계정이 있으면 계정으로, 없으면 IP 로. 원본은 어디에도 남기지 않는다."""
    raw = f"u:{uid}" if uid else f"ip:{ip}"
    return hashlib.sha256((SALT + "|" + raw).encode()).hexdigest()[:32]


def _load() -> dict[str, Any]:
    try:
        with open(STORE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(data: dict[str, Any]) -> None:
    tmp = STORE_PATH.with_suffix(".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        tmp.replace(STORE_PATH)
    except OSError:
        pass   # 저장 실패로 질문을 막지 않는다 — 다음에 한 번 더 물을 뿐이다


def seen(uid: str, ip: str) -> str | None:
    if not uid and not ip:   # 믿을 수 있는 IP 가 없는 게스트 — 서버는 모른다(브라우저 칸이 답한다)
        return None
    now = time.time()
    with _lock:
        data = _load()
        rec = data.get(_key(uid, ip))
        if not isinstance(rec, dict):
            return None
        if now - float(rec.get("at", 0)) > TTL_SECONDS:
            return None
        return rec.get("value")


def mark(uid: str, ip: str, value: str) -> None:
    if value not in _VALUES:
        value = "known"
    if not uid and not ip:   # 프록시 IP 하나로 모든 게스트가 묶이는 경우 — 기록하지 않는다
        return
    with _lock:
        data = _load()
        now = time.time()
        if len(data) > MAX_KEYS:   # 오래된 것부터 버린다
            for k in sorted(data, key=lambda k: data[k].get("at", 0))[: len(data) // 4]:
                data.pop(k, None)
        data[_key(uid, ip)] = {"value": value, "at": now}
        _save(data)


def _ip(request: Request) -> str:
    # main.ai_client_key 를 쓴다 — 프록시 신뢰 설정을 공유하고, 관리형 플랫폼에서 실제 IP 를 모르면 '' 를 준다.
    # 순환 import 를 피해 지역 import.
    try:
        from .main import ai_client_key
        return ai_client_key(request)
    except Exception:  # noqa: BLE001
        return ""


def _uid(raw: str) -> str:
    return raw if raw and _UID.match(raw) else ""


@router.get("/ipa/gate")
async def ipa_gate_get(request: Request, uid: str = "") -> JSONResponse:
    value = seen(_uid(uid), _ip(request))
    return JSONResponse({"seen": value is not None, "value": value})


@router.post("/ipa/gate")
async def ipa_gate_post(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    if not isinstance(body, dict):
        body = {}
    uid = _uid(str(body.get("uid") or ""))
    value = str(body.get("value") or "known")
    mark(uid, _ip(request), value)
    return JSONResponse({"ok": True, "value": value if value in _VALUES else "known"})
