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
        self.ledgers = []
        self.tombstone = True

    def erase(self, uid, ledger=None):
        self.erased.append(uid)
        self.ledgers.append(ledger if ledger is not None else [])
        if ledger is not None:
            ledger.extend([{"step": "tombstone", "ok": True, "code": "", "ms": 1},
                           {"step": "revoke", "ok": True, "code": "", "ms": 1}])

    def read_tombstone(self, uid):
        return self.tombstone

    def firestore(self, method, subpath, body=None):
        return {}

    def lookup_user(self, uid):
        return {}


class Boom:
    def erase(self, uid, ledger=None):
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
        body = res.json()
        self.assertTrue(body["erased"])
        # 영수증: 클라이언트가 보관해 나중에 "체인에 이 챌린지가 있는가"를 대조한다
        self.assertEqual(sorted(body["receipt"]), ["challenge", "created_at", "digest", "outcome",
                                                   "schema", "seq"])
        self.assertEqual(fake.erased, ["uid-1"])   # uid 는 토큰에서만 온다

    def test_admin_failure_is_surfaced(self):
        firebase_admin.set_admin(Boom())
        res = self.post()
        self.assertEqual(res.status_code, 503)
        self.assertEqual(res.json()["detail"], "admin_failed")

    def test_unexpected_error_is_503_not_500(self):
        """AdminError 가 아닌 예외도 500(추적 로그) 대신 503 admin_failed 로 답한다."""
        class Weird:
            def erase(self, uid, ledger=None):
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

    def test_challenge_is_echoed_in_the_receipt(self):
        """클라이언트가 **요청 전에** 만든 챌린지를 그대로 돌려준다 — 사전 커밋먼트의 대조 기준이다."""
        firebase_admin.set_admin(FakeAdmin())
        with mock.patch.dict(os.environ, {**ENV, "FIREBASE_SERVICE_ACCOUNT_JSON": SA}, clear=True), \
                mock.patch.object(firebase_auth.id_token, "verify_firebase_token", return_value=CLAIMS):
            res = self.client.post("/account/erase",
                                   headers={"Authorization": "Bearer signed-token",
                                            "X-Withdraw-Challenge": "ab" * 16})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["receipt"]["challenge"], "ab" * 16)

    def test_chain_attempt_is_recorded_before_erasing(self):
        """삭제를 시도하기 **전에** 체인에 커밋되어야 한다(순서가 사전 커밋먼트의 핵심)."""
        fake = FakeAdmin()
        firebase_admin.set_admin(fake)
        calls = []
        with mock.patch.dict(os.environ, {**ENV, "FIREBASE_SERVICE_ACCOUNT_JSON": SA}, clear=True), \
                mock.patch.object(firebase_auth.id_token, "verify_firebase_token", return_value=CLAIMS), \
                mock.patch.object(main.evidence, "configured", return_value=True), \
                mock.patch.object(main.evidence, "record_attempt",
                                  side_effect=lambda *a, **k: calls.append(("attempt", a[0])) or {"seq": 1, "digest": "d"}), \
                mock.patch.object(main.evidence, "record_outcome",
                                  side_effect=lambda *a, **k: calls.append(("outcome", a[0], a[1])) or {}):
            res = self.client.post("/account/erase",
                                   headers={"Authorization": "Bearer signed-token",
                                            "X-Withdraw-Challenge": "cd" * 16})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(calls[0], ("attempt", "cd" * 16))                     # 먼저 시도 커밋
        self.assertEqual(calls[1], ("outcome", "cd" * 16, "ok"))               # 그 뒤 결과 커밋

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

    def test_ledger_is_recorded(self):
        """실패 증거 봉인이 "어디까지 갔는지"를 남길 수 있게 단계 원장을 넘긴다."""
        fake = FakeAdmin()
        firebase_admin.set_admin(fake)
        self.post()
        self.assertEqual(fake.erased, ["uid-1"])
        self.assertTrue(fake.ledgers[0], fake.ledgers)
        self.assertEqual(fake.ledgers[0][0]["step"], "tombstone")

    def test_failure_seals_evidence_with_the_ledger(self):
        firebase_admin.set_admin(Boom())
        sealed = []
        with mock.patch.object(main, "_seal_in_background",
                               side_effect=lambda *a, **k: sealed.append((a, k))):
            res = self.post()
        self.assertEqual(res.status_code, 503)
        self.assertEqual(sealed[0][0][0], "erase_failed")      # trigger
        self.assertEqual(sealed[0][0][1], "uid-1")             # uid

    def test_success_but_mismatch_seals_evidence_and_still_reports_success(self):
        """응답이 성공이어도 실제로 남아 있으면 증거를 남긴다(단계 생략 탐지)."""
        fake = FakeAdmin()
        fake.tombstone = False                                 # 흔적이 사라졌다 = 검증 불일치
        firebase_admin.set_admin(fake)
        sealed = []
        with mock.patch.object(main, "_seal_in_background",
                               side_effect=lambda *a, **k: sealed.append((a, k))):
            res = self.post()
        self.assertEqual(res.status_code, 200)
        self.assertEqual(sealed[0][0][0], "verify_mismatch")
        self.assertEqual(sealed[0][0][3]["ok"], False)          # verification 인자

    def test_no_seal_when_verification_passes(self):
        firebase_admin.set_admin(FakeAdmin())
        with mock.patch.object(main, "_seal_in_background") as seal:
            res = self.post()
        self.assertEqual(res.status_code, 200)
        seal.assert_not_called()


