"""일정 오케스트레이터. 문장 팩과 분리된다.

플래그 ITINERARY_ENABLED 의 기본값은 꺼짐이다. 꺼져 있으면 Places 와 일정 Gemini 를
호출하지 않고 itinerary_disabled 를 돌려준다. 공개 배포에서 이 플래그를 켜지 않는다.
POST /itinerary 는 이 함수만 호출한다. 문장 팩은 /generate 에 남긴다.

1차 장소 조회는 Google Places Text Search (New) 의 Pro 필드 마스크만 쓴다.
Kakao, OSM, Routes, 영업시간, 평점, 가격, 그라운딩은 호출하지 않는다.
FACT_SOURCES_READY 와 무관하다. 콘텐츠 캐시는 없다.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from typing import Any, Callable

from .. import gemini as ai

log = logging.getLogger("app.itinerary")

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
FIELD_MASK = (
    "places.id,places.displayName,places.formattedAddress,places.location,"
    "places.primaryType,places.businessStatus,places.googleMapsUri"
)
_KINDS = ("restaurant", "cafe", "attraction")
_QUERY = {
    "restaurant": ("restaurant", "restaurant"),
    "cafe": ("cafe", "cafe"),
    "attraction": ("tourist_attraction", "tourist attraction"),
}
_TIMES = ("morning", "afternoon", "evening")
_MAP_HOSTS = {"maps.google.com", "maps.app.goo.gl"}

_cap_lock = threading.Lock()
_cap_day = ""
_cap_used = 0

Http = Callable[[str, bytes, dict[str, str], float], tuple[int, Any]]


def itinerary_enabled() -> bool:
    return (os.getenv("ITINERARY_ENABLED", "0") or "0").strip() == "1"


def google_maps_configured() -> bool:
    return bool((os.getenv("GOOGLE_MAPS_API_KEY") or "").strip())


def daily_cap() -> int:
    """UTC 하루 동안 이 프로세스가 보낼 Places 호출 상한. 호출할 때마다 읽는다."""
    raw = (os.getenv("ITINERARY_DAILY_CAP") or "").strip()
    if not raw:
        return 20
    try:
        return max(0, int(raw))
    except ValueError:
        return 20


def reset_daily_cap() -> None:
    global _cap_day, _cap_used
    with _cap_lock:
        _cap_day = ""
        _cap_used = 0


def _reserve(n: int) -> int:
    global _cap_day, _cap_used
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with _cap_lock:
        if _cap_day != today:
            _cap_day = today
            _cap_used = 0
        room = max(0, daily_cap() - _cap_used)
        take = min(n, room)
        _cap_used += take
        return take


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """다른 호스트로 따라가지 않는다. 키는 헤더에만 있고 리다이렉트로 나가지 않는다."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _default_http(url: str, body: bytes, headers: dict[str, str], timeout: float) -> tuple[int, Any]:
    if urllib.parse.urlparse(url).netloc != "places.googleapis.com":
        raise ValueError("places host only")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(req, timeout=timeout) as res:
            return res.status, json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, {}


