"""LangGraph 배선. 노드 로직은 nodes.py — 여기는 순서와 병렬만 정한다.

    START → planner ─Send→ country (나라마다)  ─┐
                    └Send→ city   (도시마다)  ─┴→ writer → END
    city(서브그래프): START → guide ∥ climate → places(대체 소스 체인, 모자랄 때만) → extract(LLM, 선택) → finalize → END

langgraph 는 처음 쓸 때 불러온다(플래그가 꺼진 서버는 메모리에 올리지 않는다).
"""
from __future__ import annotations

import operator
from typing import Annotated, Any, Optional, TypedDict

from . import nodes, report


def _merge(a: Optional[dict], b: Optional[dict]) -> dict:
    return {**(a or {}), **(b or {})}


class ResearchState(TypedDict, total=False):
    resolved: dict
    plan: dict
    country_out: Annotated[dict, _merge]
    city_out: Annotated[dict, _merge]
    issues: Annotated[list, operator.add]
    report: dict


class CityState(TypedDict, total=False):
    tc: dict
    need: list
    cached: dict
    guide: Any
    guide_sources: list
    climate: Any
    climate_sources: list
    places: dict
    extract: Any
    extract_status: str
    out: dict


def build(deps: nodes.Deps):
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import Send

    # ---- 도시 서브그래프: 위키보이지와 날씨를 동시에
    cg = StateGraph(CityState)
    cg.add_node("guide", lambda s: nodes.city_guide(deps, s["tc"], s["need"], s["cached"]))
    cg.add_node("climate", lambda s: nodes.city_climate(deps, s["tc"], s["need"], s["cached"]))
    cg.add_node("places", lambda s: {"places": nodes.city_places(deps, s["tc"], s["need"], s["cached"], s.get("guide"))})
    cg.add_node("extract", lambda s: nodes.city_extract(deps, s["tc"], s["need"], s["cached"], s.get("guide"), s.get("climate"),
                                                        (s.get("places") or {}).get("extra_places")))
    cg.add_node("finalize", lambda s: {"out": nodes.city_finalize(
        s["tc"], s.get("guide"), s.get("climate"), (s.get("guide_sources") or []) + (s.get("climate_sources") or []),
        s.get("extract"), s.get("extract_status") or "none", s.get("places"))})
    cg.add_edge(START, "guide")
    cg.add_edge(START, "climate")
    cg.add_edge(["guide", "climate"], "places")
    cg.add_edge("places", "extract")
    cg.add_edge("extract", "finalize")
    cg.add_edge("finalize", END)
    city_graph = cg.compile()

    def city(item: dict) -> dict:
        tc = item["tc"]
        try:
            out = city_graph.invoke({"tc": tc, "need": item["need"], "cached": item["cached"]})["out"]
        except Exception as exc:  # noqa: BLE001 — 한 도시가 실패해도 다른 도시는 끝까지 간다
            return {"city_out": {tc["ref"]["key"]: {"guide": {}, "climate": None, "sources": []}},
                    "issues": [{"who": tc["ref"]["input"], "issue": "city_failed", "error": type(exc).__name__}]}
        return {"city_out": {tc["ref"]["key"]: out}}

    def country(item: dict) -> dict:
        try:
            return {"country_out": {item["country"]["iso2"]: nodes.run_country(deps, item)}}
        except Exception as exc:  # noqa: BLE001
            return {"issues": [{"who": item["country"]["name"], "issue": "country_failed", "error": type(exc).__name__}]}

    def planner(state: ResearchState) -> dict:
        return {"plan": state.get("plan") or nodes.plan(deps, state["resolved"])}

    def fan_out(state: ResearchState):
        p = state["plan"]
        sends = [Send("country", c) for c in p["countries"]] + [Send("city", c) for c in p["cities"]]
        return sends or "writer"

    def writer(state: ResearchState) -> dict:
        return {"report": report.build(state["resolved"], state.get("country_out") or {}, state.get("city_out") or {},
                                       state.get("issues") or [])}

    g = StateGraph(ResearchState)
    g.add_node("planner", planner)
    g.add_node("country", country)
    g.add_node("city", city)
    g.add_node("writer", writer)
    g.add_edge(START, "planner")
    g.add_conditional_edges("planner", fan_out, ["country", "city", "writer"])
    g.add_edge("country", "writer")
    g.add_edge("city", "writer")
    g.add_edge("writer", END)
    return g.compile()


