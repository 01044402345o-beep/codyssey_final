"""사용자가 직접 추가한 장소 확인(POST /place-check) — 적은 이름을 도시 근처에서 찾아 좌표·출처를 붙인다.

순서(먼저 찾으면 멈춤): 한국관광공사 TourAPI 키워드 검색(한국 도시·키 있을 때) → Wikidata 검색(이름·별칭) → Google Places(키 있을 때, 실시간).
- 도시 좌표는 조사와 같은 방법으로 얻는다(GeoNames → 이름만 있으면 Wikidata 보강·옛 지명·상위 구역).
- 도시에서 MAX_KM 안의 것만 '찾음'으로 본다(동명 장소가 다른 도시에 있는 경우를 거른다).
- 못 찾으면 not_found — 화면은 '직접 추가' 그대로 둔다(가짜로 바꾸지 않는다).
- 결과 캐시: TourAPI·Wikidata 결과만 프로세스 메모리(7일). Google 결과는 저장하지 않는다(약관).
- 사용자 정보는 보내지 않는다(장소 이름·도시·나라만).
- 확인 창용 주소·사진(11/05): 주소는 TourAPI addr1 · Wikidata P6375(거리 주소) · Google formattedAddress, 없으면
  OpenStreetMap Nominatim 역지오코딩(좌표 → 주소). 사진은 위키미디어 공용(Wikidata P18)만 — 찾은 곳이 Wikidata 가 아니면
  같은 이름의 Wikidata 항목이 1km 안에 있을 때만 그 사진을 붙인다. TourAPI 사진은 쓰지 않는다(공공누리 3유형, tourapi.py).
  사진 주소는 화면이 직접 부르지 않고 GET /place-photo 가 받아 내보낸다(CSP img-src 'self').
"""
from __future__ import annotations

import datetime as dt
import hashlib
import html
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
PHOTO_KM = 1.0                       # 다른 소스로 찾은 곳에 Wikidata 사진을 붙일 때 허용 거리
NOMINATIM = "https://nominatim.openstreetmap.org/reverse"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
_nominatim_lock = threading.Lock()
_nominatim_last = [0.0]              # Nominatim 사용 정책: 초당 1회 이하
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


def _found(provider: str, name: str, lat: float, lon: float, url: str, km: float, kind: str = "",
           address: str = "", image: Optional[dict] = None) -> dict:
    return {"status": "found", "name": name[:120], "lat": lat, "lon": lon, "distance_km": km, "kind": kind,
            "address": _clean_addr(address), "image": image,
            "source": {"provider": provider, "url": url, "title": name[:120],
                       "license": (LICENSES.get(provider) or ("Google Maps", ""))[0]}}


def _clean_addr(s: str) -> str:
    s = re.sub(r"https?://\S+|[<>{}\[\]]", " ", s or "")
    return re.sub(r"\s+", " ", s).strip()[:160]


def commons_image(filename: str, width: int = 500) -> Optional[dict]:
    """위키미디어 공용 파일 이름 → 썸네일 주소(upload.wikimedia.org)·파일 문서 주소. 주소 규칙: md5(이름)의 앞 1·2자리 폴더.
    썸네일 폭은 위키미디어가 정한 표준 폭만 된다(330·500·960 … — 480·640 은 400 오류, 11/05 확인)."""
    name = (filename or "").strip().replace(" ", "_")
    if not name or len(name) > 240 or "/" in name or not re.search(r"\.(jpe?g|png|gif|webp|tiff?|svg)$", name, re.I):
        return None
    h = hashlib.md5(name.encode("utf-8")).hexdigest()
    q = urllib.parse.quote(name)
    ext = ".png" if name.lower().endswith((".svg", ".tif", ".tiff")) else ""
    return {"src": f"https://upload.wikimedia.org/wikipedia/commons/thumb/{h[0]}/{h[:2]}/{q}/{width}px-{q}{ext}",
            "page": "https://commons.wikimedia.org/wiki/File:" + q, "credit": "Wikimedia Commons", "file": name}