class FirestoreLikeAdmin(FakeAdmin):
    """Firestore REST 처럼 문서 경로를 검사한다: '컬렉션/문서' 쌍이라 마디 수가 짝수여야 한다.

    예전 체인 경로 'evidence_chain/entries/{seq}'(3마디)는 실제 Firestore 가 400 INVALID_ARGUMENT 로
    거절했다(10/18 확인). 가짜 관리자가 무엇이든 받아 주면 이 버그를 못 잡는다.
    """

    def __init__(self):
        super().__init__()
        self.docs = {}
        self.fail_writes = 0          # 앞에서부터 이만큼의 쓰기를 실패시킨다(일시 오류 흉내)
        self.fail_prefix = ""         # 이 경로로 시작하는 쓰기는 늘 실패시킨다

    def firestore(self, method, subpath, body=None):
        if len([p for p in subpath.split("/") if p]) % 2:
            raise firebase_admin.AdminError(503, "admin_failed")   # 400 INVALID_ARGUMENT 와 같은 처리
        if method == "PATCH":
            if self.fail_writes > 0:
                self.fail_writes -= 1
                raise firebase_admin.AdminError(503, "admin_failed")
            if self.fail_prefix and subpath.startswith(self.fail_prefix):
                raise firebase_admin.AdminError(503, "admin_failed")
            self.docs[subpath] = body
            return {}
        return self.docs.get(subpath, {})


EVIDENCE_ENV = {**ENV, "FIREBASE_SERVICE_ACCOUNT_JSON": SA,
                "EVIDENCE_PUBKEY": "x25519:" + __import__("base64").urlsafe_b64encode(b"\x07" * 32).decode().rstrip("=")}


