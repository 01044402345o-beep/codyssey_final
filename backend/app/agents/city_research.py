"""도시 자료조사 다중 에이전트 — 선택한 국가·도시마다 실제로 조회해 근거 있는 브리프를 만든다.

왜 '에이전트'인가: 한 소스를 그대로 옮기면 그 소스가 틀렸을 때 그대로 틀린다. 여기서는 역할을 나눠
서로를 검증한다.

  1) 라우터      — 국가·도시를 정규화하고 어느 소스를 어떤 제목으로 부를지 정한다(한/영).
  2) 수집가(병렬) — 위키백과(한/영) · 위키여행(영) · 위키데이터를 각각 조회한다. 하나가 죽어도 나머지는 산다.
  3) 검증자      — 좌표 일치(50km) · 도시 이름 포함 · 출처 수를 보고 신뢰도를 정한다. 어긋난 값은 버리고 gaps 에 남긴다.
  4) 정리자      — 언어에 맞는 요약을 고르고, 문단마다 출처 URL 을 붙인다.

LLM 은 쓰지 않는다(선택). 근거 없는 문장을 만들지 않는 것이 이 모듈의 계약이고,
생성형 요약이 필요하면 llm=callable 로 주입한다 — 주입하지 않으면 원문 발췌만 쓴다.

역할: **백업(롤백) 경로**다. 본 경로는 app/research(LangGraph 조사 파이프라인)이고, 그것이 꺼져 있거나
(RESEARCH_ENABLED=0) 실패했을 때 화면이 이 브리프(GET /city-brief)로 '이 도시 알아두기'를 보여 준다.
다른 에이전트 작업(2026-10-25)을 들여왔고, HTTP 는 조사 파이프라인과 같은 SafeHttp(허용 호스트·리다이렉트 거부·
크기 상한·위키미디어 동시 3·연락처 User-Agent)로 바꿨다. 끄기: CITY_BRIEF_ENABLED=0.

소스 선정 근거는 docs/ops/GEO_REFRESH.md §1 과 같다. 라이선스가 저장·재배포를 막는 소스
(Google Places 콘텐츠 저장 금지, dr5hn ODbL 전염, CountriesNow 출처 불명)는 쓰지 않는다.
위키백과·위키여행은 CC BY-SA 4.0 — 출처 URL 을 함께 남기면 인용할 수 있다.
"""
from __future__ import annotations

import math
import os
import re
import threading
import time
import urllib.parse
from typing import Any, Callable

TIMEOUT = 6.0
CACHE_TTL = 7 * 86400
MAX_CACHE = 512
COORD_TOLERANCE_KM = 50.0

Fetch = Callable[[str], dict]
_CACHE: dict[tuple, tuple[float, dict]] = {}
_LOCK = threading.Lock()


class ResearchError(RuntimeError):
    pass


def enabled() -> bool:
    """백업 경로 끄기 스위치(기본 켜짐). 호출마다 읽는다."""
    return (os.getenv("CITY_BRIEF_ENABLED") or "1").strip() != "0"


_HTTP = None


def _get_json(url: str) -> dict:
    """조사 파이프라인의 SafeHttp 로 나간다 — 허용 호스트(https)만, 리다이렉트 거부, 크기 상한."""
    global _HTTP
    from ..research.net import SafeHttp
    if _HTTP is None:
        _HTTP = SafeHttp()
    res, data = _HTTP.get_json(url, timeout=TIMEOUT)
    if not res.ok or not isinstance(data, dict):
        raise ResearchError(res.error or "bad_response")
    return data


def _haversine(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def _first_sentence(text: str, limit: int = 240) -> str:
    t = " ".join((text or "").split())
    if not t:
        return ""
    cut = t.find(". ")
    s = t if cut < 0 or cut > limit else t[: cut + 1]
    return s if len(s) <= limit else s[:limit].rsplit(" ", 1)[0] + "…"


# ── 2) 수집가: 소스마다 하나의 함수. 실패는 예외가 아니라 status 로 돌려준다 ──
def fetch_wikipedia(lang: str, title: str, fetch: Fetch | None = None) -> dict:
    fetch = fetch or _get_json
    url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(title.replace(' ', '_'))}"
    try:
        d = fetch(url)
    except Exception as e:                                        # noqa: BLE001 — 소스 실패는 데이터다
        return {"source": f"wikipedia:{lang}", "status": "error", "error": type(e).__name__, "url": url}
    if not d.get("extract"):
        return {"source": f"wikipedia:{lang}", "status": "empty", "url": url}
    if d.get("type") == "disambiguation":            # '파리는 다음을 의미한다. 파리: 곤충…' — 도시 소개가 아니다
        return {"source": f"wikipedia:{lang}", "status": "empty", "reason": "disambiguation", "url": url}
    c = d.get("coordinates") or {}
    return {"source": f"wikipedia:{lang}", "status": "ok", "url": d.get("content_urls", {}).get("desktop", {}).get("page", url),
            "title": d.get("title"), "text": d["extract"], "summary": d.get("description") or "",
            "coords": (float(c["lat"]), float(c["lon"])) if "lat" in c and "lon" in c else None}


