"""각 카테고리의 negative_cases 가 실제로 걸러지는지 자체 점검.

실행:  cd backend && python scripts/check_negatives.py
실패하면 종료코드 1.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.validators import validate_sentence

CONTRACT = BACKEND.parent / "agent_contract"
CATEGORY_DIR = CONTRACT / "categories"


def main() -> int:
    total = failed = 0
    for path in sorted(CATEGORY_DIR.glob("*.json")):
        cfg = json.loads(path.read_text(encoding="utf-8"))
        patterns = cfg.get("negative_case_patterns", {})
        for case in cfg.get("negative_cases", []):
            total += 1
            seen: set[str] = set()
            # 중복은 "두 번째 등장"에서만 잡히므로, 테스트에서는 같은 문장을 먼저 넣어둔다.
            if case.get("expect") == "duplicate_en":
                seen.add((case["sentence"].get("en") or "").lower())
            issues = validate_sentence(case["sentence"], cfg, patterns, seen)
            codes = {i["code"] for i in issues}
            ok = case["expect"] in codes
            mark = "PASS" if ok else "FAIL"
            print(f"[{mark}] {cfg['category_id']}/{case['case_id']}  expect={case['expect']}  got={sorted(codes)}")
            if not ok:
                failed += 1

    print(f"\n{total - failed}/{total} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
