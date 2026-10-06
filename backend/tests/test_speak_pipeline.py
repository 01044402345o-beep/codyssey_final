"""말하기 판정 파이프라인: 받아쓰기(AI, 목표 문장 모름) → 판정(코드) → 피드백(AI, 오디오 없음).

배포 실측에서 목표 문장을 함께 준 단일 호출은 무음에도 목표 문장을 들었다고 답했다(10/10, 95~100점).
이 테스트는 AI 권한을 최소로 둔 구조가 지켜지는지 확인한다.
"""
from __future__ import annotations

import json
import os
import unittest
from types import SimpleNamespace
from typing import Any, Callable

from fastapi.testclient import TestClient

from app import gemini as ai
from app import main
from app import speech_compare as compare

TARGET = "I have a peanut allergy."
MODELS = [SimpleNamespace(name="models/gemini-2.5-flash", supported_actions=["generateContent"])]


class Calls:
    """generate_content 호출을 기록한다. 오디오가 있으면 받아쓰기, 글만 있으면 피드백 호출이다."""

    def __init__(self, transcribe: Callable[[int], str], feedback: Callable[[int], str]) -> None:
        self.transcribe, self.feedback = transcribe, feedback
        self.transcribe_texts: list[str] = []
        self.feedback_texts: list[str] = []

    def list(self) -> list[Any]:
        return MODELS

    def generate_content(self, *, model: str, contents: Any, config: Any) -> SimpleNamespace:
        if isinstance(contents, list):          # [오디오 Part, 프롬프트]
            texts = [c for c in contents if isinstance(c, str)]
            self.transcribe_texts.append("\n".join(texts))
            return SimpleNamespace(text=self.transcribe(len(self.transcribe_texts)))
        self.feedback_texts.append(contents)    # 글만
        return SimpleNamespace(text=self.feedback(len(self.feedback_texts)))


def heard(text: str) -> Callable[[int], str]:
    return lambda _n: json.dumps({"heard": text})


def feedback_ok(_n: int) -> str:
    return json.dumps({"fix_one": "좋아요", "tip": "식당에서 주문 전에 말해요", "score": 3})


def fail(_n: int) -> str:
    raise ConnectionError("down")


class SpeakPipelineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = dict(os.environ)
        os.environ["GEMINI_API_KEY"] = "test-key"
        for k in ("AI_MIN_ATTEMPTS", "GEMINI_MODEL"):
            os.environ.pop(k, None)
        ai._sleep = lambda _s: None
        ai.reset_cache()
        main._hits.clear()
        self.http = TestClient(main.app)

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self.env)
        ai._sleep = __import__("time").sleep
        ai._client_factory = None
        ai.reset_cache()

    def run_speak(self, transcribe: Callable[[int], str], feedback: Callable[[int], str] = feedback_ok,
                  situation: str = "알레르기·재료 고지") -> tuple[dict[str, Any], Calls]:
        calls = Calls(transcribe, feedback)
        ai._client_factory = lambda: SimpleNamespace(models=calls)
        r = self.http.post("/speak-check", data={"target": TARGET, "situation": situation},
                           files={"file": ("a.webm", b"\x00" * 200, "audio/webm")})
        self.assertEqual(r.status_code, 200)
        return r.json(), calls

    # ---- 최소 권한: 받아쓰기 AI 는 목표 문장을 모른다
    def test_transcription_prompt_never_contains_target(self) -> None:
        _d, calls = self.run_speak(heard(TARGET))
        self.assertEqual(len(calls.transcribe_texts), 1)
        prompt = calls.transcribe_texts[0].lower()
        for w in ("peanut", "allergy", "i have a"):
            self.assertNotIn(w, prompt)
        self.assertNotIn("target", prompt)

    # ---- 무음: 코드가 막고, 피드백 AI 는 부르지 않는다
    def test_silence_returns_no_score_and_skips_feedback(self) -> None:
        for raw in ("", "   ", "...", "[silence]", "(no speech)", "Silence.", "[inaudible]", "♪"):
            with self.subTest(raw=raw):
                d, calls = self.run_speak(heard(raw))
                self.assertFalse(d["usable"])
                self.assertIsNone(d["score"])
                self.assertEqual((d["heard"], d["fix_one"], d["tip"], d["issues"]), ("", "", "", []))
                self.assertEqual(calls.feedback_texts, [])
                self.assertEqual(d["attempts"], 1)   # 무음은 실패가 아니라 결과다 — 재시도하지 않는다

    # ---- 점수는 코드가 정하고, 피드백 AI 는 바꿀 수 없다
    def test_score_computed_by_code_and_feedback_cannot_override(self) -> None:
        d, calls = self.run_speak(heard("I have a peanut allergy"))
        self.assertTrue(d["usable"])
        self.assertEqual(d["score"], 100)
        self.assertEqual(d["score_kind"], "word_match")
        self.assertEqual(d["fix_one"], "좋아요")           # 피드백 문장은 AI
        self.assertNotEqual(d["score"], 3)                 # AI 가 준 score 는 버림
        self.assertEqual(d["feedback"]["source"], "ai")

    def test_feedback_call_is_text_only_with_context(self) -> None:
        _d, calls = self.run_speak(heard("I have a allergy"), situation="알레르기·재료 고지")
        self.assertEqual(len(calls.feedback_texts), 1)
        p = calls.feedback_texts[0]
        self.assertIn("알레르기·재료 고지", p)   # 상황 맥락
        self.assertIn(TARGET, p)
        self.assertIn('"missing": [\n      "peanut"', p)
        self.assertIn("cannot change it", p)

    def test_wrong_sentence_gets_low_score_and_diff(self) -> None:
        d, _ = self.run_speak(heard("where is the subway station"))
        self.assertTrue(d["usable"])
        self.assertLess(d["score"], 30)
        self.assertTrue(d["diff"]["replaced"] or d["diff"]["missing"])

    def test_missing_word_is_reported(self) -> None:
        d, _ = self.run_speak(heard("I have a allergy"))
        self.assertEqual(d["diff"]["missing"], ["peanut"])
        self.assertIn({"word": "peanut", "note": "빠짐"}, d["issues"])
        self.assertEqual(d["score"], round(100 * 2 * 4 / 9))

    # ---- 피드백 AI 가 끝내 실패해도 점수는 유효, 문구만 사실 기반 문장 틀
    def test_feedback_failure_falls_back_to_template_after_floor(self) -> None:
        d, calls = self.run_speak(heard("I have a allergy"), feedback=fail)
        self.assertTrue(d["usable"])
        self.assertEqual(len(calls.feedback_texts), 30)       # 피드백 호출도 최소 30회 규칙
        self.assertEqual(d["feedback"]["source"], "template")
        self.assertIn("peanut", d["fix_one"])

    def test_bad_feedback_json_is_retried(self) -> None:
        fb = lambda n: "nope" if n < 3 else json.dumps({"fix_one": "x", "tip": "y"})
        d, calls = self.run_speak(heard(TARGET), feedback=fb)
        self.assertEqual(d["feedback"], {"source": "ai", "attempts": 3, "model": "gemini-2.5-flash"})

    # ---- 받아쓰기 실패
    def test_transcription_failure_after_floor(self) -> None:
        d, calls = self.run_speak(fail)
        self.assertFalse(d["usable"])
        self.assertIsNone(d["score"])
        self.assertEqual(d["attempts"], 30)
        self.assertEqual(calls.feedback_texts, [])

    def test_non_string_heard_is_retried(self) -> None:
        tr = lambda n: json.dumps({"heard": None}) if n < 2 else json.dumps({"heard": TARGET})
        d, _ = self.run_speak(tr)
        self.assertEqual((d["usable"], d["attempts"], d["score"]), (True, 2, 100))


class CompareTest(unittest.TestCase):
    def test_words_normalization(self) -> None:
        self.assertEqual(compare.words("I'd like a Coffee, please!"), ["i'd", "like", "a", "coffee", "please"])
        self.assertEqual(compare.words("I’m"), ["i'm"])

    def test_placeholder(self) -> None:
        for t in ("", "  ", "...", "♪♪", "[silence]", "(inaudible)", "No speech.", "unintelligible"):
            self.assertTrue(compare.is_placeholder(t), t)
        for t in ("Nothing else, thanks.", "None", "I have a peanut allergy.", "no"):
            self.assertFalse(compare.is_placeholder(t), t)

    def test_compare_scores(self) -> None:
        self.assertEqual(compare.compare(TARGET, "i have a peanut allergy")["score"], 100)
        c = compare.compare(TARGET, "I have a cashew allergy")
        self.assertEqual(c["replaced"], [["peanut", "cashew"]])
        self.assertEqual(c["score"], 80)
        c = compare.compare(TARGET, "I have a peanut allergy please")
        self.assertEqual(c["extra"], ["please"])
        self.assertLess(c["score"], 100)
        self.assertIsNone(compare.compare("", "hello")["score"])
        self.assertEqual(compare.compare(TARGET, "hello")["score"], 0)

    def test_template_feedback_states_facts(self) -> None:
        fix, tip = compare.template_feedback(compare.compare(TARGET, "I have a allergy"))
        self.assertIn("peanut", fix)
        self.assertTrue(tip)


if __name__ == "__main__":
    unittest.main()
