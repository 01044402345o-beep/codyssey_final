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
        # 규칙 배포 설정을 지우지 않는다. 색인 설정(geo_cities.data 색인 제외, docs/ops/GEO_REFRESH.md)만 더해졌다.
        self.assertEqual(cfg["firestore"], [{"database": "(default)", "rules": "firestore.rules",
                                             "indexes": "firestore.indexes.json"}])
        self.assertTrue((ROOT / "firestore.indexes.json").is_file())
        # 11/06: Hosting 은 화면(정적 파일)만 — API·통역 WS 는 Render(화면 ai.js apiBase 가 *.web.app 이면 Render 로).
        # Cloud Run(codyssey-api)은 마감 때문에 보류라 없다 — 없는 서비스로 보내는 rewrite 를 두지 않는다(FIREBASE_DEPLOY.md §0)
        self.assertNotIn("rewrites", cfg["hosting"])
        self.assertEqual(cfg["hosting"]["public"], "mockup")
        csp = next(h["value"] for b in cfg["hosting"]["headers"] for h in b["headers"] if h["key"].startswith("Content-Security"))
        connect = next(p for p in csp.split(";") if p.strip().startswith("connect-src"))
        img = next(p for p in csp.split(";") if p.strip().startswith("img-src"))
        self.assertIn("https://codyssey-final.onrender.com", connect)
        self.assertIn("wss://codyssey-final.onrender.com", connect)     # 통역 WebSocket
        self.assertIn("https://codyssey-final.onrender.com", img)        # 장소 확인 창 사진(/place-photo)
        self.assertIn("https://*.googleusercontent.com", img)            # Google 사진(바로 표시)

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
