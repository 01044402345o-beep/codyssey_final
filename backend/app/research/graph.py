"""LangGraph 배선. 노드 로직은 nodes.py — 여기는 순서와 병렬만 정한다.

    START → planner ─Send→ country (나라마다)  ─┐
                    └Send→ city   (도시마다)  ─┴→ writer → END
    city(서브그래프): START → guide ∥ climate → finalize → END

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
    out: dict


def build(deps: nodes.Deps):
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import Send

    # ---- 도시 서브그래프: 위키보이지와 날씨를 동시에
    cg = StateGraph(CityState)
    cg.add_node("guide", lambda s: nodes.city_guide(deps, s["tc"], s["need"], s["cached"]))
    cg.add_node("climate", lambda s: nodes.city_climate(deps, s["tc"], s["need"], s["cached"]))
    cg.add_node("finalize", lambda s: {"out": nodes.city_finalize(
        s["tc"], s.get("guide"), s.get("climate"), (s.get("guide_sources") or []) + (s.get("climate_sources") or []))})
    cg.add_edge(START, "guide")
    cg.add_edge(START, "climate")
    cg.add_edge(["guide", "climate"], "finalize")
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


def run(deps: nodes.Deps, resolved: dict, plan: Optional[dict] = None) -> dict:
    graph = build(deps)
    state = graph.invoke({"resolved": resolved, **({"plan": plan} if plan else {})},
                         config={"max_concurrency": 4, "recursion_limit": 40})
    return state["report"]


def from_cache(resolved: dict, plan: dict) -> dict:
    """전부 신선한 캐시일 때: 외부 호출 없이 보고서만 조립한다."""
    country_out = {x["country"]["iso2"]: {**{k: v["data"] for k, v in x["cached"].items()},
                                          "sources": [s for v in x["cached"].values() for s in v.get("sources") or []]}
                   for x in plan["countries"]}
    city_out = {}
    for x in plan["cities"]:
        g, c = x["cached"].get("guide"), x["cached"].get("climate")
        city_out[x["tc"]["ref"]["key"]] = {"guide": g["data"] if g else {}, "climate": c["data"] if c else None,
                                           "sources": (g or {}).get("sources", []) + (c or {}).get("sources", [])}
    return report.build(resolved, country_out, city_out)
