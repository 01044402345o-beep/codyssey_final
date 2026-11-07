"""영수증 서명 — 위조·키 교체·서명 없음이 모두 걸러지는지."""
import base64
import os
import unittest
from unittest import mock

from app import evidence, receipt_signing

ENTRY = {"seq": 42, "digest": "ab" * 32, "created_at": 1762400000000}
SEED_OLD = base64.urlsafe_b64encode(b"\x07" * 32).decode().rstrip("=")
SEED_NEW = base64.urlsafe_b64encode(b"\x09" * 32).decode().rstrip("=")


class ReceiptSigningTest(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"EVIDENCE_SIGN_KEY": SEED_OLD}, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)

    def signed(self):
        return evidence.receipt_for("c" * 32, ENTRY, "ok")

    def test_서명된_영수증은_검증을_통과한다(self):
        signed = self.signed()
        self.assertTrue(signed["signed"])
        self.assertEqual(signed["alg"], "Ed25519")
        self.assertTrue(receipt_signing.verify(signed)["ok"])

    def test_결과를_바꾸면_서명이_깨진다(self):
        tampered = dict(self.signed(), outcome="failed")
        self.assertEqual(receipt_signing.verify(tampered)["reason"], "invalid")

    def test_체인_위치를_바꾸면_서명이_깨진다(self):
        self.assertEqual(receipt_signing.verify(dict(self.signed(), seq=43))["reason"], "invalid")

    def test_핀이_다르면_키가_다르다고_알린다(self):
        with mock.patch.dict(os.environ, {"EVIDENCE_SIGN_KEY": SEED_NEW}, clear=False):
            pin = receipt_signing.public_key_b64()
        res = receipt_signing.verify(self.signed(), pin)
        self.assertFalse(res["ok"])
        self.assertEqual(res["reason"], "key_mismatch")

    def test_키가_없으면_서명하지_않는다(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("EVIDENCE_SIGN_KEY", None)
            receipt = evidence.receipt_for("d" * 32, ENTRY, "ok")
        self.assertFalse(receipt["signed"])
        self.assertEqual(receipt["reason"], "not_configured")
        self.assertEqual(receipt_signing.verify(receipt)["reason"], "unsigned")

    def test_health_에는_공개키만_나간다(self):
        info = receipt_signing.public_info()
        self.assertTrue(info["configured"])
        self.assertEqual(info["alg"], "Ed25519")
        self.assertNotIn(SEED_OLD, str(info))

    def test_회전해도_옛_영수증을_검증한다(self):
        old_receipt = self.signed()
        with mock.patch.dict(os.environ, {"EVIDENCE_SIGN_KEY": SEED_NEW}, clear=False):
            self.assertTrue(receipt_signing.verify(old_receipt)["ok"])
            new_pin = receipt_signing.public_key_b64()
            self.assertEqual(receipt_signing.verify(old_receipt, new_pin)["reason"], "key_mismatch")
            with mock.patch.dict(os.environ, {
                "EVIDENCE_SIGN_KEYS_OLD": f"{old_receipt['key_id']}:{old_receipt['public_key']}"
            }, clear=False):
                result = receipt_signing.verify_any(old_receipt)
        self.assertTrue(result["ok"])
        self.assertEqual(result["key_id"], old_receipt["key_id"])


if __name__ == "__main__":
    unittest.main()
