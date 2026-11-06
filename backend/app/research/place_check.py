"""사용자가 직접 추가한 장소 확인(POST /place-check) — 적은 이름을 도시 근처에서 찾아 좌표·출처를 붙인다.

순서(먼저 찾으면 멈춤): 한국관광공사 TourAPI 키워드 검색(한국 도시·키 있을 때) → Wikidata 검색(이름·별칭) → Google Places(키 있을 때, 실시간).
- 도시 좌표는 조사와 같은 방법으로 얻는다(GeoNames → 이름만 있으면 Wikidata 보강·옛 지명·상위 구역).
- 도시에서 MAX_KM 안의 것만 '찾음'으로 본다(동명 장소가 다른 도시에 있는 경우를 거른다).
- 못 찾으면 not_found — 화면은 '직접 추가' 그대로 둔다(가짜로 바꾸지 않는다).
- 결과 캐시: TourAPI·Wikidata 결과만 프로세스 메모리(7일). Google 결과는 저장하지 않는다(약관).
- 사용자 정보는 보내지 않는다(장소 이름·도시·나라만).
- 확인 창용 주소·사진(11/05): 주소는 TourAPI addr1 · Wikidata P6375(거리 주소) · Google formattedAddress, 없으면
  OpenStreetMap Nominatim 역지오코딩(좌표 → 주소). TourAPI 사진은 쓰지 않는다(공공누리 3유형, tourapi.py).
- 사진(11/06, _photo_near → _enrich): 이름이 맞는 것만 — ① 같은 이름 Wikidata 항목(1km)의 P18 ② 좌표 0.5km 의 Wikidata 항목 중
  다국어 라벨이 맞는 것의 P18 ③ 위키미디어 공용 좌표 검색(300m, 파일 이름) ④ 없으면 Google 장소 사진(키 있을 때).
  공용 사진은 저작자·라이선스(자유 라이선스만)를 붙이고 GET /place-photo 가 받아 내보낸다. Google 사진은 약관상
  저장·중계하지 않고 화면이 photoUri 를 바로 부른다(찍은 사람 표시, 기억 캐시에서 뺀다).
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
    if not _license_ok(lic) or not re.fullmatch(r"https://(upload|thumb)\.wikimedia\.org/[^\s\"'<>?]+", thumb):
        return None
    lic_url = str((meta.get("LicenseUrl") or {}).get("value") or "")
    return {"src": thumb, "page": page if page.startswith("https://commons.wikimedia.org/") else image.get("page", ""),
            "credit": "Wikimedia Commons", "author": _plain((meta.get("Artist") or {}).get("value", ""), 80) or "작자 미상",
            "license": lic, "license_url": lic_url if re.fullmatch(r"https?://[^\s\"'<>]+", lic_url) else ""}



def _img_from_page(page: dict, dist: Optional[float]) -> Optional[dict]:
    """공용 API 페이지(imageinfo) → 사진. API 가 준 썸네일 주소를 그대로 쓴다(폭·호스트를 다시 조립하면 400/403).
    라이선스가 자유 이용(CC0·PD·CC BY·BY-SA)이 아니면 쓰지 않는다(NC·ND·fair use 제외)."""
    ii = (page.get("imageinfo") or [{}])[0]
    thumb = str(ii.get("thumburl") or "").split("?")[0]
    if not re.fullmatch(r"https://(upload|thumb)\.wikimedia\.org/[^\s\"'<>?]+", thumb) or len(thumb) > 600:
        return None
    meta = ii.get("extmetadata") or {}
    short = _plain_text(((meta.get("LicenseShortName") or {}) or {}).get("value"))
    if not _license_ok(short):
        return None
    lic_url = str(((meta.get("LicenseUrl") or {}) or {}).get("value") or "")
    title = str(page.get("title") or "").replace("File:", "")
    return {"src": thumb, "page": "https://commons.wikimedia.org/wiki/File:" + urllib.parse.quote(title.replace(" ", "_")),
            "credit": "Wikimedia Commons", "author": _plain_text(((meta.get("Artist") or {}) or {}).get("value"))[:80] or "작자 미상",
            "license": short[:40], "license_url": lic_url if re.fullmatch(r"https?://[^\s\"'<>]+", lic_url) else "",
            "title": title[:120], "km": None if dist is None else round(dist / 1000.0, 2)}


# ── 위키미디어 공용: 좌표로 찾기(11/06) ────────────────────────────────────────────
# 이름으로 찾으면 한국 상호에서 0건이다(하동관 0·성수동 카페 0·광장시장 식당 0 실측).
# 좌표로 찾으면 같은 API·같은 키 없이 8~50건이 나온다. 다만 좌표 결과는 '그 집'이 아니라
# '그 근처' 사진이므로, 파일 이름이 장소 이름과 맞을 때만 그 장소의 사진으로 인정한다.
GEO_RADIUS_M = 300
GEO_LIMIT = 20
# 표시 의무가 없는(CC0·퍼블릭도메인) 것과, 저작자·라이선스를 붙이면 되는 것만 통과시킨다.
# 그 밖(fair use·비자유·NC·ND)은 쓰지 않는다. 공공누리는 제1유형(출처표시만)만 — 2·3·4유형은 상업 금지·변경 금지가 붙는다.
# GFDL·FAL·Attribution 도 공용에서 쓰는 자유 라이선스다(경복궁 대표 사진이 KOGL Type 1 — 빠뜨리면 사진이 사라진다, 11/06 실측)
_CC_OK = re.compile(r"^(cc0|cc[- ]by([- ]sa)?([- ]\d(\.\d)?)?|public domain|pd|kogl[- ]type[- ]?1\b|gfdl|fal\b|"
                    r"free art licen[cs]e|attribution\b|copyrighted free use)", re.I)
_CC_BAD = re.compile(r"(\bnc\b|\bnd\b|non[- ]?commercial|no[- ]?deriv|fair use|non[- ]?free)", re.I)


def _plain_text(html: str) -> str:
    """extmetadata 의 Artist 는 '<a href=...>이름</a>' 같은 HTML 조각으로 온다."""
    s = re.sub(r"<[^>]{1,200}>", " ", html or "")
    s = (s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
         .replace("&#39;", "'").replace("&nbsp;", " "))
    return re.sub(r"\s+", " ", s).strip()[:120]


_FOLD = str.maketrans({"ō": "o", "ū": "u", "ā": "a", "ē": "e", "ī": "i", "û": "u", "ô": "o",
                       "é": "e", "è": "e", "ê": "e", "á": "a", "à": "a", "í": "i", "ó": "o", "ú": "u",
                       "ü": "u", "ö": "o", "ä": "a", "ñ": "n", "ç": "c", "ß": "ss"})


def _name_tokens(s: str) -> set:
    """비교용 낱말. 발음기호(ō·é)를 접어 'Tōdai-ji' 와 'Todai-ji' 가 같아지게 한다."""
    return {t for t in re.findall(r"[0-9a-z가-힣]+", (s or "").casefold().translate(_FOLD)) if len(t) >= 3}


def _title_matches(name: str, title: str) -> bool:
    """파일 이름이 그 장소를 가리키는가 — 이름의 낱말이 **모두** 들어 있어야 한다.

    처음엔 하나만 겹쳐도 통과시켰는데, 'Shibuya Sky' 조회에 'Nissin Donbei noodle stand,
    Shibuya Sta'(라멘집)가 통과했다. 여행 앱에서 이건 그 식당 사진으로 보이므로
    '덜 찾는' 쪽을 택한다. 대신 번역된 이름('Eiffel Tower' ↔ 'tour Eiffel')은 놓친다."""
    nt = _name_tokens(name)
    tt = _name_tokens(re.sub(r"\.(jpe?g|png|gif|webp|tiff?)$", "", title, flags=re.I))
    if not nt or not tt:
        return False
    return nt <= tt


def _license_ok(short: str) -> bool:
    s = (short or "").strip()
    if not s or _CC_BAD.search(s):
        return False
    return bool(_CC_OK.search(s))


SPARQL = "https://query.wikidata.org/sparql"
GEO_ENTITY_KM = 0.5          # 반경(km). 랜드마크는 대개 100m 안에 엔티티가 있다
GEO_LANGS = ("ko", "en", "ja", "zh", "fr", "es", "de")


def _label_tokens_match(name: str, labels: list) -> bool:
    """이름의 낱말이 **어느 언어 라벨**에든 모두 들어 있으면 그 장소로 본다.
    Commons 파일명 대조와 달리 번역 문제가 없다 — 광장시장 라벨이 한국어로, Eiffel Tower 라벨이
    영어로 오기 때문에 어느 쪽 이름으로 물어도 맞는다."""
    nt = _name_tokens(name)
    if not nt:
        return False
    for lab in labels:
        if nt <= _name_tokens(lab):
            return True
    return False


def wikidata_geo_image(http: SafeHttp, name: str, lat: float, lon: float) -> Optional[dict]:
    """좌표 반경 안에서 '이름이 맞는' 위키데이터 항목을 찾아 그 P18 사진을 쓴다.

    왜 이게 필요한가: 공용 파일명은 영어인 경우가 많아 한국어 상호와 안 맞는다(광장시장 = 0건).
    위키데이터 라벨은 다국어라서 좌표+라벨이면 그 간극이 메워진다. 사진 자체는 결국 공용 파일이므로
    라이선스·저작자는 공용 API 에서 다시 받는다(CC BY·BY-SA 표시 의무).
    """
    q = f"""SELECT ?item ?img ?dist ?label WHERE {{
  SERVICE wikibase:around {{
    ?item wdt:P625 ?loc .
    bd:serviceParam wikibase:center "Point({lon:.6f} {lat:.6f})"^^geo:wktLiteral .
    bd:serviceParam wikibase:radius "{GEO_ENTITY_KM}" .
    bd:serviceParam wikibase:distance ?dist .
  }}
  ?item wdt:P18 ?img .
  ?item rdfs:label ?label .
  FILTER(LANG(?label) IN ({",".join('"' + x + '"' for x in GEO_LANGS)}))
}} ORDER BY ?dist LIMIT 40"""
    try:
        res, d = http.get_json(SPARQL + "?" + urllib.parse.urlencode({"query": q, "format": "json"}), timeout=8)   # 확인 창이 기다린다 — 다른 사진 조회와 같은 8초
    except Exception:      # noqa: BLE001
        return None
    if not res.ok or not isinstance(d, dict):
        return None
    rows = ((d.get("results") or {}).get("bindings") or [])
    by_item: dict = {}
    for b in rows:
        if not isinstance(b, dict):
            continue
        item = ((b.get("item") or {}).get("value") or "").rstrip("/").split("/")[-1]
        label = (b.get("label") or {}).get("value") or ""
        img = (b.get("img") or {}).get("value") or ""
        try:
            dist = float((b.get("dist") or {}).get("value") or 0) * 1000.0
        except (TypeError, ValueError):
            dist = 1e9
        if not item or not img:
            continue
        slot = by_item.setdefault(item, {"labels": [], "dist": dist, "file": img.rstrip("/").split("/")[-1]})
        slot["labels"].append(label)
        slot["dist"] = min(slot["dist"], dist)
    want = _name_tokens(name)
    hits = [v for v in by_item.values() if _label_tokens_match(name, v["labels"])]
    # 이름과 **정확히** 같은 라벨을 먼저, 그다음 가까운 순.
    # (경복궁 → '경복궁' 이 36m, '경복궁 사정전' 이 59m — 거리만 보면 사정전이 이겼다)
    hits.sort(key=lambda v: (not any(want == _name_tokens(l) for l in v["labels"]), v["dist"]))
    for hit in hits:
        got = commons_meta(http, commons_image(urllib.parse.unquote(hit["file"])))
        if got:
            got["km"] = round(hit["dist"] / 1000.0, 2)
            return got
    return None


def commons_geosearch(http: SafeHttp, name: str, lat: float, lon: float) -> Optional[dict]:
    """좌표 주변 사진 중 ①이름이 맞고 ②라이선스가 통과하는 첫 장.
    이름이 맞는 것이 없으면 None — '근처 사진'을 그 장소 사진으로 쓰지 않는다."""
    q = {"action": "query", "format": "json", "generator": "geosearch",
         "ggscoord": f"{lat:.6f}|{lon:.6f}", "ggsradius": str(GEO_RADIUS_M), "ggslimit": str(GEO_LIMIT),
         "ggsnamespace": "6", "prop": "imageinfo|coordinates", "iiprop": "url|extmetadata", "iiurlwidth": "500",
         "codistancefrompoint": f"{lat:.6f}|{lon:.6f}"}     # generator 로 부르면 거리는 coordinates[0].dist 에만 온다
    res, d = http.get_json(COMMONS_API + "?" + urllib.parse.urlencode(q), timeout=8)
    if not res.ok or not isinstance(d, dict):
        return None
    qd = d.get("query") or {}
    pages = qd.get("pages") or {}
    dist_by_id = {}
    for g in (qd.get("geosearch") or []):
        if isinstance(g, dict) and g.get("pageid") is not None:
            try:
                dist_by_id[str(g["pageid"])] = float(g.get("dist"))
            except (TypeError, ValueError):
                pass
    rows = []
    for page in pages.values() if isinstance(pages, dict) else []:
        if not isinstance(page, dict):
            continue
        title = str(page.get("title") or "")
        if not _title_matches(name, title):
            continue
        dist = dist_by_id.get(str(page.get("pageid")))
        if dist is None:
            co = (page.get("coordinates") or [{}])[0] if isinstance(page.get("coordinates"), list) else {}
            raw = page.get("dist") if page.get("dist") is not None else (co or {}).get("dist")
            try:
                dist = float(raw) if raw is not None else None
            except (TypeError, ValueError):
                dist = None
        img = _img_from_page(page, dist)
        if img:
            rows.append(img)
    rows.sort(key=lambda x: (x.get("km") if x.get("km") is not None else 99))
    return rows[0] if rows else None


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
    """무료 사진 찾기(이름이 맞는 것만 — 근처 다른 곳의 사진을 붙이지 않는다):
    ① 같은 이름의 Wikidata 항목이 PHOTO_KM 안이면 그 P18
    ② 좌표 반경(0.5km)의 Wikidata 항목 중 다국어 라벨(ko·en·ja·zh·fr·es·de)이 이름과 맞는 것의 P18 — 한국어 상호도 맞는다
    ③ 공용 좌표 검색(300m) — 파일 이름에 이름의 낱말이 모두 있는 것
    ④ 없으면 None(그다음은 _enrich 의 Google 사진)."""
    try:
        got = _by_wikidata(http, {"lat": lat, "lon": lon}, name)
        if got and got.get("image") and verify.km(lat, lon, got["lat"], got["lon"]) <= PHOTO_KM:
            a, b = _key(name), _key(got.get("name") or "")
            if a and b and (a in b or b in a):
                return got["image"]
    except Exception:  # noqa: BLE001 — 한 방법의 실패가 다음 방법을 막지 않게
        pass
    for finder in (wikidata_geo_image, commons_geosearch):
        try:
            got = finder(http, name, lat, lon)
        except Exception:  # noqa: BLE001
            got = None
        if got:
            return got
    return None


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
