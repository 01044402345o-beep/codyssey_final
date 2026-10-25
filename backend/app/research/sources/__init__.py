"""소스 어댑터. 모두 예외 대신 SourceResult(dict)를 돌려준다.

status: ok | empty | unavailable | rate_limited | capped | disabled
license·attribution 은 화면 출처 표기와 캐시 저장 조건에 그대로 쓴다.
"""
from __future__ import annotations

import time
from typing import Any

LICENSES = {
    "wikivoyage": ("CC BY-SA 4.0", "Wikivoyage contributors (CC BY-SA 4.0)"),
    "wikidata": ("CC0", "Wikidata (CC0)"),
    "openmeteo": ("CC BY 4.0", "Weather data by Open-Meteo.com (CC BY 4.0)"),
    "frankfurter": ("ECB reference rates", "Exchange rates: Frankfurter (ECB reference rates)"),
    "geonames": ("CC BY 4.0", "GeoNames (CC BY 4.0)"),
}


def result(provider: str, status: str, data: Any = None, *, url: str = "", reason: str = "") -> dict:
    lic, attr = LICENSES.get(provider, ("", provider))
    return {"provider": provider, "status": status, "reason": reason, "data": data, "url": url,
            "fetched_at": int(time.time()), "license": lic, "attribution": attr}


def disabled(provider: str) -> dict:
    return result(provider, "disabled", reason="source_off")
