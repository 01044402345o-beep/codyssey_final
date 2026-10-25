"""Open-Meteo(키 없음, CC BY 4.0, 무료는 비상업). 여행 날짜에 맞춘 날씨.

- 출발이 16일 안: 예보(forecast)
- 그 밖: 최근 5년 같은 날짜(월·일) 평균 — ERA5 재분석(archive). 연말을 넘는 여행(12/28~1/3)도 날짜 창으로 센다.
"""
from __future__ import annotations

import datetime as dt
import urllib.parse
from typing import Optional

from .. import config
from ..net import SafeHttp, status_of
from . import disabled, result

FORECAST = "https://api.open-meteo.com/v1/forecast"
ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_DAYS = 16
YEARS = 5
DAILY = "temperature_2m_max,temperature_2m_min,precipitation_sum"


def _window(start: dt.date, end: dt.date) -> set[tuple[int, int]]:
    days, d = set(), start
    while d <= end and len(days) < 60:
        days.add((d.month, d.day))
        d += dt.timedelta(days=1)
    return days


def _summarise(daily: dict, keep: Optional[set] = None) -> Optional[dict]:
    times = daily.get("time") or []
    hi, lo, pr = daily.get("temperature_2m_max") or [], daily.get("temperature_2m_min") or [], daily.get("precipitation_sum") or []
    rows = []
    for i, t in enumerate(times):
        try:
            d = dt.date.fromisoformat(t)
        except (TypeError, ValueError):
            continue
        if keep is not None and (d.month, d.day) not in keep:
            continue
        a, b, c = (hi[i] if i < len(hi) else None), (lo[i] if i < len(lo) else None), (pr[i] if i < len(pr) else None)
        if a is None or b is None:
            continue
        rows.append((a, b, c or 0.0))
    if not rows:
        return None
    n = len(rows)
    return {"tmax_avg": round(sum(r[0] for r in rows) / n, 1), "tmin_avg": round(sum(r[1] for r in rows) / n, 1),
            "precip_mm_avg": round(sum(r[2] for r in rows) / n, 1),
            "wet_days_pct": round(100 * sum(1 for r in rows if r[2] >= 1.0) / n), "days": n}


def climate(http: SafeHttp, lat: Optional[float], lon: Optional[float], start: str, end: str,
            today: Optional[dt.date] = None) -> dict:
    if not config.source_on("openmeteo"):
        return disabled("openmeteo")
    if lat is None or lon is None:
        return result("openmeteo", "empty", reason="no_coordinates")
    try:
        s, e = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    except ValueError:
        return result("openmeteo", "empty", reason="bad_dates")
    if e < s:
        s, e = e, s
    today = today or dt.date.today()
    base = {"latitude": f"{lat:.4f}", "longitude": f"{lon:.4f}", "daily": DAILY, "timezone": "auto"}
    if today <= s and e <= today + dt.timedelta(days=FORECAST_DAYS - 1):
        url = FORECAST + "?" + urllib.parse.urlencode({**base, "start_date": s.isoformat(), "end_date": e.isoformat()})
        res, data = http.get_json(url)
        if not res.ok:
            return result("openmeteo", status_of(res), reason=res.error)
        summ = _summarise((data or {}).get("daily") or {})
        kind, window = "forecast", f"{s.isoformat()}~{e.isoformat()}"
    else:
        # 같은 달·일의 최근 5해. 올해 날짜가 아직 안 왔으면 작년까지, 이미 지났으면 올해까지(archive 는 며칠 늦다).
        last = today.year - 1 if (s.month, s.day) >= (today.month, today.day) else today.year
        a0 = dt.date(last - YEARS + 1, 1, 1)
        a1 = min(dt.date(last, 12, 31), today - dt.timedelta(days=7))
        url = ARCHIVE + "?" + urllib.parse.urlencode({**base, "start_date": a0.isoformat(), "end_date": a1.isoformat()})
        res, data = http.get_json(url, timeout=12)
        if not res.ok:
            return result("openmeteo", status_of(res), reason=res.error)
        summ = _summarise((data or {}).get("daily") or {}, _window(s, e))
        kind, window = "normals", f"{s.month:02d}-{s.day:02d}~{e.month:02d}-{e.day:02d} ({a0.year}–{last})"
    if not summ:
        return result("openmeteo", "empty", reason="no_rows")
    return result("openmeteo", "ok", {"kind": kind, "window": window, **summ}, url="https://open-meteo.com/")
