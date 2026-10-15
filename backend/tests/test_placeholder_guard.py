"""자리표시자 검증. 화면과 음성이 같은 문자열을 쓰도록 생성 단계에서 막는다.

실행: cd backend && python -m unittest tests.test_placeholder_guard
"""
from __future__ import annotations

import unittest
from pathlib import Path

from app import validators

CFG = {
    "category_id": "restaurant",
    "situations": [{"situation_id": "ask_direction", "required_keywords": ["how"]}],
}
PATTERNS: dict = {}


class PlaceholderGuard(unittest.TestCase):
    def codes(self, en: str) -> list[str]:
        return [i["code"] for i in validators.validate_sentence(
            {"en": en, "situation_id": "ask_direction"}, CFG, PATTERNS)]

    def test_allowed_placeholders_pass(self):
        self.assertEqual(self.codes("How do I get to [destination]?"), [])
        self.assertEqual(self.codes("I have a reservation under [name]."), [])
        self.assertEqual(self.codes("Does this train stop at [destination]?"), [])

    def test_unknown_placeholder_blocks(self):
        self.assertIn("unknown_placeholder", self.codes("It costs [price] dollars."))

    def test_determiner_before_placeholder_blocks(self):
        self.assertIn("determiner_before_placeholder", self.codes("How do I get to your [destination]?"))
        self.assertIn("determiner_before_placeholder", self.codes("This is my [name]."))

    def test_these_are_blocking_not_warning(self):
        issues = validators.validate_sentence(
            {"en": "How do I get to your [destination]?", "situation_id": "ask_direction"}, CFG, PATTERNS)
        self.assertTrue(validators.has_blocking(issues))

    def test_plain_text_without_placeholder_passes(self):
        self.assertEqual(self.codes("Where is the restroom?"), [])


class AppKeepsOneExpansionPoint(unittest.TestCase):
    """app.js 가 자리표시자를 한 곳에서만 펼치는지 소스로 고정한다.

    화면용과 음성용이 각각 펼치면 반드시 어긋난다(2차 피드백: 듣기의 your).
    """

    def setUp(self):
        root = Path(__file__).resolve().parents[2]
        self.src = root / "mockup" / "app.js"

    def test_single_expansion_helper_exists(self):
        s = self.src.read_text(encoding="utf-8")
        self.assertIn("const slotText =", s)
        self.assertIn("const DETERMINER =", s)

    def test_only_slot_text_expands_the_placeholders(self):
        s = self.src.read_text(encoding="utf-8")
        self.assertEqual(s.count("(name|destination)"), 1,
                         "플레이스홀더를 펼치는 곳이 여러 곳입니다")

    def test_tts_only_strips_brackets(self):
        s = self.src.read_text(encoding="utf-8")
        line = next((l for l in s.splitlines() if l.startswith("const ttsText =")), None)
        self.assertIsNotNone(line, "ttsText 정의를 못 찾음")
        self.assertNotIn("your name", line)
        self.assertNotIn("your destination", line)
        self.assertIn("replace", line)

    def test_speak_expands_with_the_same_helper(self):
        s = self.src.read_text(encoding="utf-8")
        self.assertIn("ttsText(slotText(text))", s)


if __name__ == "__main__":
    unittest.main()
