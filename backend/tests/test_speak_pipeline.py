"""말하기 판정 파이프라인 — Silero VAD(코드) → 전용 STT(목표 문장 모름) → 환각 필터·판정(코드) → 피드백(AI, 오디오 없음).

배포 실측에서 녹음+목표 문장을 함께 준 LLM 은 무음에도 목표 문장을 들었다고 답했다(10/10, 95~100점).
transcribe_app 방식(신경망 VAD + 전용 STT + no_speech 필터)이 지켜지는지, AI 권한이 최소인지 확인한다.
STT 는 가짜 HTTP 세션으로 실제 요청 수·본문을 기록한다(네트워크·키 없이 돈다).
"""
from __future__ import annotations

import io
import json
import os
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import numpy as np
from fastapi.testclient import TestClient

from app import gemini as ai
from app import main
from app import speech_compare as compare
from app import stt_providers as stt

TARGET = "I have a peanut allergy."
GOOD = (Path(__file__).parent / "fixtures" / "good.wav").read_bytes()
GEMINI_MODELS = [SimpleNamespace(name="models/gemini-2.5-flash", supported_actions=["generateContent"])]
WHISPER_IDS = ["gpt-4o-transcribe", "whisper-large-v3-turbo", "llama-3.3-70b", "whisper-large-v3"]


def wav_of(x: np.ndarray) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    return buf.getvalue()


SILENCE = wav_of(np.zeros(16000))
LOUD_NOISE = wav_of(np.random.default_rng(1).normal(0, 0.3, 32000))


class Resp:
    def __init__(self, status: int, payload: Any) -> None:
        self.status_code, self._payload = status, payload
        self.text = json.dumps(payload) if not isinstance(payload, str) else payload

    def json(self) -> Any:
        return self._payload


def stt_ok(text: str, nsp: float = 0.01, lp: float = -0.2) -> dict[str, Any]:
    return {"text": text, "language": "english", "duration": 1.3,
            "segments": [{"text": text, "no_speech_prob": nsp, "avg_logprob": lp, "compression_ratio": 1.0}]}


class FakeSTT:
    """OpenAI 호환(Groq·OpenAI)과 AssemblyAI 요청을 받아 기록한다."""

    def __init__(self, transcribe: dict[str, Callable[[int], Resp]]) -> None:
        self.transcribe = transcribe
        self.posts: list[dict[str, Any]] = []
        self.calls: dict[str, int] = {}

    def _pid(self, url: str) -> str:
        return "groq" if "groq" in url else "openai" if "openai.com" in url else "assemblyai"

    def get(self, url: str, headers: Any = None, timeout: Any = None) -> Resp:
        assert timeout, "모든 요청에 timeout 이 있어야 한다"
        if url.endswith("/models"):
            return Resp(200, {"data": [{"id": i} for i in WHISPER_IDS]})
        return Resp(200, {"status": "completed", "text": self.aai_text, "speech_model": "universal"})  # AssemblyAI 폴링

    def post(self, url: str, headers: Any = None, timeout: Any = None, **kw: Any) -> Resp:
        assert timeout, "모든 요청에 timeout 이 있어야 한다"
        pid = self._pid(url)
        self.posts.append({"pid": pid, "url": url, **kw})
        if url.endswith("/upload"):
            return Resp(200, {"upload_url": "https://cdn/x"})
        if url.endswith("/transcript"):
            return Resp(200, {"id": "job1"})
        self.calls[pid] = self.calls.get(pid, 0) + 1
        r = self.transcribe[pid](self.calls[pid])
        return r

    aai_text = ""


class GeminiFake:
    def __init__(self, feedback: Callable[[int], str]) -> None:
        self.feedback = feedback
        self.texts: list[Any] = []

    def list(self) -> list[Any]:
        return GEMINI_MODELS

    def generate_content(self, *, model: str, contents: Any, config: Any) -> SimpleNamespace:
        self.texts.append(contents)
        return SimpleNamespace(text=self.feedback(len(self.texts)))


