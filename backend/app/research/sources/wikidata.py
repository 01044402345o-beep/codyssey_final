"""Wikidata SPARQL(CC0). 질의는 코드의 고정 틀 + 검증한 값(숫자 id·ISO2)만 넣는다 — 주입 불가.

- city_bridge(gid): GeoNames id(P1566) → 위키데이터 항목·나라·영어 위키보이지 사이트링크
- country_facts(iso2): 통화(P38→P498)·긴급번호(P2852)·운전 방향(P1622)·플러그(P2853)·전압(P2884)·공용어(P37)
"""
from __future__ import annotations

import re
import urllib.parse

from .. import config
from ..net import SafeHttp, status_of
from . import disabled, result

ENDPOINT = "https://query.wikidata.org/sparql"
ACCEPT = {"Accept": "application/sparql-results+json"}

_BRIDGE = """SELECT ?item ?wv WHERE { ?item wdt:P1566 "%d" .
OPTIONAL { ?wv schema:about ?item ; schema:isPartOf <https://en.wikivoyage.org/> } } LIMIT 3"""

# 통화: 지역 한정(P518 '적용 부분')·끝난(P582) 진술을 뺀 '본토' 통화(main). 없으면 아무 통화(any).
# (프랑스는 EUR 과 해외령의 XPF 가 함께 있다 — SAMPLE 로 고르면 XPF 가 나온다.)
_COUNTRY = """SELECT ?country (GROUP_CONCAT(DISTINCT ?cm; separator="|") AS ?main) (GROUP_CONCAT(DISTINCT ?cur; separator="|") AS ?currency)
(GROUP_CONCAT(DISTINCT ?em; separator="|") AS ?emergency)
(SAMPLE(?dsL) AS ?drive) (GROUP_CONCAT(DISTINCT ?plugL; separator="|") AS ?plugs) (SAMPLE(?volt) AS ?voltage)
(GROUP_CONCAT(DISTINCT ?langL; separator="|") AS ?langs) WHERE { ?country wdt:P297 "%s" .
OPTIONAL { ?country wdt:P38/wdt:P498 ?cur }
OPTIONAL { ?country p:P38 ?st . ?st ps:P38/wdt:P498 ?cm . ?st wikibase:rank ?rk . FILTER(?rk != wikibase:DeprecatedRank)
           FILTER NOT EXISTS { ?st pq:P518 [] } FILTER NOT EXISTS { ?st pq:P582 [] } }
OPTIONAL { ?country wdt:P2852 ?e . ?e rdfs:label ?em . FILTER(LANG(?em) = "en") }
OPTIONAL { ?country wdt:P1622 ?ds . ?ds rdfs:label ?dsL . FILTER(LANG(?dsL) = "en") }
OPTIONAL { ?country wdt:P2853 ?p . ?p rdfs:label ?plugL . FILTER(LANG(?plugL) = "en") }
OPTIONAL { ?country wdt:P2884 ?volt }
OPTIONAL { ?country wdt:P37 ?l . ?l rdfs:label ?langL . FILTER(LANG(?langL) = "en") } } GROUP BY ?country LIMIT 1"""


# 위 규칙으로도 하나로 안 정해지는 나라(2026-10 전수 확인: 주권국 196곳 중 12곳). 여행자가 실제로 쓰는 통화.
CURRENCY_FIX = {"CL": "CLP", "CZ": "CZK", "LR": "LRD", "LS": "LSL", "LT": "EUR", "NA": "NAD", "NL": "EUR",
                "PA": "USD", "PL": "PLN", "PS": "ILS", "TW": "TWD", "ZW": "USD"}


def pick_currency(iso2: str, main: str, anyc: str) -> str:
    if iso2 in CURRENCY_FIX:
        return CURRENCY_FIX[iso2]
    for group in (main, anyc):
        codes = sorted(c for c in group.split("|") if re.fullmatch(r"[A-Z]{3}", c))
        if codes:
            return codes[0]
    return ""


def _run(http: SafeHttp, query: str) -> "tuple[object, list[dict]]":
    res, data = http.get_json(ENDPOINT + "?" + urllib.parse.urlencode({"query": query, "format": "json"}),
                              headers=ACCEPT, timeout=12)
    rows = (((data or {}).get("results") or {}).get("bindings")) or []
    return res, rows


def _v(row: dict, key: str) -> str:
    return str((row.get(key) or {}).get("value") or "")


