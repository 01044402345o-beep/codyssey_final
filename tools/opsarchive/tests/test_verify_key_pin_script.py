"""CI 검증 스크립트(`.github/scripts/verify_key_pin.py`)를 실제로 실행해 규칙을 고정한다.

이 스크립트는 CI 전용 사본이라 `opsarchive.pins.compare` 와 규칙이 갈라질 수 있다.
그래서 여기서 **실제 프로세스로** 돌려 armed/불일치/세대 판정을 확인한다.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
SCRIPT = os.path.join(ROOT, ".github", "scripts", "verify_key_pin.py")


class VerifyScriptTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="opsarchive-ci-pin-")

    def _run(self, pin: dict, health: dict | None) -> subprocess.CompletedProcess:
        pin_path = os.path.join(self.dir, "pin.json")
        with open(pin_path, "w", encoding="utf-8") as fh:
            json.dump(pin, fh)
        argv = [sys.executable, SCRIPT, pin_path]
        if health is not None:
            health_path = os.path.join(self.dir, "health.json")
            with open(health_path, "w", encoding="utf-8") as fh:
                json.dump(health, fh)
            argv += ["--health-file", health_path]
        return subprocess.run(argv, capture_output=True, text=True,  # noqa: S603
                              encoding="utf-8", errors="replace")

    def test_unarmed_passes_with_warning(self):
        done = self._run({"schema": 1, "armed": False}, {"evidence": {}})
        self.assertEqual(done.returncode, 0)
        self.assertIn("미활성", done.stdout)

    def test_matching_pin_passes(self):
        shared = {"fingerprint": "ab" * 32, "key_id": "abcd1234", "generation": 2}
        done = self._run({"schema": 1, "armed": True, "fingerprint_sha256": "ab" * 32,
                          "generation": 2, "health_url": "https://example.test"},
                         {"evidence": shared})
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_mismatch_fails(self):
        done = self._run({"schema": 1, "armed": True, "fingerprint_sha256": "ab" * 32,
                          "generation": 2, "health_url": "https://example.test"},
                         {"evidence": {"fingerprint": "cd" * 32, "generation": 2}})
        self.assertEqual(done.returncode, 1)
        self.assertIn("fingerprint_mismatch", done.stdout)

    def test_missing_evidence_fails(self):
        done = self._run({"schema": 1, "armed": True, "fingerprint_sha256": "ab" * 32,
                          "generation": 1, "health_url": "https://example.test"}, {"ok": True})
        self.assertEqual(done.returncode, 1)
        self.assertIn("health_missing_evidence", done.stdout)

    def test_generation_regression_fails(self):
        done = self._run({"schema": 1, "armed": True, "fingerprint_sha256": "ab" * 32,
                          "generation": 3, "health_url": "https://example.test"},
                         {"evidence": {"fingerprint": "ab" * 32, "generation": 2}})
        self.assertEqual(done.returncode, 1)
        self.assertIn("generation_lower", done.stdout)


if __name__ == "__main__":
    unittest.main()
