"""장소·상황 사실. LLM 호출은 없다.

식당·카페 좌표와 주소는 카카오 키워드 검색 한 번만 확정한다.
포장·조식·와이파이는 그 좌표가 있을 때만 OSM Overpass 한 번이다.
키가 없거나 실패하거나 0건이면 status로 드러낸다. 빈 목록을 성공으로 두지 않는다.
이 모듈은 구글 지도 엔드포인트를 호출하지 않는다.

고친 것 두 가지 (2026-10-14)

  1) allergy_notice 를 OSM diet:* 태그로 채우지 않는다.
     diet:vegetarian=yes 는 채식 메뉴가 있다는 뜻이고 알레르기 안전과 다른 주장이다.
     이전에는 그 값이 allergy_notice 키에 status=verified 로 붙었고, 프롬프트가
     "verified 만 사실"이라고 적으므로 알레르기 문장이 확정처럼 생성될 수 있었다.
     allergy_notice 는 API 대응이 없는 상황이므로 OSM_SITUATIONS 에서 뺐다.

  2) 요청한 장소와 응답한 장소를 이름으로 대조한다.
     이전에는 요청 places 의 첫 이름 하나를 검색어로 쓰고, 응답 문서 최대 5개를 전부
     verified 로 넣었다. 그래서 요청하지 않은 가게가 사실이 되고, OSM 원점도 그 첫 문서가
     됐다. 지금은 요청 이름이 응답 이름의 앞에서 연속으로 시작할 때만 verified 다.
     요청 이름이 없으면 대조할 기준이 없으므로
     unavailable 이다 — 아무거나 확정하지 않는다.

남은 제약 (코드 주석이 아니라 이 문단에 남긴다)

  카카오 로컬(키워드·카테고리 장소 검색)은 한국 지번·도로명 주소 체계 위의 색인이고
  국가·로캘 파라미터가 없다. 해외 장소를 돌려주지 않는다.
    문서: https://developers.kakao.com/docs/latest/ko/local/common
    데브톡 60374: "당사에서는 해외지도는 서비스하지 않습니다."
  이 제품의 도시는 전부 해외다(뉴욕·보스턴·오사카·런던…). 그래서 카카오 조회는 한국 도시로
  범위를 좁혀 둔다(_kakao_in_scope). 이름 대조(2번)만으로도 해외 도시에서는 대부분 0건이
  되어 unavailable 로 내려가지만, 같은 이름을 쓰는 한국 가게가 하나 있으면 그대로 통과한다.
  범위 검사가 그 마지막 구멍과 헛 호출을 막는다.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable

KAKAO_SEARCH = "https://dapi.kakao.com/v2/local/search/keyword.json"
OSM_INTERPRETER = "https://overpass-api.de/api/interpreter"
USER_AGENT = "CodysseyFactBot/1.0 (educational travel-english facts)"

# 계약 상황 중 API 태그로 확정할 수 있는 것만. 나머지는 문장 에이전트 몫이다.
# allergy_notice 는 여기 없다 — diet:* 는 알레르기 안전의 근거가 아니다(위 1번).
OSM_SITUATIONS = ("takeout", "ask_breakfast", "ask_wifi")

# 카카오 로컬이 실제로 조회할 수 있는 도시. 이 제품의 도시는 여기에 하나도 없다.
KOREA_CITIES = frozenset({
    "서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "제주",
    "수원", "춘천", "전주", "경주", "여수", "강릉", "포항", "창원", "천안",
})

# 해외 좌표를 주는 공급원이 붙기 전까지 False. 키를 넣어도 외부 호출이 0회다.
FACT_SOURCES_READY = False

Http = Callable[[str, dict[str, str], float], tuple[int, dict[str, Any]]]

_APOS = re.compile(r"['\u2019`\"]")
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_WS = re.compile(r"\s+")


def kakao_configured() -> bool:
    return bool((os.getenv("KAKAO_REST_API_KEY") or "").strip())


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _redact(text: str, secret: str) -> str:
    if secret and secret in text:
        return text.replace(secret, "***")
    return text


def _name_tokens(name: Any) -> list[str]:
    """이름 비교용 토큰. 대소문자·구두점·공백 차이를 없앤다."""
    s = _APOS.sub("", str(name or "").casefold())   # Joe's → joes
    s = _PUNCT.sub(" ", s)                          # 나머지 구두점은 토큰 경계
    return _WS.sub(" ", s).strip().split()


def _same_place(requested: Any, returned: Any) -> bool:
    """요청 이름의 토큰이 응답 이름의 앞에서 연속으로 시작하는가.

    글자 부분일치와 중간 삽입은 다른 가게를 통과시킨다.
    "Joe's Pizza" 는 "JOES PIZZA" 와 "Joe's Pizza Greenwich Village" 만 통과하고,
    "Pizza", "Not Joe's Pizza", "Joe's Famous Pizza" 는 거절한다.
    요청이 세 글자 미만인 토큰 하나면 거절한다.
    """
    want, got = _name_tokens(requested), _name_tokens(returned)
    if not want or not got:
        return False
    if len(want) == 1 and len(want[0]) < 3:
        return False
    return got[:len(want)] == want


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


def _kakao_in_scope(city: Any) -> bool:
    return str(city or "").strip() in KOREA_CITIES


def _kakao_query(city: str, places: list[dict[str, Any]]) -> str:
    types = [str(p.get("place_type") or "").strip().lower() for p in places]
    names = [str(p.get("name")).strip() for p in places if str(p.get("name") or "").strip()]
    kind = "카페" if types and all(t == "cafe" for t in types) else "맛집"
    if names:
        return f"{city} {names[0]} {kind}"
    return f"{city} {kind}"


def _kakao_places(city: str, places: list[dict[str, Any]], http: Http, timeout: float) -> dict[str, Any]:
    if not _kakao_in_scope(city):
        return _box("unavailable", f"카카오 로컬은 한국 도시만 조회한다: {city!r}")
    requested = [str(p.get("name")).strip() for p in places if str(p.get("name") or "").strip()]
    if not requested:
        return _box("unavailable", "요청 장소 이름이 없어 대조할 수 없다")
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
    dropped = 0
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        name = str(doc.get("place_name") or "").strip()
        source = str(doc.get("place_url") or "").strip()
        lat = _num(doc.get("y"), -90, 90)
        lon = _num(doc.get("x"), -180, 180)
        if not name or not source or lat is None or lon is None:
            continue
        if not any(_same_place(rn, name) for rn in requested):
            dropped += 1   # 요청한 장소가 아니다. 사실로 올리지 않는다.
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
        return _box("unavailable", f"요청한 장소와 이름이 맞는 결과가 없다 (후보 {len(docs)}건)")
    reason = f"이름이 맞지 않아 제외한 후보 {dropped}건" if dropped else ""
    return _box("verified", reason, items)


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
    # allergy_notice 는 여기서 만들지 않는다. diet:* 는 채식·할랄 메뉴 유무이지
    # 알레르기 안전이 아니다(모듈 주석 1번).
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
    """좌표가 주어졌을 때만. 원점은 이름 대조를 통과한 장소의 좌표다(_kakao_places 참고)."""
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
    """한 생성 요청의 사실. 예외를 올리지 않는다.

    이 제품의 도시에는 쓸 수 있는 공급원이 아직 없다(FACT_SOURCES_READY).
    키가 있어도 호출하지 않는다. 공급원 연결은 _wire_providers 에만 있다.
    """
    if not FACT_SOURCES_READY:
        return {
            "places": _box("unavailable", "사실 공급원 없음 — 카카오 로컬은 한국 도시만 조회한다"),
            "situations": _box("unavailable", "좌표 공급원 없음"),
        }
    return _wire_providers(
        category_id=category_id, city=city, places=places, situation_ids=situation_ids,
        http=http, kakao_timeout=kakao_timeout, osm_timeout=osm_timeout,
    )


def _wire_providers(
    *,
    category_id: str,
    city: str,
    places: list[dict[str, Any]],
    situation_ids: list[str],
    http: Http | None,
    kakao_timeout: float,
    osm_timeout: float,
) -> dict[str, Any]:
    """공급원 연결. FACT_SOURCES_READY 를 켠 뒤에만 불린다."""
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
