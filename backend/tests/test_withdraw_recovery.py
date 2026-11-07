"""복구 보고 경로 — 토큰 없이 받되 체인의 커밋먼트로 거르고, 서버는 복구 키를 보지 못한다.

실행: cd backend && python -m unittest tests.test_withdraw_recovery
"""

from __future__ import annotations

import base64
import json
import os
import sys
import unittest
from unittest import mock

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "tools", "opsarchive"))
from opsarchive import container as C           # noqa: E402 — 검증용(앱은 이 패키지를 쓰지 않는다)

from fastapi.testclient import TestClient        # noqa: E402

from app import evidence, firebase_admin, main   # noqa: E402

KEY = "wrk1-" + "11" * 32
COMMITMENT = "9" * 64


class FakeStore:
    def __init__(self, known=(COMMITMENT,), fail=False):
        self.known, self.fail, self.docs = set(known), fail, {}

    def field_exists(self, collection, field, value):
        if self.fail:
            raise firebase_admin.AdminError(503, "admin_failed")
        return collection == evidence.ENTRIES_COLLECTION and field == "challenge" and value in self.known

    def firestore(self, method, subpath, body=None):
        if method == "PATCH":
            self.docs[subpath] = body
        return {}


def b64(blob: bytes) -> str:
    return base64.urlsafe_b64encode(blob).decode().rstrip("=")


class RecoveryRouteTest(unittest.TestCase):
    def setUp(self):
        evidence.reset_state()
        main._hits.clear()
        self.private, self.public = C.keypair()
        env = mock.patch.dict(os.environ, {"EVIDENCE_PUBKEY": C.pack_public_key(self.public),
                                           "EVIDENCE_NOTIFY": "0"}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(firebase_admin.set_admin, None)
        self.client = TestClient(main.app, raise_server_exceptions=False)
        self.inner = json.dumps({"recovery_key": KEY, "commitment": COMMITMENT}).encode()
        self.sealed = b64(C.seal(self.inner, self.public))

    def post(self, commitment=COMMITMENT, sealed=None):
        return self.client.post("/withdraw/recovery",
                                json={"commitment": commitment, "sealed": self.sealed if sealed is None else sealed})

    def test_public_key_route_matches_the_health_fingerprint(self):
        body = self.client.get("/withdraw/recovery-key").json()
        raw = C.unpack_public_key(body["public_key"])
        self.assertEqual(C.fingerprint(raw), evidence.fingerprint())
        self.assertEqual(body["key_id"], evidence.key_id_hex())

    def test_stored_report_never_holds_the_key_in_plain_and_admin_can_open_it(self):
        store = FakeStore()
        firebase_admin.set_admin(store)
        res = self.post()
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json(), {"received": True})
        self.assertNotIn(KEY, json.dumps(store.docs))
        parts = sorted(k for k in store.docs if "/parts/" in k)
        blob = b"".join(base64.b64decode(store.docs[k]["fields"]["data"]["stringValue"]) for k in parts)
        report = json.loads(C.unseal(blob, self.private))
        self.assertEqual(report["trigger"], "recovery_report")
        self.assertNotIn(KEY, json.dumps(report))        # 겉 봉인을 열어도 복구 키는 안쪽 봉투에 있다
        self.assertEqual(C.unseal(bytes.fromhex(report["extra"]["sealed_recovery_hex"]), self.private), self.inner)

    def test_unknown_commitment_is_rejected_without_storing(self):
        store = FakeStore(known=())
        firebase_admin.set_admin(store)
        res = self.post()
        self.assertEqual((res.status_code, res.json()["detail"]), (404, "unknown_commitment"))
        self.assertEqual(store.docs, {})

    def test_failed_chain_lookup_is_not_treated_as_received(self):
        firebase_admin.set_admin(FakeStore(fail=True))
        self.assertEqual(self.post().status_code, 503)

    def test_same_commitment_is_throttled_and_does_not_spend_server_budget(self):
        firebase_admin.set_admin(FakeStore())
        self.assertEqual(self.post().status_code, 200)
        res = self.post()
        self.assertEqual((res.status_code, res.json()["detail"]), (429, "recovery_throttled"))
        self.assertEqual(evidence._daily["server"]["count"], 0)

    def test_blob_for_another_key_or_not_mfa1_is_rejected(self):
        firebase_admin.set_admin(FakeStore())
        _, other = C.keypair()
        self.assertEqual(self.post(sealed=b64(C.seal(self.inner, other))).status_code, 400)
        self.assertEqual(self.post(sealed=b64(b"not sealed at all")).status_code, 400)

    def test_plain_key_as_commitment_is_rejected_by_shape(self):
        firebase_admin.set_admin(FakeStore())
        self.assertEqual(self.post(commitment=KEY).status_code, 422)

    def test_disabled_without_admin_key_or_by_policy(self):
        with mock.patch.dict(os.environ, {"EVIDENCE_CLIENT_REPORTS": "0"}, clear=False):
            self.assertEqual(self.client.get("/withdraw/recovery-key").status_code, 503)
            self.assertEqual(self.post().status_code, 503)
        with mock.patch.dict(os.environ, {"EVIDENCE_PUBKEY": ""}, clear=False):
            self.assertEqual(self.client.get("/withdraw/recovery-key").status_code, 503)

    def test_report_scrubbing_keeps_the_envelope_openable(self):
        firebase_admin.set_admin(FakeStore())
        report = evidence.collect("recovery_report", extra={"sealed_recovery_hex": C.seal(self.inner, self.public).hex()})
        self.assertEqual(C.unseal(bytes.fromhex(report["extra"]["sealed_recovery_hex"]), self.private), self.inner)


