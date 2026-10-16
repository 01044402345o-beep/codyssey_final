"""플랫폼 접근 로그 증인 + TSA 스탬프 id — 오프라인 계산만 검증한다(네트워크 없음)."""

from __future__ import annotations

import unittest

from opsarchive import witness


class CountRequestsTest(unittest.TestCase):
    def test_counts_only_the_target_path(self):
        logs = "\n".join([
            'INFO POST /account/erase 200 12ms',
            'INFO GET /user/state 200 3ms',
            'INFO POST /account/erase 503 40ms',
            'INFO POST /diagnostics/withdraw 200 2ms',
        ])
        self.assertEqual(witness.count_requests(logs), 2)

    def test_ignores_other_methods_on_same_path(self):
        logs = "\n".join(['POST /account/erase 200', 'GET /account/erase 405'])
        self.assertEqual(witness.count_requests(logs), 1)
        self.assertEqual(witness.count_requests(logs, method=""), 2)

    def test_empty_logs(self):
        self.assertEqual(witness.count_requests(""), 0)
        self.assertEqual(witness.count_requests(None or ""), 0)


class CompareTest(unittest.TestCase):
    def test_equal_counts_are_ok(self):
        result = witness.compare(observed=3, attempts=3)
        self.assertTrue(result["ok"])
        self.assertEqual(result["verdict"], "ok")

    def test_fewer_attempts_than_requests_is_suspicious(self):
        result = witness.compare(observed=5, attempts=2)
        self.assertFalse(result["ok"])
        self.assertEqual(result["verdict"], "missing_attempts")
        self.assertEqual(result["diff"], 3)
        self.assertIn("생략", result["note"])

    def test_tolerance_absorbs_double_logged_lines(self):
        result = witness.compare(observed=6, attempts=3, tolerance=3)
        self.assertTrue(result["ok"])

    def test_more_attempts_than_logs_is_stale_logs(self):
        result = witness.compare(observed=1, attempts=4)
        self.assertFalse(result["ok"])
        self.assertEqual(result["verdict"], "stale_logs")

    def test_no_logs_visible_is_not_treated_as_omission(self):
        """로그가 비어 있는 것과 '요청이 없었다'는 다르다 — 로그 쪽을 믿지 않는다."""
        result = witness.compare(observed=0, attempts=2)
        self.assertFalse(result["ok"])
        self.assertEqual(result["verdict"], "no_logs_visible")

    def test_stamp_id_is_the_challenge_hash(self):
        import hashlib
        value = witness.stamp_id("AB" * 16)
        self.assertEqual(value, hashlib.sha256(("ab" * 16).encode()).hexdigest())
        self.assertNotIn("ab" * 16, value)          # 원문 챌린지를 그대로 쓰지 않는다


if __name__ == "__main__":
    unittest.main()
