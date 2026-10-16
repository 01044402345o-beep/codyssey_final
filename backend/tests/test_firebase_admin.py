"""관리자(서비스 계정) 탈퇴 경로. 실행: cd backend && python -m unittest tests.test_firebase_admin"""
import io
import json
import os
import unittest
import urllib.error
from unittest import mock

from app import firebase_admin

FAKE_SA = {
    "project_id": "demo-project",
    "private_key": "-----BEGIN PRIVATE KEY-----\nFAKE\n-----END PRIVATE KEY-----\n",
    "client_email": "svc@demo-project.iam.gserviceaccount.com",
}


class Resp:
    def __init__(self, raw):
        self.raw = raw

    def read(self):
        return self.raw

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class Script:
    def __init__(self, steps):
        self.steps = list(steps)
        self.calls = []

    def __call__(self, req, timeout):
        self.calls.append((req.get_method(), req.full_url, req.get_header("Authorization"), req.data))
        item = self.steps.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def http_error(code, message):
    raw = json.dumps({"error": {"code": code, "message": message}}).encode()
    return urllib.error.HTTPError(url="https://example", code=code, msg="error", hdrs=None, fp=io.BytesIO(raw))


class T(unittest.TestCase):
    def setUp(self):
        firebase_admin.set_admin(None)

    def tearDown(self):
        firebase_admin.set_admin(None)

    def _admin(self, script):
        admin = firebase_admin.ServiceAccountAdmin("demo-project", FAKE_SA, script)
        admin._creds = mock.Mock(valid=True, token="sa-token")   # 토큰 발급은 건너뛴다
        return admin

    def test_configured_requires_service_account_and_project(self):
        SA = json.dumps(FAKE_SA)
        with mock.patch.dict(os.environ, {"FIREBASE_SERVICE_ACCOUNT_JSON": SA}, clear=True):
            self.assertTrue(firebase_admin.configured())          # 서비스 계정 JSON 에 project_id 가 있으면 충분
        with mock.patch.dict(os.environ, {"FIREBASE_PROJECT_ID": "demo-project"}, clear=True):
            self.assertFalse(firebase_admin.configured())         # 키 없음
        with mock.patch.dict(os.environ, {"FIREBASE_PROJECT_ID": "demo-project", "FIREBASE_SERVICE_ACCOUNT_JSON": SA}, clear=True):
            self.assertTrue(firebase_admin.configured())
        with mock.patch.dict(os.environ, {"FIREBASE_PROJECT_ID": "demo-project", "FIREBASE_SERVICE_ACCOUNT_JSON": "{oops"}, clear=True):
            self.assertFalse(firebase_admin.configured())         # 깨진 JSON
        nop = json.dumps({"private_key": "k"})
        with mock.patch.dict(os.environ, {"FIREBASE_SERVICE_ACCOUNT_JSON": nop}, clear=True):
            self.assertFalse(firebase_admin.configured())         # project_id 없음
        bad = json.dumps({"project_id": "demo-project"})
        with mock.patch.dict(os.environ, {"FIREBASE_PROJECT_ID": "demo-project", "FIREBASE_SERVICE_ACCOUNT_JSON": bad}, clear=True):
            self.assertFalse(firebase_admin.configured())         # private_key 없음

    def test_erase_calls_revoke_then_document_then_delete_user(self):
        script = Script([Resp(b"{}"), Resp(b"{}"), Resp(b"{}")])
        self._admin(script).erase("uid-1")
        methods = [c[0] for c in script.calls]
        urls = [c[1] for c in script.calls]
        self.assertEqual(methods, ["POST", "DELETE", "POST"])
        self.assertTrue(urls[0].endswith("/accounts:update"), urls[0])
        self.assertIn("validSince", script.calls[0][3].decode())
        self.assertIn("/databases/(default)/documents/users/uid-1", urls[1])
        self.assertTrue(urls[2].endswith("/accounts:delete"), urls[2])
        self.assertTrue(all(c[2] == "Bearer sa-token" for c in script.calls))

    def test_missing_targets_are_treated_as_success(self):
        script = Script([
            http_error(400, "USER_NOT_FOUND"),
            http_error(404, 'Document "projects/demo-project/databases/(default)/documents/users/uid-1" not found.'),
            http_error(400, "USER_NOT_FOUND"),
        ])
        self._admin(script).erase("uid-1")   # 예외 없이 끝난다(재시도 안전)

    def test_other_errors_raise_admin_failed(self):
        script = Script([http_error(403, "PERMISSION_DENIED")])
        with self.assertRaises(firebase_admin.AdminError) as caught:
            self._admin(script).erase("uid-1")
        self.assertEqual(caught.exception.status, 503)
        self.assertEqual(caught.exception.code, "admin_failed")

    def test_erase_account_requires_configuration(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(firebase_admin.AdminError) as caught:
                firebase_admin.erase_account("uid-1")
        self.assertEqual(caught.exception.code, "admin_unavailable")
        # 자격증명 관련 문자열이 예외 표현에 없다(응답 본문이 코드 문자열 하나뿐인지는 test_account_erase 가 본다).
        low = repr(caught.exception).lower()
        self.assertNotIn("private", low)
        self.assertNotIn("bearer", low)

    def test_non_missing_client_error_still_raises(self):
        """'없음'이 아닌 400/404 는 성공으로 삼키면 안 된다(토큰 미취소·문서 방치로 이어진다)."""
        script = Script([http_error(400, "INVALID_ARGUMENT: malformed localId"), Resp(b"{}"), Resp(b"{}")])
        with self.assertRaises(firebase_admin.AdminError) as caught:
            self._admin(script).erase("uid-1")
        self.assertEqual(caught.exception.code, "admin_failed")
        self.assertEqual(len(script.calls), 1)   # 뒤 단계(문서·계정 삭제)로 가지 않는다

    def test_network_error_is_wrapped_as_admin_error(self):
        """HTTP 응답이 아닌 오류(타임아웃·DNS)도 AdminError 로 감싼다 — 500 으로 새지 않게."""
        script = Script([urllib.error.URLError("dns boom")])
        with self.assertRaises(firebase_admin.AdminError) as caught:
            self._admin(script).erase("uid-1")
        self.assertEqual(caught.exception.code, "admin_failed")

    def test_credentials_receive_the_least_privilege_scopes(self):
        admin = firebase_admin.ServiceAccountAdmin("demo-project", FAKE_SA, Script([]))
        fake_creds = mock.Mock(valid=True, token="t")
        with mock.patch("google.oauth2.service_account.Credentials.from_service_account_info", return_value=fake_creds) as m:
            admin._token()
        self.assertEqual(m.call_args.kwargs.get("scopes"), firebase_admin.SCOPES)

    def test_token_failure_is_wrapped_as_admin_error(self):
        """자격증명 발급·갱신 실패가 500 으로 새지 않게 AdminError 로 감싼다(요청은 나가지 않는다)."""
        script = Script([])
        admin = firebase_admin.ServiceAccountAdmin("demo-project", FAKE_SA, script)
        with mock.patch.object(firebase_admin.ServiceAccountAdmin, "_token", side_effect=RuntimeError("refresh failed")):
            with self.assertRaises(firebase_admin.AdminError) as caught:
                admin.erase("uid-1")
        self.assertEqual(caught.exception.code, "admin_failed")
        self.assertEqual(script.calls, [])

    def test_server_error_mid_sequence_aborts_before_deleting_the_user(self):
        script = Script([Resp(b"{}"), http_error(500, "INTERNAL"), Resp(b"{}")])
        with self.assertRaises(firebase_admin.AdminError) as caught:
            self._admin(script).erase("uid-1")
        self.assertEqual(caught.exception.code, "admin_failed")
        self.assertEqual([c[0] for c in script.calls], ["POST", "DELETE"])   # accounts:delete 까지 가지 않는다

    def test_scopes_are_least_privilege(self):
        self.assertCountEqual(firebase_admin.SCOPES, [
            "https://www.googleapis.com/auth/firebase",
            "https://www.googleapis.com/auth/identitytoolkit",
            "https://www.googleapis.com/auth/datastore",
        ])
        self.assertNotIn("https://www.googleapis.com/auth/cloud-platform", firebase_admin.SCOPES)

    def test_missing_match_is_narrow(self):
        self.assertTrue(firebase_admin._missing('Document "projects/p/databases/(default)/documents/users/u" not found.'))
        self.assertTrue(firebase_admin._missing("USER_NOT_FOUND"))
        self.assertFalse(firebase_admin._missing("INVALID_ARGUMENT: request not found"))


if __name__ == "__main__":
    unittest.main()
