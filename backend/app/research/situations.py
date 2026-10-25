"""영어 상황(situation_id) 목록 — 계약(agent_contract/categories/*.json)에서 읽는다.

조사 추출(LLM)이 실용 정보마다 '이때 필요한 영어 상황'을 고를 수 있게 넘기고, 검증기는 이 목록 밖의 id 를 버린다.
주제별로 고를 수 있는 카테고리를 좁힌다(교통 정보에 식당 상황이 붙지 않게).
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

# 실용 정보 주제 → 고를 수 있는 카테고리
TOPIC_CATEGORIES = {
    "transport_airport": ("transport",), "transport_local": ("transport",), "tipping": ("restaurant",),
    "etiquette": ("restaurant", "lodging"), "cope": ("lodging", "restaurant"), "connect": ("lodging",),
    "safety": (), "health": ("restaurant",), "language": (),
}


def _contract_dir() -> Path:
    root = Path(__file__).resolve().parents[3]
    return Path(os.getenv("CONTRACT_DIR") or (root / "agent_contract"))


@lru_cache(maxsize=1)
def by_category() -> dict[str, tuple[str, ...]]:
    out: dict[str, tuple[str, ...]] = {}
    for p in sorted((_contract_dir() / "categories").glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out[p.stem] = tuple(s["situation_id"] for s in data.get("situations") or []
                            if isinstance(s, dict) and isinstance(s.get("situation_id"), str))
    return out


def allowed(topic: str) -> tuple[str, ...]:
    cats = by_category()
    return tuple(sid for c in TOPIC_CATEGORIES.get(topic, ()) for sid in cats.get(c, ()))
