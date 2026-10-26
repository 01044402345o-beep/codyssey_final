"""사용자가 직접 추가한 장소 확인(POST /place-check) — 적은 이름을 도시 근처에서 찾아 좌표·출처를 붙인다.

순서(먼저 찾으면 멈춤): 한국관광공사 TourAPI 키워드 검색(한국 도시·키 있을 때) → Wikidata 검색(이름·별칭) → Google Places(키 있을 때, 실시간).
- 도시 좌표는 조사와 같은 방법으로 얻는다(GeoNames → 이름만 있으면 Wikidata 보강·옛 지명·상위 구역).
- 도시에서 MAX_KM 안의 것만 '찾음'으로 본다(동명 장소가 다른 도시에 있는 경우를 거른다).
- 못 찾으면 not_found — 화면은 '직접 추가' 그대로 둔다(가짜로 바꾸지 않는다).
- 결과 캐시: TourAPI·Wikidata 결과만 프로세스 메모리(7일). Google 결과는 저장하지 않는다(약관).
- 사용자 정보는 보내지 않는다(장소 이름·도시·나라만).
"""
from __future__ import annotations

import datetime as dt
import re
import threading
import time
import urllib.parse
from collections import OrderedDict
from typing import Any, Optional

from . import config, identity, nodes, verify
from .cache import ResearchCache
from .net import SafeHttp
from .sources import LICENSES, google_places, tourapi, wikidata

MAX_KM = 40.0
CACHE_TTL = 7 * 86400
_SAFE = re.compile(r"^[^\"\\\r\n<>{}|@]{1,60}$")
_lock = threading.Lock()
_memo: "OrderedDict[str, tuple[float, dict]]" = OrderedDict()


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _memo_get(k: str) -> Optional[dict]:
    with _lock:
        hit = _memo.get(k)
        if hit and time.time() - hit[0] < CACHE_TTL:
            _memo.move_to_end(k)
            return hit[1]
    return None


def _memo_put(k: str, v: dict) -> None:
    with _lock:
        _memo[k] = (time.time(), v)
        _memo.move_to_end(k)
        while len(_memo) > 256:
            _memo.popitem(last=False)


def clear() -> None:
    with _lock:
        _memo.clear()


def _key(s: str) -> str:
    return re.sub(r"[\W_]+", "", (s or "").casefold())


def _near(ref: dict, lat: float, lon: float) -> Optional[float]:
    d = verify.km(ref["lat"], ref["lon"], lat, lon)
    return round(d, 1) if d <= MAX_KM else None


def _found(provider: str, name: str, lat: float, lon: float, url: str, km: float, kind: str = "") -> dict:
    return {"status": "found", "name": name[:120], "lat": lat, "lon": lon, "distance_km": km, "kind": kind,
            "source": {"provider": provider, "url": url, "title": name[:120],
                       "license": (LICENSES.get(provider) or ("Google Maps", ""))[0]}}


def _by_tourapi(http: SafeHttp, ref: dict, name: str) -> Optional[dict]:
    if ref.get("iso2") != "KR" or not tourapi.available():
        return None
    svc = tourapi.service()
    k = tourapi.key(svc)
    enc = k if "%" in k else urllib.parse.quote(k, safe="")
    url = (f"{tourapi.ROOT}/{svc}/searchKeyword2?serviceKey={enc}&" + urllib.parse.urlencode(
        {"MobileOS": "ETC", "MobileApp": tourapi.MOBILE_APP, "_type": "json", "keyword": name, "numOfRows": 10, "pageNo": 1,
         "arrange": "O"}))
    res = http.request("GET", url, timeout=8)
    data = res.json() if res.ok else None
    best = None
    for it in tourapi._items(data):
        if str(it.get("contenttypeid") or "") not in tourapi.ATTRACTION_TYPES | tourapi.FOOD_TYPES:
            continue                                    # 숙박·교통 등은 사용자가 고르는 종류(관광지·맛집·카페)가 아니다
        try:
            lat, lon = float(it.get("mapy")), float(it.get("mapx"))
        except (TypeError, ValueError):
            continue
        km = _near(ref, lat, lon)
        if km is None:
            continue
        exact = _key(str(it.get("title") or "")) == _key(name)      # 이름이 같은 것을 먼저, 그다음 가까운 것
        if best is None or (not exact, km) < (not best[4], best[0]):
            best = (km, it, lat, lon, exact)
    if not best:
        return None
    km, it, lat, lon, _ = best
    t = str(it.get("contenttypeid") or "")
    kind = "attraction" if t in tourapi.ATTRACTION_TYPES else (
        ("cafe" if str(it.get("cat3") or "") in tourapi.CAFE_CAT3 else "restaurant") if t in tourapi.FOOD_TYPES else "")
    return _found("tourapi", _norm(str(it.get("title") or name)), lat, lon, tourapi.source_url(svc), km, kind)


