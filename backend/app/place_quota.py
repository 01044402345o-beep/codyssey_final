"""장소 생성 요청(보고서 장소 조사 POST /research) 하루 횟수 — 사용자(계정) 또는 IP 당.

- 한도: 환경 변수 PLACE_SEARCH_DAILY_LIMIT(기본 3). 0 이면 제한하지 않는다. 요청마다 다시 읽어 Render 에서 바로 바꿀 수 있다.
- 세는 것: 받아들여진 장소 조사 요청(바로 끝났거나 시작된 것). 서버가 바빠 거절했거나(503) 조사 기능이 꺼져
  예시로 돌아간 요청은 세지 않는다(미리 잡았다가 돌려준다).
- 세지 않는 것: 사용자가 직접 넣은 장소 한 곳을 찾아보는 확인(POST /place-check) — '검색엔진 조사'는 횟수에서 뺀다.
- 하루 = 한국 시간(UTC+9) 날짜. 서버 메모리에 세므로 재시작하면 0부터다(비용 방어용 임시 한도).
- 누구인가: 로그인 토큰이 맞으면 계정(uid), 아니면 IP. 관리형 플랫폼에서 실제 IP 를 모르면(TRUSTED_PROXY_HOPS=0)
  X-Forwarded-For 의 첫 주소를 쓴다 — 바꿔 보낼 수 있지만 비용 방어용 느슨한 한도라 받아들인다.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import os
import threading
from typing import Optional

_lock = threading.Lock()
_counts: dict[tuple[str, str], int] = {}
KST = dt.timezone(dt.timedelta(hours=9))
MESSAGE = "하루에 장소 검색을 할 수 있는 횟수를 초과했어요"


def limit() -> int:
    try:
        return max(0, int((os.getenv("PLACE_SEARCH_DAILY_LIMIT") or "3").strip()))
    except ValueError:
        return 3


def today() -> str:
    return dt.datetime.now(KST).date().isoformat()


def key_for(uid: str = "", ip: str = "", forwarded: str = "", peer: str = "") -> str:
    """원본 IP·uid 를 그대로 들고 있지 않게 해시로 줄인다."""
    if uid:
        raw = "u:" + uid
    elif ip:
        raw = "ip:" + ip
    else:
        first = (forwarded or "").split(",")[0].strip()
        raw = ("xff:" + first) if first else ("peer:" + (peer or "unknown"))
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def _prune(day: str) -> None:
    for k in [k for k in _counts if k[0] != day]:
        del _counts[k]


def reserve(key: str) -> tuple[bool, int, int]:
    """한 번을 미리 잡는다 → (허용?, 쓴 횟수, 한도). 한도 0 이면 늘 허용(세지 않는다)."""
    n = limit()
    if n == 0:
        return True, 0, 0
    day = today()
    with _lock:
        _prune(day)
        used = _counts.get((day, key), 0)
        if used >= n:
            return False, used, n
        _counts[(day, key)] = used + 1
        return True, used + 1, n


def refund(key: str) -> None:
    """받아들여지지 않은 요청(서버 바쁨·조사 꺼짐·오류)은 돌려준다."""
    if limit() == 0:
        return
    day = today()
    with _lock:
        used = _counts.get((day, key), 0)
        if used > 0:
            _counts[(day, key)] = used - 1


def used(key: str) -> int:
    with _lock:
        return _counts.get((today(), key), 0)


def clear() -> None:
    with _lock:
        _counts.clear()


def remaining(key: str) -> Optional[int]:
    n = limit()
    return None if n == 0 else max(0, n - used(key))
