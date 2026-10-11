"""GEMINI_THINKING_BUDGET 스위치와 /generate elapsed_ms.  실행: cd backend && python -m unittest discover -s tests -t ."""
import os
import unittest
from types import SimpleNamespace
from unittest import mock

from fastapi.testclient import TestClient

from app import gemini as ai
from app import main


class Capture:
    def __init__(self):
        self.configs = []

    def generate_content(self, *, model, contents, config):
        self.configs.append(config)
        return SimpleNamespace(text='{"ok": true}')


def thinking_of(model, env):
    cap = Capture()
    with mock.patch.dict(os.environ, env, clear=False):
        if "GEMINI_THINKING_BUDGET" not in env:
            os.environ.pop("GEMINI_THINKING_BUDGET", None)
        ai.generate_text(SimpleNamespace(models=cap), model, "x", temperature=0.7)
    tc = cap.configs[0].thinking_config
    return None if tc is None else tc.thinking_budget


class T(unittest.TestCase):
    def test_unset_keeps_model_default(self):
        self.assertIsNone(thinking_of("gemini-flash-latest", {}))

    def test_budget_applies_to_flash(self):
        self.assertEqual(thinking_of("gemini-flash-latest", {"GEMINI_THINKING_BUDGET": "0"}), 0)
        self.assertEqual(thinking_of("gemini-2.5-flash-lite", {"GEMINI_THINKING_BUDGET": "512"}), 512)

    def test_not_applied_to_pro_or_bad_value(self):
        # pro 는 생각을 끌 수 없다(예산 0 = 요청 오류) — 동적 선택이 pro 로 넘어가도 실패하지 않게
        self.assertIsNone(thinking_of("gemini-2.5-pro", {"GEMINI_THINKING_BUDGET": "0"}))
        self.assertIsNone(thinking_of("gemini-flash-latest", {"GEMINI_THINKING_BUDGET": "abc"}))
        self.assertEqual(thinking_of("gemini-flash-latest", {"GEMINI_THINKING_BUDGET": "-5"}), 0)

    def test_generate_reports_elapsed_and_setting(self):
        main._hits.clear()
        with mock.patch.dict(os.environ, {"GEMINI_THINKING_BUDGET": "0"}, clear=False):
            os.environ.pop("GEMINI_API_KEY", None)
            d = TestClient(main.app).post("/generate", json={"category_id": "restaurant"}).json()
        self.assertIsInstance(d["elapsed_ms"], int)
        self.assertGreaterEqual(d["elapsed_ms"], 0)
        self.assertEqual(d["thinking_budget"], "0")


if __name__ == "__main__":
    unittest.main()