def _by_wikidata(http: SafeHttp, ref: dict, name: str) -> Optional[dict]:
    lang = "en" if name.isascii() else "ko"
    res, s = http.get_json(wikidata.ACTION_API + "?" + urllib.parse.urlencode({
        "action": "wbsearchentities", "search": name, "language": lang, "uselang": lang, "type": "item", "limit": 7,
        "format": "json"}), timeout=8)
    ids = [x.get("id") for x in (s or {}).get("search") or [] if re.fullmatch(r"Q\d+", str(x.get("id")))] if res.ok else []
    if not ids:
        return None
    res, ents = wikidata._entities(http, ids)
    best = None
    for q in ids:                                       # 검색 순서(관련도) 그대로 — 가장 가까운 것이 아니라 도시 근처의 첫 항목
        ent = ents.get(q) or {}
        c = wikidata._value(ent.get("claims") or {}, "P625")
        if "latitude" not in c:
            continue
        km = _near(ref, float(c["latitude"]), float(c["longitude"]))
        if km is not None:
            best = (km, q, ent, float(c["latitude"]), float(c["longitude"]))
            break
    if not best:
        return None
    km, q, ent, lat, lon = best
    label = str(((ent.get("labels") or {}).get("en") or {}).get("value") or name)
    return _found("wikidata", label, lat, lon, "https://www.wikidata.org/wiki/" + q, km)


def _by_google(http: SafeHttp, ref: dict, name: str) -> Optional[dict]:
    hit = google_places.find(http, ref, name)
    if not hit:
        return None
    km = _near(ref, hit["lat"], hit["lon"])
    return None if km is None else _found("google", hit["name"], hit["lat"], hit["lon"], hit["url"], km)


def check(req: dict, *, http: Optional[SafeHttp] = None, store: Any = None, cache: Optional[ResearchCache] = None) -> dict:
    """req = {country: {name, iso2?}, city: {name, gid?}, place: {name, kind}} → {status: found|not_found|no_city|unavailable, ...}"""
    if not config.research_enabled():
        return {"status": "unavailable", "reason": "research_disabled"}
    name = _norm((req.get("place") or {}).get("name") or "")
    if not _SAFE.fullmatch(name):
        return {"status": "not_found", "reason": "bad_name"}
    from . import service
    store = store or service._store()
    http = http or SafeHttp()
    today = dt.date.today().isoformat()
    city = req.get("city") or {}
    resolved = identity.resolve(store, {"countries": [req.get("country") or {}],
                                        "cities": [{"name": city.get("name") or "", "gid": city.get("gid"), "ci": 0,
                                                    "start": today, "end": today, "attr": 0, "rest": 0}]})
    deps = nodes.Deps(http=http, cache=cache or service.CACHE, store=store)
    nodes.enrich_unresolved(deps, resolved)
    ref = resolved["cities"][0]["ref"]
    if ref.get("lat") is None:
        return {"status": "no_city"}
    key = f"{ref['key']}|{name.casefold()}"
    hit = _memo_get(key)
    if hit:
        return {**hit, "cached": True}
    for finder, storable in ((_by_tourapi, True), (_by_wikidata, True), (_by_google, False)):
        try:
            got = finder(http, ref, name)
        except Exception:  # noqa: BLE001 — 한 소스가 실패해도 다음 소스로
            got = None
        if got:
            if storable:
                _memo_put(key, got)
            return got
    return {"status": "not_found"}                       # 못 찾음은 기억하지 않는다(키·한도가 바뀌면 다시 찾을 수 있게)
