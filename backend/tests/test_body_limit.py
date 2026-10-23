"""요청 본문 크기 상한 (10/23 교차 검증 #4).  실행: cd backend && python -m unittest discover -s tests -t .

예전에는 /generate 같은 로그인 없는 경로에 수백 MB JSON 을 보내도 끝까지 읽은 뒤에야 검증했다."""
import json
import unittest

from fastapi import FastAPI, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from app import main
from app.body_limit import BodyLimitMiddleware


def mini_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(BodyLimitMiddleware, default=1000, limits={"/big": 5000})
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    @app.post("/echo")
    async def echo(request: Request):
        return {"n": len(await request.body())}

    @app.post("/big")
    async def big(request: Request):
        return {"n": len(await request.body())}

    @app.websocket("/ws")
    async def ws(sock: WebSocket):
        await sock.accept()
        await sock.send_text(str(len(await sock.receive_text())))
        await sock.close()
    return app


class BodyLimitUnit(unittest.TestCase):
    def setUp(self):
        self.http = TestClient(mini_app())

    def test_under_limit_passes(self):
        self.assertEqual(self.http.post("/echo", content=b"x" * 999).json(), {"n": 999})

    def test_content_length_over_limit_is_413_with_cors(self):
        r = self.http.post("/echo", content=b"x" * 1001, headers={"Origin": "https://a.example"})
        self.assertEqual(r.status_code, 413)
        self.assertEqual(r.json(), {"detail": "request_too_large"})
        self.assertIn("access-control-allow-origin", r.headers)   # 브라우저가 CORS 오류가 아닌 413 을 본다

    def test_chunked_without_length_is_counted(self):
        def gen():
            for _ in range(20):
                yield b"x" * 100
        r = self.http.post("/echo", content=gen())   # Transfer-Encoding: chunked
        self.assertEqual(r.status_code, 413)

    def test_chunked_under_limit_passes(self):
        def gen():
            yield b"x" * 500
        self.assertEqual(self.http.post("/echo", content=gen()).json(), {"n": 500})

    def test_bad_content_length_is_413(self):
        r = self.http.post("/echo", content=b"x", headers={"Content-Length": "abc"})
        self.assertEqual(r.status_code, 413)

    def test_per_path_limit_and_trailing_slash(self):
        self.assertEqual(self.http.post("/big", content=b"x" * 4000).status_code, 200)
        self.assertEqual(self.http.post("/big", content=b"x" * 5001).status_code, 413)

    def test_websocket_not_affected(self):
        with self.http.websocket_connect("/ws") as sock:
            sock.send_text("y" * 50_000)
            self.assertEqual(sock.receive_text(), "50000")


class BodyLimitApp(unittest.TestCase):
    """실제 앱의 경로별 상한."""

    def setUp(self):
        self.http = TestClient(main.app)

    def test_generate_huge_json_rejected_before_parsing(self):
        body = json.dumps({"category_id": "restaurant", "city": "x" * 200_000}).encode()
        r = self.http.post("/generate", content=body, headers={"Content-Type": "application/json"})
        self.assertEqual(r.status_code, 413)

    def test_speak_check_allows_audio_cap_plus_form(self):
        limit = next(m for m in main.app.user_middleware if m.cls is BodyLimitMiddleware).kwargs["limits"]["/speak-check"]
        self.assertGreater(limit, main.MAX_AUDIO_BYTES)       # 오디오 상한 + multipart 여유

    def test_user_state_limit_above_handler_limit(self):
        from app import user_state
        limits = next(m for m in main.app.user_middleware if m.cls is BodyLimitMiddleware).kwargs["limits"]
        self.assertGreater(limits["/user/state"], user_state.MAX_STATE_BYTES)   # 핸들러의 state_too_large 메시지가 남는다


if __name__ == "__main__":
    unittest.main()