def fetch_wikivoyage(lang: str, title: str, fetch: Fetch | None = None) -> dict:
    """여행 문맥(가는 법·먹을 것·주의)은 위키여행이 위키백과보다 낫다. 한국어 판은 없다(2026-10 확인)."""
    fetch = fetch or _get_json
    q = urllib.parse.urlencode({"action": "query", "prop": "extracts|coordinates", "explaintext": 1,
                                "exsectionformat": "plain", "format": "json", "redirects": 1, "titles": title})
    url = f"https://{lang}.wikivoyage.org/w/api.php?{q}"
    try:
        d = fetch(url)
        pages = (d.get("query") or {}).get("pages") or {}
        page = next(iter(pages.values()), {}) if pages else {}
    except Exception as e:                                        # noqa: BLE001
        return {"source": f"wikivoyage:{lang}", "status": "error", "error": type(e).__name__, "url": url}
    text = (page or {}).get("extract") or ""
    if not text or "missing" in (page or {}):
        return {"source": f"wikivoyage:{lang}", "status": "empty", "url": url}
    return {"source": f"wikivoyage:{lang}", "status": "ok", "url": f"https://{lang}.wikivoyage.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}",
            "title": page.get("title"), "text": text}


def fetch_wikidata(name: str, lang: str, fetch: Fetch | None = None) -> dict:
    """인구·좌표. 위키백과 요약에 없는 값을 구조화해서 준다."""
    fetch = fetch or _get_json
    q = urllib.parse.urlencode({"action": "wbsearchentities", "search": name, "language": lang, "format": "json", "limit": 1})
    try:
        s = fetch(f"https://www.wikidata.org/w/api.php?{q}")
        hit = (s.get("search") or [{}])[0]
        qid = hit.get("id")
        if not qid:
            return {"source": "wikidata", "status": "empty", "url": f"https://www.wikidata.org/w/api.php?{q}"}
        e = fetch(f"https://www.wikidata.org/w/api.php?action=wbgetentities&format=json&props=claims|sitelinks&ids={qid}")
        ent = ((e.get("entities") or {}).get(qid) or {})
        claims = ent.get("claims") or {}
        links = {k: (v or {}).get("title") for k, v in (ent.get("sitelinks") or {}).items() if k in ("enwiki", "kowiki")}
    except Exception as ex:                                       # noqa: BLE001
        return {"source": "wikidata", "status": "error", "error": type(ex).__name__, "url": "https://www.wikidata.org"}

    def amount(pid: str) -> float | None:
        try:
            return float(claims[pid][0]["mainsnak"]["datavalue"]["value"]["amount"])
        except (KeyError, IndexError, TypeError, ValueError):
            return None

    coords = None
    try:
        v = claims["P625"][0]["mainsnak"]["datavalue"]["value"]
        coords = (float(v["latitude"]), float(v["longitude"]))
    except (KeyError, IndexError, TypeError, ValueError):
        pass
    pop = amount("P1082")
    return {"source": "wikidata", "status": "ok", "url": f"https://www.wikidata.org/wiki/{qid}", "qid": qid,
            "coords": coords, "population": int(pop) if pop else None, "sitelinks": links}


