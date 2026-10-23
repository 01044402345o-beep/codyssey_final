"""공개 /health 는 최소 필드만, 상세는 관리자 토큰으로(10/23 교차 검증 #6).  실행: cd backend && python -m unittest discover -s tests -t .

예전 /health 는 키 개수·쿨다운·모델 상태·공급자 키 유무·보안 점검 결과·서버 경로까지 누구에게나 보여 줬다(정찰 정보)."""
import os
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from app import main


class HealthExposure(unittest.TestCase):
    def setUp(self):
        self.http = TestClient(main.app)

    def get(self, headers=None, **env):
        with mock.patch.dict(os.environ, env):
            if "HEALTH_DETAIL_TOKEN" not in env:
                os.environ.pop("HEALTH_DETAIL_TOKEN", None)
            return self.http.get("/health", headers=headers or {}).json()

    def test_public_has_only_minimal_fields(self):
        body = self.get()
        self.assertEqual(set(body), {"status", "situations", "categories", "evidence", "deploy"})
        self.assertEqual(set(body["deploy"]), {"commit", "platform"})
        for hidden in ("gemini_keys", "security_review", "contract_dir", "model_health", "stt_providers", "min_attempts"):
            self.assertNotIn(hidden, body)

    def test_header_without_configured_token_is_still_public(self):
        self.assertNotIn("gemini_keys", self.get(headers={"X-Admin-Token": ""}))
        self.assertNotIn("gemini_keys", self.get(headers={"X-Admin-Token": "guess"}))

    def test_wrong_token_gets_public_right_token_gets_detail(self):
        self.assertNotIn("gemini_keys", self.get(headers={"X-Admin-Token": "nope"}, HEALTH_DETAIL_TOKEN="s3cret"))
        body = self.get(headers={"X-Admin-Token": "s3cret"}, HEALTH_DETAIL_TOKEN="s3cret")
        self.assertIn("gemini_keys", body)
        self.assertIn("security_review", body)

    def test_public_keeps_what_public_consumers_read(self):
        # 핀 검증 워크플로우·opsarchive(evidence), 화면(situations), 헬스체크(status)
        body = self.get()
        self.assertIn(body["status"], ("ok", "degraded"))
        self.assertIn("restaurant", body["categories"])
        self.assertIsInstance(body["evidence"], dict)


if __name__ == "__main__":
    unittest.main()
