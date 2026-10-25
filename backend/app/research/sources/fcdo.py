"""영국 외무부(FCDO) 여행 권고 — GOV.UK Content API(키 없음, OGL v3).

입국 요건(entry-requirements)은 영국 국적자 기준이라 쓰지 않는다. 안전·현지 법과 관습·건강·경고만.
나라 이름은 GOV.UK 목록(이름·동의어)으로 맞추고, 다른 것만 ISO2 표로 고친다.
"""
from __future__ import annotations

import re
import threading
import time
from typing import Optional

from .. import config
from .. import wikivoyage_parse as wp
from ..net import SafeHttp, status_of
from . import disabled, result

INDEX = "https://www.gov.uk/api/content/foreign-travel-advice"
PAGE = "https://www.gov.uk/foreign-travel-advice/"
PARTS = ("warnings-and-insurance", "safety-and-security", "local-laws-and-customs", "health", "getting-help")
MAX_PART = 3000
# GeoNames 이름과 GOV.UK 이름이 다른 나라(ISO2 → slug)
SLUG_BY_ISO = {"US": "usa", "CZ": "czech-republic", "CD": "democratic-republic-of-the-congo", "CG": "congo",
               "CI": "cote-d-ivoire", "KR": "south-korea", "KP": "north-korea", "MM": "myanmar", "VA": "italy",
               "TL": "timor-leste", "PS": "the-occupied-palestinian-territories", "MK": "north-macedonia",
               "SZ": "eswatini", "CV": "cape-verde", "VN": "vietnam", "LA": "laos", "RU": "russia", "SY": "syria",
               "IR": "iran", "BO": "bolivia", "VE": "venezuela", "TZ": "tanzania", "MD": "moldova", "BN": "brunei"}
_index_cache: dict[str, tuple[float, dict[str, str]]] = {}
_lock = threading.Lock()


def _norm(s: str) -> str:
    return re.sub(r"[^a-z]", "", (s or "").lower())


def _slugs(http: SafeHttp) -> dict[str, str]:
    with _lock:
        hit = _index_cache.get("i")
        if hit and time.time() - hit[0] < 86400:
            return hit[1]
    res, data = http.get_json(INDEX)
    out: dict[str, str] = {}
    for ch in (((data or {}).get("links") or {}).get("children")) or []:
        co = ((ch.get("details") or {}).get("country")) or {}
        slug = co.get("slug") or ""
        if not re.fullmatch(r"[a-z0-9-]{2,60}", slug):
            continue
        for n in [co.get("name") or ""] + list(co.get("synonyms") or []):
            if n and _norm(n) not in out:
                out[_norm(n)] = slug
    if out:
        with _lock:
            _index_cache["i"] = (time.time(), out)
    return out


def slug_for(http: SafeHttp, iso2: str, name: str) -> Optional[str]:
    if iso2 in SLUG_BY_ISO:
        return SLUG_BY_ISO[iso2]
    return _slugs(http).get(_norm(name))


def advisory(http: SafeHttp, iso2: str, name: str) -> dict:
    if not config.source_on("fcdo"):
        return disabled("fcdo")
    if iso2 == "GB":
        return result("fcdo", "empty", reason="home_country")
    slug = slug_for(http, iso2, name)
    if not slug:
        return result("fcdo", "empty", reason="no_page")
    res, data = http.get_json(INDEX + "/" + slug)
    if not res.ok:
        return result("fcdo", status_of(res), reason=res.error)
    det = (data or {}).get("details") or {}
    parts = []
    for p in det.get("parts") or []:
        ps = p.get("slug") or ""
        if ps not in PARTS:
            continue
        text = wp.clean(p.get("body") or "", MAX_PART)
        if text:
            parts.append({"slug": ps, "title": wp.clean(p.get("title") or ps, 60), "text": text,
                          "url": PAGE + slug + "/" + ps})
    if not parts:
        return result("fcdo", "empty", reason="no_parts")
    updated = str(det.get("updated_at") or (data or {}).get("public_updated_at") or "")[:10]
    return result("fcdo", "ok", {"slug": slug, "updated_at": updated, "parts": parts}, url=PAGE + slug)
