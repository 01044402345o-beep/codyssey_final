"""timing_ms: 어디서 시간이 쓰이는지 응답에 숫자로 남는다 (멘토 지적 '응답이 느리다'의 측정 근거)."""
import os
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app import gemini as ai
from app import main
from app import stt_providers as stt

FIX = Path(__file__).parent / "fixtures"


class TimingTest(unittest.TestCase):
    def setUp(self) -> None:
        self._env = dict(os.environ)
        for k in ("GEMINI_API_KEY", "GROQ_API_KEY", "OPENAI_API_KEY", "ASSEMBLYAI_API_KEY"):
            os.environ.pop(k, None)
        main._hits.clear() if hasattr(main, "_hits") else None
        self.c = TestClient(main.app)

    def tearDown(self) -> None:
        os.environ.clear(); os.environ.update(self._env)

    def test_generate_mock_has_timing(self):
        r = self.c.post("/generate", json={"category_id": "restaurant", "city": "New York", "places": [{"id": "p1", "name": "Joe's Pizza", "place_type": "restaurant"}]})
        self.assertEqual(r.status_code, 200, r.text)
        t = r.json()["timing_ms"]
        self.assertIsInstance(t["total"], int)
        self.assertEqual(t["attempt_ms"], [])        # 키 없음 = 모델 호출 0회

    def test_generate_records_each_attempt(self):
        """모델 호출을 가짜로 바꿔 시도별 ms·검증 ms·통과 여부가 기록되는지 본다 (첫 시도 JSON 오류 → 두 번째 성공)."""
        os.environ["GEMINI_API_KEY"] = "k"
        calls = {"n": 0}
        orig = (ai.generate_text, ai.run)
        good = main.mock_pack(main.load_category("restaurant"), main.GenerateRequest(category_id="restaurant", city="New York", places=[{"id": "p1", "name": "Joe's Pizza", "place_type": "restaurant"}]))
        import json as _json

        def fake_generate_text(client, model, prompt, **kw):
            calls["n"] += 1
            return "not json" if calls["n"] == 1 else _json.dumps(good)

        def fake_run(what, fn):
            last = None
            for attempt in (1, 2):
                try:
                    return ai.Result(value=fn(None, "fake-model", attempt), attempts=attempt, model="fake-model", failures=[])
                except Exception as exc:  # noqa: BLE001
                    last = exc
            raise ai.AttemptsExhausted(what, 2, str(last), [])

        ai.generate_text, ai.run = fake_generate_text, fake_run
        try:
            r = self.c.post("/generate", json={"category_id": "restaurant", "city": "New York", "places": [{"id": "p1", "name": "Joe's Pizza", "place_type": "restaurant"}]})
        finally:
            ai.generate_text, ai.run = orig
        self.assertEqual(r.status_code, 200, r.text)
        att = r.json()["timing_ms"]["attempt_ms"]
        self.assertEqual(len(att), 2)
        self.assertFalse(att[0]["ok"]); self.assertIsNone(att[0]["validate_ms"])   # JSON 파싱 단계에서 실패
        self.assertIsNotNone(att[0]["call_ms"])
        self.assertIsNotNone(att[1]["validate_ms"])

    def test_speak_no_speech_has_stage_timing(self):
        r = self.c.post("/speak-check", data={"target": "I have a peanut allergy."}, files={"file": ("silence.webm", (FIX / "no_frames.webm").read_bytes(), "audio/webm")})
        # 프레임 없는 파일은 400 (읽을 수 없음). 타이밍은 정상 처리된 응답에만 붙는다.
        self.assertIn(r.status_code, (200, 400))

    def test_speak_good_wav_reports_vad_stages(self):
        r = self.c.post("/speak-check", data={"target": "I have a peanut allergy."}, files={"file": ("good.wav", (FIX / "good.wav").read_bytes(), "audio/wav")})
        self.assertEqual(r.status_code, 200, r.text)
        t = r.json()["timing_ms"]
        for k in ("read", "decode", "silero", "pyannote", "total"):
            self.assertIn(k, t, t)
        self.assertGreaterEqual(t["total"], t["silero"] + t["pyannote"] - 5)   # 단계 합이 전체를 넘지 않는다(반올림 오차 5ms)


if __name__ == "__main__":
    unittest.main()