class EvidenceChainTest(unittest.TestCase):
    """증거 기능을 켠 채 **진짜** record_attempt/record_outcome 이 도는 경로(배포와 같은 설정)."""

    def setUp(self):
        self.admin = FirestoreLikeAdmin()
        firebase_admin.set_admin(self.admin)
        self.client = TestClient(main.app, raise_server_exceptions=False)
        main._hits.clear()
        self.sealed = []
        self.patches = [mock.patch.object(main, "CHAIN_RETRY_DELAYS", (0, 0), create=True),
                        mock.patch.object(main, "_seal_in_background",
                                          side_effect=lambda *a, **k: self.sealed.append(a))]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        main._hits.clear()
        firebase_admin.set_admin(None)

    def post(self):
        with mock.patch.dict(os.environ, EVIDENCE_ENV, clear=True), \
                mock.patch.object(firebase_auth.id_token, "verify_firebase_token", return_value=CLAIMS):
            return self.client.post("/account/erase", headers={"Authorization": "Bearer signed-token",
                                                               "X-Withdraw-Challenge": "ef" * 16})

    def test_erase_succeeds_and_chain_entries_use_valid_document_paths(self):
        res = self.post()
        self.assertEqual(res.status_code, 200, res.text)
        self.assertTrue(res.json()["erased"])
        self.assertEqual(self.admin.erased, ["uid-1"])
        self.assertEqual(res.json()["receipt"]["seq"], 1)                     # 시도 기록의 체인 위치
        self.assertIn("evidence_entries/1", self.admin.docs)                   # 시도
        self.assertIn("evidence_entries/2", self.admin.docs)                   # 결과
        self.assertEqual(self.admin.docs["evidence_entries/2"]["fields"]["outcome"]["stringValue"], "ok")
        self.assertEqual(self.admin.docs["evidence_chain/head"]["fields"]["seq"]["integerValue"], "2")

    def test_attempt_not_recorded_means_nothing_is_erased(self):
        """시도 기록은 반드시 남아야 한다 — 끝내 못 남기면 계정을 지우지 않고 원인이 드러나는 503."""
        self.admin.fail_prefix = "evidence_entries/"
        res = self.post()
        self.assertEqual(res.status_code, 503, res.text)
        self.assertEqual(res.json()["detail"], "evidence_unavailable")        # 500 이 아니다
        self.assertEqual(self.admin.erased, [])
        # 이 실패도 봉인한다 — 예전에는 삭제 전 실패가 봉인되지 않아 관리자 아카이브 목록이 비었다
        self.assertEqual(self.sealed[0][0], "attempt_unrecorded")
        self.assertEqual(self.sealed[0][1], "uid-1")
        self.assertEqual(self.sealed[0][3]["challenge"], "ef" * 16)

    def test_transient_chain_failure_is_retried(self):
        self.admin.fail_writes = 1                                             # 첫 쓰기만 실패
        res = self.post()
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(self.admin.erased, ["uid-1"])
        self.assertIn("evidence_entries/1", self.admin.docs)

    def test_outcome_failure_after_erase_still_reports_erased_and_seals(self):
        """계정을 지운 뒤 결과 기록만 실패하면, 응답을 '실패'로 바꾸지 않고 증거로 봉인한다."""
        real = main.evidence.record_outcome

        def outcome_always_fails(*a, **k):
            raise firebase_admin.AdminError(503, "admin_failed")

        with mock.patch.object(main.evidence, "record_outcome", side_effect=outcome_always_fails):
            res = self.post()
        self.assertIs(main.evidence.record_outcome, real)
        self.assertEqual(res.status_code, 200, res.text)
        self.assertTrue(res.json()["erased"])
        self.assertIn("evidence_entries/1", self.admin.docs)                   # 시도 기록은 남았다
        self.assertEqual(self.sealed[0][0], "outcome_unrecorded")


class DiagnosticsTest(unittest.TestCase):
    """POST /diagnostics/withdraw — 화면이 보고하는 탈퇴 불일치."""

    def setUp(self):
        firebase_admin.set_admin(FakeAdmin())
        self.client = TestClient(main.app, raise_server_exceptions=False)
        main._hits.clear()

    def tearDown(self):
        main._hits.clear()
        firebase_admin.set_admin(None)

    def _token_patch(self):
        # verify_bearer 가 돌려주는 모양(uid/provider/…)으로 패치한다 — sub 를 그대로 주면 uid 가 없다.
        return mock.patch.object(firebase_auth, "verify_bearer",
                                 return_value={"uid": "uid-1", "provider": "google.com",
                                               "name": "김여행", "email": "traveler@example.com"})

    def test_requires_a_token(self):
        with mock.patch.object(firebase_auth, "verify_bearer",
                               side_effect=firebase_auth.AuthError(401, "missing_token")):
            res = self.client.post("/diagnostics/withdraw", json={"reason": "no_receipt"})
        self.assertEqual(res.status_code, 401)

    def test_report_is_sealed_as_background_evidence(self):
        sealed = []
        with self._token_patch(), mock.patch.object(
                main, "_seal_in_background", side_effect=lambda *a, **k: sealed.append((a, k))):
            res = self.client.post("/diagnostics/withdraw", headers={"Authorization": "Bearer signed-token"},
                                   json={"reason": "still_alive", "has_account": True,
                                         "server_said_erased": True})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(sealed[0][0][0], "client_report")
        self.assertEqual(sealed[0][0][3]["client"]["reason"], "still_alive")

    def test_extra_fields_are_ignored(self):
        with self._token_patch():
            res = self.client.post("/diagnostics/withdraw", headers={"Authorization": "Bearer signed-token"},
                                   json={"reason": "x", "uid": "uid-2", "token": "leak"})
        self.assertEqual(res.status_code, 200)     # uid·token 은 받지 않는다(모델에 없다)


if __name__ == "__main__":
    unittest.main()
