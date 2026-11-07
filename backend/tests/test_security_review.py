"""/health 의 security_review — 정책 경고를 숨기지 않고, 키 값은 절대 내보내지 않는다."""
import os
import unittest
from unittest import mock

from app import main


class SecurityReviewTest(unittest.TestCase):
    def test_관리형에서_와일드카드는_fail_closed(self):
        with mock.patch.dict(os.environ, {"RENDER": "1", "FIREBASE_PROJECT_ID": "demo-project"}, clear=False):
            for value in ("*", "https://a.example,*"):
                os.environ["ALLOW_ORIGINS"] = value
                self.assertEqual(main.effective_cors_origins(), [], value)

    def test_관리형에서_누락이면_Hosting_두_주소만(self):
        """ALLOW_ORIGINS 가 없는 배포(render.yaml 이 적용되지 않는 서비스)에서도 web.app 화면이 죽지 않고, '*' 로 열리지도 않는다."""
        with mock.patch.dict(os.environ, {"RENDER": "1", "FIREBASE_PROJECT_ID": "demo-project"}, clear=False):
            for value in (None, ""):
                if value is None:
                    os.environ.pop("ALLOW_ORIGINS", None)
                else:
                    os.environ["ALLOW_ORIGINS"] = value
                self.assertEqual(main.effective_cors_origins(),
                                 ["https://demo-project.web.app", "https://demo-project.firebaseapp.com"], value)
            os.environ.pop("ALLOW_ORIGINS", None)
            os.environ["FIREBASE_PROJECT_ID"] = "bad/id"          # 이상한 값이면 닫는다
            self.assertEqual(main.effective_cors_origins(), [])

    def test_관리형에서_명시적_출처만_허용한다(self):
        with mock.patch.dict(os.environ, {
            "RENDER": "1",
            "ALLOW_ORIGINS": "https://a.example, https://b.example",
        }, clear=False):
            self.assertEqual(main.effective_cors_origins(), ["https://a.example", "https://b.example"])

    def test_기본값에서는_CORS_와_프록시_경고가_나온다(self):
        with mock.patch.dict(os.environ, {}, clear=False):           # 관리형이 아닌(로컬) 기본값은 '*'
            os.environ.pop("ALLOW_ORIGINS", None); os.environ.pop("RENDER", None); os.environ.pop("K_SERVICE", None)
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
