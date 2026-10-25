"""조사 노드(에이전트) 함수 — LangGraph 를 몰라도 되게 (state, deps) 만 받는다. graph.py 가 이어 붙인다.

- planner: 여행 입력 해석 + 섹션별 캐시 확인 → 새로 조사할 나라·도시만 남긴다
- country agent: Wikidata 사실 → (통화가 나오면) Frankfurter 환율. 안전 권고는 외교부 키가 생기면(영국 FCDO 는 쓰지 않는다)
- city agents: guide(Wikidata 다리 → 위키보이지) ∥ climate(Open-Meteo) → extract(LLM: 여행 조건별 순위·한국어 요약) → finalize
모든 소스 실패는 status 로 남고 예외를 올리지 않는다.
"""
from __future__ import annotations

import datetime as dt
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from . import config
from .cache import ResearchCache
from .net import SafeHttp
from . import extract
from .sources import frankfurter, openmeteo, wikidata, wikivoyage

DAY = 86400
UNRESOLVED_TTL = 7 * DAY
# LLM 추출은 이 풀에서 돈다. 잡은 소프트 마감까지만 기다리고, 늦은 추출은 끝까지 돌아 캐시만 데운다(다음 사용자는 바로 받는다).
# Gemini 경로는 최소 시도 규칙(30회) 때문에 장애 때 몇 분이 걸릴 수 있다 — 화면(150초)이 예시로 떨어지지 않게 한다.
_EXTRACT_POOL = None
_EXTRACT_LOCK = threading.Lock()


def _extract_pool():
    global _EXTRACT_POOL
    from concurrent.futures import ThreadPoolExecutor
    with _EXTRACT_LOCK:
        if _EXTRACT_POOL is None:
            _EXTRACT_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="research-extract")
        return _EXTRACT_POOL


@dataclass
class Deps:
    http: SafeHttp
    cache: ResearchCache
    store: Any                                         # geo.GeoStore
    today: dt.date = field(default_factory=dt.date.today)
    started: float = field(default_factory=time.monotonic)
    on_progress: Optional[Callable[[dict], None]] = None
    llm: Optional[extract.LLM] = None                  # 테스트용 가짜 모델. None 이면 Gemini
    llm_on: Optional[bool] = None                      # None 이면 config.llm_enabled()
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def progress(self, who: str, step: str, state: str = "running") -> None:
        if self.on_progress:
            with self._lock:
                self.on_progress({"who": who, "step": step, "state": state, "at": int(time.time())})

    def use_llm(self) -> bool:
        if self.llm_on is None:
            self.llm_on = self.llm is not None or config.llm_enabled()
        return self.llm_on

    def past_deadline(self) -> bool:
        return time.monotonic() - self.started > config.soft_deadline_s()


def _src(r: dict) -> dict:
    return {k: r.get(k, "") for k in ("provider", "status", "reason", "url", "license", "attribution")}


def climate_section(tc: dict) -> str:
    s = dt.date.fromisoformat(tc["start"])
    return f"climate_{s.month:02d}{s.day:02d}_{min(tc['nights'], 59)}"


# ------------------------------------------------------------------ planner
def plan(deps: Deps, resolved: dict) -> dict:
    """나라·도시별로 캐시에서 신선한 섹션을 읽고, 빠진 것만 need 로 남긴다."""
    countries, cities = [], []
    for c in resolved["countries"]:
        if not c["iso2"]:
            continue
        cached = {s: deps.cache.get("research_countries", c["iso2"], s) for s in ("facts", "fx")}
        need = [s for s, v in cached.items() if v is None]
        countries.append({"country": c, "need": need, "cached": {s: v for s, v in cached.items() if v}})
    for tc in resolved["cities"]:
        key = tc["ref"]["key"]
        sec = climate_section(tc)
        cached = {"guide": deps.cache.get("research_cities", key, "guide"),
                  "climate": deps.cache.get("research_cities", key, sec) if tc["ref"]["lat"] is not None else None}
        need = [s for s, v in cached.items() if v is None and (s != "climate" or tc["ref"]["lat"] is not None)]
        if deps.use_llm():
            ex = deps.cache.get("research_cities", key, extract.section_name(tc))
            g = ((cached["guide"] or {}).get("data") or {}).get("wikivoyage") if cached["guide"] else None
            if ex is not None:
                cached["extract"] = ex
            # 위키보이지 문서가 바뀌었으면(revid) 다시 고른다. 문서가 없는 도시는 고를 것이 없다.
            if cached["guide"] is None or (g and (ex is None or ex["data"].get("revid") != g.get("revid"))):
                need.append("extract")
        cities.append({"tc": tc, "need": need, "cached": {s: v for s, v in cached.items() if v}})
    return {"countries": countries, "cities": cities}


def all_fresh(p: dict) -> bool:
    return not any(x["need"] for x in p["countries"] + p["cities"])


