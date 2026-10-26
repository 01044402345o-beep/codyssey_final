"""골든 코퍼스 기대값 갱신 — tests/fixtures/research_golden/*.json(실제 조사 결과를 고정한 것)의 장소 어휘를 다시 계산해
expected/vocab.json 에 쓴다. 어휘 규칙(research/vocab.py)을 바꿨다면 이 스크립트를 돌리고 diff 를 사람이 확인한 뒤 커밋한다.

    cd backend && python scripts/update_research_golden.py          # 갱신
    cd backend && python scripts/update_research_golden.py --check  # 바뀐 장소만 보여 주고 종료 코드 1
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.research import vocab  # noqa: E402

GOLDEN = ROOT / "tests" / "fixtures" / "research_golden"
EXPECTED = GOLDEN / "expected" / "vocab.json"


def compute() -> dict:
    out = {}
    for f in sorted(GOLDEN.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        out[f.stem] = {f"{i:02d} {p['name']}": [[v["en"], v["kind"], v["src"]] for v in vocab.for_place(p)]
                       for i, p in enumerate(d["places"])}           # 같은 이름이 둘일 수 있어 순번을 붙인다
    return out


def main() -> int:
    now = compute()
    if "--check" in sys.argv:
        old = json.loads(EXPECTED.read_text(encoding="utf-8")) if EXPECTED.exists() else {}
        diff = [(c, n) for c in now for n in now[c] if (old.get(c) or {}).get(n) != now[c][n]]
        for c, n in diff[:50]:
            print(f"{c} / {n}: {(old.get(c) or {}).get(n)} -> {now[c][n]}")
        return 1 if diff else 0
    EXPECTED.write_text(json.dumps(now, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("written", EXPECTED, sum(len(v) for v in now.values()), "places")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
