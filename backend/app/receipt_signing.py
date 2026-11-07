"""탈퇴 영수증 서명(Ed25519).

왜 필요한가
-----------
영수증(`evidence.receipt_for`)은 원래 서명이 없었다. 그래서 사용자가 "서버가 영수증을
돌려줬다"고 보여 줘도 **서버가 낸 것인지 증명할 방법이 없었다** — 응답 JSON 은 프록시·
확장 프로그램·악성 클라이언트가 얼마든지 만들 수 있다. 서명이 붙으면 영수증만 들고
오프라인에서도 위조 여부를 확인할 수 있고, 서버는 나중에 "안 줬다"고 발뺌할 수 없다.

왜 직접 만든 해시(S-box·XOR 조합)를 쓰지 않는가
------------------------------------------------
관리자는 증거를 **다시 계산해서** 대조한다. 표준 Ed25519 는 누구나 검증할 수 있지만
검토되지 않은 자작 해시는 재현이 불가능해 증거로서 가치가 0 이 된다. 게다가 S-box 는
가역 블록 암호의 부품이라 단방향성 보장이 없다. 표준 primitive 를 자작으로 바꾸는 것은
보안 강화가 아니라 후퇴다.

키
--
`EVIDENCE_SIGN_KEY` (base64url 32바이트 시드). 없으면 **서명하지 않는다** —
그럴듯한 서명을 흉내 내는 것보다 `signed:false` 로 정직하게 비어 있는 편이 낫다.
공개키는 `/health` 의 `receipt_signing` 에 노출해 클라이언트가 핀으로 고정할 수 있게 한다.

서명 대상
---------
`b"SEAL-RECEIPT-v2\\x00" + canonical_json(서명 필드)`. 도메인 접두사를 붙이는 이유는
같은 키로 다른 종류의 문서에 서명하게 될 때 서명을 옮겨 붙이지 못하게 하기 위해서다.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from typing import Any

SCHEMA = "SEAL-RECEIPT-v2"
DOMAIN = b"SEAL-RECEIPT-v2\x00"
_KEY_ID_LEN = 8


def _b64d(raw: str) -> bytes | None:
    try:
        data = base64.urlsafe_b64decode(raw.encode() + b"=" * (-len(raw) % 4))
    except Exception:  # noqa: BLE001 — 값이 이상하면 '없음'으로 본다
        return None
    return data if len(data) == 32 else None


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _seed() -> bytes | None:
    raw = (os.getenv("EVIDENCE_SIGN_KEY") or "").strip()
    return _b64d(raw) if raw else None


def configured() -> bool:
    return _seed() is not None


def _private():
    seed = _seed()
    if seed is None:
        return None
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    return Ed25519PrivateKey.from_private_bytes(seed)


def public_key_b64() -> str:
    key = _private()
    if key is None:
        return ""
    from cryptography.hazmat.primitives import serialization
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return _b64e(raw)


def key_id() -> str:
    """공개키 지문 앞 8바이트 — 키를 회전해도 어느 키로 서명했는지 영수증만으로 알 수 있다."""
    pub = public_key_b64()
    return hashlib.sha256(pub.encode()).hexdigest()[:_KEY_ID_LEN * 2] if pub else ""


def public_info() -> dict[str, Any]:
    """/health 에 넣는 공개 정보. 개인키는 절대 나가지 않는다."""
    if not configured():
        return {"configured": False}
    return {"configured": True, "alg": "Ed25519", "public_key": public_key_b64(),
            "key_id": key_id(), "schema": SCHEMA}


def canonical(fields: dict[str, Any]) -> bytes:
    """서명 대상 바이트. 정렬된 키·구분자 고정 — 구현이 다르면 서명이 맞지 않는다(그게 정상)."""
    body = {k: fields.get(k) for k in
            ("challenge", "outcome", "seq", "digest", "created_at", "schema")}
    return DOMAIN + json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sign(fields: dict[str, Any]) -> dict[str, Any]:
    """영수증에 서명 필드를 붙인다. 키가 없으면 signed:false 로 남긴다(거짓 서명을 만들지 않는다)."""
    key = _private()
    if key is None:
        return {**fields, "schema": SCHEMA, "signed": False, "reason": "not_configured"}
    sig = key.sign(canonical({**fields, "schema": SCHEMA}))
    return {**fields, "schema": SCHEMA, "signed": True, "alg": "Ed25519",
            "sig": _b64e(sig), "public_key": public_key_b64(), "key_id": key_id()}


def verify(receipt: dict[str, Any], public_key: str | None = None) -> dict[str, Any]:
    """영수증의 서명을 검증한다. 공개키를 인자로 주면 영수증에 박힌 키를 믿지 않는다(핀 검증).

    반환: {"ok": bool, "reason": str, "key_id": str}
    `ok` 가 True 라는 것은 **서명이 유효하다**는 뜻이지, 탈퇴가 실제로 끝났다는 뜻이 아니다.
    그건 앵커된 체인의 seq·digest 대조가 판정한다.
    """
    if not receipt or receipt.get("signed") is not True:
        return {"ok": False, "reason": "unsigned", "key_id": ""}
    pub_b64 = public_key or receipt.get("public_key") or ""
    if not pub_b64:
        return {"ok": False, "reason": "no_key", "key_id": ""}
    # 핀을 줬다면 '그 키가 맞는지'를 서명 검증보다 먼저 본다. 다른 키로는 당연히 서명이 맞지
    # 않으므로, 순서를 바꾸지 않으면 '키가 다르다'가 '서명 위조'로 잘못 보고된다.
    if public_key:
        expected = hashlib.sha256(pub_b64.encode()).hexdigest()[:_KEY_ID_LEN * 2]
        if expected != (receipt.get("key_id") or ""):
            return {"ok": False, "reason": "key_mismatch", "key_id": expected}
    try:
        raw_sig = base64.urlsafe_b64decode((receipt.get("sig") or "") + "=" * (-len(receipt.get("sig") or "") % 4))
        raw_pub = base64.urlsafe_b64decode(pub_b64 + "=" * (-len(pub_b64) % 4))
    except Exception:  # noqa: BLE001
        return {"ok": False, "reason": "bad_encoding", "key_id": ""}
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    try:
        Ed25519PublicKey.from_public_bytes(raw_pub).verify(raw_sig, canonical(receipt))
    except InvalidSignature:
        return {"ok": False, "reason": "invalid", "key_id": receipt.get("key_id") or ""}
    except Exception:  # noqa: BLE001 — 길이 오류 등
        return {"ok": False, "reason": "bad_key", "key_id": ""}
    kid = hashlib.sha256(pub_b64.encode()).hexdigest()[:_KEY_ID_LEN * 2]
    if public_key and kid != receipt.get("key_id"):
        return {"ok": False, "reason": "key_mismatch", "key_id": kid}
    return {"ok": True, "reason": "valid", "key_id": kid}

def history() -> dict[str, str]:
    """회전해도 옛 영수증을 검증할 수 있게, 지난 공개키를 `EVIDENCE_SIGN_KEYS_OLD` 에 남긴다.

    형식: `kid1:pubkey1,kid2:pubkey2` (kid 는 기존 key_id 와 같은 16자 sha256 앞부분).
    키를 회전하면 옛 영수증은 새 키로 검증되지 않는다 — 그때 "위조"라고 답하면 거짓말이 된다.
    """
    raw = (os.getenv("EVIDENCE_SIGN_KEYS_OLD") or "").strip()
    out: dict[str, str] = {}
    for part in raw.split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        kid, pub = part.split(":", 1)
        kid, pub = kid.strip(), pub.strip()
        if kid and pub:
            out[kid] = pub
    return out


def verify_any(receipt: dict[str, Any]) -> dict[str, Any]:
    """영수증의 key_id 로 알맞은 공개키를 골라 검증한다(현재 키 → 지난 키 순).

    `ok:true` 는 '위조되지 않았다'는 뜻이지 '탈퇴가 끝났다'는 뜻이 아니다.
    """
    kid = str(receipt.get("key_id") or "")
    if kid and kid == key_id():
        return verify(receipt)
    old = history().get(kid)
    if old:
        return verify(receipt, old)
    return verify(receipt)      # 알 수 없는 kid — 영수증에 박힌 키로 검증(핀 없음)
