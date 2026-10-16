#!/usr/bin/env python3
"""CI(cron)에서 도는 핀 검증 — 표준 라이브러리만 쓴다(설치 단계 없음).

`security/evidence-key-pin.json` 의 지문·세대와 배포된 앱의 `/health` 보고를 대조한다.
- `armed` 가 false 면 아직 활성화 전이므로 **경고만** 하고 통과한다(레드 크론 소음 방지).
- armed 면 불일치·미보고·연결 실패를 **실패**로 올린다.

운영자용 구현은 `tools/opsarchive` 의 `pin-check` 다(같은 규칙). 이 스크립트는 CI 전용 사본이며,
규칙이 갈라지지 않게 `tools/opsarchive/tests/test_verify_key_pin_script.py` 가 실제로 실행해 검증한다.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request

MISSING = "health_missing_evidence"


def load_pin(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def fetch_health(url: str, timeout: int = 20) -> dict:
    with urllib.request.urlopen(url.rstrip("/") + "/health", timeout=timeout) as res:
        return json.loads(res.read().decode() or "{}")


def check(pin: dict, health: dict) -> list[str]:
    """불일치 이유 목록. 비어 있으면 통과."""
    if not pin.get("armed"):
        return []
    block = health.get("evidence")
    if not isinstance(block, dict) or not block.get("fingerprint"):
        return [MISSING]
    reasons = []
    if str(block.get("fingerprint", "")) != str(pin.get("fingerprint_sha256", "")):
        reasons.append("fingerprint_mismatch")
    runtime_generation = block.get("generation")
    expected = pin.get("generation")
    if not isinstance(runtime_generation, int):
        reasons.append("runtime_generation_missing")
    elif runtime_generation < int(expected or 0):
        reasons.append("generation_lower")
    elif runtime_generation > int(expected or 0):
        reasons.append("generation_higher")
    return reasons


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="증거 봉인 키 핀 검증")
    parser.add_argument("pin")
    parser.add_argument("--health-file", default="", help="테스트용: /health JSON 파일")
    args = parser.parse_args(argv)

    pin = load_pin(args.pin)
    if not pin.get("armed"):
        print("::warning::핀 미활성(armed=false) — keygen/pin 후 활성화하세요")
        return 0
    try:
        health = (json.load(open(args.health_file, encoding="utf-8")) if args.health_file
                  else fetch_health(str(pin.get("health_url", ""))))
    except Exception as exc:        # noqa: BLE001 — 연결 실패도 실패다
        print("::error::/health 를 읽지 못했습니다: %s" % type(exc).__name__)
        return 1
    reasons = check(pin, health)
    if reasons:
        print("::error::핀 검증 실패: %s (pin=%s runtime=%s)" % (
            ", ".join(reasons), pin.get("fingerprint_sha256", "")[:16],
            str((health.get("evidence") or {}).get("fingerprint", ""))[:16]))
        return 1
    print("핀 검증 통과: 세대 %s" % pin.get("generation"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
