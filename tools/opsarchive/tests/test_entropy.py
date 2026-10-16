"""무작위 값 생성 — OS별 명령 선택·출력 검증·폴백(네트워크 없이 검증한다)."""

from __future__ import annotations

import os
import re
import unittest

from opsarchive import entropy


class DefaultCommandTest(unittest.TestCase):
    def test_windows_uses_dotnet_csprng(self):
        text = entropy.default_command(kind="windows", length=32, encoding="hex")
        self.assertIn("RandomNumberGenerator", text)
        self.assertIn("System.BitConverter", text)

    def test_windows_base64(self):
        text = entropy.default_command(kind="windows", length=16, encoding="base64")
        self.assertIn("ToBase64String", text)
        self.assertIn("Byte[] 16", text)

    def test_posix_prefers_openssl_or_urandom(self):
        text = entropy.default_command(kind="linux", length=32, encoding="hex")
        self.assertTrue("openssl rand -hex 32" in text or "/dev/urandom" in text, text)

    def test_chars_encoding_uses_tr(self):
        self.assertIn("tr -dc", entropy.default_command(kind="linux", encoding="chars"))

    def test_os_kind_is_one_of_the_known_values(self):
        self.assertIn(entropy.os_kind(), ("windows", "macos", "linux", "other"))


class SanitizeTest(unittest.TestCase):
    def test_picks_the_value_line(self):
        self.assertEqual(entropy.sanitize("\n  1a2b3c4d5e6f7788  \n", "hex"), "1a2b3c4d5e6f7788")

    def test_ignores_prompts_and_warnings(self):
        raw = "PS C:\\Users\\seong> [System.BitConverter]...\nWARNING: something\ndeadbeefdeadbeef\n"
        self.assertEqual(entropy.sanitize(raw, "hex"), "deadbeefdeadbeef")

    def test_longest_candidate_wins(self):
        self.assertEqual(entropy.sanitize("ab\nabcdef0123456789\n", "hex"), "abcdef0123456789")

    def test_rejects_wrong_alphabet(self):
        with self.assertRaises(entropy.EntropyError) as caught:
            entropy.sanitize("this-is-not-hex-and-has-dashes", "hex")
        self.assertEqual(caught.exception.code, "empty")

    def test_rejects_short_values(self):
        with self.assertRaises(entropy.EntropyError):
            entropy.sanitize("abcd", "hex")

    def test_bad_encoding(self):
        with self.assertRaises(entropy.EntropyError) as caught:
            entropy.sanitize("abcd1234", "rot13")
        self.assertEqual(caught.exception.code, "bad_encoding")


class RunCommandTest(unittest.TestCase):
    def test_runs_a_command_and_returns_the_value(self):
        if os.name == "nt":
            value = entropy.run_command(entropy.default_command(kind="windows"),
                                        encoding="hex")      # 이 PC 의 실제 기본 명령
            self.assertGreaterEqual(len(value), 32)
        else:
            self.assertEqual(entropy.run_command("printf 'cafebabe0123456789'"), "cafebabe0123456789")

    def test_failing_command_raises(self):
        with self.assertRaises(entropy.EntropyError):
            entropy.run_command("exit 1" if os.name != "nt" else "exit /b 1")

    def test_empty_command_raises(self):
        with self.assertRaises(entropy.EntropyError):
            entropy.run_command("   ")


class GenerateTest(unittest.TestCase):
    def test_uses_the_command_when_it_works(self):
        # 셸을 명시적으로 경유하므로, 명령 문자열은 그 셸의 문법이어야 한다(PowerShell / sh).
        fixed = "0123456789abcdef0123456789abcdef"
        command = ("Write-Output '%s'" % fixed) if os.name == "nt" else ("printf '%s'" % fixed)
        result = entropy.generate(command=command, encoding="hex")
        self.assertEqual(result["source"], "command")
        self.assertEqual(result["value"], fixed)
        self.assertEqual(result["note"], "")

    def test_falls_back_and_says_so(self):
        result = entropy.generate(command="exit 1" if os.name != "nt" else "exit /b 1", encoding="hex")
        self.assertEqual(result["source"], "fallback")
        self.assertIn("대체", result["note"])
        self.assertGreaterEqual(len(result["value"]), 32)      # 32바이트 hex

    def test_empty_command_falls_back_with_note(self):
        result = entropy.generate(command="", encoding="hex")
        self.assertEqual(result["source"], "fallback")
        self.assertIn("비어 있어", result["note"])

    def test_no_fallback_when_disallowed(self):
        with self.assertRaises(entropy.EntropyError):
            entropy.generate(command="exit 1", encoding="hex", allow_fallback=False)

    def test_default_command_per_os_is_used(self):
        result = entropy.generate(length=16, encoding="hex")
        self.assertIn(result["source"], ("command", "fallback"))
        self.assertTrue(result["command"])

    def test_values_are_unique(self):
        values = {entropy.generate(command="")["value"] for _ in range(5)}
        self.assertEqual(len(values), 5)
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]+", v) for v in values))


if __name__ == "__main__":
    unittest.main()
