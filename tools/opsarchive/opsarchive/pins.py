"""검증키 핀 고정 — '예상 밖 키'를 조기에 잡는 최소 장치.

무엇을 하는가: 관리자가 **개인키에서 역산해** 공개키 지문을 저장소 파일(`security/evidence-key-pin.json`)에
직접 커밋하고, CI(cron)가 배포된 앱의 `/health` 가 보고하는 지문·세대와 대조한다.

무엇을 하지 못하는가(정직하게):
- 저장소와 CI 를 함께 장악한 공격자는 핀 자체를 바꿀 수 있다 → **앵커는 저장소 밖이어야** 한다
  (관리자 오프라인 키·서명 태그·투명성 로그). 이 파일은 그 첫 겹일 뿐이다.
- 앱을 완전히 장악한 공격자가 자기 키로 서명·보고하면 이 검사로는 구분할 수 없다(TEE 없이는 불가).

그래서 `armed` 가 false 인 동안은 "미활성"으로 보고하고, true 가 되면 불일치를 **실패**로 올린다.
"""

from __future__ import annotations

import json
import urllib.request

SCHEMA = 1
GENERATION_MAX = 1_000_000


class PinError(Exception):
    """code: bad_pin | generation_regression | unwritable"""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def read(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        pin = json.load(fh)
    if not isinstance(pin, dict) or pin.get("schema") != SCHEMA:
        raise PinError("bad_pin")
    return pin


def write(path: str, pin: dict) -> dict:
    """핀을 쓴다. **세대(generation)를 낮추는 것은 거부한다** — 회전 되돌리기(rollback)를 막는다."""
    if pin.get("schema") != SCHEMA:
        raise PinError("bad_pin")
    generation = int(pin.get("generation", 0))
    if not 0 <= generation <= GENERATION_MAX:
        raise PinError("bad_pin")
    try:
        old = read(path)
    except FileNotFoundError:
        old = None
    except PinError:
        old = None
    if old and int(old.get("generation", 0)) > generation:
        raise PinError("generation_regression")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(pin, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    return pin


def make(public_key: bytes, fingerprint: str, key_id: str, *, generation: int,
         health_url: str, commit: str = "", armed: bool = True, note: str = "") -> dict:
    """핀 문서를 만든다(개인키에서 역산한 값만 넣는다 — 앱이 알려준 값을 그대로 믿지 않는다)."""
    from . import container as C      # 순환 import 를 피하려고 함수 안에서 가져온다
    return {
        "schema": SCHEMA,
        "armed": bool(armed),
        "generation": int(generation),
        "key_id": key_id,
        "fingerprint_sha256": fingerprint,
        "public_key": C.pack_public_key(public_key),
        "health_url": health_url.rstrip("/"),
        "rotated_by_commit": commit,
        "note": note,
    }


def fetch_health(health_url: str, timeout: int = 20) -> dict:
    url = health_url.rstrip("/") + "/health"
    with urllib.request.urlopen(url, timeout=timeout) as res:
        return json.loads(res.read().decode() or "{}")


def compare(pin: dict, health: dict) -> dict:
    """핀과 런타임 보고를 대조한다. reasons 가 비어 있고 armed 면 ok."""
    out = {"armed": bool(pin.get("armed")), "ok": None, "reasons": [],
           "pin_fingerprint": pin.get("fingerprint_sha256", ""),
           "runtime_fingerprint": "", "pin_generation": int(pin.get("generation", 0)),
           "runtime_generation": None, "runtime_key_id": ""}
    if not out["armed"]:
        out["reasons"].append("unarmed")
        return out
    block = health.get("evidence")
    if not isinstance(block, dict) or not block.get("fingerprint"):
        out["reasons"].append("health_missing_evidence")
        out["ok"] = False
        return out
    out["runtime_fingerprint"] = str(block.get("fingerprint", ""))
    out["runtime_key_id"] = str(block.get("key_id", ""))
    raw_generation = block.get("generation")
    out["runtime_generation"] = int(raw_generation) if isinstance(raw_generation, int) else None

    if out["runtime_fingerprint"] != out["pin_fingerprint"]:
        out["reasons"].append("fingerprint_mismatch")
    if out["runtime_generation"] is None:
        out["reasons"].append("runtime_generation_missing")
    elif out["runtime_generation"] != out["pin_generation"]:
        # 낮으면 되돌리기(옛 키로 복귀), 높으면 핀을 안 올린 회전 — 둘 다 사람이 봐야 한다
        out["reasons"].append("generation_lower" if out["runtime_generation"] < out["pin_generation"]
                              else "generation_higher")
    out["ok"] = not out["reasons"]
    return out
