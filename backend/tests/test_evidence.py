"""증거 봉인 훅 — 형식 호환·수집 캡·스크럽·보관·통보·스로틀.

가장 중요한 검사는 **CLI 와의 형식 호환**이다: 앱이 봉인한 것을 관리자 CLI 의 `unseal` 로 실제로 연다.
그래서 이 테스트는 `tools/opsarchive` 를 경로에 넣고 그 구현을 그대로 쓴다(명세가 갈라지면 실패한다).

실행: cd backend && python -m unittest tests.test_evidence
"""

from __future__ import annotations

import base64
import io
import json
import os
import sys
import unittest
from unittest import mock

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "tools", "opsarchive"))
from opsarchive import container as C          # noqa: E402 — 검증용(앱은 이 패키지를 쓰지 않는다)

from app import evidence                        # noqa: E402


class SealedCompatibilityTest(unittest.TestCase):
    """앱이 봉인 → CLI 가 해제. 형식(MFA1)이 어긋나면 여기서 깨진다."""

    def setUp(self):
        evidence.reset_state()
        self.private, self.public = C.keypair()
        self.env = mock.patch.dict(os.environ, {
            "EVIDENCE_PUBKEY": C.pack_public_key(self.public),
            "EVIDENCE_KEY_GENERATION": "3",
        }, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_app_seal_is_opened_by_the_cli(self):
        payload = json.dumps({"trigger": "erase_failed", "uid_hash": "abc"}, ensure_ascii=False).encode()
        blob = evidence.seal(payload, evidence.public_key())
        self.assertEqual(C.unseal(blob, self.private), payload)

    def test_cli_seal_is_readable_by_the_app(self):
        """반대 방향도 확인한다(관리자가 만든 것은 없지만, 형식이 대칭임을 고정한다)."""
        payload = b"hello"
        blob = C.seal(payload, self.public)
        # 앱에는 unseal 이 없다 — 개인키를 앱에 두지 않기 때문이다. 대신 헤더 계약을 확인한다.
        self.assertTrue(blob.startswith(evidence.MAGIC))
        self.assertEqual(blob[4], evidence.ALG)
        self.assertEqual(blob[5], evidence.VERSION)
        self.assertEqual(blob[6:14], C.key_id(self.public))

    def test_health_block_exposes_only_public_info(self):
        block = evidence.health_block()
        self.assertEqual(block["generation"], 3)
        self.assertEqual(block["key_id"], C.key_id(self.public).hex())
        self.assertEqual(block["fingerprint"], C.fingerprint(self.public))
        self.assertNotIn("public_key", block)

    def test_disabled_without_key(self):
        with mock.patch.dict(os.environ, {"EVIDENCE_PUBKEY": ""}, clear=False):
            self.assertFalse(evidence.configured())
            self.assertEqual(evidence.health_block(), {})
            self.assertEqual(evidence.seal_and_report("erase_failed")["reason"], "no_key")


class ScrubTest(unittest.TestCase):
    def test_credentials_are_masked(self):
        text = ("Authorization: Bearer abcdefghijklmnop\n"
                "key=AIzaSyA1234567890abcdefghijklmnop\n"
                "pat=github_pat_11ABCDEFG0123456789AB\n"
                "jwt=eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIxIn0.abcdef")
        out = evidence.scrub_text(text)
        self.assertNotIn("abcdefghijklmnop", out)
        self.assertNotIn("AIzaSyA1234567890abcdefghijklmnop", out)
        self.assertNotIn("github_pat_11ABCDEFG0123456789AB", out)
        self.assertNotIn("eyJhbGciOiJSUzI1NiJ9", out)
        self.assertIn("[MASKED]", out)

    def test_environment_secret_values_are_masked(self):
        with mock.patch.dict(os.environ, {"SOME_API_TOKEN": "s3cr3t-value-12345"}, clear=False):
            self.assertNotIn("s3cr3t-value-12345", evidence.scrub_text("token=s3cr3t-value-12345"))

    def test_override_keeps_everything(self):
        with mock.patch.dict(os.environ, {"EVIDENCE_INCLUDE_SECRETS": "1"}, clear=False):
            text = "Bearer abcdefghijklmnop"
            self.assertEqual(evidence.scrub_text(text), text)


class CollectTest(unittest.TestCase):
    def setUp(self):
        evidence.reset_state()

    def test_caps_truncate_source_and_mark_it(self):
        import tempfile
        root = tempfile.mkdtemp(prefix="evidence-src-")
        with open(os.path.join(root, "big.py"), "w", encoding="utf-8") as fh:
            fh.write("x" * 5000)
        with open(os.path.join(root, "small.py"), "w", encoding="utf-8") as fh:
            fh.write("print('hi')\n")
        with mock.patch.dict(os.environ, {"EVIDENCE_MAX_SOURCE_BYTES": "100"}, clear=False):
            report = evidence.collect("erase_failed", source_root=root)
        self.assertIn("source", report)
        self.assertEqual(len(report["source"]["files"]), 2)      # 목록은 다 남는다(크기만 잘림)
        self.assertTrue(report["truncated"].get("source"))
        self.assertLessEqual(len(json.dumps(report["source"]["content"], ensure_ascii=False)), 200)

    def test_logs_are_capped(self):
        for index in range(30):
            evidence._ring.records.append("line-%d-%s" % (index, "y" * 100))
        with mock.patch.dict(os.environ, {"EVIDENCE_MAX_LOGS_BYTES": "300"}, clear=False):
            report = evidence.collect("erase_failed")
        self.assertTrue(report["truncated"].get("logs"))
        self.assertLess(len(json.dumps(report["logs"])), 400)

    def test_ledger_verification_and_error_are_recorded(self):
        error = ValueError("boom")
        report = evidence.collect("erase_failed", uid="uid-1",
                                  ledger=[{"step": "tombstone", "ok": True, "code": ""}],
                                  verification={"ok": False}, error=error)
        self.assertEqual(report["ledger"][0]["step"], "tombstone")
        self.assertEqual(report["verification"]["ok"], False)
        self.assertEqual(report["error"]["type"], "ValueError")
        self.assertIn("boom", report["error"]["message"])
        self.assertEqual(report["uid_hash"], __import__("hashlib").sha256(b"uid-1").hexdigest()[:16])

    def test_env_values_are_not_collected_only_names(self):
        with mock.patch.dict(os.environ, {"EVIDENCE_PUBKEY": "x25519:AAABBB"}, clear=False):
            report = evidence.collect("erase_failed")
        self.assertIn("EVIDENCE_PUBKEY", report["runtime"]["env_names"])
        self.assertNotIn("x25519:AAABBB", json.dumps(report))


class StoreTest(unittest.TestCase):
    class Admin:
        def __init__(self):
            self.calls = []
            self.head = {}

        def firestore(self, method, subpath, body=None):
            self.calls.append((method, subpath, body))
            return self.head if subpath == "evidence_chain/head" else {}

    def test_chunks_are_written_with_ttl(self):
        admin = StoreTest.Admin()
        from app import firebase_admin
        firebase_admin.set_admin(admin)
        try:
            blob = b"z" * (evidence.CHUNK_BYTES + 10)
            document = evidence.store(blob, {"archive_id": "aid1", "expire_at": 123, "trigger": "t"})
        finally:
            firebase_admin.set_admin(None)
        self.assertEqual(document["chunks"], 2)
        self.assertEqual(document["size"], len(blob))
        paths = [c[1] for c in admin.calls]
        writes = [c[1] for c in admin.calls if c[0] == "PATCH"]
        self.assertEqual(paths[0], "evidence_chain/head")                # 먼저 체인 머리를 읽는다
        self.assertEqual(writes[0], "evidence_archives/aid1")            # 메타가 먼저 쓰인다
        self.assertEqual(writes[1:3], ["evidence_archives/aid1/parts/0", "evidence_archives/aid1/parts/1"])
        self.assertEqual(writes[-1], "evidence_chain/head")              # 마지막에 머리를 옮긴다
        part = admin.calls[2][2]["fields"]
        self.assertEqual(part["seq"]["integerValue"], "0")
        self.assertEqual(part["expire_at"]["integerValue"], "123")
        self.assertEqual(base64.b64decode(part["data"]["stringValue"]), blob[:evidence.CHUNK_BYTES])

    def test_manifest_chains_to_the_previous_head(self):
        admin = StoreTest.Admin()
        admin.head = {"fields": {"seq": {"integerValue": "4"},
                                 "digest": {"stringValue": "prev-digest"}}}
        from app import firebase_admin
        firebase_admin.set_admin(admin)
        try:
            document = evidence.store(b"x", {"archive_id": "aid2", "created_at": 7, "expire_at": 9})
        finally:
            firebase_admin.set_admin(None)
        self.assertEqual(document["seq"], 5)
        self.assertEqual(document["prev_digest"], "prev-digest")
        self.assertEqual(document["schema"], evidence.MANIFEST_SCHEMA)
        # digest 는 **매니페스트 필드만**으로 (prev_digest 포함) 계산된다 → 체인이 된다
        body = {k: v for k, v in document.items()
                if k in ("schema", "archive_id", "created_at", "ciphertext_sha256", "size",
                         "chunks", "recipient_key_id", "trigger", "seq", "prev_digest")}
        self.assertEqual(evidence.manifest_digest(body), document["digest"])
        self.assertNotEqual(evidence.manifest_digest(dict(body, prev_digest="other")), document["digest"])


class NotifyTest(unittest.TestCase):
    class Response(io.BytesIO):
        status = 201

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def test_issue_contains_metadata_only(self):
        seen = {}

        def fake_urlopen(request, timeout=0):
            seen["url"] = request.full_url
            seen["body"] = json.loads(request.data.decode())
            seen["auth"] = request.get_header("Authorization")
            return NotifyTest.Response(b"{}")

        env = {"EVIDENCE_GH_TOKEN": "ghp_" + "x" * 20, "EVIDENCE_GH_REPO": "org/repo"}
        with mock.patch.dict(os.environ, env, clear=False), \
                mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            ok = evidence.notify({"archive_id": "aid1", "trigger": "erase_failed", "key_id": "kid",
                                  "sha256": "aa", "size": 10, "chunks": 1, "expire_at": 99,
                                  "ledger": [], "verification": {}})
        self.assertTrue(ok)
        self.assertEqual(seen["url"], "https://api.github.com/repos/org/repo/issues")
        self.assertIn("aid1", seen["body"]["body"])
        self.assertEqual(seen["body"]["labels"], ["evidence-seal"])
        self.assertNotIn("data", seen["body"])          # 본문(암호문)은 이슈로 가지 않는다
        self.assertNotIn("x" * 20, json.dumps(seen["body"]))   # 토큰도 본문에 없다

    def test_missing_token_skips_notification(self):
        with mock.patch.dict(os.environ, {"EVIDENCE_GH_TOKEN": "", "EVIDENCE_GH_REPO": ""}, clear=False):
            self.assertFalse(evidence.notify({"archive_id": "aid1"}))


class ThrottleTest(unittest.TestCase):
    def setUp(self):
        evidence.reset_state()
        self.env = mock.patch.dict(os.environ, {"EVIDENCE_DAILY_CAP": "2",
                                                "EVIDENCE_PER_UID_SECONDS": "3600"}, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(evidence.reset_state)

    def test_same_uid_is_throttled(self):
        self.assertTrue(evidence.throttle_ok("uid-1"))
        self.assertFalse(evidence.throttle_ok("uid-1"))

    def test_daily_cap_applies(self):
        self.assertTrue(evidence.throttle_ok("uid-1"))
        self.assertTrue(evidence.throttle_ok("uid-2"))
        self.assertFalse(evidence.throttle_ok("uid-3"))

    def test_seal_and_report_respects_throttle_and_never_raises(self):
        private, public = C.keypair()
        with mock.patch.dict(os.environ, {"EVIDENCE_PUBKEY": C.pack_public_key(public)}, clear=False):
            with mock.patch.object(evidence, "store", side_effect=RuntimeError("firestore down")):
                first = evidence.seal_and_report("erase_failed", uid="uid-9")
                second = evidence.seal_and_report("erase_failed", uid="uid-9")
        self.assertEqual(first["reason"], "failed")          # 저장 실패를 삼킨다
        self.assertEqual(second["reason"], "throttled")      # 스로틀은 실패와 무관하게 먼저 걸린다


class HealthEndpointTest(unittest.TestCase):
    """/health 가 공개 지문·세대를 노출한다 — 핀 검증(.github/workflows/verify-key-pin.yml)이 이 값을 본다."""

    def test_health_exposes_fingerprint_when_enabled(self):
        from fastapi.testclient import TestClient
        from app import main
        _, public = C.keypair()
        with mock.patch.dict(os.environ, {"EVIDENCE_PUBKEY": C.pack_public_key(public),
                                          "EVIDENCE_KEY_GENERATION": "7"}, clear=False):
            body = TestClient(main.app).get("/health").json()
        self.assertEqual(body["evidence"]["fingerprint"], C.fingerprint(public))
        self.assertEqual(body["evidence"]["generation"], 7)

    def test_health_has_empty_evidence_when_disabled(self):
        from fastapi.testclient import TestClient
        from app import main
        with mock.patch.dict(os.environ, {"EVIDENCE_PUBKEY": ""}, clear=False):
            body = TestClient(main.app).get("/health").json()
        self.assertEqual(body["evidence"], {})


class VerifyErasedTest(unittest.TestCase):
    def setUp(self):
        from app import firebase_admin
        self.firebase_admin = firebase_admin
        firebase_admin.set_admin(None)

    def tearDown(self):
        self.firebase_admin.set_admin(None)

    def _admin(self, tombstone=True, document=None, user=None):
        class Admin:
            def read_tombstone(self, uid):
                return tombstone

            def firestore(self, method, subpath, body=None):
                return document or {}

            def lookup_user(self, uid):
                return user or {}

        return Admin()

    def test_ok_when_all_three_are_gone(self):
        self.firebase_admin.set_admin(self._admin())
        result = self.firebase_admin.verify_erased("uid-1")
        self.assertTrue(result["ok"])
        self.assertTrue(result["document_gone"] and result["account_gone"] and result["tombstone"])

    def test_mismatch_when_document_remains(self):
        self.firebase_admin.set_admin(self._admin(document={"fields": {}}))
        result = self.firebase_admin.verify_erased("uid-1")
        self.assertFalse(result["ok"])
        self.assertFalse(result["document_gone"])

    def test_mismatch_when_account_remains(self):
        self.firebase_admin.set_admin(self._admin(user={"localId": "uid-1"}))
        self.assertFalse(self.firebase_admin.verify_erased("uid-1")["ok"])

    def test_verification_failure_does_not_raise(self):
        class Broken:
            def read_tombstone(self, uid):
                raise RuntimeError("boom")

        self.firebase_admin.set_admin(Broken())
        result = self.firebase_admin.verify_erased("uid-1")
        self.assertIsNone(result["ok"])
        self.assertEqual(result["error"], "verify_failed")


if __name__ == "__main__":
    unittest.main()
