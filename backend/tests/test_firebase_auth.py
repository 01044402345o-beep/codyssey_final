"""Firebase 로그인 설정과 토큰 확인. 실행: cd backend && python -m unittest tests.test_firebase_auth"""
import os
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from app import firebase_auth, main

ENV = {
    "FIREBASE_API_KEY": "public-web-key",
    "FIREBASE_AUTH_DOMAIN": "demo-project.firebaseapp.com",
    "FIREBASE_PROJECT_ID": "demo-project",
    "FIREBASE_APP_ID": "1:1:web:abc",
}
CLAIMS = {
    "sub": "uid-1",
    "iss": "https://securetoken.google.com/demo-project",
    "aud": "demo-project",
    "email": "traveler@example.com",
    "name": "김여행",
    "firebase": {"sign_in_provider": "google.com"},
}


class T(unittest.TestCase):
    def setUp(self):
        self.http = TestClient(main.app, raise_server_exceptions=False)

    def test_config_is_off_without_env(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            for key in ENV:
                os.environ.pop(key, None)
            self.assertEqual(self.http.get("/auth/config").json(), {"enabled": False})
            self.assertIs(self.http.get("/health").json()["firebase_auth"], False)

    def test_config_returns_only_public_fields(self):
        with mock.patch.dict(os.environ, ENV):
            body = self.http.get("/auth/config").json()
            self.assertIs(self.http.get("/health").json()["firebase_auth"], True)
        self.assertEqual(body["enabled"], True)
        self.assertEqual(body["projectId"], "demo-project")
        self.assertNotIn("private_key", body)

    def test_me_requires_a_bearer_token(self):
        with mock.patch.dict(os.environ, ENV):
            res = self.http.get("/auth/me")
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.json()["detail"], "missing_token")

    def test_me_is_unavailable_until_firebase_is_configured(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            for key in ENV:
                os.environ.pop(key, None)
            res = self.http.get("/auth/me", headers={"Authorization": "Bearer x"})
        self.assertEqual(res.status_code, 503)
        self.assertEqual(res.json()["detail"], "firebase_unconfigured")

    def test_me_returns_the_verified_account(self):
        with mock.patch.dict(os.environ, ENV), \
             mock.patch.object(firebase_auth.id_token, "verify_firebase_token", return_value=CLAIMS):
            res = self.http.get("/auth/me", headers={"Authorization": "Bearer signed-token"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {
            "uid": "uid-1", "email": "traveler@example.com", "name": "김여행", "provider": "google.com",
        })

    def test_me_rejects_a_token_the_verifier_refuses(self):
        with mock.patch.dict(os.environ, ENV), \
             mock.patch.object(
                 firebase_auth.id_token, "verify_firebase_token",
                 side_effect=ValueError("bad"),
             ):
            res = self.http.get("/auth/me", headers={"Authorization": "Bearer nope"})
        self.assertEqual(res.status_code, 401)
        self.assertNotIn("nope", res.text)

    def test_generate_stays_open_without_a_token(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GEMINI_API_KEY", None)
            res = self.http.post("/generate", json={"category_id": "restaurant", "city": "뉴욕"})
        self.assertEqual(res.status_code, 200)


if __name__ == "__main__":
    unittest.main()
