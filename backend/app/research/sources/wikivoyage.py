"""영어 위키보이지(MediaWiki Action API). 문서 제목은 Wikidata 사이트링크와 도시 ASCII 이름 후보 중 listing 이 많은 쪽.

- 한 번의 요청으로 여러 제목을 받는다(titles=A|B, 최대 3).
- 큰 도시(구역 하위 문서에 장소가 있는 문서, 예: Tokyo)는 {{Regionlist}} 앞쪽 구역 최대 2개를 한 번에 더 받는다.
- revid 를 돌려준다 — 캐시와 같으면 다시 파싱하지 않는다.
"""
from __future__ import annotations

import re
import urllib.parse
from typing import Optional

from .. import config
from .. import wikivoyage_parse as wp
from ..net import SafeHttp, status_of
from . import disabled, result

API = "https://en.wikivoyage.org/w/api.php"
PAGE = "https://en.wikivoyage.org/wiki/"
PRACTICAL = ("Understand", "Talk", "Get in", "Get around", "See", "Do", "Eat", "Drink", "Respect",
             "Stay safe", "Stay healthy", "Cope", "Connect")
DISTRICT_IF_FEWER = 8          # 본문 listing(장소형)이 이보다 적고 구역이 있으면 구역 문서를 더 본다


LANGS = ("en", "de", "it", "fr", "es", "ja", "zh")
WIKIDATA_API = "https://www.wikidata.org/w/api.php"


def page_url(title: str, lang: str = "en") -> str:
    base = PAGE if lang == "en" else f"https://{lang}.wikivoyage.org/wiki/"
    return base + urllib.parse.quote(title.replace(" ", "_"), safe="/()_,'")


def api(lang: str) -> str:
    if lang not in LANGS:
        raise ValueError("unknown wikivoyage edition")
    return API if lang == "en" else f"https://{lang}.wikivoyage.org/w/api.php"


def dedupe(ls: list[dict]) -> list[dict]:
    """지도 표시(marker)는 같은 이름의 listing 이 있으면 뺀다(설명 있는 쪽을 남긴다)."""
    named = {re.sub(r"\W+", "", x["name"].casefold()) for x in ls if not x.get("marker")}
    out, seen = [], set()
    for x in ls:
        k = re.sub(r"\W+", "", x["name"].casefold())
        if x.get("marker") and k in named:
            continue
        if (k, x.get("page")) in seen:
            continue
        seen.add((k, x.get("page")))
        out.append(x)
    return out


def repair_coords(http: SafeHttp, ls: list[dict], limit: int = 50) -> int:
    """좌표 없는 listing 중 wikidata= 가 있는 것은 Wikidata P625 로 좌표를 채운다(한 번에 최대 50개). → 채운 수.
    실패해도 그대로(좌표 없는 장소는 거리 검사만 빠진다)."""
    need = list(dict.fromkeys(x["wikidata"] for x in ls if x.get("wikidata") and (x.get("lat") is None or x.get("lon") is None)))[:limit]
    if not need:
        return 0
    q = urllib.parse.urlencode({"action": "wbgetentities", "ids": "|".join(need), "props": "claims", "format": "json"})
    res, data = http.get_json(WIKIDATA_API + "?" + q, timeout=8)
    if not res.ok:
        return 0
    coords = {}
    for qid, ent in ((data or {}).get("entities") or {}).items():
        v = ((((ent.get("claims") or {}).get("P625") or [{}])[0].get("mainsnak") or {}).get("datavalue") or {}).get("value") or {}
        if isinstance(v.get("latitude"), (int, float)) and isinstance(v.get("longitude"), (int, float)):
            coords[qid] = (float(v["latitude"]), float(v["longitude"]))
    n = 0
    for x in ls:
        c = coords.get(x.get("wikidata"))
        if c and (x.get("lat") is None or x.get("lon") is None):
            x["lat"], x["lon"], x["coord_src"] = c[0], c[1], "wikidata"
            n += 1
    return n


