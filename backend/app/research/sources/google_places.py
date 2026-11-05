"""대체 장소 소스 ③ — Google Places(New) 텍스트 검색, **실시간 전용**(결과를 저장하지 않는다).

- Google 약관: place_id 외의 내용(이름·좌표·주소…)은 캐시·저장 금지(좌표는 30일). 그래서 이 소스의 장소는
  places_extra 캐시에도, LLM 추출 캐시에도 들어가지 않는다(nodes.py 가 provider=="google" 을 걸러 낸다).
  캐시된 보고서가 모자라면 그때마다 이 소스만 다시 묻는다(need "live").
- 호출은 기존 일정 에이전트(agents/itinerary.py)의 _search_one·_place_from 을 그대로 쓰고, 도시 좌표 원으로 locationBias 를 건다.
- 한도: ITINERARY_DAILY_CAP(프로세스·UTC 하루, 일정 에이전트와 공유). 다 쓰면 capped → 체인이 6시간 쉰다.
- 키: GOOGLE_MAPS_API_KEY. 없으면 disabled(체인이 건너뜀).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import urllib.parse
from typing import Any

from .. import config, verify
from ..net import SafeHttp
from . import result

NO_STORE = "google"
KIND_QUERIES = {"attraction": [("attraction", "tourist_attraction", "tourist attraction")],
                "food": [("restaurant", "restaurant", "restaurant"), ("cafe", "cafe", "cafe")]}


def radius_m(population: int) -> int:
    return 10000 if population >= 1_000_000 else (6000 if population >= 200_000 else 4000)


def _http(http: SafeHttp):
    def call(url: str, body: bytes, headers: dict, timeout: float) -> "tuple[int, Any]":
        res = http.request("POST", url, body=body, headers=headers, timeout=timeout)
        return res.status, (res.json() if res.ok else {})
    return call


def fetch(http: SafeHttp, ref: dict, key: str, want: dict) -> dict:
    from ...agents import itinerary
    if not config.source_on("google") or not itinerary.google_maps_configured():
        return result("google", "disabled", reason="no_key")
    lat, lon = ref.get("lat"), ref.get("lon")
    if lat is None or lon is None:
        return result("google", "empty", reason="no_coords")
    plan = [q for bucket in ("attraction", "food") if want.get(bucket) for q in KIND_QUERIES[bucket]]
    if not plan:
        return result("google", "empty", reason="not_needed")
    take = itinerary._reserve(len(plan))
    if take <= 0:
        return result("google", "capped", reason="daily_cap")
    city = " ".join(x for x in (ref.get("name") or ref.get("input"), ref.get("country_name")) if x)
    from .. import chain
    bias = {"lat": float(lat), "lon": float(lon),
            "radius_m": min(50000, int(radius_m(int(ref.get("population") or 0)) * chain.scale(ref)))}
    fetched_at = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    key_ = (os.getenv("GOOGLE_MAPS_API_KEY") or "").strip()
    out, statuses = [], []
    for kind, included, tail in plan[:take]:
        row = itinerary._search_one({"text": f"{city} {tail}", "included_type": included}, _http(http), key_, fetched_at, bias)
        statuses.append(row.get("reason") or row.get("status"))
        for g in row.get("places") or []:
            p = verify.place({"id": f"gp:{key}:{g['provider_id']}", "name": g["name"], "kind": kind, "lat": g["lat"], "lon": g["lon"],
                              "area": "", "desc_en": "", "section": "", "homepage": "", "wikidata": "", "provider": NO_STORE,
                              "live": True,
                              "sources": [{"provider": "google", "url": g["source_url"], "title": g["name"], "license": "Google Maps"}]},
                             lat, lon)
            if p and not any(x["id"] == p["id"] for x in out):
                out.append(p)
    if out:
        return result("google", "ok", out, url="https://maps.google.com/")
    if any(s == "http_429" for s in statuses):
        return result("google", "rate_limited", reason="http_429")
    if any(s in ("http_401", "http_403") for s in statuses):
        return result("google", "unavailable", reason=next(s for s in statuses if s in ("http_401", "http_403")))
    if any(str(s).startswith("http_5") or s == "http_0" or s in ("URLError", "TimeoutError", "bad_json") for s in statuses):
        return result("google", "unavailable", reason="http_5xx")
    return result("google", "empty", reason=json.dumps(statuses)[:40])


def adapter(deps: Any, tc: dict, want: dict) -> dict:
    return fetch(deps.http, tc["ref"], tc["ref"]["key"], want)


def find(http: SafeHttp, ref: dict, name: str) -> "dict | None":
    """사용자가 적은 장소 이름 하나를 도시 근처에서 찾는다(place_check). 종류 제한 없이, 결과는 저장하지 않는다.
    → {name, lat, lon, url, address} 또는 None. 일 한도(ITINERARY_DAILY_CAP)를 1 쓴다."""
    from ...agents import itinerary
    if not available() or ref.get("lat") is None or itinerary._reserve(1) <= 0:
        return None
    from .. import chain
    body = {"textQuery": name, "languageCode": "en", "maxResultCount": 3,
            "locationBias": {"circle": {"center": {"latitude": float(ref["lat"]), "longitude": float(ref["lon"])},
                                        "radius": float(min(50000, radius_m(int(ref.get("population") or 0)) * chain.scale(ref)))}}}
    # 장소 확인 창: 사진 참조(places.photos)도 함께 받는다 — 무료 공용 사진이 없을 때만 쓴다(photo_uri)
    headers = {"Content-Type": "application/json", "X-Goog-Api-Key": (os.getenv("GOOGLE_MAPS_API_KEY") or "").strip(),
               "X-Goog-FieldMask": itinerary.FIELD_MASK + ",places.photos"}
    res = http.request("POST", itinerary.SEARCH_URL, body=json.dumps(body).encode("utf-8"), headers=headers, timeout=8)
    data = res.json() if res.ok else None
    fetched = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for item in (data or {}).get("places") or []:
        p = itinerary._place_from(item, fetched)
        if p:
            return {"name": p["name"], "lat": p["lat"], "lon": p["lon"], "url": p["source_url"],
                    "address": ((p.get("data") or {}).get("formatted_address") or ""), "photo": _first_photo(item)}
    return None


def _first_photo(item: Any) -> "dict | None":
    """첫 사진의 참조 이름과 찍은 사람(표시 의무 — authorAttributions). 참조 이름은 오래 두지 않는다."""
    for ph in (item or {}).get("photos") or []:
        name = str((ph or {}).get("name") or "")
        if not re.fullmatch(r"places/[A-Za-z0-9_-]{1,300}/photos/[A-Za-z0-9_-]{1,800}", name):
            continue
        authors = []
        for a in (ph.get("authorAttributions") or [])[:3]:
            n = re.sub(r"<[^>]*>|[<>{}]", " ", str((a or {}).get("displayName") or ""))   # 태그는 통째로, 남은 꺾쇠도 지운다
            n = re.sub(r"\s+", " ", n).strip()[:60]
            u = str((a or {}).get("uri") or "")
            if u.startswith("//"):
                u = "https:" + u
            authors.append({"name": n or "Google 사용자", "uri": u if re.fullmatch(r"https://[^\s\"'<>]+", u) else ""})
        return {"name": name, "authors": authors}
    return None


def photo_uri(http: SafeHttp, photo: dict, width: int = 500) -> "dict | None":
    """사진 참조 → 화면에 바로 넣을 짧게 쓰는 주소(photoUri, googleusercontent — API 키가 들어 있지 않다).
    Google 약관: 사진·주소를 저장·캐시하지 않는다 — 이 결과는 그 확인 창 한 번에만 쓴다. 일 한도를 1 쓴다."""
    from ...agents import itinerary
    if not photo or not available() or itinerary._reserve(1) <= 0:
        return None
    url = (f"https://places.googleapis.com/v1/{photo['name']}/media?"
           + urllib.parse.urlencode({"maxWidthPx": width, "skipHttpRedirect": "true"}))
    res = http.request("GET", url, headers={"X-Goog-Api-Key": (os.getenv("GOOGLE_MAPS_API_KEY") or "").strip()}, timeout=8)
    uri = str(((res.json() or {}) if res.ok else {}).get("photoUri") or "")
    if not re.fullmatch(r"https://[a-z0-9-]+\.googleusercontent\.com/[^\s\"'<>]+", uri):
        return None
    return {"src": uri, "provider": "google", "credit": "Google 지도", "authors": photo.get("authors") or [],
            "license": "Google Maps"}


def available() -> bool:
    """키가 있고 소스가 켜져 있을 때만 체인에 들어간다(없으면 '실시간 보충 필요'로 캐시 응답을 막지 않게)."""
    from ...agents import itinerary
    return config.source_on("google") and itinerary.google_maps_configured()


adapter.available = available  # type: ignore[attr-defined]
