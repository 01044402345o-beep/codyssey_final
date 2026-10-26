"""대체 장소 소스 — 한국관광공사 TourAPI 4.0(공공데이터포털, 한국 도시 전용). 저장 가능('이용허락범위 제한 없음').

한국어판 위키보이지가 없고 영어판도 한국 소도시는 빈약하다(통영 listing 24개 중 좌표 3개, 10/26 실측) — 그 빈칸을 메운다.
- 영문 관광정보서비스(EngService2)를 기본으로 쓴다: 장소 이름이 영어라 영어 문장에 그대로 쓸 수 있다.
  TOURAPI_SERVICE=KorService2 로 국문 서비스도 쓸 수 있다(활용신청은 서비스마다 따로 — 키에 승인된 서비스로).
- 도시당 한 번: locationBasedList2(도시 좌표, 인구 비례 반경 ≤20km, 거리순, 최대 100건, 종류 구분 없이) →
  contenttypeid(국문 12·14 관광, 39 음식 / 다국어 76·78 관광, 82 음식 — 둘 다 받아 준다)와 신분류체계(lclsSystm2 FD05 카페·찻집)로 나눈다.
  (활용매뉴얼 v4.4·신분류체계 연계 정의서, 2026-02: 응답에 cat1~3 대신 lclsSystm1~3. 옛 cat3 A05020900 도 받아 준다.)
- 영문 등 다국어 서비스의 title 은 "HiKR Ground (하이커 그라운드)" 처럼 끝 괄호에 한국어 이름이 붙는다 → 이름과 name_ko 로 나눈다.
- 사진(firstimage)은 쓰지 않는다: 공공누리 3유형(변경 금지) 조건이 섞여 있다.
- 오류: resultCode 22(일 한도) → capped(체인 6시간 쉼), 23(초당 한도) → rate_limited, 20·30·31(키 미등록·만료·거부) → exhaust.
  게이트웨이 오류는 HTTP 200 에 XML(OpenAPI_ServiceResponse)로 오기도 해서 본문 글자로도 판정한다.
- 키: 언어(서비스)별 TOURAPI_KEY_KOR·ENG·FRE·JPN·CHS, 없으면 공통 TOURAPI_SERVICE_KEY(공공데이터포털 '일반 인증키'는
  계정당 하나라 보통 같은 값 — 서비스마다 활용신청만 따로). Encoding/Decoding 어느 쪽이든 된다. 키 값은 로그·응답에 남기지 않는다.
- 장소 조사는 영문(ENG) 키가 있으면 영문, 없으면 국문(KOR). TOURAPI_SERVICE 로 강제할 수 있다. 불어·일문·중문은
  키 이름만 받아 둔다(이 앱은 한국인 영어 학습용이라 지금은 쓰지 않는다).
"""
from __future__ import annotations

import os
import re
import urllib.parse
from typing import Any

from .. import config, verify
from ..net import SafeHttp
from . import LICENSES, result

ROOT = "https://apis.data.go.kr/B551011"
# 언어 → (서비스 이름, 키 환경변수). 서비스 이름은 활용매뉴얼(국문·영문·불어·일문·중문간체, v4.3~4.4)의 Call Back URL 로 확인.
LANGS = {"kor": ("KorService2", "TOURAPI_KEY_KOR"), "eng": ("EngService2", "TOURAPI_KEY_ENG"),
         "fre": ("FreService2", "TOURAPI_KEY_FRE"), "jpn": ("JpnService2", "TOURAPI_KEY_JPN"),
         "chs": ("ChsService2", "TOURAPI_KEY_CHS")}
SERVICES = tuple(v[0] for v in LANGS.values())
RESEARCH_ORDER = ("EngService2", "KorService2")      # 장소 조사에 쓰는 순서(영어 이름 우선)
SOURCE_URL = {"EngService2": "https://www.data.go.kr/data/15101753/openapi.do",
              "KorService2": "https://www.data.go.kr/data/15101578/openapi.do"}
GENERIC_URL = "https://api.visitkorea.or.kr/"
ATTRACTION_TYPES = {"12", "14", "76", "78"}
FOOD_TYPES = {"39", "82"}
CAFE_CAT3 = {"A05020900"}                           # 옛 분류(cat3)
CAFE_LCLS2 = {"FD05"}                               # 신분류체계 중분류: 카페/찻집(FD050100 카페 …)
_KO_TAIL = re.compile(r"^(.*?)\s*[(（]([^()（）]*[가-힣][^()（）]*)[)）]\s*$")


def split_title(title: str) -> "tuple[str, str]":
    """다국어 title 끝의 한국어 괄호를 떼어 (이름, 한국어 이름). 괄호가 없거나 한글이 없으면 (원문, "")."""
    t = re.sub(r"\s+", " ", title or "").strip()
    m = _KO_TAIL.match(t)
    if m and m.group(1).strip() and re.search(r"[A-Za-z\u3040-\u30ff\u4e00-\u9fff]", m.group(1)):
        return m.group(1).strip(), m.group(2).strip()
    return t, ""


def food_kind(it: dict) -> str:
    cafe = str(it.get("lclsSystm2") or "") in CAFE_LCLS2 or str(it.get("cat3") or "") in CAFE_CAT3
    return "cafe" if cafe else "restaurant"
MOBILE_APP = "MADI"


