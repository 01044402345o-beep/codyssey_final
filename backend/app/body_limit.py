"""요청 본문 크기 상한 (10/23 교차 검증 #4).

FastAPI 는 pydantic 본문(/generate 등)을 끝까지 읽은 뒤 검증하고, /user/* 핸들러도 본문을 다 읽은 뒤 크기를 본다.
그래서 로그인 없이 수백 MB 를 보내 메모리를 쓰게 할 수 있었다. 경로별 상한을 앞단에서 건다.

- Content-Length 가 있으면 읽기 전에 413.
- 길이가 없거나(chunked) 거짓이면 받는 만큼 세다가 넘는 순간 413.
- WebSocket·lifespan 은 건드리지 않는다.
- CORSMiddleware 보다 안쪽에 둔다(main.py 에서 CORS 보다 먼저 add) — 413 에도 CORS 헤더가 붙어 브라우저가 CORS 오류가 아닌 413 을 본다.
상한은 정적 경로 기준이다. 경로를 바꾸면 main.py 의 표도 같이 고친다.
"""
from __future__ import annotations

from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class BodyTooLarge(HTTPException):
    def __init__(self) -> None:
        super().__init__(status_code=413, detail="request_too_large")


class BodyLimitMiddleware:
    def __init__(self, app: ASGIApp, limits: dict[str, int], default: int) -> None:
        self.app, self.limits, self.default = app, limits, default

    def limit_for(self, path: str) -> int:
        return self.limits.get(path.rstrip("/") or "/", self.default)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = self.limit_for(scope["path"])
        cl = next((v for k, v in scope["headers"] if k == b"content-length"), None)
        if cl is not None:
            try:
                n = int(cl)
            except ValueError:
                n = -1
            if n < 0 or n > limit:
                await JSONResponse({"detail": "request_too_large"}, 413)(scope, receive, send)
                return
        seen, started = 0, False

        async def limited_receive() -> Message:
            nonlocal seen
            msg = await receive()
            if msg["type"] == "http.request":
                seen += len(msg.get("body", b""))
                if seen > limit:
                    raise BodyTooLarge()
            return msg

        async def tracking_send(msg: Message) -> None:
            nonlocal started
            if msg["type"] == "http.response.start":
                started = True
            await send(msg)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except BodyTooLarge:
            if started:
                raise
            await JSONResponse({"detail": "request_too_large"}, 413)(scope, receive, send)
