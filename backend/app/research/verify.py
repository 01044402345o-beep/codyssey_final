"""코드 검증 — 출처가 없는 장소·이상한 값은 버린다(모델·외부 문서를 믿지 않는다).

- 이름: 비었거나 주입 흔적(<, {, http, @)이 있으면 버린다.
- 좌표: 도시 중심에서 50km 넘으면 다른 동네 장소로 보고 버린다(공항 같은 'go' 는 애초에 장소로 쓰지 않는다).
- 종류: attraction|restaurant|cafe 만.
"""
from __future__ import annotations

import math
import re
from typing import Optional

KINDS = ("attraction", "restaurant", "cafe")
MAX_KM = 50.0
_BAD = re.compile(r"[<>{}]|https?:|www\.|@")


def km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(min(1.0, a)))


def safe_text(s: str, cap: int) -> str:
    s = (s or "").strip()
    return "" if not s or _BAD.search(s) else s[:cap]


def place(p: dict, lat: Optional[float], lon: Optional[float]) -> Optional[dict]:
    name = safe_text(p.get("name", ""), 120)
    if not name or p.get("kind") not in KINDS:
        return None
    if p.get("lat") is not None and p.get("lon") is not None:
        if not (-90 <= p["lat"] <= 90 and -180 <= p["lon"] <= 180):
            p = {**p, "lat": None, "lon": None}
        elif lat is not None and lon is not None and km(lat, lon, p["lat"], p["lon"]) > MAX_KM:
            return None
    desc = p.get("desc_en", "")
    return {**p, "name": name, "desc_en": desc if not re.search(r"[<>{}]", desc) else ""}
