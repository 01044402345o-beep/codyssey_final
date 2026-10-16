"""POST /account/erase — 관리자 탈퇴 엔드포인트. 실행: cd backend && python -m unittest tests.test_account_erase"""
import json
import os
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from app import firebase_admin, firebase_auth, main

ENV = {
    "FIREBASE_API_KEY": "public-web-key",
    "FIREBASE_AUTH_DOMAIN": "demo-project.firebaseapp.com",
    "FIREBASE_PROJECT_ID": "demo-project",
    "FIREBASE_APP_ID": "1:1:web:abc",
}
SA = json.dumps({"project_id": "demo-project", "private_key": "FAKE", "client_email": "svc@demo-project.iam.gserviceaccount.com"})
CLAIMS = {
    "sub": "uid-1",
    "iss": "https://securetoken.google.com/demo-project",
    "aud": "demo-project",
    "email": "traveler@example.com",
    "name": "김여행",
    "firebase": {"sign_in_provider": "google.com"},
}


class FakeAdmin:
    def __init__(self):
        self.erased = []

    def erase(self, uid):
        self.erased.append(uid)


class Boom:
    def erase(self, uid):
        raise firebase_admin.AdminError(503, "admin_failed")


class T(unittest.TestCase):
    def setUp(self):
        firebase_admin.set_admin(None)
        self.client = TestClient(main.app, raise_server_exceptions=False)

    def tearDown(self):
        firebase_admin.set_admin(None)

    def post(self, claims=None, env=None, token="signed-token"):
        with mock.patch.dict(os.environ, env if env is not None else {**ENV, "FIREBASE_SERVICE_ACCOUNT_JSON": SA}, clear=True), \
                mock.patch.object(firebase_auth.id_token, "verify_firebase_token", return_value=claims or CLAIMS):
            return self.client.post("/account/erase", headers={"Authorization": "Bearer " + token})

    def test_requires_a_token(self):
        with mock.patch.dict(os.environ, ENV, clear=True):
            res = self.client.post("/account/erase")
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.json()["detail"], "missing_token")

    def test_rejects_anonymous(self):
        res = self.post({**CLAIMS, "firebase": {"sign_in_provider": "anonymous"}})
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.json()["detail"], "anonymous_rejected")

    def test_unconfigured_returns_admin_unavailable(self):
        res = self.post(env=ENV)   # 서비스 계정 JSON 없음
        self.assertEqual(res.status_code, 503)
        self.assertEqual(res.json()["detail"], "admin_unavailable")

    def test_erases_only_the_token_uid(self):
        fake = FakeAdmin()
        firebase_admin.set_admin(fake)
        res = self.post()
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json(), {"erased": True})
        self.assertEqual(fake.erased, ["uid-1"])   # uid 는 토큰에서만 온다

    def test_admin_failure_is_surfaced(self):
        firebase_admin.set_admin(Boom())
        res = self.post()
        self.assertEqual(res.status_code, 503)
        self.assertEqual(res.json()["detail"], "admin_failed")

    def test_unexpected_error_is_503_not_500(self):
        """AdminError 가 아닌 예외도 500(추적 로그) 대신 503 admin_failed 로 답한다."""
        class Weird:
            def erase(self, uid):
                raise RuntimeError("unexpected")

        firebase_admin.set_admin(Weird())
        res = self.post()
        self.assertEqual(res.status_code, 503)
        self.assertEqual(res.json()["detail"], "admin_failed")

    def test_ignores_a_body_uid(self):
        fake = FakeAdmin()
        firebase_admin.set_admin(fake)
        with mock.patch.dict(os.environ, {**ENV, "FIREBASE_SERVICE_ACCOUNT_JSON": SA}, clear=True), \
                mock.patch.object(firebase_auth.id_token, "verify_firebase_token", return_value=CLAIMS):
            res = self.client.post("/account/erase", headers={"Authorization": "Bearer signed-token"}, json={"uid": "uid-2"})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(fake.erased, ["uid-1"])   # uid 는 토큰에서만 온다

    def test_rate_limited(self):
        firebase_admin.set_admin(FakeAdmin())
        main._hits.clear()
        try:
            with mock.patch.object(main, "RATE_LIMIT", 2):
                codes = [self.post().status_code for _ in range(3)]
        finally:
            main._hits.clear()
        self.assertEqual(codes[:2], [200, 200])
        self.assertEqual(codes[2], 429)


if __name__ == "__main__":
    unittest.main()
