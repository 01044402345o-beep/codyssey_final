"""measure_latency 의 집계 함수 테스트.  실행: python backend/scripts/test_measure_latency.py"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from measure_latency import pct, summarize  # noqa: E402


class T(unittest.TestCase):
    def test_pct(self):
        self.assertIsNone(pct([], .5))
        self.assertEqual(pct([5], .95), 5)
        self.assertEqual(pct([1, 2, 3, 4, 100], .5), 3)
        self.assertEqual(pct([1, 2, 3, 4, 100], .95), 100)
        self.assertEqual(pct([3, float("nan"), 1], .5), 3 if False else pct([3, 1], .5))   # NaN 은 무시

    def test_summarize(self):
        s = summarize([10, 20, 30])
        self.assertEqual((s["n"], s["p50"], s["max"]), (3, 20, 30))
        self.assertEqual(summarize([])["p50"], None)


if __name__ == "__main__":
    unittest.main()
