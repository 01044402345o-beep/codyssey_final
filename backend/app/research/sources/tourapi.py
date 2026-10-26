"""대체 장소 소스 — 한국관광공사 TourAPI 4.0(공공데이터포털, 한국 도시 전용). 저장 가능('이용허락범위 제한 없음').

한국어판 위키보이지가 없고 영어판도 한국 소도시는 빈약하다(통영 listing 24개 중 좌표 3개, 10/26 실측) — 그 빈칸을 메운다.
- 영문 관광정보서비스(EngService2)를 기본으로 쓴다: 장소 이름이 영어라 영어 문장에 그대로 쓸 수 있다.
  TOURAPI_SERVICE=KorService2 로 국문 서비스도 쓸 수 있다(활용신청은 서비스마다 따로 — 키에 승인된 서비스로).
- 도시당 한 번: locationBasedList2(도시 좌표, 인구 비례 반경 ≤20km, 거리순, 최대 100건, 종류 구분 없이) →
  contenttypeid(국문 12·14 관광, 39 음식 / 영문 76·78 관광, 82 음식 — 둘 다 받아 준다)와 cat3(A05020900 카페)로 나눈다.
- 사진(firstimage)은 쓰지 않는다: 공공누리 3유형(변경 금지) 조건이 섞여 있다.
- 오류: resultCode 22(일 한도) → capped(체인 6시간 쉼), 23(초당 한도) → rate_limited, 20·30·31(키 미등록·만료·거부) → exhaust.
  게이트웨이 오류는 HTTP 200 에 XML(OpenAPI_ServiceResponse)로 오기도 해서 본문 글자로도 판정한다.
- 키: TOURAPI_SERVICE_KEY(공공데이터포털 '일반 인증키'). Encoding/Decoding 어느 쪽을 넣어도 된다. 키 값은 로그·응답에 남기지 않는다.
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
SERVICES = ("EngService2", "KorService2")
SOURCE_URL = {"EngService2": "https://www.data.go.kr/data/15101753/openapi.do",
              "KorService2": "https://www.data.go.kr/data/15101578/openapi.do"}
ATTRACTION_TYPES = {"12", "14", "76", "78"}
FOOD_TYPES = {"39", "82"}
CAFE_CAT3 = {"A05020900"}
MOBILE_APP = "MADI"


def key() -> str:
    return (os.getenv("TOURAPI_SERVICE_KEY") or "").strip()


def service() -> str:
    s = (os.getenv("TOURAPI_SERVICE") or "EngService2").strip()
    return s if s in SERVICES else "EngService2"


def available() -> bool:
    return config.source_on("tourapi") and bool(key())


def radius_m(population: int) -> int:
    return 10000 if population >= 1_000_000 else (6000 if population >= 200_000 else 4000)


def _scale(ref: dict) -> float:
    from .. import chain
    return chain.scale(ref)


def _url(svc: str, params: dict) -> str:
    k = key()
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
        t, cat3 = str(it.get("contenttypeid") or ""), str(it.get("cat3") or "")
        if t in ATTRACTION_TYPES:
            kind = "attraction"
        elif t in FOOD_TYPES:
            kind = "cafe" if cat3 in CAFE_CAT3 else "restaurant"
        else:
            continue
        cid = str(it.get("contentid") or "")
        try:
            plat, plon = float(it.get("mapy")), float(it.get("mapx"))
        except (TypeError, ValueError):
            continue
        if not re.fullmatch(r"\d{1,12}", cid):
            continue
        name = re.sub(r"\s+", " ", str(it.get("title") or "")).strip()
        addr = re.sub(r"\s+", " ", str(it.get("addr1") or "")).strip()[:120]
        p = verify.place({"id": f"kto:{ckey}:{cid}", "name": name, "kind": kind, "lat": plat, "lon": plon, "area": "",
                          "desc_en": (f"Address: {addr}." if addr and svc == "EngService2" else ""), "section": "",
                          "homepage": "", "wikidata": "", "provider": "tourapi", "kto_id": cid, "address": addr,
                          "sources": [{"provider": "tourapi", "url": SOURCE_URL[svc], "title": name,
                                       "license": LICENSES["tourapi"][0]}]},
                         lat, lon)
        if p:
            out.append(p)
    return result("tourapi", "ok" if out else "empty", out, url=SOURCE_URL[svc])


def adapter(deps: Any, tc: dict, want: dict) -> dict:
    return fetch(deps.http, tc["ref"], tc["ref"]["key"], want)


adapter.available = available  # type: ignore[attr-defined]
