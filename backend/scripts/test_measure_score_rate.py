"""measure_score_rate 의 분류 규칙 테스트.  실행: python backend/scripts/test_measure_score_rate.py"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from measure_score_rate import classify, is_valid_score, summarize  # noqa: E402


class T(unittest.TestCase):
    def test_valid_score(self):
        self.assertTrue(is_valid_score({"score": 0}))
        self.assertTrue(is_valid_score({"score": 100.0}))
        for bad in (True, False, None, "40", float("nan"), float("inf"), -1, 101):
            self.assertFalse(is_valid_score({"score": bad}), bad)
        self.assertFalse(is_valid_score({"score": 40, "score_discarded": True}))

    def test_classify(self):
        ok = classify(200, {"usable": True, "score": 55, "heard": "x"})
        self.assertTrue(ok["usable"] and ok["valid_score"] and not ok["no_score_with_heard"])
        nos = classify(200, {"usable": True, "score": None, "heard": "x"})
        self.assertTrue(nos["usable"] and not nos["valid_score"] and nos["no_score_with_heard"])
        unusable = classify(200, {"usable": False, "score": 55, "heard": ""})
        self.assertFalse(unusable["usable"] or unusable["valid_score"])   # usable:false 의 점수는 세지 않는다
        self.assertTrue(unusable["heard_empty"])
        boolean = classify(200, {"usable": True, "score": True, "heard": "x"})
        self.assertFalse(boolean["valid_score"])
        disc = classify(200, {"usable": True, "score": None, "score_discarded": True, "heard": "x"})
        self.assertTrue(disc["score_discarded"] and not disc["no_score_with_heard"])
        self.assertTrue(classify(200, {"mock": True, "usable": False})["mock"])
        for st, res, err in ((None, None, "TimeoutError"), (200, None, "invalid JSON"), (429, None, "HTTP 429")):
            c = classify(st, res, err)
            self.assertFalse(c["http_ok"] or c["real"] or c["usable"])

    def test_missing_vs_invalid_score(self):
        for bad in (150, True, "40", float("nan")):
            c = classify(200, {"usable": True, "score": bad, "heard": "x"})
            self.assertFalse(c["no_score_with_heard"], bad)   # 값이 있으나 무효 → 지표 4에 넣지 않는다
            self.assertTrue(c["invalid_score"], bad)
        for missing in ({"usable": True, "heard": "x"}, {"usable": True, "score": None, "heard": "x"}):
            c = classify(200, missing)
            self.assertTrue(c["no_score_with_heard"] and not c["invalid_score"])

    def test_summarize_denominators(self):
        rows = [classify(200, {"usable": True, "score": 50, "heard": "x"}),
                classify(200, {"usable": True, "score": None, "heard": "x"}),
                classify(200, {"usable": False, "heard": ""}),
                classify(None, None, "TimeoutError")]
        s = summarize(rows)
        self.assertEqual(s["1 HTTP 성공 / 전체 요청"], (3, 4))
        self.assertEqual(s["2 usable:true / 실제 응답"], (2, 3))
        self.assertEqual(s["3 유효 score / usable:true"], (1, 2))
        self.assertEqual(s["4 점수 누락(null)+heard 있음 / usable:true"], (1, 2))


if __name__ == "__main__":
    unittest.main()