class ScreenRedirectTest(unittest.TestCase):
    """운영(Render)의 화면은 Hosting 으로 넘어가고, API·로컬은 그대로다."""

    def get(self, path, env):
        clean = {k: v for k, v in os.environ.items() if k not in ("RENDER", "SCREEN_HOME_URL")}
        client = TestClient(main.app, raise_server_exceptions=False, follow_redirects=False)
        with mock.patch.dict(os.environ, {**clean, **env}, clear=True):
            return client.get(path)

    def test_render_redirects_the_screen_and_browsers_remember_it(self):
        res = self.get("/", {"RENDER": "true"})
        self.assertEqual(res.status_code, 301)
        self.assertEqual(res.headers["location"], main.HOSTED_SCREEN + "/")
        self.assertIn("max-age=604800", res.headers["cache-control"])
        self.assertEqual(self.get("/index.html", {"RENDER": "true"}).status_code, 301)

    def test_query_is_kept(self):
        res = self.get("/?demo=1&gate=off", {"RENDER": "true"})
        self.assertEqual(res.headers["location"], main.HOSTED_SCREEN + "/?demo=1&gate=off")

    def test_api_is_not_redirected(self):
        self.assertEqual(self.get("/health", {"RENDER": "true"}).status_code, 200)

    def test_stay_keeps_the_old_screen_for_rescuing_saved_proofs(self):
        self.assertEqual(self.get("/?stay=1", {"RENDER": "true"}).status_code, 200)

    def test_local_and_ci_serve_the_screen(self):
        self.assertEqual(self.get("/", {}).status_code, 200)

    def test_can_be_turned_off_or_pointed_elsewhere_but_only_to_https(self):
        self.assertEqual(self.get("/", {"RENDER": "true", "SCREEN_HOME_URL": ""}).status_code, 200)
        self.assertEqual(self.get("/", {"RENDER": "true", "SCREEN_HOME_URL": "http://a.test"}).status_code, 200)
        self.assertEqual(self.get("/", {"SCREEN_HOME_URL": "https://a.test/"}).headers["location"], "https://a.test/")


class FieldExistsTest(unittest.TestCase):
    """runQuery 는 객체가 아니라 배열을 돌려준다. 빈 결과 행(readTime 만)은 '없음'이다."""

    def admin(self, payload):
        class Res:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return json.dumps(payload).encode()

        seen = {}

        def opener(req, timeout=10):
            seen["url"], seen["body"] = req.full_url, json.loads(req.data)
            return Res()

        admin = firebase_admin.ServiceAccountAdmin("demo", {"client_email": "a", "private_key": "b"}, opener=opener)
        admin._token = lambda: "tok"
        return admin, seen

    def test_found_row(self):
        admin, seen = self.admin([{"document": {"name": "x"}, "readTime": "t"}])
        self.assertTrue(admin.field_exists("evidence_entries", "challenge", "abc"))
        self.assertTrue(seen["url"].endswith("/documents:runQuery"))
        where = seen["body"]["structuredQuery"]["where"]["fieldFilter"]
        self.assertEqual(where["value"], {"stringValue": "abc"})

    def test_empty_result_row(self):
        admin, _ = self.admin([{"readTime": "t"}])
        self.assertFalse(admin.field_exists("evidence_entries", "challenge", "abc"))


if __name__ == "__main__":
    unittest.main()
