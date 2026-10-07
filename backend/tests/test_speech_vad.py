"""Silero VAD 실제 동작 테스트 — 데시벨(음량) 판정이 아니라는 것을 확인한다.

큰 백색잡음·신호음은 음량은 크지만 말소리가 아니므로 발화 0구간이어야 한다.
fixtures/good.wav: macOS `say -v Samantha "I have a peanut allergy."` → 16kHz mono WAV.
"""
from __future__ import annotations

import io
import unittest
import wave
from pathlib import Path

import numpy as np

from app import speech_vad as vad

SR = vad.SAMPLE_RATE
GOOD = (Path(__file__).parent / "fixtures" / "good.wav").read_bytes()


def wav_bytes(x: np.ndarray) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    return buf.getvalue()


def encode(fmt: str, codec: str, pcm16k: np.ndarray) -> bytes:
    """브라우저가 보내는 형식(webm/opus, mp4/aac)을 PyAV 로 만든다."""
    import av

    buf = io.BytesIO()
    out = av.open(buf, "w", format=fmt)
    st = out.add_stream(codec, rate=48000)
    st.layout = "mono"
    x = np.interp(np.arange(len(pcm16k) * 3) / 3, np.arange(len(pcm16k)), pcm16k)
    frame = av.AudioFrame.from_ndarray((x * 32767).astype("<i2").reshape(1, -1), format="s16", layout="mono")
    frame.sample_rate = 48000
    for p in st.encode(frame):
        out.mux(p)
    for p in st.encode(None):
        out.mux(p)
    out.close()
    return buf.getvalue()


class VadTest(unittest.TestCase):
    def speech(self, data: bytes) -> vad.SpeechResult:
        return vad.detect(vad.decode(data))

    def test_silence_has_no_speech(self) -> None:
        r = self.speech(wav_bytes(np.zeros(SR)))
        self.assertFalse(r.has_speech)
        self.assertEqual(r.speech_sec, 0)

    def test_loud_noise_and_tones_are_not_speech(self) -> None:
        """데시벨 판정이면 통과했을 큰 소리들 — 말소리가 아니므로 0구간."""
        rng = np.random.default_rng(0)
        t = np.arange(SR * 2) / SR
        loud = {
            "white_noise_0.3": rng.normal(0, 0.3, SR * 2),
            "tone_440Hz_0.5": 0.5 * np.sin(2 * np.pi * 440 * t),
            "pulsed_beeps_0.5": 0.5 * np.sin(2 * np.pi * 1000 * t) * ((t % 1) < 0.15),
        }
        for name, x in loud.items():
            with self.subTest(name):
                self.assertGreater(float(np.sqrt(np.mean(x ** 2))), 0.05)   # 음량은 충분히 크다
                self.assertFalse(self.speech(wav_bytes(x)).has_speech)

    def test_tts_speech_detected(self) -> None:
        r = self.speech(GOOD)
        self.assertTrue(r.has_speech)
        self.assertGreater(r.speech_sec, 0.8)

    def test_browser_formats_decode_from_memory(self) -> None:
        pcm = vad.decode(GOOD)
        for fmt, codec in (("webm", "libopus"), ("mp4", "aac"), ("ogg", "libopus")):
            with self.subTest(fmt):
                self.assertTrue(self.speech(encode(fmt, codec, pcm)).has_speech)

    def test_real_browser_recordings(self) -> None:
        """Chrome MediaRecorder 로 실제 녹음한 파일.
        no_frames.webm: 소리 입력이 없는 스트림 → 오디오 프레임 없는 110바이트(깨진 파일이 아니라 소리 없는 녹음)
        tone_440hz.webm: 440Hz 신호음 1.5초 → 음량은 있지만 말소리가 아님"""
        fx = Path(__file__).parent / "fixtures"
        for name in ("no_frames.webm", "tone_440hz.webm"):
            with self.subTest(name):
                self.assertFalse(self.speech((fx / name).read_bytes()).has_speech)

    def test_garbage_is_decode_error(self) -> None:
        for bad in (b"not audio" * 100, b"\x00" * 200):
            with self.subTest(bad[:8]), self.assertRaises(vad.AudioDecodeError):
                vad.decode(bad)

    def test_speech_only_wav_contains_only_speech(self) -> None:
        pcm = np.concatenate([np.zeros(SR * 2, dtype=np.float32), vad.decode(GOOD),
                              np.zeros(SR * 2, dtype=np.float32)])
        r = vad.detect(pcm)
        out = vad.speech_only_wav(pcm, r)
        with wave.open(io.BytesIO(out)) as w:
            self.assertEqual((w.getframerate(), w.getnchannels()), (SR, 1))
            self.assertEqual(w.getnframes(), sum(s["end"] - s["start"] for s in r.segments))
        self.assertLess(r.speech_sec, 2.5)          # 앞뒤 무음 4초는 빠졌다

    def test_summary_shape(self) -> None:
        s = self.speech(GOOD).summary()
        self.assertEqual(s["engine"], "silero (faster-whisper)")
        self.assertTrue(s["segments"])


if __name__ == "__main__":
    unittest.main()


class PyannoteLocalTest(unittest.TestCase):
    """두 번째 검출기(로컬 pyannote segmentation-3.0). 단독으로는 신호음 일부를 말소리로 보지만,
    Silero 와의 AND 판정은 모든 비음성 입력을 거른다."""

    def both(self, data: bytes) -> tuple[bool, bool]:
        a = vad.decode(data)
        return vad.detect(a).has_speech, vad.detect_pyannote(a).has_speech

    def test_model_checksum(self) -> None:
        import hashlib
        self.assertEqual(hashlib.sha256(vad.PYANNOTE_MODEL.read_bytes()).hexdigest(), vad.PYANNOTE_SHA256)

    def test_speech_detected_by_both(self) -> None:
        self.assertEqual(self.both(GOOD), (True, True))

    def test_noise_and_silence_rejected_by_pyannote(self) -> None:
        rng = np.random.default_rng(0)
        for name, x in (("silence", np.zeros(SR)), ("noise_0.3", rng.normal(0, 0.3, SR * 2))):
            with self.subTest(name):
                self.assertFalse(vad.detect_pyannote(vad.decode(wav_bytes(x))).has_speech)

    def test_and_rule_rejects_every_non_speech_input(self) -> None:
        rng = np.random.default_rng(0)
        t = np.arange(SR * 2) / SR
        fx = Path(__file__).parent / "fixtures"
        inputs = {
            "silence": wav_bytes(np.zeros(SR)),
            "noise": wav_bytes(rng.normal(0, 0.3, SR * 2)),
            "tone_440": wav_bytes(0.5 * np.sin(2 * np.pi * 440 * t)),
            "pulsed": wav_bytes(0.5 * np.sin(2 * np.pi * 1000 * t) * ((t % 1) < 0.15)),
            "browser_tone_webm": (fx / "tone_440hz.webm").read_bytes(),
            "no_frames_webm": (fx / "no_frames.webm").read_bytes(),
        }
        for name, data in inputs.items():
            with self.subTest(name):
                silero, pyannote = self.both(data)
                self.assertFalse(silero and pyannote)

    def test_segment_across_window_boundary_is_merged(self) -> None:
        pcm = np.concatenate([np.zeros(SR * 9, dtype=np.float32), vad.decode(GOOD), np.zeros(SR * 3, dtype=np.float32)])
        r = vad.detect_pyannote(pcm)
        self.assertEqual(len(r.segments), 1)
        self.assertGreater(r.speech_sec, 1.0)