# ── 3) 검증자 ──
def verify(sources: list[dict], city: str, trusted: frozenset = frozenset()) -> dict:
    """trusted: 위키데이터 항목이 가리키는 문서 제목(sitelink) — 괄호가 있어도('파리 (프랑스)') 그 도시 문서다."""
    ok = [s for s in sources if s.get("status") == "ok"]
    gaps: list[str] = []
    coords: tuple[float, float] | None = None
    pts = [(s["source"], s["coords"]) for s in ok if s.get("coords")]
    if pts:
        base_name, base = pts[0]
        for name, p in pts[1:]:
            km = _haversine(base, p)
            if km > COORD_TOLERANCE_KM:
                gaps.append(f"{name} 좌표가 {base_name} 와 {km:.0f}km 어긋나 좌표를 쓰지 않았다")
                pts = None
                break
        if pts:
            coords = (round(sum(p[0] for _, p in pts) / len(pts), 5), round(sum(p[1] for _, p in pts) / len(pts), 5))
    names = [s.get("title") or "" for s in ok]
    if ok and not any(city.replace(" ", "").lower() in (n or "").replace(" ", "").lower() for n in names):
        gaps.append("조회한 문서 제목에 도시 이름이 없다 — 동명이인 문서일 수 있다")
    if ok and any(re.search(r"[(（]", n or "") and n not in trusted for n in names):
        gaps.append("괄호가 붙은 제목(동명이인 문서)이 섞였다 — 그 문서는 도시 소개로 쓰지 않는다")
    if not ok:
        return {"confidence": "unavailable", "ok": False, "coords": None, "gaps": gaps or ["조회 가능한 출처가 없다"]}
    pop = next((s.get("population") for s in ok if s.get("population")), None)
    conf = "verified" if len(ok) >= 2 and not any("동명이인" in g for g in gaps) else "single_source"
    if gaps:
        return {"confidence": "partial", "ok": True, "coords": coords, "population": pop, "gaps": gaps}
    return {"confidence": conf, "ok": True, "coords": coords, "population": pop, "gaps": gaps}