def _plain(s: str, n: int) -> str:
    """위키미디어 extmetadata 값(HTML 섞임) → 글자만."""
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    return re.sub(r"\s+", " ", s).strip()[:n]


def commons_meta(http: SafeHttp, image: dict) -> Optional[dict]:
    """사진의 저작자·라이선스·원본 파일 문서(CC BY-SA 표시 요건 — 저작자·라이선스·출처 링크). 공용 API 가 주는 썸네일 주소를 쓴다.
    라이선스를 알 수 없으면 None — 표시 요건을 못 채우는 사진은 보이지 않는다."""
    name = (image or {}).get("file") or ""
    if not name:
        return None
    res, d = http.get_json(COMMONS_API + "?" + urllib.parse.urlencode({
        "action": "query", "titles": "File:" + name, "prop": "imageinfo", "iiprop": "url|extmetadata",
        "iiurlwidth": 500, "iiextmetadatafilter": "Artist|LicenseShortName|LicenseUrl", "format": "json"}), timeout=8)
    if not res.ok:
        return None
    pages = ((d or {}).get("query") or {}).get("pages") or {}
    info = next(iter(((p or {}).get("imageinfo") or [{}])[0] for p in pages.values()), {}) if pages else {}
    meta = info.get("extmetadata") or {}
    lic = _plain((meta.get("LicenseShortName") or {}).get("value", ""), 40)
    thumb = str(info.get("thumburl") or "").split("?")[0]      # 공용 API 는 thumb.wikimedia.org(+추적 쿼리)를 준다
    page = str(info.get("descriptionurl") or image.get("page") or "")
    if not lic or not re.fullmatch(r"https://(upload|thumb)\.wikimedia\.org/[^\s\"'<>?]+", thumb):
        return None
    lic_url = str((meta.get("LicenseUrl") or {}).get("value") or "")
    return {"src": thumb, "page": page if page.startswith("https://commons.wikimedia.org/") else image.get("page", ""),
            "credit": "Wikimedia Commons", "author": _plain((meta.get("Artist") or {}).get("value", ""), 80) or "작자 미상",
            "license": lic, "license_url": lic_url if re.fullmatch(r"https?://[^\s\"'<>]+", lic_url) else ""}


def _wd_text(cl: dict, pid: str) -> str:
    v = wikidata._value(cl, pid)
    return str(v.get("text") or "") if isinstance(v, dict) else ""


def _wd_image(cl: dict) -> Optional[dict]:
    v = (((cl.get("P18") or [{}])[0].get("mainsnak") or {}).get("datavalue") or {}).get("value")
    return commons_image(v) if isinstance(v, str) else None


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
        en, ko = tourapi.split_title(str(it.get("title") or ""))
        exact = _key(name) in (_key(en), _key(ko))      # 이름이 같은 것을 먼저(영문·괄호 속 한국어 이름 둘 다), 그다음 가까운 것
        if best is None or (not exact, km) < (not best[4], best[0]):
            best = (km, it, lat, lon, exact)
    if not best:
        return None
    km, it, lat, lon, _ = best
    t = str(it.get("contenttypeid") or "")
    kind = "attraction" if t in tourapi.ATTRACTION_TYPES else (
        tourapi.food_kind(it) if t in tourapi.FOOD_TYPES else "")
    addr = " ".join(x for x in (str(it.get("addr1") or "").strip(), str(it.get("addr2") or "").strip()) if x)
    return _found("tourapi", tourapi.split_title(str(it.get("title") or name))[0], lat, lon, tourapi.source_url(svc), km, kind,
                  address=addr)


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
    cl = ent.get("claims") or {}
    return _found("wikidata", label, lat, lon, "https://www.wikidata.org/wiki/" + q, km,
                  address=_wd_text(cl, "P6375"), image=_wd_image(cl))


def _by_google(http: SafeHttp, ref: dict, name: str) -> Optional[dict]:
    hit = google_places.find(http, ref, name)
    if not hit:
        return None
    km = _near(ref, hit["lat"], hit["lon"])
    if km is None:
        return None
    got = _found("google", hit["name"], hit["lat"], hit["lon"], hit["url"], km, address=hit.get("address") or "")
    got["_gphoto"] = hit.get("photo")                    # 사진 참조 — 무료 사진이 없을 때만 주소로 바꾼다(저장 안 함)
    return got


