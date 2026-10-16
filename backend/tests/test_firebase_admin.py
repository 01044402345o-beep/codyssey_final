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

    def test_erase_writes_tombstone_then_revokes_then_document_then_user(self):
        script = Script([Resp(b"{}"), Resp(b"{}"), Resp(b"{}"), Resp(b"{}")])
        self._admin(script).erase("uid-1")
        methods = [c[0] for c in script.calls]
        urls = [c[1] for c in script.calls]
        self.assertEqual(methods, ["POST", "POST", "DELETE", "POST"])
        self.assertIn("/documents/deleted?documentId=uid-1", urls[0])          # 흔적을 가장 먼저
        self.assertTrue(urls[1].endswith("/accounts:update"), urls[1])
        self.assertIn("validSince", script.calls[1][3].decode())
        self.assertIn("/documents/users/uid-1", urls[2])
        self.assertTrue(urls[3].endswith("/accounts:delete"), urls[3])
        self.assertTrue(all(c[2] == "Bearer sa-token" for c in script.calls))

    def test_tombstone_is_read_from_the_deleted_collection(self):
        script = Script([Resp(b'{"fields":{"at":{"stringValue":"2026-10-16T00:00:00Z"}}}')])
        self.assertTrue(self._admin(script).read_tombstone("uid-1"))
        self.assertIn("/documents/deleted/uid-1", script.calls[0][1])

        missing = Script([http_error(404, 'Document "projects/p/databases/(default)/documents/deleted/uid-1" not found.')])
        self.assertFalse(self._admin(missing).read_tombstone("uid-1"))

    def test_tombstone_body_carries_the_time(self):
        script = Script([Resp(b"{}")])
        self._admin(script).write_tombstone("uid-1")
        method, url, _, body = script.calls[0]
        self.assertEqual(method, "POST")
        self.assertIn("/documents/deleted?documentId=uid-1", url)
        sent = json.loads(body.decode())
        self.assertIn("at", sent["fields"])
        self.assertTrue(sent["fields"]["at"]["stringValue"].endswith("Z"))

    def test_erase_rolls_the_tombstone_back_when_a_later_step_fails(self):
        """계정이 살아 있는데 흔적만 남으면 그 사용자는 로그인한 채로 저장을 못 하게 된다."""
        script = Script([Resp(b"{}"), http_error(500, "INTERNAL"), Resp(b"{}")])
        with self.assertRaises(firebase_admin.AdminError):
            self._admin(script).erase("uid-1")
        methods = [c[0] for c in script.calls]
        urls = [c[1] for c in script.calls]
        self.assertEqual(methods, ["POST", "POST", "DELETE"])
        self.assertIn("/documents/deleted/uid-1", urls[2])     # 흔적을 되돌린다

    def test_erase_survives_a_failed_rollback(self):
        """되돌리기도 실패하면 원래 오류를 그대로 올린다(조용히 성공하지 않는다)."""
        script = Script([Resp(b"{}"), http_error(500, "INTERNAL"), http_error(503, "UNAVAILABLE")])
        with self.assertRaises(firebase_admin.AdminError) as caught:
            self._admin(script).erase("uid-1")
        self.assertEqual(caught.exception.code, "admin_failed")

    def test_conflict_is_only_swallowed_for_the_tombstone(self):
        """토큰 취소·삭제의 409 를 성공으로 삼키면 살아 있는 토큰을 지웠다고 보고하게 된다."""
        script = Script([Resp(b"{}"), http_error(409, "ALREADY_EXISTS"), Resp(b"{}")])
        with self.assertRaises(firebase_admin.AdminError):
            self._admin(script).erase("uid-1")
        self.assertEqual([c[0] for c in script.calls], ["POST", "POST", "DELETE"])   # 취소에서 멈추고 되돌린다

    def test_is_erased_caches_positive_only(self):
        """'흔적 없음'은 캐시하지 않는다 — 캐시하면 다른 인스턴스가 막 쓴 흔적을 못 보고 통과시킨다."""
        firebase_admin.reset_cache()
        reads = {"n": 0}

        class Admin:
            def read_tombstone(self, uid):
                reads["n"] += 1
                return uid == "uid-1"

        firebase_admin.set_admin(Admin())
        try:
            self.assertTrue(firebase_admin.is_erased("uid-1"))
            self.assertTrue(firebase_admin.is_erased("uid-1"))     # 양성 캐시 — 다시 읽지 않는다
            self.assertEqual(reads["n"], 1)
            self.assertFalse(firebase_admin.is_erased("uid-2"))
            self.assertEqual(reads["n"], 2)
            self.assertFalse(firebase_admin.is_erased("uid-2"))    # 음성은 캐시하지 않는다(즉시 재확인)
            self.assertEqual(reads["n"], 3)
        finally:
            firebase_admin.reset_cache()
            firebase_admin.set_admin(None)

    def test_is_erased_sees_a_tombstone_written_by_another_instance(self):
        """다른 인스턴스가 흔적을 쓴 직후 이 인스턴스도 즉시 막는다(음성 캐시 없음)."""
        firebase_admin.reset_cache()
        store = {"erased": False}

        class Admin:
            def read_tombstone(self, uid):
                return store["erased"]

        firebase_admin.set_admin(Admin())
        try:
            self.assertFalse(firebase_admin.is_erased("uid-1"))    # 아직 흔적 없음
            store["erased"] = True                                 # 다른 인스턴스가 탈퇴 처리
            self.assertTrue(firebase_admin.is_erased("uid-1"))     # 같은 프로세스가 즉시 차단
        finally:
            firebase_admin.reset_cache()
            firebase_admin.set_admin(None)

    def test_mark_erased_skips_the_store_read(self):
        firebase_admin.reset_cache()

        class Boom:
            def read_tombstone(self, uid):
                raise AssertionError("흔적을 읽으면 안 된다")

        firebase_admin.mark_erased("uid-1")
        firebase_admin.set_admin(Boom())
        try:
            self.assertTrue(firebase_admin.is_erased("uid-1"))
        finally:
            firebase_admin.reset_cache()
            firebase_admin.set_admin(None)

    def test_cache_does_not_grow_without_bound(self):
        firebase_admin.reset_cache()
        old = firebase_admin.CACHE_MAX
        firebase_admin.CACHE_MAX = 4
        try:
            for i in range(9):
                firebase_admin.mark_erased("uid-%d" % i)
            self.assertLess(len(firebase_admin._erased), 9)
        finally:
            firebase_admin.CACHE_MAX = old
            firebase_admin.reset_cache()

    def test_read_failure_is_remembered_briefly(self):
        """저장소 장애 때 요청마다 재시도로 몰리지 않게 짧게 기억한다(그래도 통과시킨다)."""
        firebase_admin.reset_cache()
        reads = {"n": 0}

        class Down:
            def read_tombstone(self, uid):
                reads["n"] += 1
                raise firebase_admin.AdminError(503, "admin_failed")

        firebase_admin.set_admin(Down())
        try:
            self.assertFalse(firebase_admin.is_erased("uid-1"))
            self.assertFalse(firebase_admin.is_erased("uid-1"))
            self.assertEqual(reads["n"], 1)
        finally:
            firebase_admin.reset_cache()
            firebase_admin.set_admin(None)

    def test_is_erased_lets_requests_through_when_the_store_fails(self):
        """흔적 조회 실패가 앱 전체 쓰기를 막지 않는다(일시 장애에 fail-open)."""
        firebase_admin.reset_cache()

        class Down:
            def read_tombstone(self, uid):
                raise firebase_admin.AdminError(503, "admin_failed")

        firebase_admin.set_admin(Down())
        try:
            self.assertFalse(firebase_admin.is_erased("uid-1"))
        finally:
            firebase_admin.reset_cache()
            firebase_admin.set_admin(None)

    def test_missing_targets_are_treated_as_success(self):
        script = Script([
            http_error(409, "ALREADY_EXISTS"),                                   # 흔적이 이미 있음
            http_error(400, "USER_NOT_FOUND"),                                   # 계정 없음
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
        script = Script([Resp(b"{}"), Resp(b"{}"), http_error(500, "INTERNAL"), Resp(b"{}")])
        with self.assertRaises(firebase_admin.AdminError) as caught:
            self._admin(script).erase("uid-1")
        self.assertEqual(caught.exception.code, "admin_failed")
        calls = [c[0] + " " + c[1] for c in script.calls]
        self.assertEqual([c[0] for c in script.calls], ["POST", "POST", "DELETE", "DELETE"])
        self.assertTrue(all("accounts:delete" not in c for c in calls))     # 계정 삭제까지 가지 않는다
        self.assertIn("/documents/deleted/uid-1", calls[-1])                # 대신 흔적을 되돌린다

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
