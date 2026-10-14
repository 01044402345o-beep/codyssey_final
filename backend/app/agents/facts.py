"""장소·상황 사실. LLM 호출은 없다.

식당·카페 좌표와 주소는 카카오 키워드 검색 한 번만 확정한다.
식이·포장·조식·와이파이는 그 좌표가 있을 때만 OSM Overpass 한 번이다.
키가 없거나 실패하거나 0건이면 status로 드러낸다. 빈 목록을 성공으로 두지 않는다.
이 모듈은 구글 지도 엔드포인트를 호출하지 않는다.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable

KAKAO_SEARCH = "https://dapi.kakao.com/v2/local/search/keyword.json"
OSM_INTERPRETER = "https://overpass-api.de/api/interpreter"
USER_AGENT = "CodysseyFactBot/1.0 (educational travel-english facts)"

# 계약 상황 중 API 태그로 확정할 수 있는 것만. 나머지는 문장 에이전트 몫이다.
OSM_SITUATIONS = ("allergy_notice", "takeout", "ask_breakfast", "ask_wifi")

Http = Callable[[str, dict[str, str], float], tuple[int, dict[str, Any]]]


def kakao_configured() -> bool:
    return bool((os.getenv("KAKAO_REST_API_KEY") or "").strip())


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _redact(text: str, secret: str) -> str:
    if secret and secret in text:
        return text.replace(secret, "***")
    return text


class _StripAuthOnRedirect(urllib.request.HTTPRedirectHandler):
    """리다이렉트된 다른 호스트로 카카오 키가 나가지 않게 한다."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None:
            new.remove_header("Authorization")
        return new


def _default_http(url: str, headers: dict[str, str], timeout: float) -> tuple[int, dict[str, Any]]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **headers})
    opener = urllib.request.build_opener(_StripAuthOnRedirect)
    try:
        with opener.open(req, timeout=timeout) as res:
            return res.status, json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, {}


def _num(value: Any, lo: float, hi: float) -> float | None:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    if n < lo or n > hi:
        return None
    return n


def _box(status: str, reason: str, items: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"status": status, "reason": reason, "items": items or []}


def _kakao_query(city: str, places: list[dict[str, Any]]) -> str:
    types = [str(p.get("place_type") or "").strip().lower() for p in places]
    names = [str(p.get("name")).strip() for p in places if str(p.get("name") or "").strip()]
    kind = "카페" if types and all(t == "cafe" for t in types) else "맛집"
    if names:
        return f"{city} {names[0]} {kind}"
    return f"{city} {kind}"


def _kakao_places(city: str, places: list[dict[str, Any]], http: Http, timeout: float) -> dict[str, Any]:
    key = (os.getenv("KAKAO_REST_API_KEY") or "").strip()
    if not key:
        return _box("unavailable", "KAKAO_REST_API_KEY 없음")
    query = _kakao_query(city, places)
    url = KAKAO_SEARCH + "?" + urllib.parse.urlencode({"query": query, "size": 5})
    try:
        status, body = http(url, {"Authorization": f"KakaoAK {key}"}, timeout)
    except Exception as exc:  # noqa: BLE001 — 조회 실패가 문장 생성을 죽이지 않게
        return _box("failed", _redact(f"{type(exc).__name__}", key))
    if status != 200 or not isinstance(body, dict):
        return _box("failed", f"kakao http {status}")
    docs = body.get("documents")
    if not isinstance(docs, list) or not docs:
        return _box("unavailable", "검색 결과 0건")
    found = _now()
    items: list[dict[str, Any]] = []
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        name = str(doc.get("place_name") or "").strip()
        source = str(doc.get("place_url") or "").strip()
        lat = _num(doc.get("y"), -90, 90)
        lon = _num(doc.get("x"), -180, 180)
        if not name or not source or lat is None or lon is None:
            continue
        items.append({
            "name": name,
            "address": str(doc.get("road_address_name") or doc.get("address_name") or ""),
            "lat": lat,
            "lon": lon,
            "source_type": "kakao",
            "source_url": source,
            "retrieved_at": found,
            "status": "verified",
        })
    if not items:
        return _box("unavailable", "좌표와 출처가 있는 장소가 없다")
    return _box("verified", "", items)


def _wanted(situation_ids: list[str]) -> list[str]:
    seen: list[str] = []
    for sid in situation_ids:
        if sid in OSM_SITUATIONS and sid not in seen:
            seen.append(sid)
    return seen


def _overpass_ql(lat: float, lon: float) -> str:
    return (
        f"[out:json][timeout:8];"
        f"(node[\"amenity\"~\"restaurant|cafe|fast_food\"](around:400,{lat},{lon});"
        f"way[\"amenity\"~\"restaurant|cafe|fast_food\"](around:400,{lat},{lon}););"
        f"out tags center 5;"
    )


