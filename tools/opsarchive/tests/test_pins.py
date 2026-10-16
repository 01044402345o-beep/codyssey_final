"""핀 고정과 IAM 점검 테스트 — 대조 규칙과 판정을 실제로 검증한다.

실행: `tools/opsarchive` 에서 `$env:PYTHONPATH="."; python -m unittest discover -s tests -t .`
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest import mock

from opsarchive import commands, container as C, gcp, pins


class PinFileTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="opsarchive-pin-")
        self.path = os.path.join(self.dir, "evidence-key-pin.json")

    def _pin(self, generation=1, armed=True):
        private, public = C.keypair()
        return pins.make(public, C.fingerprint(public), C.key_id(public).hex(),
                         generation=generation, health_url="https://example.test", armed=armed)

    def test_write_read_roundtrip(self):
        document = self._pin()
        pins.write(self.path, document)
        self.assertEqual(pins.read(self.path)["fingerprint_sha256"], document["fingerprint_sha256"])
        self.assertTrue(document["public_key"].startswith("x25519:"))

    def test_generation_regression_is_refused(self):
        pins.write(self.path, self._pin(generation=3))
        with self.assertRaises(pins.PinError) as caught:
            pins.write(self.path, self._pin(generation=2))
        self.assertEqual(caught.exception.code, "generation_regression")
        self.assertEqual(pins.read(self.path)["generation"], 3)         # 파일이 바뀌지 않았다

    def test_same_or_higher_generation_is_allowed(self):
        pins.write(self.path, self._pin(generation=3))
        pins.write(self.path, self._pin(generation=4))
        self.assertEqual(pins.read(self.path)["generation"], 4)

    def test_bad_schema(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"schema": 99}, fh)
        with self.assertRaises(pins.PinError):
            pins.read(self.path)


class PinCompareTest(unittest.TestCase):
    def setUp(self):
        self.private, self.public = C.keypair()
        self.document = pins.make(self.public, C.fingerprint(self.public), C.key_id(self.public).hex(),
                                  generation=2, health_url="https://example.test")
        self.health = {"evidence": {"fingerprint": C.fingerprint(self.public),
                                    "key_id": C.key_id(self.public).hex(), "generation": 2}}

    def test_matching_is_ok(self):
        result = pins.compare(self.document, self.health)
        self.assertTrue(result["ok"])
        self.assertEqual(result["reasons"], [])

    def test_unarmed_is_not_ok_and_not_failed(self):
        result = pins.compare(dict(self.document, armed=False), {})
        self.assertIsNone(result["ok"])
        self.assertEqual(result["reasons"], ["unarmed"])

    def test_fingerprint_mismatch(self):
        other, _ = C.keypair()
        result = pins.compare(self.document, {"evidence": {"fingerprint": C.fingerprint(other),
                                                           "generation": 2}})
        self.assertFalse(result["ok"])
        self.assertIn("fingerprint_mismatch", result["reasons"])

    def test_generation_drift_both_directions(self):
        low = pins.compare(self.document, {"evidence": {"fingerprint": C.fingerprint(self.public),
                                                        "generation": 1}})
        high = pins.compare(self.document, {"evidence": {"fingerprint": C.fingerprint(self.public),
                                                         "generation": 3}})
        self.assertIn("generation_lower", low["reasons"])       # 되돌리기 의심
        self.assertIn("generation_higher", high["reasons"])     # 핀을 안 올린 회전

    def test_missing_evidence_block(self):
        result = pins.compare(self.document, {"ok": True})
        self.assertFalse(result["ok"])
        self.assertEqual(result["reasons"], ["health_missing_evidence"])

    def test_runtime_generation_missing(self):
        result = pins.compare(self.document, {"evidence": {"fingerprint": C.fingerprint(self.public)}})
        self.assertIn("runtime_generation_missing", result["reasons"])


class IamCheckTest(unittest.TestCase):
    """앱 SA 가 증거를 지우거나 덮어쓸 수 있는지 — 스텁 저장소로 판정만 검증한다."""

    def _run(self, delete_denied=True, update_denied=True, create_ok=True):
        class Store:
            def __init__(self, *args, **kwargs):
                pass

            def set(self, path, data):
                if not create_ok:
                    raise gcp.GcpError("http_error")
                if data.get("tampered") and update_denied:
                    raise gcp.GcpError("http_error")

            def delete(self, path):
                if delete_denied:
                    raise gcp.GcpError("http_error")

        with mock.patch.object(commands.gcp, "Firestore", Store):
            return commands.iam_check("proj", "sa.json", canary_id="iam-canary-test")

    def test_ok_when_app_cannot_delete_or_overwrite(self):
        result = self._run()
        self.assertEqual(result["verdict"], "ok")
        self.assertTrue(result["created"])

    def test_app_can_delete_is_flagged(self):
        result = self._run(delete_denied=False)
        self.assertEqual(result["verdict"], "app_can_delete")

    def test_app_can_overwrite_is_flagged(self):
        result = self._run(update_denied=False)
        self.assertEqual(result["verdict"], "app_can_overwrite")

    def test_create_failure_is_reported(self):
        result = self._run(create_ok=False)
        self.assertEqual(result["verdict"], "create_failed:http_error")
        self.assertFalse(result["created"])

    def test_canary_id_is_marked(self):
        result = self._run()
        self.assertTrue(result["canary"].startswith("iam-canary-"))
        self.assertIn("expire_at", result["note"]) or self.assertIn("TTL", result["note"])


class MakePinTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="opsarchive-mkpin-")
        self.key = os.path.join(self.dir, "admin.key")
        self.private, self.public = C.keypair()
        C.save_private_key(self.key, self.private, "phrase")

    def test_make_pin_uses_the_local_key_and_increments(self):
        first = commands.make_pin(self.key, "phrase", health_url="https://example.test",
                                  out=os.path.join(self.dir, "pin.json"))
        self.assertEqual(first["generation"], 1)
        self.assertEqual(first["fingerprint_sha256"], C.fingerprint(self.public))
        second = commands.make_pin(self.key, "phrase", health_url="https://example.test",
                                   out=os.path.join(self.dir, "pin.json"))
        self.assertEqual(second["generation"], 2)

    def test_check_pin_unarmed_is_not_a_failure(self):
        path = os.path.join(self.dir, "pin.json")
        document = pins.make(self.public, C.fingerprint(self.public), C.key_id(self.public).hex(),
                             generation=1, health_url="", armed=False)
        pins.write(path, document)
        self.assertIsNone(commands.check_pin(path)["ok"])

    def test_check_pin_without_health_url_fails_when_armed(self):
        path = os.path.join(self.dir, "pin.json")
        commands.make_pin(self.key, "phrase", health_url="", out=path)
        result = commands.check_pin(path)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reasons"], ["health_url_missing"])


if __name__ == "__main__":
    unittest.main()