# ── 1)·4) 라우터 + 정리자 ──
def research(country: str, city: str, lang: str = "ko", fetch: Fetch | None = None, llm: Callable | None = None) -> dict:
    fetch = fetch or _get_json
    city, country = (city or "").strip(), (country or "").strip()
    if not city:
        raise ResearchError("city_required")            # 국가는 표기용 — 없어도 조사는 된다(문장 생성은 도시만 안다)
    key = (country.lower(), city.lower(), lang if lang in ("ko", "en") else "en")
    now = time.time()
    with _LOCK:
        hit = _CACHE.get(key)
        if hit and now - hit[0] < CACHE_TTL:
            return {**hit[1], "cached": True}

    titles = {"ko": city, "en": city}                                    # 라우터: 두 언어로 같은 이름을 먼저 시도
    jobs = [lambda: fetch_wikipedia("ko", titles["ko"], fetch), lambda: fetch_wikipedia("en", titles["en"], fetch),
            lambda: fetch_wikivoyage("en", titles["en"], fetch), lambda: fetch_wikidata(city, key[2], fetch)]
    out: list[dict] = [None] * len(jobs)                                  # type: ignore[list-item]
    threads = []
    for i, job in enumerate(jobs):
        def run(i=i, job=job):
            try:
                out[i] = job()
            except Exception as e:                                        # noqa: BLE001
                out[i] = {"source": "unknown", "status": "error", "error": type(e).__name__, "url": ""}
        t = threading.Thread(target=run, daemon=True); t.start(); threads.append(t)
    for t in threads:
        t.join(TIMEOUT + 2)

    sources = [s for s in out if s]
    # 1차에서 비었으면(한국어 제목으로 영어 위키를 부르거나, 한국어 제목이 동음이의 문서인 경우) 위키데이터 항목의
    # 문서 제목(sitelink)으로 한 번 더 부른다. '파리' → kowiki '파리 (프랑스)', enwiki 'Paris'
    wd = next((s for s in sources if s.get("source") == "wikidata"), {})
    links = wd.get("sitelinks") or {}
    en_title, ko_title = links.get("enwiki"), links.get("kowiki")
    trusted = frozenset(t for t in (en_title, ko_title) if t)
    bad = {s.get("source") for s in sources if s.get("status") != "ok"}
    retry = []
    if en_title and bad & {"wikipedia:en", "wikivoyage:en"}:
        retry += [lambda: fetch_wikipedia("en", en_title, fetch), lambda: fetch_wikivoyage("en", en_title, fetch)]
    if ko_title and ko_title != city and "wikipedia:ko" in bad:
        retry.append(lambda: fetch_wikipedia("ko", ko_title, fetch))
    if retry:
        extra = [None] * len(retry)
        ts = []
        for i, job in enumerate(retry):
            def run(i=i, job=job):
                try:
                    extra[i] = job()
                except Exception as e:                                # noqa: BLE001
                    extra[i] = {"source": "unknown", "status": "error", "error": type(e).__name__, "url": ""}
            t = threading.Thread(target=run, daemon=True); t.start(); ts.append(t)
        for t in ts:
            t.join(TIMEOUT + 2)
        got = {(x or {}).get("source"): x for x in extra if x}
        sources = [got.get(s.get("source"), s) if s.get("status") != "ok" else s for s in sources]
    v = verify(sources, city, trusted)
    order = ["wikipedia:ko", "wikipedia:en"] if key[2] == "ko" else ["wikipedia:en", "wikipedia:ko"]
    clean = [s for s in sources if s.get("status") == "ok"
             and (not re.search(r"[(（]", s.get("title") or "") or s.get("title") in trusted)]
    primary = next((s for n in order for s in clean if s.get("source") == n), None)
    travel = next((s for s in sources if s.get("source", "").startswith("wikivoyage") and s.get("status") == "ok"), None)
    sections = []
    if primary:
        sections.append({"kind": "overview", "title": "도시 소개", "text": _first_sentence(primary["text"], 400),
                         "source": primary["source"], "url": primary["url"]})
    if travel:
        body = " ".join(travel["text"].split())
        for head in ("Understand", "Get in", "See", "Eat", "Stay safe"):
            i = body.find(head)
            if i >= 0:
                sections.append({"kind": head.lower().replace(" ", "_"), "title": head, "text": _first_sentence(body[i + len(head):], 320),
                                 "source": travel["source"], "url": travel["url"]})
                if len([s for s in sections if s["source"] == travel["source"]]) >= 2:
                    break
    if v.get("population"):
        sections.append({"kind": "facts", "title": "인구", "text": f"{v['population']:,}명 (위키데이터)", "source": "wikidata",
                         "url": next((s["url"] for s in sources if s.get("source") == "wikidata"), "")})
    if llm and sections:                                                 # 선택: 요약 재작성. 근거 문장 밖으로 못 나간다
        try:
            summary = llm({"country": country, "city": city, "sections": sections})
            if summary:
                sections.insert(0, {"kind": "brief", "title": "한눈에", "text": str(summary)[:600], "source": "llm", "url": ""})
        except Exception:                                                # noqa: BLE001
            pass

    res = {"ok": v["ok"], "country": country, "city": city, "lang": key[2], "confidence": v["confidence"],
           "coords": v["coords"], "sections": sections, "gaps": v["gaps"],
           "sources": [{"name": s.get("source"), "status": s.get("status"), "url": s.get("url")} for s in sources],
           "attribution": "위키백과·위키여행 CC BY-SA 4.0, 위키데이터 CC0 — 문단마다 출처 URL 을 함께 표시한다",
           "fetched_at": int(now)}
    with _LOCK:
        if len(_CACHE) >= MAX_CACHE:
            _CACHE.pop(next(iter(_CACHE)))
        _CACHE[key] = (now, res)
    return {**res, "cached": False}


def clear_cache() -> None:
    with _LOCK:
        _CACHE.clear()


def prompt_facts(country: str, city: str, fetch: Fetch | None = None) -> dict:
    """문장 생성 프롬프트에 넣을 사실 묶음. facts_clause 규약(status)에 맞춰 돌려준다.

    verified/partial 의 문단만 넣는다 — 출처가 없거나 좌표가 어긋난 브리프는 unavailable 이다.
    실패해도 예외를 올리지 않는다(도시 조사가 문장 생성을 막으면 안 된다).
    """
    fetch = fetch or _get_json
    try:
        b = research(country, city, "ko", fetch=fetch)
    except Exception as e:                                     # noqa: BLE001
        return {"status": "unavailable", "reason": type(e).__name__}
    if not b.get("ok") or not b.get("sections"):
        return {"status": "unavailable", "reason": "no_sources", "gaps": b.get("gaps") or []}
    trusted = [x for x in b["sections"] if x.get("source") != "llm" and x.get("url")]
    if not trusted:
        return {"status": "unavailable", "reason": "no_sourced_section"}
    return {"status": "verified" if b["confidence"] in ("verified", "single_source") else "partial",
            "confidence": b["confidence"], "coords": b.get("coords"),
            "items": [{"kind": x["kind"], "text": x["text"], "source": x["source"], "url": x["url"]} for x in trusted],
            "attribution": b.get("attribution")}
