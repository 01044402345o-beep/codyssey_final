"""Firebase(Hosting) + Cloud Run 배포 설정 점검.

- firebase.json: Firestore 규칙 배포 설정을 지우지 않는다. API 경로만 Cloud Run 으로, WebSocket 은 Hosting 을 거치지 않는다.
- /interp/providers 의 ws_url: Hosting 도메인에서 열린 화면이 통역 WebSocket 을 직접 주소로 열게 한다.
- /health deploy: Cloud Run 에서도 어떤 배포인지(리비전·커밋) 보인다.
실행: cd backend && python -m unittest tests.test_firebase_deploy
"""
import json
import os
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from app import main

ROOT = Path(__file__).resolve().parents[2]


class T(unittest.TestCase):
    def setUp(self):
        self.http = TestClient(main.app)

    def test_firebase_json_keeps_firestore_and_routes_only_api(self):
        cfg = json.loads((ROOT / "firebase.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["firestore"], [{"database": "(default)", "rules": "firestore.rules"}])
        sources = [r["source"] for r in cfg["hosting"]["rewrites"]]
        self.assertNotIn("/interp/stream", sources)                    # Hosting 은 WS 를 중계하지 못한다
        self.assertFalse(any(s in ("**", "/**") for s in sources))     # 정적 파일까지 Cloud Run 으로 보내지 않는다
        routes = {r.path for r in main.app.routes if getattr(r, "methods", None)}
        api = {p for p in routes if not p.startswith(("/docs", "/openapi", "/redoc"))} - {"/"}
        covered = lambda p: any(p == s or (s.endswith("/**") and p.startswith(s[:-3])) for s in sources)
        missing = sorted(p for p in api if not covered(p) and not p.startswith("/static"))
        self.assertEqual(missing, [], "Hosting rewrite 에 빠진 API 경로")

    def test_ws_url_only_when_valid(self):
        for value, want in [("", None), ("https://x.run.app/interp/stream", None), ("wss://x.run.app/other", None),
                            ("wss://codyssey-api-abc.a.run.app/interp/stream", "wss://codyssey-api-abc.a.run.app/interp/stream"),
                            ("wss://codyssey-final.onrender.com/interp/stream/", "wss://codyssey-final.onrender.com/interp/stream")]:
            with mock.patch.dict(os.environ, {"INTERP_WS_URL": value}):
                self.assertEqual(self.http.get("/interp/providers").json()["ws_url"], want, value)

    def test_health_deploy_on_cloud_run(self):
        env = {"K_SERVICE": "codyssey-api", "K_REVISION": "codyssey-api-00007-abc", "GIT_COMMIT": "1234567",
               "RENDER": "", "RENDER_GIT_COMMIT": ""}
        with mock.patch.dict(os.environ, env):
            d = main.health_detail()["deploy"]
        self.assertEqual(d["platform"], "cloud-run")
        self.assertEqual(d["revision"], "codyssey-api-00007-abc")
        self.assertEqual(d["commit"], "1234567")


if __name__ == "__main__":
    unittest.main()