def fb_ok(_n: int) -> str:
    return json.dumps({"fix_one": "좋아요", "tip": "주문 전에 말해요", "score": 3})


class Base(unittest.TestCase):
    KEYS = ("GROQ_API_KEY", "OPENAI_API_KEY", "ASSEMBLYAI_API_KEY", "ASSEMBLY_AI_API_KEY", "GEMINI_API_KEY",
            "AI_MIN_ATTEMPTS", "GROQ_STT_MODEL", "OPENAI_STT_MODEL", "GEMINI_MODEL")

    def setUp(self) -> None:
        self.env = dict(os.environ)
        for k in self.KEYS:
            os.environ.pop(k, None)
        os.environ["GEMINI_API_KEY"] = "g"
        ai._sleep = lambda _s: None
        ai.reset_cache()
        stt.reset_cache()
        main._hits.clear()
        self.http = TestClient(main.app)

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self.env)
        ai._sleep = __import__("time").sleep
        ai._client_factory = None
        stt._session_factory = None
        ai.reset_cache()
        stt.reset_cache()

    def install(self, transcribe: dict[str, Callable[[int], Resp]], keys: tuple[str, ...] = ("GROQ_API_KEY",),
                feedback: Callable[[int], str] = fb_ok) -> tuple[FakeSTT, GeminiFake]:
        for k in keys:
            os.environ[k] = "k"
        fake = FakeSTT(transcribe)
        gem = GeminiFake(feedback)
        stt._session_factory = lambda: fake
        ai._client_factory = lambda: SimpleNamespace(models=gem)
        return fake, gem

    def speak(self, audio: bytes, situation: str = "알레르기·재료 고지") -> tuple[int, dict[str, Any]]:
        r = self.http.post("/speak-check", data={"target": TARGET, "situation": situation},
                           files={"file": ("a.wav", audio, "audio/wav")})
        return r.status_code, r.json()


class SilenceGateTest(Base):
    """말소리가 없으면 외부 API 를 하나도 부르지 않는다 — 데시벨이 아니라 Silero 판정."""

    def test_silence_and_loud_noise_call_no_api(self) -> None:
        for name, audio in (("silence", SILENCE), ("loud_noise", LOUD_NOISE)):
            with self.subTest(name):
                fake, gem = self.install({"groq": lambda n: Resp(200, stt_ok(TARGET))})
                code, d = self.speak(audio)
                self.assertEqual(code, 200)
                self.assertFalse(d["usable"])
                self.assertIsNone(d["score"])
                self.assertEqual(d["vad"]["speech_sec"], 0)
                self.assertEqual(fake.posts, [])        # STT 호출 0회
                self.assertEqual(gem.texts, [])         # 피드백 호출 0회

    def test_vad_runs_without_any_key(self) -> None:
        code, d = self.speak(SILENCE)
        self.assertEqual((code, d["usable"]), (200, False))
        self.assertNotIn("mock", d)                     # 목업이 아니라 VAD 판정
        self.assertIn("음성이 인식되지 않았습니다", d["reason"])

    def test_speech_without_stt_key_is_mock(self) -> None:
        code, d = self.speak(GOOD)
        self.assertTrue(d["mock"])
        self.assertGreater(d["vad"]["speech_sec"], 0.8)

    def test_garbage_audio_is_400(self) -> None:
        code, _ = self.speak(b"not audio" * 100)
        self.assertEqual(code, 400)