def _photo_near(http: SafeHttp, name: str, lat: float, lon: float) -> Optional[dict]:
    """다른 소스로 찾은 곳: 같은 이름의 Wikidata 항목이 PHOTO_KM 안에 있으면 그 사진(P18)."""
    got = _by_wikidata(http, {"lat": lat, "lon": lon}, name)
    if not got or not got.get("image") or verify.km(lat, lon, got["lat"], got["lon"]) > PHOTO_KM:
        return None
    a, b = _key(name), _key(got.get("name") or "")
    if not a or not b or (a not in b and b not in a):        # 이름이 다르면 근처 다른 곳의 사진이다 — 붙이지 않는다
        return None
    return got["image"]


def _reverse(http: SafeHttp, lat: float, lon: float) -> str:
    """좌표 → 주소(OpenStreetMap Nominatim). 초당 1회 이하로만 부른다."""
    with _nominatim_lock:
        wait = 1.05 - (time.time() - _nominatim_last[0])
        if wait > 0:
            time.sleep(wait)
        _nominatim_last[0] = time.time()
    res, d = http.get_json(NOMINATIM + "?" + urllib.parse.urlencode(
        {"format": "jsonv2", "lat": f"{lat:.6f}", "lon": f"{lon:.6f}", "zoom": 18, "accept-language": "ko,en"}), timeout=8)
    return str((d or {}).get("display_name") or "") if res.ok else ""


def _enrich(http: SafeHttp, name: str, got: dict) -> dict:
    """확인 창에 보일 주소·사진을 채운다. 하나가 실패해도 찾은 결과는 그대로 둔다."""
    if not got.get("image"):
        try:
            got["image"] = _photo_near(http, name, got["lat"], got["lon"])
        except Exception:  # noqa: BLE001
            got["image"] = None
    if got.get("image") and not got["image"].get("license"):
        try:
            got["image"] = commons_meta(http, got["image"])     # 저작자·라이선스를 못 알면 사진을 쓰지 않는다
        except Exception:  # noqa: BLE001
            got["image"] = None
    if not got.get("image"):
        # 무료 공용 사진이 없으면 Google 사진(찍은 사람 표시, 저장·캐시 안 함). 다른 소스로 찾은 곳은 Google 에서 이름으로
        # 다시 찾되 같은 이름·1km 안일 때만 그 사진을 쓴다(근처 다른 가게 사진을 붙이지 않게)
        try:
            ph = got.get("_gphoto")
            if ph is None and got["source"]["provider"] != "google" and google_places.available():
                hit = google_places.find(http, {"lat": got["lat"], "lon": got["lon"], "population": 0}, name)
                if hit and verify.km(got["lat"], got["lon"], hit["lat"], hit["lon"]) <= PHOTO_KM:
                    a, b = _key(name), _key(hit.get("name") or "")
                    ph = hit.get("photo") if a and b and (a in b or b in a) else None
            got["image"] = google_places.photo_uri(http, ph) if ph else None
        except Exception:  # noqa: BLE001
            got["image"] = None
    got.pop("_gphoto", None)
    if not got.get("address"):
        try:
            got["address"] = _clean_addr(_reverse(http, got["lat"], got["lon"]))
            if got["address"]:
                got["address_source"] = "OpenStreetMap (ODbL)"
        except Exception:  # noqa: BLE001
            got["address"] = ""
    return got


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
            got = _enrich(http, name, got)
            if storable:
                keep = dict(got)
                if (keep.get("image") or {}).get("provider") == "google":
                    keep["image"] = None                     # Google 사진은 기억하지 않는다(약관) — 다음 확인 때 다시 받는다
                _memo_put(key, keep)
            return got
    return {"status": "not_found"}                       # 못 찾음은 기억하지 않는다(키·한도가 바뀌면 다시 찾을 수 있게)
