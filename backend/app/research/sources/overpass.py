"""대체 장소 소스 ② — OpenStreetMap Overpass(ODbL, "© OpenStreetMap contributors"). 식당·카페가 주 목적, 관광지도 보탠다.

기본 체인에서는 꺼져 있다(config.DEFAULT_PLACE_CHAIN). 2026-10-26 확인: 공용 overpass-api.de 가 포화(502) 응답에서
"공용 엔드포인트는 사람이 쓰는 도구용, 자동화·대량 사용은 자체 인스턴스"라고 안내하고, 다른 공용 인스턴스도 응답이 없었다.
쓸 수 있는 인스턴스가 생기면 RESEARCH_PLACE_CHAIN 에 overpass 를 넣는다(호스트는 net.ALLOWED_HOSTS 로만).

- 도시당 한 번(모자란 종류만): amenity=restaurant|cafe(도심 반경 1.5–3km), tourism=attraction|museum|gallery|viewpoint(3–8km).
  이름(name)이 있는 것만. 질의 틀은 코드 상수, 넣는 값은 숫자뿐.
- 결과 순서는 의미가 없어서(요소 id 순) 코드가 다시 고른다: wikidata 태그·웹사이트·영업시간·요리 종류·영어 이름이 있을수록,
  도심에 가까울수록 앞. 공용 인스턴스 정책(하루 ~1만 회·1GB)을 넘지 않게 결과 상한·질의 타임아웃(25초)을 둔다.
- 설명은 태그에서만 만든다(요리 종류·영업시간). 지어내는 문장은 없다.
"""
from __future__ import annotations

import re
import urllib.parse
from typing import Any

from .. import config, verify
from ..net import SafeHttp, status_of
from . import LICENSES, disabled, result

ENDPOINT = "https://overpass-api.de/api/interpreter"
_Q = """[out:json][timeout:25];(%s);out center tags 250;"""
_FOOD = 'nwr(around:%d,%.5f,%.5f)["amenity"~"^(restaurant|cafe)$"]["name"];'
_SIGHT = 'nwr(around:%d,%.5f,%.5f)["tourism"~"^(attraction|museum|gallery|viewpoint)$"]["name"];'
_NAME_OK = re.compile(r"^[^<>{}@]{1,120}$")


def radii_m(population: int) -> "tuple[int, int]":
    """(식당·카페, 관광지) 반경."""
    if population >= 1_000_000:
        return 3000, 8000
    if population >= 200_000:
        return 2000, 5000
    return 1500, 3000


def _kind(tags: dict) -> str:
    a = tags.get("amenity")
    if a == "restaurant":
        return "restaurant"
    if a == "cafe":
        return "cafe"
    return "attraction" if tags.get("tourism") else ""


def _desc(tags: dict) -> str:
    bits = []
    if tags.get("cuisine"):
        bits.append("Cuisine: " + tags["cuisine"].replace(";", ", ").replace("_", " ")[:60] + ".")
    if tags.get("tourism") in ("museum", "gallery", "viewpoint"):
        bits.append(tags["tourism"].capitalize() + ".")
    if tags.get("opening_hours"):
        bits.append("Opening hours (OpenStreetMap): " + tags["opening_hours"][:80] + ".")
    return " ".join(bits)


def _score(tags: dict, d_km: float) -> float:
    return (3 * bool(tags.get("wikidata")) + bool(tags.get("website") or tags.get("contact:website"))
            + bool(tags.get("opening_hours")) + bool(tags.get("cuisine")) + bool(tags.get("name:en")) - d_km / 5)


def fetch(http: SafeHttp, ref: dict, key: str, want: dict) -> dict:
    if not config.source_on("overpass"):
        return disabled("osm")
    lat, lon = ref.get("lat"), ref.get("lon")
    if lat is None or lon is None:
        return result("osm", "empty", reason="no_coords")
    from .. import chain
    rf, rs = (int(r * chain.scale(ref)) for r in radii_m(int(ref.get("population") or 0)))
    parts = ([_FOOD % (rf, lat, lon)] if want.get("food") else []) + ([_SIGHT % (rs, lat, lon)] if want.get("attraction") else [])
    if not parts:
        return result("osm", "empty", reason="not_needed")
    body = urllib.parse.urlencode({"data": _Q % "".join(parts)}).encode("ascii")
    res = http.request("POST", ENDPOINT, body=body, timeout=20,
                       headers={"Content-Type": "application/x-www-form-urlencoded"})
    data = res.json() if res.ok else None
    if not res.ok or not isinstance(data, dict):
        return result("osm", status_of(res) if not res.ok else "unavailable", reason=res.error or "bad_json")
    picked = []
    for el in data.get("elements") or []:
        if not isinstance(el, dict) or el.get("type") not in ("node", "way", "relation"):
            continue
        tags = el.get("tags") or {}
        c = el.get("center") or el
        try:
            plat, plon = float(c["lat"]), float(c["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        kind = _kind(tags)
        name = (tags.get("name:en") or tags.get("name") or "").strip()
        if not kind or not _NAME_OK.match(name) or tags.get("disused") or tags.get("abandoned"):
            continue
        picked.append((_score(tags, verify.km(lat, lon, plat, plon)), el["type"], int(el.get("id") or 0), tags, kind, name, plat, plon))
    picked.sort(key=lambda x: -x[0])
    limits = {"attraction": 3 * want.get("attraction", 0), "food": 3 * want.get("food", 0)}
    out, used = [], {"attraction": 0, "food": 0}
    for _, etype, eid, tags, kind, name, plat, plon in picked:
        bucket = "attraction" if kind == "attraction" else "food"
        if used[bucket] >= limits[bucket]:
            continue
        site = tags.get("website") or tags.get("contact:website") or ""
        wd = tags.get("wikidata") or ""
        url = f"https://www.openstreetmap.org/{etype}/{eid}"
        p = verify.place({"id": f"osm:{key}:{etype[0]}{eid}", "name": name, "kind": kind, "lat": plat, "lon": plon,
                          "area": "", "desc_en": _desc(tags), "section": "",
                          "homepage": site if re.fullmatch(r"https?://[^\s\"'<>]{4,300}", site) else "",
                          "wikidata": wd if re.fullmatch(r"Q\d+", wd) else "", "name_local": tags.get("name", "")[:120],
                          "provider": "osm",
                          "sources": [{"provider": "osm", "url": url, "title": name, "license": LICENSES["osm"][0]}]},
                         lat, lon)
        if p:
            used[bucket] += 1
            out.append(p)
    return result("osm", "ok" if out else "empty", out, url="https://www.openstreetmap.org/")


def adapter(deps: Any, tc: dict, want: dict) -> dict:
    return fetch(deps.http, tc["ref"], tc["ref"]["key"], want)