def city_bridge(http: SafeHttp, gid: int) -> dict:
    if not config.source_on("wikidata"):
        return disabled("wikidata")
    if type(gid) is not int or gid <= 0:
        return result("wikidata", "empty", reason="no_gid")
    res, rows = _run(http, _BRIDGE % gid)
    if not res.ok:
        return result("wikidata", status_of(res), reason=res.error)
    if not rows:
        return result("wikidata", "empty", reason="no_item")
    qid = _v(rows[0], "item").rsplit("/", 1)[-1]
    wv = next((_v(r, "wv") for r in rows if _v(r, "wv")), "")
    title = urllib.parse.unquote(wv.split("/wiki/", 1)[1]).replace("_", " ") if "/wiki/" in wv else ""
    return result("wikidata", "ok", {"qid": qid if re.fullmatch(r"Q\d+", qid) else "", "wikivoyage": title},
                  url="https://www.wikidata.org/wiki/" + qid)


def _split(v: str, limit: int, maxlen: int = 40) -> list[str]:
    out = [x.strip()[:maxlen] for x in v.split("|") if x.strip()]
    return list(dict.fromkeys(out))[:limit]


def country_facts(http: SafeHttp, iso2: str) -> dict:
    if not config.source_on("wikidata"):
        return disabled("wikidata")
    if not re.fullmatch(r"[A-Z]{2}", iso2 or ""):
        return result("wikidata", "empty", reason="no_iso2")
    res, rows = _run(http, _COUNTRY % iso2)
    if not res.ok:
        return result("wikidata", status_of(res), reason=res.error)
    if not rows:
        return result("wikidata", "empty", reason="no_country")
    r = rows[0]
    qid = _v(r, "country").rsplit("/", 1)[-1]
    cur = pick_currency(iso2, _v(r, "main"), _v(r, "currency"))
    emergency = [e for e in _split(_v(r, "emergency"), 6, 12) if re.fullmatch(r"[0-9 +\-]{2,12}", e)]
    volt = _v(r, "voltage")
    data = {
        "qid": qid if re.fullmatch(r"Q\d+", qid) else "",
        "currency": cur if re.fullmatch(r"[A-Z]{3}", cur) else "",
        "emergency": emergency,
        "driving_side": _v(r, "drive")[:10],
        "plugs": _split(_v(r, "plugs"), 6),
        "voltage": volt.split(".")[0] if re.fullmatch(r"\d{2,3}(\.\d+)?", volt) else "",
        "languages": _split(_v(r, "langs"), 6),
    }
    return result("wikidata", "ok", data, url="https://www.wikidata.org/wiki/" + data["qid"] if data["qid"] else "")



# 이름만 있는 도시(GeoNames 에서 못 찾음): Wikidata 검색 API(별칭·'~시' 포함, 빠름) → 같은 나라(P17)·좌표(P625)가 있는 첫 항목.
# SPARQL 라벨 일치는 한국어 라벨이 '경주시'·'가마쿠라시' 라 놓치고, 질의 서비스 지연이 2~25초로 들쭉날쭉했다(10/26 실측).
ACTION_API = "https://www.wikidata.org/w/api.php"
_SAFE_NAME = re.compile(r"^[^\"\\\r\n<>{}|]{1,60}$")


def _claim_ids(claims: dict, pid: str) -> list[str]:
    return [((c.get("mainsnak") or {}).get("datavalue") or {}).get("value", {}).get("id") for c in claims.get(pid) or []
            if isinstance(((c.get("mainsnak") or {}).get("datavalue") or {}).get("value"), dict)]


def _value(cl: dict, pid: str) -> dict:
    v = (((cl.get(pid) or [{}])[0].get("mainsnak") or {}).get("datavalue") or {}).get("value")
    return v if isinstance(v, dict) else {}


def _current_ids(cl: dict, pid: str) -> list[str]:
    """끝난(P582 종료 시점) 진술은 빼고, 우선 순위(preferred) 진술을 앞에."""
    rows = [c for c in cl.get(pid) or [] if not (c.get("qualifiers") or {}).get("P582") and c.get("rank") != "deprecated"]
    rows.sort(key=lambda c: c.get("rank") != "preferred")
    return [((c.get("mainsnak") or {}).get("datavalue") or {}).get("value", {}).get("id") for c in rows
            if isinstance(((c.get("mainsnak") or {}).get("datavalue") or {}).get("value"), dict)]


def _pop(cl: dict) -> int:
    try:
        return max(0, int(float(str(_value(cl, "P1082").get("amount", "0")))))
    except (TypeError, ValueError):
        return 0