def _osm_item(situation_id: str, claim: str, value: Any, element: dict[str, Any], found: str) -> dict[str, Any] | None:
    typ = element.get("type")
    eid = element.get("id")
    if typ not in ("node", "way", "relation") or not isinstance(eid, int):
        return None
    return {
        "situation_id": situation_id,
        "claim": claim,
        "value": value,
        "source_type": "osm",
        "source_url": f"https://www.openstreetmap.org/{typ}/{eid}",
        "retrieved_at": found,
        "status": "verified",
    }


def _tags_for(element: dict[str, Any], wanted: list[str], found: str) -> list[dict[str, Any]]:
    tags = element.get("tags") if isinstance(element.get("tags"), dict) else {}
    out: list[dict[str, Any]] = []
    if "allergy_notice" in wanted:
        diet = {k.split(":", 1)[1]: v for k, v in tags.items()
                if k.startswith("diet:") and "password" not in k.lower()}
        if diet:
            item = _osm_item("allergy_notice", "diet tags", diet, element, found)
            if item:
                out.append(item)
    if "takeout" in wanted and tags.get("takeaway") and "password" not in str(tags.get("takeaway")).lower():
        item = _osm_item("takeout", f"takeaway={tags.get('takeaway')}", tags.get("takeaway"), element, found)
        if item:
            out.append(item)
    if "ask_breakfast" in wanted and tags.get("breakfast"):
        item = _osm_item("ask_breakfast", f"breakfast={tags.get('breakfast')}", tags.get("breakfast"), element, found)
        if item:
            out.append(item)
    if "ask_wifi" in wanted and tags.get("internet_access"):
        wifi = {"internet_access": tags.get("internet_access")}
        if tags.get("internet_access:fee"):
            wifi["fee"] = tags.get("internet_access:fee")
        item = _osm_item("ask_wifi", "internet_access", wifi, element, found)
        if item:
            out.append(item)
    return out


def _osm_facts(wanted: list[str], places: dict[str, Any], http: Http, timeout: float) -> dict[str, Any]:
    if not wanted:
        return _box("unavailable", "이 카테고리에 조회할 상황 사실이 없다")
    origin = next((p for p in places.get("items") or [] if places.get("status") == "verified"), None)
    if not origin:
        return _box("unavailable", "좌표 없음")
    ql = _overpass_ql(origin["lat"], origin["lon"])
    url = OSM_INTERPRETER + "?" + urllib.parse.urlencode({"data": ql})
    try:
        status, body = http(url, {}, timeout)
    except Exception as exc:  # noqa: BLE001
        return _box("failed", type(exc).__name__)
    if status != 200 or not isinstance(body, dict):
        return _box("failed", f"osm http {status}")
    elements = body.get("elements")
    if not isinstance(elements, list) or not elements:
        return _box("unavailable", "주변 태그 없음")
    found = _now()
    items: list[dict[str, Any]] = []
    covered: set[str] = set()
    for el in elements:
        if not isinstance(el, dict):
            continue
        for item in _tags_for(el, wanted, found):
            if item["situation_id"] in covered:
                continue
            covered.add(item["situation_id"])
            items.append(item)
    if not items:
        return _box("unavailable", "해당 태그가 없다")
    return _box("verified", "", items)


def collect_facts(
    *,
    category_id: str,
    city: str,
    places: list[dict[str, Any]],
    situation_ids: list[str],
    http: Http | None = None,
    kakao_timeout: float = 5.0,
    osm_timeout: float = 8.0,
) -> dict[str, Any]:
    """한 생성 요청의 사실. 예외를 올리지 않는다."""
    call = http or _default_http
    try:
        if category_id != "restaurant":
            located = _box("unavailable", "식당·카페만 조회한다")
        else:
            located = _kakao_places(city, places, call, kakao_timeout)
        situations = _osm_facts(_wanted(situation_ids), located, call, osm_timeout)
    except Exception as exc:  # noqa: BLE001
        return {
            "places": _box("failed", type(exc).__name__),
            "situations": _box("failed", type(exc).__name__),
        }
    return {"places": located, "situations": situations}


def facts_clause(facts: dict[str, Any]) -> str:
    """프롬프트에 붙이는 사실. verified만 사실이고 나머지는 말하지 말라고 적는다."""
    return (
        "\n\nVERIFIED_FACTS:\n"
        + json.dumps(facts, ensure_ascii=False)
        + "\nOnly items with status verified are facts. "
        "Do not invent place names, addresses, diet, takeaway, breakfast, or wifi. "
        "Do not state unavailable or failed items as facts."
    )
