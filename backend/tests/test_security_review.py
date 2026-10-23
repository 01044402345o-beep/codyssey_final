"""/health 의 security_review — 정책 경고를 숨기지 않고, 키 값은 절대 내보내지 않는다."""
import os
import unittest
from unittest import mock

from app import main


class SecurityReviewTest(unittest.TestCase):
    def test_기본값에서는_CORS_와_프록시_경고가_나온다(self):
        with mock.patch.dict(os.environ, {"RENDER": "1"}, clear=False):
            os.environ.pop("ALLOW_ORIGINS", None)
            r = main.security_review()
        self.assertEqual(r["cors"], "open")
        self.assertEqual(r["rate_limit_scope"], "process")
        self.assertTrue(any("ALLOW_ORIGINS" in w for w in r["warnings"]))
        self.assertTrue(any("/generate" in w for w in r["warnings"]))

    def test_허용목록과_홉을_주면_경고가_줄어든다(self):
        with mock.patch.dict(os.environ, {"ALLOW_ORIGINS": "https://a.example,https://b.example"}, clear=False):
            r = main.security_review()
        self.assertEqual(r["cors"], "allowlist")
        self.assertFalse(any("ALLOW_ORIGINS" in w for w in r["warnings"]))

    def test_키_값은_어디에도_없다(self):
        secret = "AIzaSyTESTKEYVALUE1234567890"
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": secret, "SONIOX_API_KEY": "sk_" + secret}, clear=False):
            r = main.security_review()
            h = main.health_detail()
        blob = repr(r) + repr(h.get("security_review")) + repr(h.get("gemini_keys"))
        self.assertNotIn(secret, blob)

    def test_health_에_점검_블록이_있다(self):
        h = main.health_detail()
        self.assertIn("security_review", h)
        self.assertIsInstance(h["security_review"].get("warnings"), list)


if __name__ == "__main__":
    unittest.main()