def _cap_state() -> tuple[int, int]:
    """로그용: 이 프로세스가 지금까지 예약한 Places 질의 수와 지금의 상한.
    세는 값은 성공한 HTTP 가 아니라 예약한 질의 수다. 날짜가 바뀌면 0 부터다."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with _cap_lock:
        used = _cap_used if _cap_day == today else 0
        return used, daily_cap()


def _off(reason: str) -> dict[str, Any]:
    return {"status": "unavailable", "reason": reason}


def _attr(req: Any, name: str, default: Any = None) -> Any:
    if isinstance(req, dict):
        return req.get(name, default)
    return getattr(req, name, default)


def _span(req: Any) -> int | None:
    raw_date = _attr(req, "start_date", None)
    if raw_date not in (None, ""):
        try:
            date.fromisoformat(str(raw_date).strip())
        except ValueError:
            return None
    raw_days = _attr(req, "days", None)
    if raw_days is None:
        return 1
    if isinstance(raw_days, bool):
        return None
    try:
        days = int(raw_days)
    except (TypeError, ValueError):
        return None
    if days < 1 or days > 14:
        return None
    return days


def _kinds(req: Any) -> list[str]:
    found: set[str] = set()
    for place in _attr(req, "places", None) or []:
        kind = str(_attr(place, "place_type", "") or "").strip().lower()
        if kind in ("restaurant", "cafe"):
            found.add(kind)
    for kind in _attr(req, "itinerary_kinds", None) or []:
        token = str(kind or "").strip().lower()
        if token in _KINDS:
            found.add(token)
    return [kind for kind in _KINDS if kind in found]


def _queries(city: str, kinds: list[str]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for kind in kinds:
        included, tail = _QUERY[kind]
        text = f"{city} {tail}"
        key = (text, included)
        if key in seen:
            continue
        seen.add(key)
        out.append({"text": text, "included_type": included})
    return out[:4]


def _num(value: Any, lo: float, hi: float) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    if n != n or n < lo or n > hi:  # NaN
        return None
    return n


def _maps_uri_ok(url: Any) -> bool:
    if not isinstance(url, str) or not url or url.startswith("https://map.kakao.com"):
        return False
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        return False
    host = parsed.netloc.lower()
    path = parsed.path or ""
    query = parsed.query or ""
    if host in _MAP_HOSTS:
        return not (path in ("", "/") and not query)
    if host == "www.google.com" and path.startswith("/maps"):
        return not (path in ("/maps", "/maps/") and not query)
    return False


def _place_from(item: Any, fetched_at: str) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    if item.get("businessStatus") == "CLOSED_PERMANENTLY":
        return None
    provider_id = item.get("id")
    name = (item.get("displayName") or {}).get("text") if isinstance(item.get("displayName"), dict) else None
    if not isinstance(provider_id, str) or not provider_id.strip():
        return None
    if not isinstance(name, str) or not name.strip():
        return None
    loc = item.get("location") if isinstance(item.get("location"), dict) else {}
    lat = _num(loc.get("latitude"), -90, 90)
    lon = _num(loc.get("longitude"), -180, 180)
    if lat is None or lon is None:
        return None
    source = item.get("googleMapsUri")
    if not _maps_uri_ok(source):
        return None
    address = item.get("formattedAddress") if isinstance(item.get("formattedAddress"), str) else ""
    primary = item.get("primaryType") if isinstance(item.get("primaryType"), str) else ""
    business = item.get("businessStatus") if isinstance(item.get("businessStatus"), str) else ""
    return {
        "kind": "place",
        "provider": "google_places",
        "provider_id": provider_id,
        "name": name,
        "lat": lat,
        "lon": lon,
        "data": {
            "formatted_address": address,
            "primary_type": primary,
            "business_status": business,
        },
        "source_url": source,
        "fetched_at": fetched_at,
        "valid_for": None,
        "status": "verified",
        "attribution": "Google Maps",
    }


def _search_one(query: dict[str, str], http: Http, key: str, fetched_at: str) -> dict[str, Any]:
    body = {
        "textQuery": query["text"],
        "includedType": query["included_type"],
        "strictTypeFiltering": True,
        "languageCode": "en",
        "maxResultCount": 5,
    }
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": key,
        "X-Goog-FieldMask": FIELD_MASK,
    }
    meta = {"query": query["text"], "included_type": query["included_type"], "places": []}
    try:
        status, payload = http(SEARCH_URL, json.dumps(body).encode("utf-8"), headers, 8.0)
    except Exception as exc:  # noqa: BLE001 — 질의 하나의 실패가 나머지를 지우면 안 된다
        meta["status"] = "unavailable"
        meta["reason"] = type(exc).__name__
        return meta
    if status != 200 or not isinstance(payload, dict):
        meta["status"] = "unavailable"
        meta["reason"] = f"http_{status}"
        return meta
    raw = payload.get("places")
    if not isinstance(raw, list):
        meta["status"] = "unavailable"
        meta["reason"] = "bad_json"
        return meta
    kept = [p for item in raw if (p := _place_from(item, fetched_at))]
    meta["places"] = kept
    meta["status"] = "verified" if kept else "unavailable"
    meta["reason"] = "" if kept else "none_verified"
    return meta


def _why(place: dict[str, Any]) -> str:
    primary = str(place["data"].get("primary_type") or "").strip()
    address = str(place["data"].get("formatted_address") or "").strip()
    text = " · ".join(part for part in (primary, address) if part) or "Google Maps place"
    return text[:160]


def _outside_name(text: str, name: str) -> str:
    idx = text.casefold().find(name.casefold())
    if idx < 0:
        return text
    return text[:idx] + text[idx + len(name):]


def _foreign_name(text: str, name: str, others: list[str]) -> bool:
    return any(
        other and other.casefold() != name.casefold() and other.casefold() in text.casefold()
        for other in others
    )


def _sentence_ok(text: Any, name: str, others: list[str]) -> bool:
    if not isinstance(text, str) or not text.strip():
        return False
    if name.casefold() not in text.casefold():
        return False
    if _foreign_name(text, name, others):
        return False
    return not any(ch in _outside_name(text, name) for ch in "[]{}")


def _ko_ok(text: Any, name: str, others: list[str]) -> bool:
    """한국어 문장은 선택이다. 비어 있으면 통과하고, 다른 장소 이름이나 자리표시자는 거절한다."""
    if text in (None, ""):
        return True
    if not isinstance(text, str):
        return False
    if _foreign_name(text, name, others):
        return False
    rest = _outside_name(text, name) if name.casefold() in text.casefold() else text
    return not any(ch in rest for ch in "[]{}")


def _parse_json_object(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in model output")
    parsed = json.loads(text[start:end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("JSON object required")
    return parsed


def _verify(model_days: Any, places: list[dict[str, Any]], day_count: int) -> tuple[list[dict[str, Any]], int]:
    by_id = {p["provider_id"]: p for p in places}
    names = [p["name"] for p in places]
    raw_days = model_days if isinstance(model_days, list) else []
    by_day: dict[int, list[Any]] = {}
    for entry in raw_days:
        if not isinstance(entry, dict):
            continue
        try:
            day_n = int(entry.get("day"))
        except (TypeError, ValueError):
            continue
        blocks = entry.get("blocks")
        if day_n < 1 or day_n > day_count or not isinstance(blocks, list):
            continue
        by_day[day_n] = blocks
    dropped = 0
    days_out: list[dict[str, Any]] = []
    for day_n in range(1, day_count + 1):
        seen: set[str] = set()
        kept: list[dict[str, Any]] = []
        for block in by_day.get(day_n, []):
            if not isinstance(block, dict):
                dropped += 1
                continue
            place_id = block.get("place_id")
            place = by_id.get(place_id) if isinstance(place_id, str) else None
            label = block.get("time_label")
            if place is None or label not in _TIMES or place_id in seen:
                dropped += 1
                continue
            others = [n for n in names if n != place["name"]]
            if not _sentence_ok(block.get("sentence_en"), place["name"], others):
                dropped += 1
                continue
            if not _ko_ok(block.get("sentence_ko"), place["name"], others):
                dropped += 1
                continue
            ko = block.get("sentence_ko") if isinstance(block.get("sentence_ko"), str) else ""
            seen.add(place_id)
            kept.append({
                "day": day_n,
                "time_label": label,
                "place_name": place["name"],
                "place_id": place["provider_id"],
                "sentence_ko": ko,
                "sentence_en": block["sentence_en"],
                "why": _why(place),
                "provider": "google_places",
                "source_url": place["source_url"],
                "status": "verified",
                "travel_min": None,
                "fetched_at": place["fetched_at"],
            })
        if kept:
            days_out.append({"day": day_n, "status": "verified", "blocks": kept})
        else:
            days_out.append({"day": day_n, "status": "unavailable", "reason": "day_empty", "blocks": []})
    return days_out, dropped


def _prompt(places: list[dict[str, Any]], day_count: int) -> str:
    payload = [{
        "provider_id": p["provider_id"],
        "name": p["name"],
        "formatted_address": p["data"].get("formatted_address") or "",
        "primary_type": p["data"].get("primary_type") or "",
        "source_url": p["source_url"],
    } for p in places]
    return (
        "Return one JSON object only. "
        "days is an array of objects with integer day and blocks. "
        f"day is from 1 to {day_count}. "
        "Each block has time_label (morning, afternoon, or evening), "
        "place_id copied from provider_id, sentence_en, and sentence_ko. "
        "sentence_en is one English sentence that contains that place's name exactly as given. "
        "Do not name a place that is not in PLACES. Do not use brackets or braces. "
        "Do not mention ratings, hours, or prices.\n"
        f"DAY_COUNT: {day_count}\nPLACES:\n{json.dumps(payload, ensure_ascii=False)}"
    )


def _merge_places(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        for place in row.get("places") or []:
            if place["provider_id"] in seen:
                continue
            seen.add(place["provider_id"])
            out.append(place)
    return out


def _public_query(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "query": row["query"],
        "included_type": row["included_type"],
        "status": row["status"],
        "reason": row.get("reason") or "",
    }


def collect_itinerary(req: Any, *, http: Http | None = None, run: Any = None) -> dict[str, Any]:
    """검증된 장소가 있을 때만 일정 문장을 한 번 요청한다. 실패는 unavailable 이다."""
    if not itinerary_enabled():
        return _off("itinerary_disabled")
    day_count = _span(req)
    if day_count is None:
        return _off("bad_date")
    kinds = _kinds(req)
    if not kinds:
        return _off("no_place_types")
    if not google_maps_configured():
        return _off("missing_google_key")

    queries = _queries(str(_attr(req, "city", "") or "").strip(), kinds)
    take = _reserve(len(queries))
    cap_used, cap_limit = _cap_state()
    if take <= 0:
        log.info("status=unavailable reason=daily_cap queries=0 cap_used=%s cap_limit=%s",
                 cap_used, cap_limit)
        return _off("daily_cap")

    caller = http or _default_http
    key = (os.getenv("GOOGLE_MAPS_API_KEY") or "").strip()
    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    t0 = datetime.now(timezone.utc)
    rows: list[dict[str, Any] | None] = [None] * take

    def one(i: int) -> None:
        rows[i] = _search_one(queries[i], caller, key, fetched_at)

    with ThreadPoolExecutor(max_workers=min(4, take)) as pool:
        list(pool.map(one, range(take)))
    done = [row for row in rows if row is not None]
    for skipped in queries[take:]:
        done.append({
            "query": skipped["text"],
            "included_type": skipped["included_type"],
            "status": "unavailable",
            "reason": "daily_cap",
            "places": [],
        })
    places_ms = int((datetime.now(timezone.utc) - t0).total_seconds() * 1000)
    places = _merge_places(done)
    http_fail = sum(1 for row in done if row["status"] != "verified")
    base = {
        "provider": "google_places",
        "weather": [],
        "weather_status": "unavailable",
        "weather_reason": "not_in_slice_1",
        "queries": [_public_query(row) for row in done],
        "places": places,
    }
    if not places:
        log.info("status=unavailable reason=no_verified_places queries=%s http_fail=%s cap_used=%s cap_limit=%s",
                 len(done), http_fail, cap_used, cap_limit)
        return {
            **base,
            "status": "unavailable",
            "reason": "no_verified_places",
            "days": [],
            "timing_ms": {"places": places_ms, "prose": 0, "verify": 0},
        }
    if not (os.getenv("GEMINI_API_KEY") or "").strip():
        log.info("status=unavailable reason=no_gemini_key places=%s cap_used=%s cap_limit=%s",
                 len(places), cap_used, cap_limit)
        return {
            **base,
            "status": "unavailable",
            "reason": "no_gemini_key",
            "days": [],
            "timing_ms": {"places": places_ms, "prose": 0, "verify": 0},
        }

    prompt = _prompt(places, day_count)
    runner = run or ai.run
    t1 = datetime.now(timezone.utc)

    def once(client: Any, model: str, attempt: int) -> dict[str, Any]:
        raw = ai.generate_text(client, model, prompt, temperature=0.2, max_output_tokens=2048)
        return _parse_json_object(raw)

    try:
        result = runner("itinerary", once)
    except ai.AttemptsExhausted:
        prose_ms = int((datetime.now(timezone.utc) - t1).total_seconds() * 1000)
        log.info("status=unavailable reason=prose_failed places=%s cap_used=%s cap_limit=%s",
                 len(places), cap_used, cap_limit)
        return {
            **base,
            "status": "unavailable",
            "reason": "prose_failed",
            "days": [],
            "timing_ms": {"places": places_ms, "prose": prose_ms, "verify": 0},
        }
    prose_ms = int((datetime.now(timezone.utc) - t1).total_seconds() * 1000)
    t2 = datetime.now(timezone.utc)
    model_days = result.value.get("days") if isinstance(result.value, dict) else None
    days_out, dropped = _verify(model_days, places, day_count)
    verify_ms = int((datetime.now(timezone.utc) - t2).total_seconds() * 1000)
    any_block = any(day["blocks"] for day in days_out)
    status = "verified" if any_block else "unavailable"
    reason = "" if any_block else "all_days_empty"
    log.info(
        "status=%s reason=%s queries=%s http_fail=%s places=%s dropped=%s places_ms=%s prose_attempts=%s model=%s cap_used=%s cap_limit=%s",
        status, reason or "-", len(done), http_fail, len(places), dropped, places_ms,
        getattr(result, "attempts", None), getattr(result, "model", None), cap_used, cap_limit,
    )
    return {
        **base,
        "status": status,
        "reason": reason,
        "days": days_out,
        "timing_ms": {"places": places_ms, "prose": prose_ms, "verify": verify_ms},
    }
