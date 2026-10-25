"""조사 결과 → 화면 보고서 JSON(schema research.v1). 코드로만 조립한다.

이번 단계(PR1)는 위키보이지 원문(영어)을 그대로 싣는다. 한국어 요약·여행 조건별 순위는 후속 LLM 단계(PR3)가 더한다.
출처 URL 은 코드가 소스 기록에서 붙인다 — 외부 문서 속 링크는 '홈페이지'로 표시만 한다.
"""
from __future__ import annotations

import re
import time
from typing import Any, Optional

from . import verify
from .sources import LICENSES
from .sources.wikivoyage import page_url

SCHEMA = "research.v1"
# 실용 정보 주제 → 위키보이지 섹션
TOPICS = (("transport_airport", "Get in"), ("transport_local", "Get around"), ("etiquette", "Respect"),
          ("safety", "Stay safe"), ("health", "Stay healthy"), ("language", "Talk"), ("connect", "Connect"),
          ("cope", "Cope"))
TIP_SECTIONS = ("Eat", "Drink", "Respect", "Cope", "Understand", "Get around")
PRACTICAL_CHARS = 700
# 날짜 역할별로 특히 필요한 주제(화면이 그날 카드에 강조한다)
ROLE_TOPICS = {"arrival": ["transport_airport", "transport_local"], "departure": ["transport_airport"],
               "transfer_out": ["transport_local"], "transfer_in": ["transport_local"], "stay": []}


def _kind(l: dict) -> Optional[str]:
    t = l.get("type")
    if t in ("see", "do"):
        return "attraction"
    if t == "eat":
        return "restaurant"
    if t == "drink":
        text = (l.get("name", "") + " " + l.get("content", "")).lower()
        return "cafe" if re.search(r"caf[eé]|coffee|tea\b|tea house|teahouse|bakery|patisserie", text) else "restaurant"
    return None


def places_from(ref: dict, guide: dict) -> list[dict]:
    out = []
    for n, l in enumerate(guide.get("listings") or []):
        kind = _kind(l)
        if not kind:
            continue
        page = l.get("page") or guide.get("title") or ""
        area = page.split("/", 1)[1] if "/" in page else ""
        p = verify.place({
            "id": f"wv:{ref['key']}:{n}", "name": l["name"], "kind": kind, "lat": l.get("lat"), "lon": l.get("lon"),
            "area": area, "desc_en": l.get("content", ""), "section": l.get("section", ""),
            "homepage": l.get("url", ""), "wikidata": l.get("wikidata", ""),
            "sources": [{"provider": "wikivoyage", "url": page_url(page), "title": page,
                         "license": LICENSES["wikivoyage"][0]}],
        }, ref.get("lat"), ref.get("lon"))
        if p:
            out.append(p)
    return out


def _tipping(sections: dict) -> str:
    out = []
    for sec in TIP_SECTIONS:
        for sent in re.split(r"(?<=[.!?])\s+", sections.get(sec, "")):
            if re.search(r"\btip(s|ping|ped)?\b|gratuit|service charge", sent, re.I) and sent not in out:
                out.append(sent.strip())
            if len(" ".join(out)) > PRACTICAL_CHARS:
                break
    return " ".join(out)[:PRACTICAL_CHARS]


def practical_from(guide: dict) -> list[dict]:
    secs, title = guide.get("sections") or {}, guide.get("title") or ""
    out = []
    for topic, sec in TOPICS:
        text = (secs.get(sec) or "")[:PRACTICAL_CHARS]
        if text:
            out.append({"topic": topic, "text_en": text, "source": {
                "provider": "wikivoyage", "url": page_url(title) + "#" + sec.replace(" ", "_"), "title": f"{title} › {sec}"}})
    tip = _tipping(secs)
    if tip:
        out.append({"topic": "tipping", "text_en": tip, "source": {"provider": "wikivoyage", "url": page_url(title),
                                                                    "title": title}})
    return out


def city_report(tc: dict, res: dict) -> dict:
    ref, guide = tc["ref"], ((res.get("guide") or {}).get("wikivoyage") or {})
    places = places_from(ref, guide) if guide.get("listings") else []
    clim = res.get("climate") or {}
    status = "ok" if places else ("partial" if guide.get("sections") else "empty")
    return {
        "key": ref["key"], "idx": tc["idx"], "name": ref["name"], "input": ref["input"], "ko": ref["ko"],
        "iso2": ref["iso2"], "resolved": ref["resolved"], "status": status,
        "wikivoyage": {"title": guide.get("title") or "", "url": page_url(guide["title"]) if guide.get("title") else ""},
        "places": places, "practical": practical_from(guide) if guide else [],
        "climate": ({**clim, "source": {"provider": "openmeteo", "url": "https://open-meteo.com/"}} if clim else None),
        "days": [{"date": r["date"], "role": r["role"], "topics": ROLE_TOPICS.get(r["role"], [])} for r in tc["roles"]],
        "cross_border_next": tc.get("cross_border_next", False),
        "sources": res.get("sources") or [],
    }


def country_report(c: dict, res: dict) -> dict:
    facts, fx = res.get("facts") or {}, res.get("fx") or {}
    return {
        "iso2": c["iso2"], "name": c["name"], "name_en": c["name_en"],
        "currency": ({"code": facts.get("currency", ""), **({"krw_per_unit": fx["krw_per_unit"], "as_of": fx["as_of"]} if fx else {})}
                     if facts.get("currency") else None),
        "emergency": facts.get("emergency") or [], "plugs": facts.get("plugs") or [], "voltage": facts.get("voltage") or "",
        "driving_side": facts.get("driving_side") or "", "languages": facts.get("languages") or [],
        # 안전 권고: 한국인 기준 출처(외교부 해외안전여행)가 붙기 전까지 비운다 — 영국 FCDO 는 영국 국적자 기준이라 쓰지 않는다
        "advisory": None,
        "sources": res.get("sources") or [],
    }


def build(resolved: dict, country_out: dict, city_out: dict, notes: Optional[list] = None) -> dict:
    countries = {c["iso2"]: country_report(c, country_out.get(c["iso2"]) or {})
                 for c in resolved["countries"] if c["iso2"]}
    cities = [city_report(tc, city_out.get(tc["ref"]["key"]) or {}) for tc in resolved["cities"]]
    used = {s.get("provider") for x in list(countries.values()) + cities for s in x.get("sources") or [] if s.get("status") == "ok"}
    if any(c["resolved"] for c in cities):
        used.add("geonames")
    attributions = [{"provider": p, "license": LICENSES[p][0], "text": LICENSES[p][1]} for p in LICENSES if p in used]
    ok = sum(1 for c in cities if c["status"] == "ok")
    quality = "full" if cities and ok == len(cities) else ("reduced" if ok or any(c["status"] == "partial" for c in cities) else "failed")
    return {"schema": SCHEMA, "status": "done", "quality": quality, "generated_at": int(time.time()),
            "countries": countries, "cities": cities, "attributions": attributions, "notes": notes or []}