def _entities(http: SafeHttp, ids: list[str]) -> "tuple[object, dict]":
    res, e = http.get_json(ACTION_API + "?" + urllib.parse.urlencode({
        "action": "wbgetentities", "ids": "|".join(ids), "props": "claims|sitelinks|labels", "languages": "en",
        "sitefilter": "enwikivoyage", "format": "json"}), timeout=8)
    return res, ((e or {}).get("entities") or {}) if res.ok else {}


def _city_data(q: str, ent: dict, via: dict | None = None) -> dict:
    cl = ent.get("claims") or {}
    coord = _value(cl, "P625")
    return {"qid": q, "lat": float(coord["latitude"]), "lon": float(coord["longitude"]),
            "name_en": str(((ent.get("labels") or {}).get("en") or {}).get("value") or "")[:80], "population": _pop(cl),
            "wikivoyage": str(((ent.get("sitelinks") or {}).get("enwikivoyage") or {}).get("title") or "")[:120],
            **({"via": via} if via else {})}


def city_by_name(http: SafeHttp, country_qid: str, name: str) -> dict:
    """→ data {qid, lat, lon, name_en, population, wikivoyage, via?}. country_qid 는 나라 사실(country_facts)의 qid.

    같은 나라 항목 중에서 고른다:
      1) 좌표가 있으면 그대로(인구가 있는 항목 → 검색 순서).
      2) 좌표가 없고 해산된(P576) 옛 행정구역이면 '통합됨'(P7888)·'대체됨'(P1366)이 가리키는 지금의 도시로
         — 예: 옥구군(1995 해산) → 군산시. via = {kind: "merged", from: 옛 항목}.
      3) 좌표가 없고 상위 행정구역(P131)만 있으면(신생 구역 등) 그 상위 구역 좌표로 — via = {kind: "parent"}.
    2)·3)은 호출이 한 번 더 든다."""
    if not config.source_on("wikidata"):
        return disabled("wikidata")
    name = (name or "").strip()
    if not re.fullmatch(r"Q\d+", country_qid or "") or not _SAFE_NAME.fullmatch(name):
        return result("wikidata", "empty", reason="bad_input")
    lang = "en" if name.isascii() else "ko"
    res, s = http.get_json(ACTION_API + "?" + urllib.parse.urlencode({
        "action": "wbsearchentities", "search": name, "language": lang, "uselang": lang, "type": "item", "limit": 7,
        "format": "json"}), timeout=8)
    if not res.ok:
        return result("wikidata", status_of(res), reason=res.error)
    ids = [x.get("id") for x in (s or {}).get("search") or [] if re.fullmatch(r"Q\d+", str(x.get("id")))]
    if not ids:
        return result("wikidata", "empty", reason="no_item")
    res, ents = _entities(http, ids)
    if not res.ok:
        return result("wikidata", status_of(res), reason=res.error)
    direct, merged, parent = [], [], []
    for order, q in enumerate(ids):
        ent = ents.get(q) or {}
        cl = ent.get("claims") or {}
        if country_qid not in _claim_ids(cl, "P17"):
            continue
        if "latitude" in _value(cl, "P625"):
            direct.append((_pop(cl) == 0, order, q, ent))
            continue
        succ = _claim_ids(cl, "P7888") or _claim_ids(cl, "P1366")
        if cl.get("P576") and succ:
            merged.append((order, q, succ[0]))
            continue
        up = _current_ids(cl, "P131")
        if up:
            parent.append((order, q, up[0]))
    if direct:
        _, _, q, ent = min(direct, key=lambda h: (h[0], h[1]))
        return result("wikidata", "ok", _city_data(q, ent), url="https://www.wikidata.org/wiki/" + q)
    for kind, rows in (("merged", merged), ("parent", parent)):
        if not rows:
            continue
        _, old, target = rows[0]
        if not re.fullmatch(r"Q\d+", target or ""):
            continue
        res, more = _entities(http, [target])
        if not res.ok:
            return result("wikidata", status_of(res), reason=res.error)
        ent = more.get(target) or {}
        if "latitude" not in _value(ent.get("claims") or {}, "P625"):
            continue
        label = str(((ent.get("labels") or {}).get("en") or {}).get("value") or "")[:80]
        return result("wikidata", "ok", _city_data(target, ent, {"kind": kind, "from": old, "label": label}),
                      url="https://www.wikidata.org/wiki/" + target)
    return result("wikidata", "empty", reason="no_item")
