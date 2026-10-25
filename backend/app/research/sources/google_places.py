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
    bias = {"lat": float(lat), "lon": float(lon), "radius_m": radius_m(int(ref.get("population") or 0))}
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


def available() -> bool:
    """키가 있고 소스가 켜져 있을 때만 체인에 들어간다(없으면 '실시간 보충 필요'로 캐시 응답을 막지 않게)."""
    from ...agents import itinerary
    return config.source_on("google") and itinerary.google_maps_configured()


adapter.available = available  # type: ignore[attr-defined]