def run_graph(deps: nodes.Deps, resolved: dict, plan: Optional[dict] = None) -> dict:
    graph = build(deps)
    state = graph.invoke({"resolved": resolved, **({"plan": plan} if plan else {})},
                         config={"max_concurrency": 4, "recursion_limit": 40})
    return state["report"]


def _city_plain(deps: nodes.Deps, item: dict) -> dict:
    tc, need, cached = item["tc"], item["need"], item["cached"]
    g = nodes.city_guide(deps, tc, need, cached)
    c = nodes.city_climate(deps, tc, need, cached)
    pl = nodes.city_places(deps, tc, need, cached, g.get("guide"))
    e = nodes.city_extract(deps, tc, need, cached, g.get("guide"), c.get("climate"), pl.get("extra_places"))
    return nodes.city_finalize(tc, g.get("guide"), c.get("climate"), (g.get("guide_sources") or []) + (c.get("climate_sources") or []),
                               e.get("extract"), e.get("extract_status") or "none", pl)


def run_plain(deps: nodes.Deps, resolved: dict, plan: Optional[dict] = None) -> dict:
    """LangGraph 없이 같은 노드를 스레드 4개로 돌린다 — 결과는 run_graph 와 같다(테스트로 고정).
    RESEARCH_USE_GRAPH=0 이거나 그래프가 실패했을 때(메모리·의존성 문제) 쓰는 탈출구."""
    from concurrent.futures import ThreadPoolExecutor

    plan = plan or nodes.plan(deps, resolved)
    country_out, city_out, issues = {}, {}, []
    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="research-plain") as ex:
        jobs = [("country", c, ex.submit(nodes.run_country, deps, c)) for c in plan["countries"]]
        jobs += [("city", c, ex.submit(_city_plain, deps, c)) for c in plan["cities"]]
        for kind, item, fut in jobs:
            try:
                out = fut.result()
            except Exception as exc:  # noqa: BLE001 — 하나가 실패해도 나머지는 끝까지
                who = item["country"]["name"] if kind == "country" else item["tc"]["ref"]["input"]
                issues.append({"who": who, "issue": f"{kind}_failed", "error": type(exc).__name__})
                if kind == "city":
                    city_out[item["tc"]["ref"]["key"]] = {"guide": {}, "climate": None, "sources": []}
                continue
            if kind == "country":
                country_out[item["country"]["iso2"]] = out
            else:
                city_out[item["tc"]["ref"]["key"]] = out
    return report.build(resolved, country_out, city_out, issues)


def run(deps: nodes.Deps, resolved: dict, plan: Optional[dict] = None) -> dict:
    from . import config
    if not config.use_graph():
        return run_plain(deps, resolved, plan)
    try:
        return run_graph(deps, resolved, plan)
    except Exception as exc:  # noqa: BLE001 — 그래프(의존성·메모리)가 실패하면 같은 노드로 다시 돈다. 캐시된 섹션은 다시 받지 않는다
        import logging
        logging.getLogger("app.research").warning("research graph failed %s — plain runner", type(exc).__name__)
        return run_plain(deps, resolved, plan)


def from_cache(resolved: dict, plan: dict) -> dict:
    """전부 신선한 캐시일 때: 외부 호출 없이 보고서만 조립한다."""
    country_out = {x["country"]["iso2"]: {**{k: v["data"] for k, v in x["cached"].items()},
                                          "sources": [s for v in x["cached"].values() for s in v.get("sources") or []]}
                   for x in plan["countries"]}
    city_out = {}
    for x in plan["cities"]:
        g, c, e = x["cached"].get("guide"), x["cached"].get("climate"), x["cached"].get("extract")
        px = x["cached"].get("places_extra")
        city_out[x["tc"]["ref"]["key"]] = {"guide": g["data"] if g else {}, "climate": c["data"] if c else None,
                                           "sources": (g or {}).get("sources", []) + (c or {}).get("sources", []),
                                           "extract": e["data"] if e else None, "extract_status": "ok" if e else "none",
                                           "extra_places": ((px or {}).get("data") or {}).get("places") or [],
                                           "places_stale": bool(px and px.get("stale")),
                                           "chain": ((px or {}).get("data") or {}).get("by_source") or {}}
    return report.build(resolved, country_out, city_out)
