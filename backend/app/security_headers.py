"""모든 응답에 붙이는 보안 헤더 (ZAP 2026-10-16 수동 스캔 대응).

Render 운영은 FastAPI 가 정적 화면(mockup/)과 API 를 한 출처에서 내보낸다. Render·Cloudflare 는 보안 헤더를
붙이지 않으므로(2026-10-23 실측) 여기서 붙인다. Firebase Hosting 배포는 firebase.json 의 headers 가 맡는다.

- X-Content-Type-Options: nosniff — MIME 추측 금지.
- X-Frame-Options: DENY + CSP frame-ancestors 'none' — 앱은 어디에도 iframe 으로 들어가지 않는다(클릭재킹).
- Strict-Transport-Security: max-age 1년. onrender.com 은 우리 도메인이 아니므로 includeSubDomains·preload 는 넣지 않는다.
- Referrer-Policy, Permissions-Policy — 마이크는 말하기·통역이 쓰므로 self 만 허용(microphone=() 로 쓰면 녹음이 깨진다).
- Cache-Control — 정적 파일 이름에 버전이 없으므로 화면·스크립트는 no-cache(ETag 로 재검증, 304).
  계정 데이터(/user/*, /account/*, /auth/me, /diagnostics/*)는 no-store.
- Content-Security-Policy — 인라인 스크립트는 boot.js 로 옮겨 script-src 에 'unsafe-inline' 이 없다.
  스타일은 app.js 가 style="..." 를 많이 써서 'unsafe-inline' 이 남는다(스크립트 실행과는 무관).
  CSP_MODE 환경변수: enforce(기본) | report(Report-Only, 막지 않고 콘솔에만) | off.
  배포 뒤 로그인이 막히면 코드 수정 없이 CSP_MODE=report 로 되돌릴 수 있다.
"""
from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import urlparse

from fastapi import Request

# Swagger UI(/docs)는 jsdelivr 스크립트와 인라인 스크립트를 쓴다 — CSP 를 걸지 않는다.
CSP_EXEMPT = ("/docs", "/redoc", "/openapi.json")
NO_STORE = ("/user/", "/account/", "/auth/me", "/diagnostics/")   # 계정 데이터·이메일이 담긴 응답
_HOST = re.compile(r"^[A-Za-z0-9.-]{1,253}(:\d{1,5})?$")         # Host 헤더로 CSP 지시어를 끼워 넣지 못하게
STATIC_SUFFIX = (".html", ".js", ".css", ".json", ".webmanifest")


def _origin(url: str) -> str | None:
    p = urlparse((url or "").strip())
    if p.scheme in ("http", "https", "ws", "wss") and p.hostname:
        return f"{p.scheme}://{p.netloc}"
    return None


def csp_mode() -> str:
    m = (os.getenv("CSP_MODE") or "enforce").strip().lower()
    return m if m in ("enforce", "report", "off") else "enforce"


def build_csp(host: str) -> str:
    """요청 host 기준 CSP. 같은 출처 WebSocket(wss://host)은 'self' 해석이 브라우저마다 달라 명시한다."""
    # blob: — 이 페이지가 만든 녹음 blob 을 다시 읽는 경우(출처 밖으로 나가지 않는다)
    connect = ["'self'", "blob:", "https://identitytoolkit.googleapis.com", "https://securetoken.googleapis.com"]
    if host and _HOST.match(host):
        connect += [f"wss://{host}", f"ws://{host}"] if host.split(":")[0] in ("localhost", "127.0.0.1") else [f"wss://{host}"]
    ws = _origin(os.getenv("INTERP_WS_URL") or "")      # 통역 스트림이 다른 호스트(Cloud Run)일 때
    if ws and ws not in connect:
        connect.append(ws)
    auth_domain = (os.getenv("FIREBASE_AUTH_DOMAIN") or "").strip()
    # Firebase signInWithPopup 은 authDomain 의 숨은 iframe 으로 결과를 받는다. 값이 없으면 로그인 자체가 꺼져 있다.
    frame = f"https://{auth_domain}" if auth_domain and "/" not in auth_domain else "'none'"
    return "; ".join([
        "default-src 'self'",
        # Firebase SDK 는 gstatic 에서 동적 import, 구글 팝업 로그인은 apis.google.com 의 gapi 를 불러온다.
        "script-src 'self' https://www.gstatic.com https://apis.google.com",
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net",
        "font-src 'self' https://fonts.gstatic.com https://cdn.jsdelivr.net",
        "img-src 'self' data: blob:",
        "media-src 'self' blob:",                 # 내 발음 다시 듣기(녹음 blob)
        "connect-src " + " ".join(connect),
        f"frame-src {frame}",
        "worker-src 'self'",
        "manifest-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ])


def _static(path: str) -> bool:
    return path == "/" or path.endswith(STATIC_SUFFIX)


async def add_security_headers(request: Request, call_next: Any) -> Any:
    response = await call_next(request)
    h = response.headers
    path = request.url.path
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("X-Frame-Options", "DENY")
    h.setdefault("Strict-Transport-Security", "max-age=31536000")
    h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    h.setdefault("Permissions-Policy", "microphone=(self), camera=(), geolocation=()")
    if path.startswith(NO_STORE):
        h["Cache-Control"] = "no-store"
    elif request.method in ("GET", "HEAD") and _static(path) and "cache-control" not in h:
        h["Cache-Control"] = "no-cache"
    mode = csp_mode()
    if mode != "off" and not path.startswith(CSP_EXEMPT):
        name = "Content-Security-Policy" if mode == "enforce" else "Content-Security-Policy-Report-Only"
        h[name] = build_csp(request.headers.get("host", ""))
    return response
