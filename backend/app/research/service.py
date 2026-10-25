"""엔드포인트가 부르는 진입점. main.py 는 요청 검증·속도 제한만 하고 여기로 넘긴다."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from typing import Any, Optional

from . import config, graph, identity, nodes
from .cache import ResearchCache
from .jobs import JOBS, Busy  # noqa: F401 — main 이 Busy 를 잡는다
from .net import SafeHttp

CACHE = ResearchCache()


def _store():
    from .. import geo
    return geo.STORE


def check_dates(cities: list[dict], today: Optional[dt.date] = None) -> Optional[str]:
    """여행 날짜는 어제 ~ 400일 뒤 안이어야 한다(남용·이상 값 차단)."""
    today = today or dt.date.today()
    lo, hi = today - dt.timedelta(days=1), today + dt.timedelta(days=400)
    for c in cities:
        try:
            s, e = dt.date.fromisoformat(c["start"]), dt.date.fromisoformat(c["end"])
        except (KeyError, ValueError):
            return "bad_dates"
        if e < s or s < lo or e > hi or (e - s).days > 59:
            return "bad_dates"
    return None


def job_key(req: dict) -> str:
    body = {"countries": [(c.get("iso2") or "", c.get("name") or "") for c in req["countries"]],
            "cities": [(c.get("name"), c.get("gid"), c.get("ci"), c.get("start"), c.get("end"), c.get("attr"), c.get("rest"))
                       for c in req["cities"]]}
    return hashlib.sha1(json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def submit(req: dict, ip: str, *, http: Optional[SafeHttp] = None, cache: Optional[ResearchCache] = None,
           store: Any = None, today: Optional[dt.date] = None) -> dict:
    """→ {status: unavailable|done|miss|running, ...}. Busy 는 호출부가 503 으로."""
    if not config.research_enabled():
        return {"status": "unavailable", "reason": "research_disabled"}
    if len(req["cities"]) > config.max_cities():
        return {"status": "unavailable", "reason": "too_many_cities"}
    bad = check_dates(req["cities"], today)
    if bad:
        return {"status": "unavailable", "reason": bad}
    store = store or _store()
    cache = cache or CACHE
    resolved = identity.resolve(store, req)
    base = nodes.Deps(http=http or SafeHttp(), cache=cache, store=store, today=today or dt.date.today())
    plan = nodes.plan(base, resolved)
    if nodes.all_fresh(plan):
        return {"status": "done", "report": graph.from_cache(resolved, plan), "cached": True}
    if req.get("cache_only"):
        return {"status": "miss"}

    def work(on_progress) -> dict:
        deps = nodes.Deps(http=base.http, cache=cache, store=store, today=base.today, on_progress=on_progress)
        return graph.run(deps, resolved, plan)

    jid, joined = JOBS.start(job_key(req), ip, work)
    return {"status": "running", "job_id": jid, "joined": joined}


def poll(job_id: str) -> Optional[dict]:
    return JOBS.get(job_id)


def health() -> dict:
    """키 값 없이 상태만."""
    try:
        import importlib.util
        lg = importlib.util.find_spec("langgraph") is not None
    except (ImportError, ValueError):
        lg = False
    rss = None
    try:
        import resource  # 리눅스(Render)만
        rss = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)
    except Exception:  # noqa: BLE001 — 윈도우 등
        rss = None
    return {"enabled": config.research_enabled(), "langgraph": lg, "sources": sorted(config.sources_enabled()),
            "implemented": list(config.KEYLESS_SOURCES), "jobs_active": JOBS.active(), "max_jobs": config.max_jobs(),
            "max_rss_mb": rss}