def key(svc: str = "") -> str:
    """그 서비스의 키: 언어별 변수 → 공통 TOURAPI_SERVICE_KEY. svc 를 안 주면 지금 쓸 서비스(service())의 키."""
    svc = svc or service()
    env = next((e for s, e in LANGS.values() if s == svc), "")
    return ((os.getenv(env) if env else "") or os.getenv("TOURAPI_SERVICE_KEY") or "").strip()


def service() -> str:
    """장소 조사에 쓸 서비스. TOURAPI_SERVICE(키가 있을 때) → 영문 → 국문 순으로 키가 있는 것."""
    forced = (os.getenv("TOURAPI_SERVICE") or "").strip()
    for svc in ((forced,) if forced in SERVICES else ()) + RESEARCH_ORDER:
        if key(svc):
            return svc
    return "EngService2"


def source_url(svc: str) -> str:
    return SOURCE_URL.get(svc, GENERIC_URL)


def available() -> bool:
    return config.source_on("tourapi") and bool(key(service()))


def radius_m(population: int) -> int:
    return 10000 if population >= 1_000_000 else (6000 if population >= 200_000 else 4000)


def _scale(ref: dict) -> float:
    from .. import chain
    return chain.scale(ref)


def _url(svc: str, params: dict) -> str:
    k = key(svc)
    enc = k if "%" in k else urllib.parse.quote(k, safe="")       # Encoding 키는 그대로, Decoding 키는 인코딩
    base = {"MobileOS": "ETC", "MobileApp": MOBILE_APP, "_type": "json"}
    return f"{ROOT}/{svc}/locationBasedList2?serviceKey={enc}&" + urllib.parse.urlencode({**base, **params})


def _code_status(code: str, text: str) -> "tuple[str, str]":
    if code == "22" or "LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS" in text:
        return "capped", "daily_quota"
    if code == "23" or "LIMITED_NUMBER_OF_SERVICE_REQUESTS_PER_SECOND" in text:
        return "rate_limited", "per_second"
    if code in ("20", "30", "31") or "SERVICE_KEY" in text or "SERVICE_ACCESS_DENIED" in text:
        return "unavailable", "http_403"                           # chain.classify → exhaust(6시간)
    return "unavailable", f"code_{code or 'gw'}"[:20]


def _items(data: Any) -> list:
    body = ((data or {}).get("response") or {}).get("body") or {}
    items = body.get("items")
    item = items.get("item") if isinstance(items, dict) else None   # 결과가 없으면 items 가 "" 로 온다
    if isinstance(item, dict):
        return [item]
    return item if isinstance(item, list) else []


def fetch(http: SafeHttp, ref: dict, ckey: str, want: dict) -> dict:
    if not available():
        return result("tourapi", "disabled", reason="no_key")
    if ref.get("iso2") != "KR":
        return result("tourapi", "empty", reason="not_korea")
    lat, lon = ref.get("lat"), ref.get("lon")
    if lat is None or lon is None:
        return result("tourapi", "empty", reason="no_coords")
    if not want.get("attraction") and not want.get("food"):
        return result("tourapi", "empty", reason="not_needed")
    svc = service()
    res = http.request("GET", _url(svc, {"mapX": f"{float(lon):.6f}", "mapY": f"{float(lat):.6f}",
                                         "radius": min(20000, int(radius_m(int(ref.get("population") or 0)) * _scale(ref))),
                                         "arrange": "E", "numOfRows": 100, "pageNo": 1}), timeout=10)
    text = res.body[:2000].decode("utf-8", "replace") if res.body else ""
    if not res.ok:
        st, why = ("rate_limited", "http_429") if res.status == 429 else _code_status("", text)
        return result("tourapi", st if res.status != 0 else "unavailable", reason=why if res.status else (res.error or "network"))
    data = res.json()
    code = str((((data or {}).get("response") or {}).get("header") or {}).get("resultCode") or "")
    if data is None or code not in ("0000", "00"):
        st, why = _code_status(code, text)
        return result("tourapi", st, reason=why)
    out = []
    for it in _items(data):
        if not isinstance(it, dict):
            continue
        t = str(it.get("contenttypeid") or "")
        if t in ATTRACTION_TYPES:
            kind = "attraction"
        elif t in FOOD_TYPES:
            kind = food_kind(it)
        else:
            continue
        cid = str(it.get("contentid") or "")
        try:
            plat, plon = float(it.get("mapy")), float(it.get("mapx"))
        except (TypeError, ValueError):
            continue
        if not re.fullmatch(r"\d{1,12}", cid):
            continue
        name, name_ko = split_title(str(it.get("title") or ""))
        addr = re.sub(r"\s+", " ", str(it.get("addr1") or "")).strip()[:120]
        p = verify.place({"id": f"kto:{ckey}:{cid}", "name": name, "kind": kind, "lat": plat, "lon": plon, "area": "",
                          "desc_en": (f"Address: {addr}." if addr and svc == "EngService2" else ""), "section": "",
                          "homepage": "", "wikidata": "", "provider": "tourapi", "kto_id": cid, "address": addr,
                          "name_ko": name_ko, "category": str(it.get("lclsSystm3") or "")[:12],
                          "sources": [{"provider": "tourapi", "url": source_url(svc), "title": name,
                                       "license": LICENSES["tourapi"][0]}]},
                         lat, lon)
        if p:
            out.append(p)
    return result("tourapi", "ok" if out else "empty", out, url=source_url(svc))


def adapter(deps: Any, tc: dict, want: dict) -> dict:
    return fetch(deps.http, tc["ref"], tc["ref"]["key"], want)


adapter.available = available  # type: ignore[attr-defined]
