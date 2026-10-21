"""실시간 통역 WebSocket 의 문지기: 유료 제공자는 로그인 계정만, 시작 횟수 제한, 언어 쌍.

키가 서버에 있으면 /interp/stream 은 누구나 과금을 일으킬 수 있는 길이 된다.
실행: cd backend && python -m unittest tests.test_interp_gate
"""
import os
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from app import firebase_auth, interp, main

PAID = {"INTERP_PROVIDER": "soniox", "SONIOX_API_KEY": "test-key"}
FAKE = {"INTERP_PROVIDER": "fake", "INTERP_ALLOW_FAKE": "1"}


def _events(ws, n=3):
    out = []
    for _ in range(n):
        m = ws.receive_json()
        out.append(m)
        if m.get("type") in ("error", "closed", "ready"):
            break
    return out


class T(unittest.TestCase):
    def setUp(self):
        interp._starts.clear()
        self.http = TestClient(main.app)

    def start(self, env, **first):
        with mock.patch.dict(os.environ, env, clear=False):
            with self.http.websocket_connect("/interp/stream") as ws:
                ws.send_json({"type": "start", "a": "ko", "b": "en", **first})
                return _events(ws)

    def test_no_key_says_unavailable(self):
        with mock.patch.dict(os.environ, {"INTERP_PROVIDER": "", "SONIOX_API_KEY": "", "OPENAI_API_KEY": "", "INTERP_ALLOW_FAKE": ""}):
            with self.http.websocket_connect("/interp/stream") as ws:
                ws.send_json({"type": "start", "a": "ko", "b": "en"})
                self.assertEqual(ws.receive_json()["code"], "no_key")

    def test_paid_provider_without_token_is_refused(self):
        with mock.patch.object(interp, "_connect", side_effect=AssertionError("제공자에 붙으면 안 된다")):
            ev = self.start(PAID)
        self.assertEqual(ev[0]["code"], "login_required")

    def test_paid_provider_rejects_bad_and_anonymous_tokens(self):
        with mock.patch.object(firebase_auth, "verify_bearer", side_effect=firebase_auth.AuthError(401, "bad")), \
             mock.patch.object(interp, "_connect", side_effect=AssertionError):
            self.assertEqual(self.start(PAID, token="x")[0]["code"], "login_required")
        with mock.patch.object(firebase_auth, "verify_bearer", return_value={"uid": "u1", "provider": "anonymous"}), \
             mock.patch.object(interp, "_connect", side_effect=AssertionError):
            self.assertEqual(self.start(PAID, token="x")[0]["code"], "login_required")

    def test_paid_provider_with_login_reaches_provider(self):
        with mock.patch.object(firebase_auth, "verify_bearer", return_value={"uid": "u1", "provider": "google.com"}) as vb, \
             mock.patch.object(interp, "_connect", side_effect=OSError("offline")) as conn:
            ev = self.start(PAID, token="tok")
        vb.assert_called_once_with("Bearer tok")
        conn.assert_called_once()
        self.assertEqual(ev[0]["code"], "all_failed")   # 문은 통과했고, 제공자 연결에서 실패(넘어갈 엔진 없음)

    def test_starts_are_limited_per_account(self):
        with mock.patch.object(firebase_auth, "verify_bearer", return_value={"uid": "u1", "provider": "google.com"}), \
             mock.patch.object(interp, "_connect", side_effect=OSError("offline")):
            codes = [self.start(PAID, token="tok")[0]["code"] for _ in range(interp.STARTS + 1)]
        self.assertEqual(codes[:-1], ["all_failed"] * interp.STARTS)
        self.assertEqual(codes[-1], "rate_limited")

    def test_bad_language_pair(self):
        self.assertEqual(self.start(FAKE, a="ko", b="fr")[0]["code"], "bad_pair")
        self.assertEqual(self.start(FAKE, a="en", b="en")[0]["code"], "bad_pair")

    def test_fake_mode_needs_no_login(self):
        ev = self.start(FAKE)
        self.assertEqual(ev[0]["type"], "ready")
        self.assertTrue(ev[0].get("test"))


if __name__ == "__main__":
    unittest.main()
