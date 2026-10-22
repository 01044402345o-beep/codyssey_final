"""KMS 서명 감사 대조 — 감사 로그·Firestore 는 가짜. 실행: cd tools/opsarchive && python -m unittest tests.test_kms_audit"""
from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import unittest
import urllib.error
from unittest import mock

from opsarchive import commands, kms_audit, pins

KEY = "projects/demo-project-123/locations/asia-northeast3/keyRings/opsarchive/cryptoKeys/checkpoint-signer/cryptoKeyVersions/1"
CI = "evidence-anchor@demo-project-123.iam.gserviceaccount.com"
ADMIN = "firebase-adminsdk@demo-project-123.iam.gserviceaccount.com"
KID = "a1b2c3d4e5f60708"
T0 = 1_761_100_000


def ev(at, who=CI, ok=True):
    return {"at": float(at), "time": "", "principal": who, "resource": KEY, "ok": ok, "status": "" if ok else "denied"}


def cp(seq, at, kid=KID):
    return {"seq": seq, "created_at": at, "signing_key_id": kid}


class ClassifyTest(unittest.TestCase):
    def run_(self, events, cps):
        return kms_audit.classify(events, cps, key_id=KID, admin_principals={ADMIN})

    def test_one_sign_per_checkpoint_is_ok(self):
        r = self.run_([ev(T0), ev(T0 + 21600)], [cp(1, T0 + 1), cp(2, T0 + 21601)])
        self.assertEqual(r["verdict"], "ok")
        self.assertEqual(r["by_principal"], {CI: 2})

    def test_extra_signature_by_someone_else_is_a_violation_and_names_who(self):
        r = self.run_([ev(T0), ev(T0 + 5000, who="intruder@evil.iam.gserviceaccount.com")], [cp(1, T0)])
        self.assertEqual(r["verdict"], "violation")
        self.assertEqual(r["unexplained"][0]["principal"], "intruder@evil.iam.gserviceaccount.com")

    def test_extra_signature_by_ci_without_a_checkpoint_is_a_violation(self):
        """CI 계정이 체크포인트 없이 서명했다 = 워크플로·코드가 바뀌어 다른 것을 서명했을 수 있다."""
        r = self.run_([ev(T0), ev(T0 + 3000)], [cp(1, T0)])
        self.assertEqual(r["verdict"], "violation")

    def test_seq_retry_and_admin_probe_are_warnings(self):
        r = self.run_([ev(T0), ev(T0 + 2), ev(T0 + 9000, who=ADMIN)], [cp(1, T0 + 3)])
        self.assertEqual(r["verdict"], "warning")
        self.assertEqual(r["counts"], {"matched": 1, "retry": 1, "admin_probe": 1})

    def test_denied_attempt_reports_who_tried(self):
        r = self.run_([ev(T0), ev(T0 + 100, who="someone@x.iam.gserviceaccount.com", ok=False)], [cp(1, T0)])
        self.assertEqual(r["verdict"], "warning")
        self.assertEqual(r["denied"][0]["principal"], "someone@x.iam.gserviceaccount.com")

    def test_no_log_but_checkpoints_means_logs_are_off(self):
        self.assertEqual(self.run_([], [cp(1, T0)])["verdict"], "logs_missing")

    def test_checkpoints_of_other_keys_are_ignored(self):
        r = self.run_([ev(T0)], [cp(1, T0), cp(2, T0 + 10, kid="ffff")])
        self.assertEqual((r["verdict"], r["checkpoints"]), ("ok", 1))


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class SignEventsTest(unittest.TestCase):
    def test_filter_paging_and_parsing(self):
        seen = []
        pages = [{"entries": [{"timestamp": "2026-10-22T01:00:00Z", "protoPayload": {
                     "authenticationInfo": {"principalEmail": CI}, "resourceName": KEY}}], "nextPageToken": "p2"},
                 {"entries": [{"timestamp": "2026-10-22T02:00:00Z", "protoPayload": {
                     "authenticationInfo": {"principalEmail": "x@y"}, "resourceName": KEY,
                     "status": {"code": 7, "message": "Permission denied"}}}]}]

        def opener(req, timeout):
            seen.append(json.loads(req.data))
            return Resp(json.dumps(pages.pop(0)).encode())
        out = kms_audit.sign_events("demo-project-123", "tok", KEY, T0, opener=opener)
        f = seen[0]["filter"]
        self.assertIn('protoPayload.methodName="AsymmetricSign"', f)
        self.assertIn("cloudaudit.googleapis.com%2Fdata_access", f)
        self.assertIn('protoPayload.resourceName:"projects/demo-project-123/locations/asia-northeast3/keyRings/opsarchive/cryptoKeys/checkpoint-signer"', f)
        self.assertNotIn("cryptoKeyVersions", f)                 # 모든 버전의 서명을 본다
        self.assertEqual(seen[1]["pageToken"], "p2")
        self.assertEqual([(e["principal"], e["ok"]) for e in out], [(CI, True), ("x@y", False)])

    def test_forbidden(self):
        def opener(req, timeout):
            raise urllib.error.HTTPError(req.full_url, 403, "x", None, io.BytesIO(b"{}"))
        with self.assertRaises(kms_audit.AuditError) as c:
            kms_audit.sign_events("demo-project-123", "tok", KEY, T0, opener=opener)
        self.assertEqual(c.exception.code, "forbidden")


class CommandTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="kms-audit-")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.pin = os.path.join(self.dir, "pin.json")
        pins.write(self.pin, {"schema": pins.SCHEMA, "generation": 1,
                              "auto_signing_keys": [{"public_key": "x25519:AA", "key_id": KID, "kms_key": KEY}]})
        self.sa = os.path.join(self.dir, "sa.json")
        with open(self.sa, "w", encoding="utf-8") as fh:
            json.dump({"client_email": ADMIN}, fh)

    def check(self, events, cps):
        with mock.patch.object(commands.kms_audit, "sign_events", return_value=events), \
             mock.patch.object(commands, "firestore_checkpoints", return_value=[{"checkpoint": c} for c in cps]), \
             mock.patch.object(commands.time, "time", return_value=T0 + 3600):
            return commands.kms_audit_check("demo-project-123", self.sa, KEY, pin_path=self.pin,
                                            out_dir=os.path.join(self.dir, "none"), token_fn=lambda sa, sc: "tok")

    def test_violation_is_an_error(self):
        r = self.check([ev(T0), ev(T0 + 500, who="intruder@x")], [cp(1, T0)])
        self.assertTrue(r["error"].startswith("unexplained_signatures"))

    def test_admin_probe_is_recognized_from_the_service_account_file(self):
        r = self.check([ev(T0), ev(T0 + 900, who=ADMIN)], [cp(1, T0)])
        self.assertEqual(r["verdict"], "warning")
        self.assertNotIn("error", r)

    def test_logs_off_is_an_error(self):
        self.assertTrue(self.check([], [cp(1, T0)])["error"].startswith("logs_missing"))

    def test_key_must_be_pinned(self):
        with self.assertRaises(commands.CommandError):
            commands.kms_audit_check("demo-project-123", self.sa, KEY.replace("/1", "/2"), pin_path=self.pin,
                                     token_fn=lambda sa, sc: "tok")

    def test_forbidden_gives_role_hint(self):
        with mock.patch.object(commands.kms_audit, "sign_events", side_effect=kms_audit.AuditError("forbidden")):
            r = commands.kms_audit_check("demo-project-123", self.sa, KEY, pin_path=self.pin, token_fn=lambda sa, sc: "tok")
        self.assertIn("privateLogViewer", r["error"])


if __name__ == "__main__":
    unittest.main()
