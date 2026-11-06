"""탈퇴 영수증 검증 CLI — 서버 없이, 영수증 파일만으로.

    python -m app.verify_receipt withdraw-proof-xxxx.json
    python -m app.verify_receipt proof.json --pin <공개키 base64url>   # /health 의 값을 붙여 넣는다

검증하는 것: 서명이 유효한가(위조되지 않았는가). 검증하지 않는 것: 탈퇴가 실제로 끝났는가 —
그건 관리자가 앵커한 증거 체인의 seq·digest 와 대조해야 판정된다.

`--pin` 을 주면 영수증에 박힌 공개키를 믿지 않는다. 사용자가 내려받은 파일을 그대로
믿으면 서명 검증이 무의미해지므로, 실무에서는 핀을 주는 쪽이 옳다.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import receipt_signing


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="verify_receipt", description="탈퇴 영수증 서명 검증")
    ap.add_argument("path", type=Path, help="영수증 JSON 파일")
    ap.add_argument("--pin", default=None, help="공개키(base64url) — 주면 영수증에 박힌 키를 믿지 않는다")
    a = ap.parse_args(argv)

    try:
        doc = json.loads(a.path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"읽지 못했어요: {exc}")
        return 2

    receipt = doc.get("receipt") or doc          # 내보낸 파일은 {receipt:{...}} 로 감싸여 있다
    res = receipt_signing.verify(receipt, a.pin)

    print(f"파일     : {a.path}")
    print(f"챌린지   : {receipt.get('challenge')}")
    print(f"결과     : {receipt.get('outcome')} (체인 seq {receipt.get('seq')})")
    print(f"키 지문  : {res['key_id'] or receipt.get('key_id') or '-'}")
    if res["ok"]:
        print("서명     : 유효 — 이 영수증은 해당 키로 서명된 뒤 바뀌지 않았다")
        if not a.pin:
            print("           (--pin 을 주면 '그 키가 진짜 서버 키인지'까지 확인합니다)")
        return 0
    reason = {"unsigned": "서명 없음 — 내보낸 시점에 서버 서명 키가 설정되지 않았다",
              "invalid": "서명 불일치 — 파일이 바뀌었거나 다른 키로 만들어졌다",
              "key_mismatch": "핀한 공개키와 영수증의 키가 다르다",
              "no_key": "공개키가 없다", "bad_encoding": "서명/키 형식이 깨졌다",
              "bad_key": "공개키 길이가 올바르지 않다"}.get(res["reason"], res["reason"])
    print(f"서명     : 무효 — {reason}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
