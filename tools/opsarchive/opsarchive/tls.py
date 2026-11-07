"""관리자 도구가 설정값 주소(`/health`)에 붙을 때의 TLS 규칙.

고정 주소(Render·Google API)와 달리 앱 주소는 설정에서 오므로 `http://` 도 들어올 수 있다.
그러면 핀 대조에 쓰는 지문을 경로 위의 누구나 바꿔 끼울 수 있다. 그래서 여기서만 연다:

- https 만 허용한다(개발용 루프백은 예외).
- 인증서·호스트 이름을 검증하고 TLS 1.2 미만을 거부한다.
- 리다이렉트로 평문에 내려가는 것을 거부한다(urllib 은 기본으로 따라간다).
"""

from __future__ import annotations

import ssl
import urllib.parse
import urllib.request

LOOPBACK = {"localhost", "127.0.0.1", "::1"}


class InsecureUrl(Exception):
    """TLS 없는 주소로 나가려 했다. 값(주소)은 호출자가 이미 알고 있으므로 담지 않는다."""


def check_url(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme == "https" or (parts.scheme == "http" and parts.hostname in LOOPBACK):
        return url
    raise InsecureUrl("insecure_url")


class _NoDowngrade(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()      # 인증서·호스트 이름 검증이 켜진 기본값
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx


def open_url(url: str, timeout: int = 20):
    """`check_url` 을 통과한 주소만 연다. 응답 객체는 `urlopen` 과 같게 쓴다."""
    check_url(url)
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=context()), _NoDowngrade())
    return opener.open(url, timeout=timeout)
