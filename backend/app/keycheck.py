"""키 점검 — 부팅 때 '약한 키·같은 키 재사용'을 조용히 통과시키지 않는다.

왜 필요한가
-----------
키는 대개 '설정했다/안 했다'만 확인된다. 그런데 실제 사고는 대개 **설정은 됐는데 약한** 경우다:
짧은 값, 사람이 고른 문장, 한 비밀로 여러 역할 겸용. 후자가 가장 나쁘다 — 한 곳이 새면
전부 새고, 하나를 회전하면 다른 기능이 조용히 죽는다.

왜 '키를 46번 늘리고 여러 번 암복호화'하지 않는가
------------------------------------------------
안전성은 **길이**가 아니라 **엔트로피**에서 나온다. 임의 32바이트는 2^256 이고, 같은 값을
길게 늘어놓아도 엔트로피는 1비트도 늘지 않는다. 키를 다시 암호화하는 것은 새 키를 하나 더
만들 뿐이고, 그 새 키를 또 어디 둘지가 문제로 돌아온다(키 관리 지점만 늘어난다).
그래서 여기서는 길이만이 아니라 **서로 다른 바이트 수·역할 간 중복·회전 준비**를 본다.
"""
from __future__ import annotations

import base64
import hashlib
import os
from typing import Any

# (환경변수, 최소 바이트, 설명)
ROLES: tuple[tuple[str, int, str], ...] = (
    ("EVIDENCE_SIGN_KEY", 32, "탈퇴 영수증 Ed25519 서명 시드"),
    ("EVIDENCE_PUBKEY", 32, "증거 봉인 X25519 공개키"),
    ("HEALTH_DETAIL_TOKEN", 24, "/health 상세 조회 토큰"),
    ("TRIP_API_TOKEN", 24, "여행 API 토큰"),
    ("ADMIN_TOKEN", 24, "관리자 경로 토큰"),
)
MIN_DISTINCT = 16      # 서로 다른 바이트가 이보다 적으면 '사람이 만든 값'으로 본다


def _decode(raw: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(raw.encode() + b"=" * (-len(raw) % 4))
    except Exception:  # noqa: BLE001 — base64 가 아니면 원문 바이트로 본다
        return raw.encode()


def fingerprint(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def check(env: dict[str, str] | None = None) -> dict[str, Any]:
    """설정된 키만 검사한다. 비어 있는 것은 '아직 안 켬'이지 오류가 아니다."""
    src = env if env is not None else os.environ
    issues: list[dict[str, str]] = []
    seen: dict[str, str] = {}          # 지문 → 역할
    out: dict[str, Any] = {"ok": True, "issues": issues, "keys": {}}

    for name, need, desc in ROLES:
        raw = (src.get(name) or "").strip()
        if not raw:
            continue
        data = _decode(raw)
        fp = fingerprint(data)
        out["keys"][name] = {"bytes": len(data), "fingerprint": fp, "role": desc}
        if len(data) < need:
            issues.append({"key": name, "code": "too_short",
                           "detail": f"{len(data)}바이트 — 최소 {need}바이트 필요"})
        if len(set(data)) < MIN_DISTINCT:
            issues.append({"key": name, "code": "low_diversity",
                           "detail": f"서로 다른 바이트 {len(set(data))}개 — 난수로 만든 값이 아님"})
        if fp in seen:
            issues.append({"key": name, "code": "reused",
                           "detail": f"{seen[fp]} 와(과) 같은 값 — 한 곳이 새면 둘 다 새고, 회전하면 둘 다 죽는다"})
        else:
            seen[fp] = name

    out["ok"] = not issues
    return out


def summary() -> str:
    """로그 한 줄 — 값은 절대 찍지 않고 지문·길이만."""
    r = check()
    if not r["keys"]:
        return "키 점검: 설정된 키 없음(기능이 꺼진 상태로 동작)"
    parts = [f"{k}({v['bytes']}B, {v['fingerprint']})" for k, v in r["keys"].items()]
    head = "키 점검: 정상" if r["ok"] else "키 점검: 문제 있음"
    return head + " · " + ", ".join(parts) + ("" if r["ok"] else " / " + "; ".join(i["detail"] for i in r["issues"]))


def main() -> int:   # python -m app.keycheck
    import json
    r = check()
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
