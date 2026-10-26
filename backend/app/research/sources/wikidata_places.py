"""대체 장소 소스 ① — Wikidata 주변 명소(CC0) + 영어 위키백과 첫 문단(CC BY-SA)으로 설명 보강.

- SPARQL wikibase:around(도시 좌표, 인구 비례 반경) + 정해 둔 종류(P31)만: 관광 명소·박물관·미술관·공원·정원·성·궁전·
  사원·신사·성당·모스크·기념물·랜드마크·광장·전망대·동물원·수족관. 위키 사이트링크 수(인지도)로 정렬해 상위만.
- 질의 틀은 코드 상수, 넣는 값은 숫자(좌표·반경)뿐 — 주입 불가.
- 설명: 영어 위키백과 문서가 있으면 첫 두 문장(prop=extracts, 한 번에 최대 20개), 없으면 Wikidata 짧은 설명.
- 위키백과 주변검색(list=geosearch)은 쓰지 않는다: 종류 정보가 없어 역·학교·관공서가 섞인다(10/26 검토).
"""
from __future__ import annotations

import re
import urllib.parse
from typing import Any

from .. import config, verify
from ..net import SafeHttp, status_of
from . import LICENSES, disabled, result
from .wikidata import _run, _v

# 종류(P31) — 하위 클래스 경로(P279*)는 주변 검색과 겹치면 느려서 쓰지 않고 직접 값만 본다
CLASSES = ("Q570116", "Q33506", "Q207694", "Q22698", "Q1107656", "Q23413", "Q16560", "Q44539", "Q845945",
           "Q16970", "Q2977", "Q32815", "Q4989906", "Q2319498", "Q174782", "Q1440300", "Q43501", "Q2281788",
           "Q1370598", "Q839954", "Q5393308")
_AROUND = """SELECT ?item ?loc ?en ?ko ?desc ?site ?wp ?links WHERE {
SERVICE wikibase:around { ?item wdt:P625 ?loc . bd:serviceParam wikibase:center "Point(%.5f %.5f)"^^geo:wktLiteral .
  bd:serviceParam wikibase:radius "%.1f" . }
VALUES ?cls { %s } ?item wdt:P31 ?cls . ?item wikibase:sitelinks ?links . FILTER(?links >= %d)
OPTIONAL { ?item rdfs:label ?en FILTER(LANG(?en) = "en") }
OPTIONAL { ?item rdfs:label ?ko FILTER(LANG(?ko) = "ko") }
OPTIONAL { ?item schema:description ?desc FILTER(LANG(?desc) = "en") }
OPTIONAL { ?item wdt:P856 ?site }
OPTIONAL { ?wp schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> }
} ORDER BY DESC(?links) LIMIT 120"""
WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
MAX_PLACES = 30
_POINT = re.compile(r"Point\(([-0-9.]+) ([-0-9.]+)\)")


def radius_km(population: int) -> float:
    return 10.0 if population >= 1_000_000 else (6.0 if population >= 200_000 else 4.0)


def _qid(uri: str) -> str:
    q = uri.rsplit("/", 1)[-1]
    return q if re.fullmatch(r"Q\d+", q) else ""


def _title(url: str) -> str:
    return urllib.parse.unquote(url.split("/wiki/", 1)[1]).replace("_", " ") if "/wiki/" in url else ""


def _extracts(http: SafeHttp, titles: list[str]) -> dict[str, str]:
    """영어 위키백과 첫 두 문장. 실패하면 빈 사전(설명만 짧아질 뿐)."""
    if not titles:
        return {}
    q = urllib.parse.urlencode({"action": "query", "format": "json", "formatversion": "2", "prop": "extracts",
                                "exintro": "1", "explaintext": "1", "exsentences": "2", "exlimit": "20",
                                "redirects": "1", "titles": "|".join(titles[:20])})
    res, data = http.get_json(WIKIPEDIA_API + "?" + q, timeout=10)
    if not res.ok:
        return {}
    q_ = (data or {}).get("query") or {}
    back = {r.get("to"): r.get("from") for r in q_.get("redirects") or [] if isinstance(r, dict)}
    out = {}
    for p in q_.get("pages") or []:
        t, text = p.get("title") or "", re.sub(r"\s+", " ", p.get("extract") or "").strip()
        if t and text:
            out[back.get(t, t)] = text[:400]
    return out


def fetch(http: SafeHttp, ref: dict, key: str, limit: int = MAX_PLACES) -> dict:
    """→ SourceResult(data = 장소 목록, 모두 kind=attraction)."""
    if not config.source_on("wikidata"):
        return disabled("wikidata")
    lat, lon = ref.get("lat"), ref.get("lon")
    if lat is None or lon is None:
        return result("wikidata", "empty", reason="no_coords")
    pop = int(ref.get("population") or 0)
    from .. import chain
    query = _AROUND % (float(lon), float(lat), min(30.0, radius_km(pop) * chain.scale(ref)), " ".join("wd:" + c for c in CLASSES),
                       3 if pop >= 200_000 else 2)
    res, rows = _run(http, query)
    if not res.ok:
        return result("wikidata", status_of(res), reason=res.error)
    seen, items = set(), []
    for r in rows:
        qid = _qid(_v(r, "item"))
        m = _POINT.match(_v(r, "loc"))
        name = _v(r, "en") or _v(r, "ko")
        if not qid or qid in seen or not m or not name or re.fullmatch(r"Q\d+", name):
            continue
        seen.add(qid)
        site = _v(r, "site")
        items.append({"qid": qid, "name": name, "ko": _v(r, "ko"), "lon": float(m.group(1)), "lat": float(m.group(2)),
                      "desc": _v(r, "desc"), "site": site if re.fullmatch(r"https?://[^\s\"'<>]{4,300}", site) else "",
                      "wp": _v(r, "wp")})
        if len(items) >= limit:
            break
    if not items:
        return result("wikidata", "empty", reason="no_places")
    ext = _extracts(http, [_title(i["wp"]) for i in items if i["wp"]])
    places = []
    for n, i in enumerate(items):
        wp_title = _title(i["wp"])
        sources = [{"provider": "wikidata", "url": "https://www.wikidata.org/wiki/" + i["qid"], "title": i["name"],
                    "license": LICENSES["wikidata"][0]}]
        if wp_title:
            sources.append({"provider": "wikipedia", "url": i["wp"], "title": wp_title, "license": LICENSES["wikipedia"][0]})
        p = verify.place({"id": f"wd:{key}:{i['qid']}", "name": i["name"], "kind": "attraction", "lat": i["lat"], "lon": i["lon"],
                          "area": "", "desc_en": ext.get(wp_title) or i["desc"], "section": "", "homepage": i["site"],
                          "wikidata": i["qid"], "name_ko": i["ko"], "provider": "wikidata", "sources": sources},
                         lat, lon)
        if p:
            places.append(p)
    return result("wikidata", "ok" if places else "empty", places, url="https://query.wikidata.org/")


def adapter(deps: Any, tc: dict, want: dict) -> dict:
    if not want.get("attraction"):
        return result("wikidata", "empty", reason="not_needed")
    return fetch(deps.http, tc["ref"], tc["ref"]["key"])