def _query(http: SafeHttp, titles: list[str], lang: str = "en") -> "tuple[object, list[dict]]":
    q = urllib.parse.urlencode({"action": "query", "prop": "revisions", "rvprop": "content|ids", "rvslots": "main",
                                "titles": "|".join(titles[:3]), "format": "json", "formatversion": "2",
                                "redirects": "1"})
    res, data = http.get_json(api(lang) + "?" + q)
    pages = []
    for p in ((data or {}).get("query") or {}).get("pages") or []:
        revs = p.get("revisions") or []
        if p.get("missing") or not revs:
            continue
        w = (((revs[0].get("slots") or {}).get("main") or {}).get("content") or "")
        pages.append({"title": p.get("title") or "", "revid": revs[0].get("revid"), "text": w})
    return res, pages


def _placeish(ls: list[dict]) -> int:
    return sum(1 for x in ls if x["type"] in ("see", "do", "eat", "drink"))


def fetch(http: SafeHttp, candidates: list[str], known_revid: Optional[int] = None) -> dict:
    """후보 제목들 중 장소 listing 이 가장 많은 문서를 고른다. data = {title, revid, url, listings, sections, unchanged}."""
    if not config.source_on("wikivoyage"):
        return disabled("wikivoyage")
    titles = [t for t in dict.fromkeys(c.strip() for c in candidates if c and c.strip())][:3]
    if not titles:
        return result("wikivoyage", "empty", reason="no_title")
    res, pages = _query(http, titles)
    if not res.ok:
        return result("wikivoyage", status_of(res), reason=res.error)
    if not pages:
        return result("wikivoyage", "empty", reason="no_article")
    scored = []
    for order, p in enumerate(pages):
        ls = wp.listings(p["text"], p["title"])
        scored.append((-_placeish(ls), order, p, ls))
    scored.sort(key=lambda x: (x[0], x[1]))
    _, _, page, ls = scored[0]
    if known_revid and page["revid"] == known_revid:
        return result("wikivoyage", "ok", {"title": page["title"], "revid": page["revid"], "unchanged": True},
                      url=page_url(page["title"]))
    secs = {t: wp.prose(b) for t, b in wp.sections(page["text"]) if t in PRACTICAL}
    sources = [page["title"]]
    if _placeish(ls) < DISTRICT_IF_FEWER:
        subs = wp.districts(page["text"], page["title"], limit=2)
        if subs:
            r2, sub_pages = _query(http, subs)
            if r2.ok:
                for sp in sub_pages:
                    ls += wp.listings(sp["text"], sp["title"])
                    sources.append(sp["title"])
    ls = dedupe(ls)
    repaired = repair_coords(http, ls)
    data = {"title": page["title"], "revid": page["revid"], "unchanged": False, "pages": sources,
            "listings": ls, "sections": {k: v for k, v in secs.items() if v}, "coords_repaired": repaired}
    return result("wikivoyage", "ok" if (ls or data["sections"]) else "empty", data, url=page_url(page["title"]))


def fetch_edition(http: SafeHttp, lang: str, title: str) -> dict:
    """다른 언어판 위키보이지 한 문서의 listing(언어별 템플릿) → data {lang, title, revid, listings}. 좌표 복구 포함."""
    if not config.source_on("wikivoyage"):
        return disabled("wikivoyage")
    if lang not in LANGS or not title.strip():
        return result("wikivoyage", "empty", reason="bad_edition")
    res, pages = _query(http, [title], lang)
    if not res.ok:
        return result("wikivoyage", status_of(res), reason=res.error)
    if not pages:
        return result("wikivoyage", "empty", reason="no_article")
    page = pages[0]
    ls = dedupe(wp.listings(page["text"], page["title"], lang))
    for x in ls:
        x["lang"] = lang
    repair_coords(http, ls)
    return result("wikivoyage", "ok" if ls else "empty",
                  {"lang": lang, "title": page["title"], "revid": page["revid"], "listings": ls},
                  url=page_url(page["title"], lang))