class SttTest(Base):
    def test_request_has_no_target_and_only_speech_audio(self) -> None:
        fake, _ = self.install({"groq": lambda n: Resp(200, stt_ok(TARGET))})
        from app import speech_vad as vad
        self.speak(wav_of(np.concatenate([np.zeros(32000), vad.decode(GOOD), np.zeros(32000)])))
        post = [p for p in fake.posts if p["url"].endswith("/audio/transcriptions")][0]
        sent = post["data"]
        self.assertEqual(set(sent), {"model", "response_format", "language", "temperature"})
        self.assertEqual((sent["response_format"], sent["language"], sent["temperature"]), ("verbose_json", "en", "0"))
        blob = json.dumps(sent).lower()
        for w in ("peanut", "allergy", "prompt"):
            self.assertNotIn(w, blob)
        name, wav, mime = post["files"]["file"]
        with wave.open(io.BytesIO(wav)) as w:
            self.assertLess(w.getnframes() / 16000, 2.5)       # 앞뒤 2초 무음은 보내지 않음

    def test_model_chosen_dynamically_whisper_only(self) -> None:
        fake, _ = self.install({"groq": lambda n: Resp(200, stt_ok(TARGET))})
        _, d = self.speak(GOOD)
        self.assertEqual(d["stt"]["provider"], "groq")
        self.assertEqual(d["model"], "whisper-large-v3")       # turbo·gpt-4o-transcribe·llama 보다 앞
        self.assertEqual(stt.cached_models()["groq"], ["whisper-large-v3", "whisper-large-v3-turbo"])

    def test_preferred_model_env(self) -> None:
        os.environ["GROQ_STT_MODEL"] = "whisper-large-v3-turbo"
        self.install({"groq": lambda n: Resp(200, stt_ok(TARGET))})
        _, d = self.speak(GOOD)
        self.assertEqual(d["model"], "whisper-large-v3-turbo")

    def test_success_scored_by_code(self) -> None:
        _, gem = self.install({"groq": lambda n: Resp(200, stt_ok("I have a peanut allergy"))})
        _, d = self.speak(GOOD)
        self.assertTrue(d["usable"])
        self.assertEqual((d["score"], d["score_kind"]), (100, "word_match"))
        self.assertEqual(d["fix_one"], "좋아요")            # 문장은 AI
        self.assertEqual(len(gem.texts), 1)
        self.assertIsInstance(gem.texts[0], str)             # 피드백은 글만
        self.assertIn("알레르기·재료 고지", gem.texts[0])
        self.assertNotIn("score\": 3", json.dumps(d))        # AI 가 준 점수는 버림

    def test_no_gemini_key_uses_template_feedback(self) -> None:
        os.environ.pop("GEMINI_API_KEY")
        _, gem = self.install({"groq": lambda n: Resp(200, stt_ok("I have a allergy"))})
        os.environ.pop("GEMINI_API_KEY", None)
        _, d = self.speak(GOOD)
        self.assertTrue(d["usable"])
        self.assertEqual(d["feedback"]["source"], "template")
        self.assertIn("peanut", d["fix_one"])
        self.assertEqual(gem.texts, [])


class HallucinationFilterTest(Base):
    def test_high_no_speech_prob_dropped_then_no_speech(self) -> None:
        _, gem = self.install({"groq": lambda n: Resp(200, stt_ok(TARGET, nsp=0.9))})
        _, d = self.speak(GOOD)
        self.assertFalse(d["usable"])
        self.assertEqual(d["dropped_segments"][0]["reason"], "no_speech_prob")
        self.assertEqual(d["heard_raw"], TARGET)
        self.assertEqual(gem.texts, [])

    def test_whisper_default_rule(self) -> None:
        self.install({"groq": lambda n: Resp(200, stt_ok(TARGET, nsp=0.7, lp=-1.5))})
        _, d = self.speak(GOOD)
        self.assertEqual(d["dropped_segments"][0]["reason"], "no_speech_and_low_logprob")

    def test_known_phrase_dropped(self) -> None:
        self.install({"groq": lambda n: Resp(200, stt_ok("Thank you for watching!"))})
        _, d = self.speak(GOOD)
        self.assertFalse(d["usable"])
        self.assertEqual(d["dropped_segments"][0]["reason"], "known_phrase")

    def test_mixed_segments_keep_real_speech(self) -> None:
        payload = {"text": "I have a peanut allergy. Thank you for watching.", "segments": [
            {"text": "I have a peanut allergy.", "no_speech_prob": 0.02, "avg_logprob": -0.1},
            {"text": "Thank you for watching.", "no_speech_prob": 0.3, "avg_logprob": -0.4}]}
        self.install({"groq": lambda n: Resp(200, payload)})
        _, d = self.speak(GOOD)
        self.assertEqual((d["heard"], d["score"]), ("I have a peanut allergy.", 100))

    def test_missing_signal_fields_skip_numeric_rules(self) -> None:
        self.install({"groq": lambda n: Resp(200, {"text": TARGET, "segments": [{"text": TARGET}]})})
        _, d = self.speak(GOOD)
        self.assertTrue(d["usable"])

    def test_filter_unit(self) -> None:
        self.assertEqual(compare.filter_segments("Thank you for watching", []), ("", [{"text": "Thank you for watching", "reason": "known_phrase"}]))
        self.assertEqual(compare.filter_segments("Thank you.", [])[0], "Thank you.")   # 학습 문장일 수 있어 남김
        self.assertIsNone(compare.hallucination_reason("hi", 0.6, -1.0))                 # 경계값은 남김
        self.assertEqual(compare.hallucination_reason("hi", 0.86, None), "no_speech_prob")


