"""Frankfurter 환율(키 없음, ECB 등 중앙은행 기준). 그 나라 통화 1단위가 몇 원인지."""
from __future__ import annotations

import re
import urllib.parse

from .. import config
from ..net import SafeHttp, status_of
from . import disabled, result

API = "https://api.frankfurter.dev/v2/rates"


def krw_rate(http: SafeHttp, currency: str) -> dict:
    if not config.source_on("frankfurter"):
        return disabled("frankfurter")
    if not re.fullmatch(r"[A-Z]{3}", currency or ""):
        return result("frankfurter", "empty", reason="no_currency")
    if currency == "KRW":
        return result("frankfurter", "empty", reason="same_currency")
    res, data = http.get_json(API + "?" + urllib.parse.urlencode({"base": currency, "quotes": "KRW"}))
    if not res.ok:
        # 지원하지 않는 통화는 4xx — 이 소스가 줄 수 없다는 뜻이라 empty 로 본다
        return result("frankfurter", "empty" if 400 <= res.status < 500 and res.status != 429 else status_of(res),
                      reason=res.error)
    rows = data if isinstance(data, list) else []
    row = next((r for r in rows if isinstance(r, dict) and r.get("quote") == "KRW"), None)
    try:
        rate = float(row["rate"]) if row else 0.0
    except (TypeError, ValueError):
        rate = 0.0
    if rate <= 0:
        return result("frankfurter", "empty", reason="no_rate")
    return result("frankfurter", "ok", {"currency": currency, "krw_per_unit": round(rate, 4 if rate < 10 else 2),
                                        "as_of": str(row.get("date") or "")[:10]},
                  url="https://frankfurter.dev/")
