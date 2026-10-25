"""대체 장소 소스 — 다른 언어판 위키보이지(de·it·fr·es·ja·zh, CC BY-SA). 키 없음·저장 가능.

10/26 실측: 영어판이 빈약한 일본·유럽 소도시에서 독일어판이 크게 보탠다(로텐부르크 22→100, 가나자와 71→122,
다카야마 38→81), 이탈리아·페루는 이탈리아어판(마테라 16→71), 프랑스는 프랑스어판. 한국어판 위키보이지는 없다
(인큐베이터뿐) — 한국 도시는 이 소스로 채워지지 않는다(TourAPI 몫).

- 도시 Wikidata 항목(ref["qid"])의 사이트링크로 각 언어판 문서 제목을 찾는다(호출 1번).
- 나라별로 먼저 볼 언어판을 정하고(COUNTRY_FIRST), 모자람이 채워질 때까지 최대 2개 판을 읽는다.
- it·es 판은 영어판을 옮긴 경우가 많다 — 같은 장소는 chain.merge 가 wikidata id·이름·가까운 거리로 합친다.
- 설명은 그 언어 원문(desc_lang). 한국어 요약은 LLM 추출이 만든다.
"""
from __future__ import annotations

import re
import urllib.parse
from typing import Any

from .. import config, report
from ..net import SafeHttp, status_of
from . import disabled, result
from . import wikivoyage as wv

EDITIONS = ("de", "it", "fr", "es", "ja", "zh")
COUNTRY_FIRST = {"IT": ("it", "de"), "FR": ("fr", "de"), "BE": ("fr", "de"), "CH": ("de", "fr", "it"), "DE": ("de",),
                 "AT": ("de",), "ES": ("es", "de"), "MX": ("es", "de"), "PE": ("it", "es", "de"), "AR": ("es", "it"),
                 "JP": ("de", "ja"), "CN": ("zh", "de"), "TW": ("zh", "de"), "HK": ("zh", "de")}
MAX_EDITIONS = 2


def sitelinks(http: SafeHttp, qid: str) -> "tuple[object, dict[str, str]]":
    q = urllib.parse.urlencode({"action": "wbgetentities", "ids": qid, "props": "sitelinks", "format": "json",
                                "sitefilter": "|".join(f"{l}wikivoyage" for l in EDITIONS)})
    res, data = http.get_json(wv.WIKIDATA_API + "?" + q, timeout=8)
    links = ((((data or {}).get("entities") or {}).get(qid) or {}).get("sitelinks") or {}) if res.ok else {}
    return res, {k[:-len("wikivoyage")]: str(v.get("title") or "") for k, v in links.items()
                 if k.endswith("wikivoyage") and k[:-len("wikivoyage")] in EDITIONS and v.get("title")}


def order(iso2: str, available: dict[str, str]) -> list[str]:
    first = COUNTRY_FIRST.get(iso2, ())
    return [l for l in list(first) + [e for e in EDITIONS if e not in first] if l in available]


def adapter(deps: Any, tc: dict, want: dict) -> dict:
    if not config.source_on("wikivoyage"):
        return disabled("wikivoyage")
    ref = tc["ref"]
    qid = ref.get("qid") or ""
    if not re.fullmatch(r"Q\d+", qid):
        return result("wikivoyage", "empty", reason="no_qid")
    res, links = sitelinks(deps.http, qid)
    if not res.ok:
        return result("wikivoyage", status_of(res), reason=res.error)
    langs = order(ref.get("iso2") or "", links)[:MAX_EDITIONS]
    if not langs:
        return result("wikivoyage", "empty", reason="no_other_edition")
    places, last_bad = [], None
    for lang in langs:
        r = wv.fetch_edition(deps.http, lang, links[lang])
        if r["status"] != "ok":
            last_bad = r if r["status"] in ("unavailable", "rate_limited") else last_bad
            continue
        places += report.places_from(ref, {"lang": lang, "title": r["data"]["title"], "listings": r["data"]["listings"]})
        got = {"attraction": sum(p["kind"] == "attraction" for p in places),
               "food": sum(p["kind"] in ("restaurant", "cafe") for p in places)}
        if all(got[k] >= want.get(k, 0) for k in got):
            break
    if places:
        return result("wikivoyage", "ok", places, url=wv.page_url(links[langs[0]], langs[0]))
    if last_bad:
        return result("wikivoyage", last_bad["status"], reason=last_bad.get("reason") or "")
    return result("wikivoyage", "empty", reason="no_listings")
