"""조사 단계의 HTTP. 정해 둔 호스트(https)에만, 리다이렉트를 따라가지 않고, 크기 상한을 두고 나간다.

- 호스트 허용 목록 밖이면 요청 자체를 하지 않는다(SSRF). URL 은 코드의 상수 + quote 로만 만든다.
  외부 문서 안의 링크(listing 의 url 등)는 화면에 표시만 하고 절대 가져오지 않는다.
- 위키미디어(위키보이지·위키데이터)는 정책상 동시 3개 이하·연락처 User-Agent 가 필요하다.
- 실패는 예외가 아니라 Response(status=0|4xx|5xx, error=...)로 돌려준다 — 소스 하나가 죽어도 조사는 계속된다.
- 로그에 남기는 URL 은 키(apiKey=)를 가린다.
"""
from __future__ import annotations

import json
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Optional

from . import config

ALLOWED_HOSTS = frozenset({
    "en.wikivoyage.org", "query.wikidata.org",
    "ko.wikipedia.org", "en.wikipedia.org", "www.wikidata.org",      # 백업 경로(agents/city_research — GET /city-brief)
    "api.open-meteo.com", "archive-api.open-meteo.com",
    "api.frankfurter.dev", "api.geoapify.com", "api.tavily.com", "places.googleapis.com",
    "overpass-api.de",                                                  # 대체 장소 소스(OSM, chain.py)
    "de.wikivoyage.org", "it.wikivoyage.org", "fr.wikivoyage.org", "es.wikivoyage.org", "ja.wikivoyage.org",
    "zh.wikivoyage.org",                                                # 다른 언어판 위키보이지(sources/wikivoyage_intl)
})
WIKIMEDIA = frozenset({"en.wikivoyage.org", "query.wikidata.org", "ko.wikipedia.org", "en.wikipedia.org", "www.wikidata.org",
                       "de.wikivoyage.org", "it.wikivoyage.org", "fr.wikivoyage.org", "es.wikivoyage.org",
                       "ja.wikivoyage.org", "zh.wikivoyage.org"})
MAX_BYTES = 4 * 1024 * 1024          # 위키보이지 큰 도시 문서(위키텍스트) ~200KB, 5년치 날씨 ~150KB
DEFAULT_TIMEOUT = 8.0

# transport(method, url, body, headers, timeout) -> (status, body_bytes, headers)
Transport = Callable[[str, str, Optional[bytes], dict, float], "tuple[int, bytes, dict]"]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """다른 주소로 따라가지 않는다(허용 목록을 우회하는 길을 막는다)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _default_transport(method: str, url: str, body: Optional[bytes], headers: dict, timeout: float) -> "tuple[int, bytes, dict]":
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(req, timeout=timeout) as res:
            data = res.read(MAX_BYTES + 1)
            return res.status, data, {k.lower(): v for k, v in res.headers.items()}
    except urllib.error.HTTPError as exc:
        return exc.code, b"", {k.lower(): v for k, v in (exc.headers or {}).items()}


def redact(url: str) -> str:
    return re.sub(r"(?i)(api_?key|key|token)=[^&]+", r"\1=***", url)


@dataclass
class Response:
    status: int                  # 0 = 연결 실패·시간 초과·크기 초과·허용 안 된 호스트
    body: bytes = b""
    error: str = ""
    retry_after: float = 0.0

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def json(self) -> Any:
        try:
            return json.loads(self.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None


class SafeHttp:
    def __init__(self, transport: Optional[Transport] = None, sleep: Callable[[float], None] = time.sleep) -> None:
        self._transport = transport or _default_transport
        self._sleep = sleep
        self._wm = threading.BoundedSemaphore(3)          # 위키미디어 동시 요청 ≤ 3
        self.calls: list[str] = []                        # 테스트·진단용(키는 가린 URL)

    def _check(self, url: str) -> str:
        p = urllib.parse.urlparse(url)
        if p.scheme != "https" or p.hostname not in ALLOWED_HOSTS or p.username or p.password or p.port not in (None, 443):
            return "host_not_allowed"
        return ""

    def request(self, method: str, url: str, *, body: Optional[bytes] = None, headers: Optional[dict] = None,
                timeout: float = DEFAULT_TIMEOUT) -> Response:
        bad = self._check(url)
        if bad:
            return Response(0, error=bad)
        host = urllib.parse.urlparse(url).hostname
        h = {"User-Agent": config.user_agent(), "Accept": "application/json", **(headers or {})}
        self.calls.append(redact(url))
        for attempt in (1, 2):                            # 5xx·연결 실패·짧은 429 는 한 번만 다시
            res = self._once(method, url, body, h, timeout, host)
            if res.ok or attempt == 2:
                return res
            if res.status == 429 and 0 < res.retry_after <= 5:
                self._sleep(res.retry_after)
                continue
            if res.status == 0 and res.error in ("timeout", "network") or 500 <= res.status < 600:
                self._sleep(0.5)
                continue
            return res
        return res  # pragma: no cover

    def _once(self, method: str, url: str, body: Optional[bytes], headers: dict, timeout: float, host: str) -> Response:
        sem = self._wm if host in WIKIMEDIA else None
        if sem:
            sem.acquire()
        try:
            status, data, rh = self._transport(method, url, body, headers, timeout)
        except (socket.timeout, TimeoutError):
            return Response(0, error="timeout")
        except (urllib.error.URLError, OSError, ValueError):
            return Response(0, error="network")
        finally:
            if sem:
                sem.release()
        if len(data) > MAX_BYTES:
            return Response(0, error="too_large")
        ra = 0.0
        if status == 429:
            try:
                ra = float((rh or {}).get("retry-after") or 0)
            except ValueError:
                ra = 0.0
        return Response(status, data, "" if 200 <= status < 300 else f"http_{status}", ra)

    def get_json(self, url: str, **kw: Any) -> "tuple[Response, Any]":
        res = self.request("GET", url, **kw)
        return res, (res.json() if res.ok else None)


def status_of(res: Response) -> str:
    """HTTP 결과 → 소스 결과 status."""
    if res.ok:
        return "ok"
    if res.status == 429:
        return "rate_limited"
    return "unavailable"
