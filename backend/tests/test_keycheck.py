"""키 점검 — 약한 키·같은 키 재사용을 통과시키지 않는지."""
import base64
import unittest

from app import keycheck


def b64(n: int, seed: int = 0) -> str:
    return base64.urlsafe_b64encode(bytes((i * 7 + seed) % 256 for i in range(n))).decode().rstrip("=")


class KeycheckTest(unittest.TestCase):
    def test_난수_32바이트는_통과한다(self):
        result = keycheck.check({"EVIDENCE_SIGN_KEY": b64(32)})
        self.assertTrue(result["ok"])
        self.assertEqual(result["keys"]["EVIDENCE_SIGN_KEY"]["bytes"], 32)

    def test_설정이_없으면_오류가_아니다(self):
        result = keycheck.check({})
        self.assertTrue(result["ok"])
        self.assertEqual(result["keys"], {})

    def test_짧은_키는_잡는다(self):
        result = keycheck.check({"EVIDENCE_SIGN_KEY": b64(16)})
        self.assertFalse(result["ok"])
        self.assertTrue(any(item["code"] == "too_short" for item in result["issues"]))

    def test_같은_바이트_반복은_잡는다(self):
        result = keycheck.check({"EVIDENCE_SIGN_KEY": base64.urlsafe_b64encode(b"a" * 32).decode().rstrip("=")})
        self.assertTrue(any(item["code"] == "low_diversity" for item in result["issues"]))

    def test_한_비밀을_두_역할에_쓰면_잡는다(self):
        value = b64(32, seed=3)
        result = keycheck.check({"EVIDENCE_SIGN_KEY": value, "EVIDENCE_PUBKEY": value})
        self.assertFalse(result["ok"])
        self.assertEqual([item["code"] for item in result["issues"]], ["reused"])

    def test_요약에_비밀값이_들어가지_않는다(self):
        value = b64(32, seed=5)
        result = keycheck.check({"EVIDENCE_SIGN_KEY": value})
        self.assertNotIn(value, str(result))


if __name__ == "__main__":
    unittest.main()