class ProviderChainTest(Base):
    def test_groq_floor_then_openai(self) -> None:
        fake, _ = self.install({"groq": lambda n: Resp(503, "busy"),
                                "openai": lambda n: Resp(200, stt_ok(TARGET))},
                               keys=("GROQ_API_KEY", "OPENAI_API_KEY"))
        _, d = self.speak(GOOD)
        self.assertEqual(fake.calls, {"groq": 30, "openai": 1})
        self.assertEqual((d["stt"]["provider"], d["stt"]["skipped_providers"]), ("openai", ["groq"]))
        self.assertEqual(d["attempts"], 31)
        self.assertTrue(d["usable"])

    def test_all_providers_fail(self) -> None:
        fake, gem = self.install({"groq": lambda n: Resp(500, "x"), "openai": lambda n: Resp(429, "x")},
                                 keys=("GROQ_API_KEY", "OPENAI_API_KEY"))
        _, d = self.speak(GOOD)
        self.assertFalse(d["usable"])
        self.assertEqual((d["failed_at"], d["attempts"]), ("stt", 60))
        self.assertEqual(gem.texts, [])

    def test_unconfigured_provider_skipped(self) -> None:
        fake, _ = self.install({"openai": lambda n: Resp(200, stt_ok(TARGET))}, keys=("OPENAI_API_KEY",))
        _, d = self.speak(GOOD)
        self.assertEqual((d["stt"]["provider"], fake.calls), ("openai", {"openai": 1}))

    def test_assemblyai_no_speech_models_and_language(self) -> None:
        fake, _ = self.install({}, keys=("ASSEMBLYAI_API_KEY",))
        fake.aai_text = "I have a peanut allergy."
        _, d = self.speak(GOOD)
        job = [p for p in fake.posts if p["url"].endswith("/transcript")][0]["json"]
        self.assertEqual(job, {"audio_url": "https://cdn/x", "language_code": "en"})   # speech_models 없음
        self.assertEqual((d["stt"]["provider"], d["score"]), ("assemblyai", 100))

    def test_404_model_cooled_and_rotated(self) -> None:
        def groq(n: int) -> Resp:
            return Resp(404, "gone") if n == 1 else Resp(200, stt_ok(TARGET))
        fake, _ = self.install({"groq": groq})
        _, d = self.speak(GOOD)
        self.assertEqual(d["model"], "whisper-large-v3-turbo")   # 1순위가 404 → 다음 모델
        self.assertIn("groq:whisper-large-v3", ai.model_health()["cooling"])


class ModelPickTest(unittest.TestCase):
    def test_pick(self) -> None:
        self.assertEqual(stt.pick_stt_models("openai", ["gpt-4o-transcribe", "gpt-4o-mini-transcribe", "whisper-1"]),
                         ["whisper-1"])
        self.assertEqual(stt.pick_stt_models("groq", ["distil-whisper-large-v3-en", "whisper-large-v3-turbo",
                                                      "whisper-large-v3"]),
                         ["whisper-large-v3", "whisper-large-v3-turbo", "distil-whisper-large-v3-en"])


if __name__ == "__main__":
    unittest.main()