# ------------------------------------------------------------------ country agent
def run_country(deps: Deps, item: dict) -> dict:
    c, need, cached = item["country"], item["need"], item["cached"]
    iso2 = c["iso2"]
    out = {k: v["data"] for k, v in cached.items()}
    sources = [s for v in cached.values() for s in v.get("sources") or []]
    deps.progress(c["name"], "country")
    if "facts" in need:
        r = wikidata.country_facts(deps.http, iso2)
        sources.append(_src(r))
        if r["status"] == "ok":
            out["facts"] = r["data"]
            deps.cache.put("research_countries", iso2, "facts", r["data"], config.cache_days() * DAY, [_src(r)])
    if "fx" in need and (out.get("facts") or {}).get("currency"):
        r = frankfurter.krw_rate(deps.http, out["facts"]["currency"])
        sources.append(_src(r))
        if r["status"] == "ok":
            out["fx"] = r["data"]
            deps.cache.put("research_countries", iso2, "fx", r["data"], config.volatile_hours() * 3600, [_src(r)])
    out["sources"] = sources
    deps.progress(c["name"], "country", "done")
    return out


# ------------------------------------------------------------------ city agents
def city_guide(deps: Deps, tc: dict, need: list, cached: dict) -> dict:
    """위키보이지 문서 하나(+구역 2개). 제목 후보: Wikidata 사이트링크, 도시 ASCII 이름."""
    ref = tc["ref"]
    if "guide" not in need:
        return {"guide": cached["guide"]["data"], "guide_sources": cached["guide"].get("sources") or []}
    deps.progress(ref["input"], "guide")
    sources, candidates = [], []
    if ref["gid"]:
        b = wikidata.city_bridge(deps.http, ref["gid"])
        sources.append(_src(b))
        if b["status"] == "ok" and b["data"]["wikivoyage"]:
            candidates.append(b["data"]["wikivoyage"])
    if ref["ascii"]:
        candidates.append(ref["ascii"])
    r = wikivoyage.fetch(deps.http, candidates)
    sources.append(_src(r))
    guide = {"wikivoyage": r["data"] if r["status"] == "ok" else None}
    if r["status"] == "ok":
        ttl = config.cache_days() * DAY if ref["resolved"] else UNRESOLVED_TTL
        deps.cache.put("research_cities", ref["key"], "guide", guide, ttl, sources)
    deps.progress(ref["input"], "guide", "done" if r["status"] == "ok" else r["status"])
    return {"guide": guide, "guide_sources": sources}


def city_climate(deps: Deps, tc: dict, need: list, cached: dict) -> dict:
    ref = tc["ref"]
    if "climate" not in need:
        c = cached.get("climate")
        return {"climate": c["data"] if c else None, "climate_sources": (c or {}).get("sources") or []}
    deps.progress(ref["input"], "climate")
    r = openmeteo.climate(deps.http, ref["lat"], ref["lon"], tc["start"], tc["end"], deps.today)
    if r["status"] == "ok":
        ttl = config.volatile_hours() * 3600 if r["data"]["kind"] == "forecast" else config.cache_days() * DAY
        deps.cache.put("research_cities", ref["key"], climate_section(tc), r["data"], ttl, [_src(r)])
    deps.progress(ref["input"], "climate", "done" if r["status"] == "ok" else r["status"])
    return {"climate": r["data"] if r["status"] == "ok" else None, "climate_sources": [_src(r)]}


def city_extract(deps: Deps, tc: dict, need: list, cached: dict, guide: Optional[dict], climate: Optional[dict]) -> dict:
    """→ {"extract": {revid, places, practical} | None, "extract_status": str}. 실패는 None(보고서는 listing 그대로)."""
    from . import report
    ref = tc["ref"]
    wv = (guide or {}).get("wikivoyage") or {}
    ex = cached.get("extract")
    if ex is not None and ex["data"].get("revid") == wv.get("revid"):
        return {"extract": ex["data"], "extract_status": "ok"}
    if "extract" not in need or not deps.use_llm():
        return {"extract": None, "extract_status": "disabled" if not deps.use_llm() else "none"}
    if not wv.get("listings") and not wv.get("sections"):
        return {"extract": None, "extract_status": "empty"}
    if deps.past_deadline():
        return {"extract": None, "extract_status": "deadline"}
    deps.progress(ref["input"], "extract")
    places = report.places_from(ref, wv) if wv.get("listings") else []

    def work() -> dict:
        r = extract.run(tc, places, report.practical_from(wv), climate, deps.llm)
        if r["status"] == "ok":
            r["data"] = {"revid": wv.get("revid"), **r["data"]}
            ttl = config.cache_days() * DAY if ref["resolved"] else UNRESOLVED_TTL
            deps.cache.put("research_cities", ref["key"], extract.section_name(tc), r["data"], ttl,
                           [{"provider": "gemini", "status": "ok", "reason": "", "url": "", "license": "", "attribution": ""}])
        return r

    from concurrent.futures import TimeoutError as FutureTimeout
    left = config.soft_deadline_s() - (time.monotonic() - deps.started)
    try:
        r = _extract_pool().submit(work).result(timeout=max(1.0, left))
    except FutureTimeout:
        deps.progress(ref["input"], "extract", "deadline")
        return {"extract": None, "extract_status": "deadline"}
    if r["status"] != "ok":
        deps.progress(ref["input"], "extract", r["status"])
        return {"extract": None, "extract_status": r["status"]}
    deps.progress(ref["input"], "extract", "done")
    return {"extract": r["data"], "extract_status": "ok"}


def city_finalize(tc: dict, guide: dict, climate: Optional[dict], sources: list,
                  ext: Optional[dict] = None, ext_status: str = "none") -> dict:
    return {"guide": guide or {}, "climate": climate, "sources": sources, "extract": ext, "extract_status": ext_status}
