"""음소 노드(app/acoustic). 모델 파일이 없어도 도는 테스트가 기본이고, 실제 모델 테스트는 파일이 있을 때만.

실행: cd backend && python -m unittest tests.test_acoustic
"""
from __future__ import annotations

import io
import os
import unittest
import wave
from pathlib import Path
from unittest import mock

import numpy as np
from fastapi.testclient import TestClient

from app.acoustic import g2p, model, remote, score, server
from app.acoustic.align import forced_align, log_softmax
from app.acoustic.inventory import tip_for

FIX = Path(__file__).parent / "fixtures"
TOKEN = "t" * 32


def synthetic(seq, frames_per=4, V=8, conf=6.0):
    """seq 의 각 음소가 frames_per 프레임씩 이어진 이상적인 로짓(0번 = 공백)."""
    logits = np.zeros((len(seq) * frames_per, V), dtype=np.float32)
    for i, tok in enumerate(seq):
        logits[i * frames_per:(i + 1) * frames_per, tok] = conf
    return log_softmax(logits)


def wav(samples: np.ndarray, rate=16000, channels=1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
    return buf.getvalue()


class AlignTest(unittest.TestCase):
    def test_spans_ordered(self):
        spans = forced_align(synthetic([1, 2, 3]), [1, 2, 3])
        self.assertEqual(len(spans), 3)
        self.assertTrue(all(e >= s >= 0 for s, e in spans))
        self.assertEqual(spans[0][0], 0)

    def test_empty(self):
        self.assertEqual(forced_align(np.zeros((0, 8), dtype=np.float32), [1]), [])
        self.assertEqual(forced_align(np.zeros((5, 8), dtype=np.float32), []), [])


class G2PTest(unittest.TestCase):
    def test_lexicon_with_stress(self):
        toks = g2p.tokenize("Can I have a window seat, please?")
        self.assertEqual(g2p.coverage("Can I have a window seat, please?")[:2], (7, 7))
        self.assertIn("iː", [t.ipa for t in toks if t.word == "seat"])
        self.assertFalse(any(t.fallback for t in toks))

    def test_unstressed_ah_is_schwa(self):
        self.assertEqual(g2p.tokenize("about")[0].ipa, "ə")

    def test_oov_fallback_is_marked(self):
        toks = g2p.tokenize("zzqvist")
        self.assertTrue(toks and all(t.fallback for t in toks))
        self.assertEqual(g2p.coverage("a zzqvist")[2], ["zzqvist"])

    def test_wifi_joins_like_phonemes_module(self):
        self.assertEqual(g2p.words("the Wi-Fi password"), ["the", "wifi", "password"])

    def test_tip_for_unknown(self):
        self.assertTrue(all(tip_for("ʘ")))


class ScoreTest(unittest.TestCase):
    def test_perfect(self):
        vocab = ["<pad>", "k", "æ", "t"]
        rep = score.evaluate("cat", synthetic([1, 2, 3], 5, 4), vocab, {s: i for i, s in enumerate(vocab)}, 600)
        self.assertEqual(rep["phoneme_accuracy"], 100.0)
        self.assertIsNone(rep["focus"])
        self.assertEqual(rep["basis"], "acoustic")

    def test_substitution_has_heard_as_and_tip(self):
        vocab = ["<pad>", "θ", "s", "ɪ", "n"]
        rep = score.evaluate("thin", synthetic([2, 3, 4], 5, 5), vocab, {s: i for i, s in enumerate(vocab)})
        self.assertEqual((rep["focus"]["ipa"], rep["focus"]["heard_as"]), ("θ", "s"))
        self.assertTrue(rep["focus"]["tip"])

    def test_equivalent_symbol_is_not_an_error(self):
        # 사전의 슈와 ə 를 모델이 ɐ 로 적어도 같은 소리다(합성음 'a window' 실측 오탐)
        vocab = ["<pad>", "ə", "ɐ", "b", "aʊ", "t"]
        rep = score.evaluate("about", synthetic([2, 3, 4, 5], 5, 6), vocab, {s: i for i, s in enumerate(vocab)})
        self.assertEqual(rep["phoneme_accuracy"], 100.0)
        self.assertEqual(rep["phonemes"][0]["variant"], "ɐ")

    def test_fallback_word_is_never_the_focus(self):
        vocab = ["<pad>", "z", "k", "w", "ɪ", "s", "t", "v", "ə"]
        rep = score.evaluate("zzqvist", synthetic([8, 8, 8], 5, 9), vocab, {s: i for i, s in enumerate(vocab)})
        self.assertIsNone(rep["focus"])


class RemoteTest(unittest.TestCase):
    def env(self, **kw):
        remote.reset_state()
        return mock.patch.dict(os.environ, {"PHONEME_REMOTE_URL": "", "PHONEME_REMOTE_URLS": "", "PHONEME_TOKEN": "", **kw})

    def test_configured_rules(self):
        with self.env(PHONEME_REMOTE_URL="https://pc.tail1.ts.net", PHONEME_TOKEN=TOKEN):
            self.assertTrue(remote.configured())
        with self.env(PHONEME_REMOTE_URL="https://pc.tail1.ts.net"):
            self.assertFalse(remote.configured())                 # 토큰 없는 노드로는 음성을 안 보낸다
        with self.env(PHONEME_REMOTE_URL="http://100.64.1.2:8443", PHONEME_TOKEN=TOKEN):
            self.assertFalse(remote.configured())                 # 평문 http 는 같은 PC 일 때만
        with self.env(PHONEME_REMOTE_URL="http://127.0.0.1:8443", PHONEME_TOKEN=TOKEN):
            self.assertTrue(remote.configured())

    def test_not_configured_makes_no_call(self):
        with self.env(), mock.patch("urllib.request.urlopen") as op:
            self.assertEqual(remote.analyze(np.zeros(1600, np.float32), "x")["status"], "disabled")
            op.assert_not_called()

    def test_network_error_never_raises(self):
        with self.env(PHONEME_REMOTE_URL="http://127.0.0.1:9", PHONEME_TOKEN=TOKEN, PHONEME_REMOTE_TIMEOUT="1"):
            r = remote.analyze(np.zeros(1600, np.float32), "seat")
        self.assertEqual(r["status"], "unavailable")

    def test_sanitize_keeps_only_known_fields(self):
        raw = {"status": "ok", "phoneme_accuracy": 95.0, "evil": "<script>", "model": "m",
               "phonemes": [{"ipa": "iː", "word": "seat", "status": "weak", "gop": 0.1, "heard_as": "ɪ", "x": 1},
                            {"status": "bogus"}, "nope"],
               "focus": {"ipa": "iː", "word": "seat", "heard_as": "ɪ", "tip": "t" * 500, "label": "l"},
               "lexicon": {"fallback_words": ["zz"]}}
        out = remote.sanitize(raw)
        self.assertNotIn("evil", out)
        self.assertEqual(len(out["phonemes"]), 1)
        self.assertNotIn("x", out["phonemes"][0])
        self.assertEqual(len(out["focus"]["tip"]), 200)
        self.assertEqual(out["fallback_words"], ["zz"])
        self.assertEqual(remote.sanitize({"status": "ok", "phoneme_accuracy": 900})["phoneme_accuracy"], None)
        self.assertEqual(remote.sanitize("x")["status"], "unavailable")
        self.assertEqual(remote.sanitize({"status": "error", "reason": "Boom"})["reason"], "Boom")


class FakeModel:
    vocab = ["<pad>", "s", "iː", "t"]
    index = {s: i for i, s in enumerate(vocab)}

    def log_probs(self, samples):
        return synthetic([1, 2, 3], 5, 4)


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.p = [mock.patch.dict(os.environ, {"PHONEME_TOKEN": TOKEN}),
                  mock.patch.object(server.model, "load", return_value=FakeModel()),
                  mock.patch.dict(server._state, {"ready": True})]
        for p in self.p:
            p.start()
        self.c = TestClient(server.app)

    def tearDown(self):
        for p in reversed(self.p):
            p.stop()

    def post(self, data, token=TOKEN, text="seat"):
        return self.c.post("/phoneme-check", files={"audio": ("a.wav", data, "audio/wav")}, data={"text": text},
                           headers={"X-Phoneme-Token": token} if token is not None else {})

    def test_ok(self):
        r = self.post(wav(np.zeros(16000, np.float32)))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["phoneme_accuracy"], 100.0)

    def test_token_required(self):
        self.assertEqual(self.post(wav(np.zeros(16000)), token="x" * 32).status_code, 401)
        self.assertEqual(self.post(wav(np.zeros(16000)), token=None).status_code, 401)

    def test_audio_limits(self):
        self.assertEqual(self.post(wav(np.zeros(16000 * 25))).status_code, 413)
        self.assertEqual(self.post(wav(np.zeros(16000), rate=44100)).status_code, 400)
        self.assertEqual(self.post(wav(np.zeros(16000), channels=2)).status_code, 400)
        self.assertEqual(self.post(b"not a wav").status_code, 400)
        self.assertEqual(self.post(wav(np.zeros(100))).status_code, 400)
        self.assertEqual(self.post(wav(np.zeros(16000)), text="x" * 301).status_code, 422)

    def test_healthz_reveals_no_paths_or_token(self):
        body = self.c.get("/healthz").text
        self.assertNotIn(TOKEN, body)
        self.assertNotIn(str(model.MODEL_PATH.parent), body)

    def test_refuses_to_start_with_short_token(self):
        with mock.patch.dict(os.environ, {"PHONEME_TOKEN": "short"}), mock.patch("uvicorn.run") as run:
            self.assertEqual(server.main(), 2)
            run.assert_not_called()


@unittest.skipUnless(model.available(), "음소 모델 없음(tools/fetch_phoneme_model.py)")
class RealModelTest(unittest.TestCase):
    """합성음(Windows Zira TTS)으로 실제 모델을 돌린다 — 정확히 말한 'seat' 는 지적 없음, 'sit' 는 seat 의 iː→ɪ."""

    def read(self, name):
        with wave.open(str(FIX / name)) as w:
            return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768

    def run_one(self, name):
        m = model.load()
        a = self.read(name)
        return score.evaluate("Can I have a window seat, please?", m.log_probs(a), m.vocab, m.index,
                              duration_ms=int(1000 * a.size / 16000))

    def test_correct_sentence_has_no_focus(self):
        rep = self.run_one("say_window_seat.wav")
        self.assertGreaterEqual(rep["phoneme_accuracy"], 95.0)
        self.assertIsNone(rep["focus"])

    def test_sit_is_caught_on_seat(self):
        rep = self.run_one("say_window_sit.wav")
        self.assertEqual((rep["focus"]["word"], rep["focus"]["ipa"], rep["focus"]["heard_as"]), ("seat", "iː", "ɪ"))


if __name__ == "__main__":
    unittest.main()
