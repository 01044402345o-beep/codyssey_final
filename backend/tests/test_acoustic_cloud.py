"""노드가 모두 실패할 때의 클라우드 발음 평가 대체(app/acoustic/cloud.py·chain.py). 네트워크·키 없이 돈다.

실행: cd backend && python -m unittest tests.test_acoustic_cloud
"""
from __future__ import annotations

import base64
import io
import json
import os
import unittest
from unittest import mock

import numpy as np

from app.acoustic import chain, cloud, remote

AUDIO = np.zeros(16000, dtype=np.float32)
TARGET = "a window seat"


def azure_ph(p, score, nbest=None, off=1000000, dur=500000):
    pa = {"AccuracyScore": score}
    if nbest:
        pa["NBestPhonemes"] = [{"Phoneme": x, "Score": s} for x, s in nbest]
    return {"Phoneme": p, "PronunciationAssessment": pa, "Offset": off, "Duration": dur}


AZURE_OK = {"RecognitionStatus": "Success", "NBest": [{"Words": [
    {"Word": "a", "PronunciationAssessment": {"ErrorType": "None"}, "Phonemes": [azure_ph("ə", 95)]},
    {"Word": "window", "PronunciationAssessment": {"ErrorType": "None"},
     "Phonemes": [azure_ph(p, 92) for p in ("w", "ɪ", "n", "d", "oʊ")]},
    {"Word": "seat", "PronunciationAssessment": {"ErrorType": "Mispronunciation"},
     "Phonemes": [azure_ph("s", 96), azure_ph("i", 22, [("i", 22), ("ɪ", 80)]), azure_ph("t", 90)]},
    {"Word": "uh", "PronunciationAssessment": {"ErrorType": "Insertion"}, "Phonemes": [azure_ph("ʌ", 10)]},
]}]}

SPEECHACE_OK = {"status": "success", "text_score": {"word_score_list": [
    {"word": "seat", "phone_score_list": [
        {"phone": "s", "quality_score": 98, "sound_most_like": "s", "extent": [10, 20]},
        {"phone": "iy", "quality_score": 30, "sound_most_like": "ih", "extent": [20, 35]},
        {"phone": "t", "quality_score": 91, "sound_most_like": "t", "extent": [35, 40]}]}]}}


class Env(unittest.TestCase):
    def setUp(self):
        cloud.reset_cap()
        remote.reset_state()
        self.env = mock.patch.dict(os.environ, {
            "PHONEME_REMOTE_URL": "", "PHONEME_REMOTE_URLS": "", "PHONEME_TOKEN": "",
            "PHONEME_AZURE_KEY": "", "PHONEME_AZURE_REGION": "", "PHONEME_SPEECHACE_KEY": "",
            "PHONEME_SPEECHACE_URL": "", "PHONEME_CLOUD_ORDER": "", "PHONEME_CLOUD_DAILY_CAP": ""})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        cloud.reset_cap()


class ParseTest(Env):
    def test_azure_rows_and_report(self):
        rep = cloud.build_report(cloud.azure_rows(AZURE_OK), "azure", "m")
        self.assertEqual([r["word"] for r in rep["phonemes"]].count("uh"), 0)        # 삽입된 말은 목표 음소가 아니다
        seat_i = next(r for r in rep["phonemes"] if r["word"] == "seat" and r["ipa"] == "iː")   # i → iː 로 맞춤
        self.assertEqual((seat_i["status"], seat_i["heard_as"]), ("missing", "ɪ"))
        self.assertEqual((rep["focus"]["word"], rep["focus"]["ipa"], rep["focus"]["heard_as"]), ("seat", "iː", "ɪ"))
        self.assertIn("길게", rep["focus"]["tip"])                                     # 표기를 맞춰야 조음 안내가 붙는다
        self.assertEqual(rep["phonemes"][0]["start_ms"], 100)                          # 100ns → ms
        self.assertEqual((rep["basis"], rep["via"]), ("acoustic", "azure"))

    def test_azure_flat_rest_format(self):
        """라이브 실측(2026-11-04): REST format=detailed 는 점수를 음소·단어 바로 아래에 둔다(중첩 아님)."""
        flat = {"RecognitionStatus": "Success", "NBest": [{"AccuracyScore": 80, "Words": [
            {"Word": "a", "AccuracyScore": 95, "ErrorType": "None",
             "Phonemes": [{"Phoneme": "ə", "AccuracyScore": 95, "Offset": 100000, "Duration": 50000}]},
            {"Word": "seat", "AccuracyScore": 60, "ErrorType": "Mispronunciation", "Phonemes": [
                {"Phoneme": "s", "AccuracyScore": 97, "Offset": 200000, "Duration": 50000},
                {"Phoneme": "i", "AccuracyScore": 20, "Offset": 250000, "Duration": 60000,
                 "NBestPhonemes": [{"Phoneme": "ɪ", "Score": 85}, {"Phoneme": "i", "Score": 20}]},
                {"Phoneme": "t", "AccuracyScore": 92, "Offset": 310000, "Duration": 40000}]},
            {"Word": "uh", "AccuracyScore": 0, "ErrorType": "Insertion", "Phonemes": [{"Phoneme": "ʌ", "AccuracyScore": 0}]}]}]}
        rep = cloud.build_report(cloud.azure_rows(flat), "azure", "m")
        self.assertEqual([r["status"] for r in rep["phonemes"]], ["ok", "ok", "missing", "ok"])
        self.assertEqual(rep["phoneme_accuracy"], 75.0)
        self.assertEqual((rep["focus"]["word"], rep["focus"]["ipa"], rep["focus"]["heard_as"]), ("seat", "iː", "ɪ"))

    def test_azure_without_any_score_is_a_failure_not_zero_percent(self):
        """점수를 못 읽으면 '전부 틀림 0%'를 만들지 않고 실패로 넘긴다(첫 배포의 버그)."""
        noscore = {"RecognitionStatus": "Success", "NBest": [{"Words": [
            {"Word": "seat", "Phonemes": [{"Phoneme": "s"}, {"Phoneme": "i"}]}]}]}
        with self.assertRaises(ValueError) as cm:
            cloud.azure_rows(noscore)
        self.assertEqual(str(cm.exception), "azure_no_scores")

    def test_unknown_score_rows_are_dropped(self):
        rep = cloud.build_report([{"ipa": "s", "word": "seat", "score": 95}, {"ipa": "i", "word": "seat", "score": None}],
                                 "azure", "m")
        self.assertEqual([r["ipa"] for r in rep["phonemes"]], ["s"])
        self.assertEqual(rep["phoneme_accuracy"], 100.0)

    def test_azure_omission_is_missing(self):
        data = {"RecognitionStatus": "Success", "NBest": [{"Words": [
            {"Word": "seat", "PronunciationAssessment": {"ErrorType": "Omission"}, "Phonemes": [azure_ph("s", 90)]}]}]}
        self.assertEqual(cloud.build_report(cloud.azure_rows(data), "azure", "m")["phonemes"][0]["status"], "missing")

    def test_azure_errors(self):
        for bad in ({"RecognitionStatus": "NoMatch"}, {"RecognitionStatus": "Success", "NBest": []}, "x",
                    {"RecognitionStatus": "Success", "NBest": [{"Words": []}]}):
            with self.assertRaises(ValueError):
                cloud.azure_rows(bad)

    def test_speechace_rows(self):
        rep = cloud.build_report(cloud.speechace_rows(SPEECHACE_OK), "speechace", "m")
        self.assertEqual([r["ipa"] for r in rep["phonemes"]], ["s", "iː", "t"])         # ARPAbet → IPA(+길이 표시)
        self.assertEqual((rep["focus"]["ipa"], rep["focus"]["heard_as"]), ("iː", "ɪ"))
        self.assertEqual((rep["phonemes"][1]["start_ms"], rep["phonemes"][1]["end_ms"]), (200, 350))
        with self.assertRaises(ValueError):
            cloud.speechace_rows({"status": "error", "short_message": "invalid key"})

    def test_equivalent_heard_symbol_is_not_an_error(self):
        rep = cloud.build_report([{"ipa": "ə", "word": "a", "score": 30, "heard_as": "ɐ"}], "azure", "m")
        self.assertEqual(rep["phonemes"][0]["status"], "ok")
        self.assertIsNone(rep["focus"])

    def test_report_passes_remote_sanitize(self):
        rep = cloud.build_report(cloud.azure_rows(AZURE_OK), "azure", "m")
        self.assertEqual(remote.sanitize(rep)["focus"], rep["focus"])                    # 화면이 쓰는 형식과 같다


class ProviderTest(Env):
    def test_order_needs_keys(self):
        self.assertEqual(cloud.providers(), [])
        os.environ.update(PHONEME_SPEECHACE_KEY="s", PHONEME_AZURE_KEY="a")
        self.assertEqual(cloud.providers(), ["speechace"])                               # Azure 는 리전도 있어야
        os.environ["PHONEME_AZURE_REGION"] = "koreacentral"
        self.assertEqual(cloud.providers(), ["azure", "speechace"])
        os.environ["PHONEME_CLOUD_ORDER"] = "speechace,azure"
        self.assertEqual(cloud.providers(), ["speechace", "azure"])
        os.environ["PHONEME_CLOUD_DAILY_CAP"] = "0"
        self.assertFalse(cloud.configured())

    def test_falls_through_to_next_provider(self):
        os.environ.update(PHONEME_AZURE_KEY="a", PHONEME_AZURE_REGION="koreacentral", PHONEME_SPEECHACE_KEY="s")
        ok = cloud.build_report(cloud.speechace_rows(SPEECHACE_OK), "speechace", "m")
        with mock.patch.dict(cloud.CALLERS, {"azure": mock.Mock(side_effect=ValueError("http_401")),
                                             "speechace": mock.Mock(return_value=ok)}):
            out = cloud.analyze(AUDIO, TARGET)
        self.assertEqual(out["via"], "speechace")
        self.assertEqual(out["attempts"][0], {"provider": "azure", "result": "http_401", "ms": out["attempts"][0]["ms"]})

    def test_all_fail_never_raises(self):
        os.environ.update(PHONEME_AZURE_KEY="a", PHONEME_AZURE_REGION="koreacentral")
        with mock.patch.dict(cloud.CALLERS, {"azure": mock.Mock(side_effect=RuntimeError("boom"))}):
            out = cloud.analyze(AUDIO, TARGET)
        self.assertEqual((out["status"], out["reason"]), ("unavailable", "all_cloud_failed"))

    def test_daily_cap(self):
        os.environ.update(PHONEME_AZURE_KEY="a", PHONEME_AZURE_REGION="koreacentral", PHONEME_CLOUD_DAILY_CAP="2")
        call = mock.Mock(return_value={"status": "ok", "via": "azure"})
        with mock.patch.dict(cloud.CALLERS, {"azure": call}):
            for _ in range(2):
                self.assertEqual(cloud.analyze(AUDIO, TARGET)["status"], "ok")
            out = cloud.analyze(AUDIO, TARGET)
        self.assertEqual(out["reason"], "cloud_daily_cap")
        self.assertEqual(call.call_count, 2)
        self.assertEqual(cloud.cap_state()["used"], 2)

    def test_azure_request_shape(self):
        os.environ.update(PHONEME_AZURE_KEY="KEY123", PHONEME_AZURE_REGION="koreacentral")
        seen = {}

        def fake(req, timeout):
            seen.update(url=req.full_url, headers={k.lower(): v for k, v in req.header_items()}, n=len(req.data), t=timeout)
            return io.BytesIO(json.dumps(AZURE_OK).encode())

        with mock.patch("urllib.request.urlopen", side_effect=fake):
            out = cloud.analyze(AUDIO, TARGET)
        self.assertEqual(out["via"], "azure")
        self.assertTrue(seen["url"].startswith("https://koreacentral.stt.speech.microsoft.com/"))
        self.assertIn("language=en-US", seen["url"])
        self.assertEqual(seen["headers"]["ocp-apim-subscription-key"], "KEY123")
        pa = json.loads(base64.b64decode(seen["headers"]["pronunciation-assessment"]))
        self.assertEqual((pa["ReferenceText"], pa["Granularity"], pa["PhonemeAlphabet"]), (TARGET, "Phoneme", "IPA"))
        self.assertGreater(seen["n"], 32000)                                             # 16k mono WAV 1초
        self.assertNotIn("KEY123", json.dumps(out))

    def test_bad_region_is_refused_without_call(self):
        os.environ.update(PHONEME_AZURE_KEY="a", PHONEME_AZURE_REGION="evil.com/x?")
        with mock.patch("urllib.request.urlopen") as op:
            out = cloud.analyze(AUDIO, TARGET)
        op.assert_not_called()
        self.assertEqual(out["attempts"][0]["result"], "azure_bad_region")

    def test_status_hides_keys(self):
        os.environ.update(PHONEME_AZURE_KEY="SECRET", PHONEME_AZURE_REGION="koreacentral", PHONEME_SPEECHACE_KEY="SECRET2")
        self.assertNotIn("SECRET", json.dumps(cloud.status()))


class ChainTest(Env):
    def cloud_on(self):
        os.environ.update(PHONEME_AZURE_KEY="a", PHONEME_AZURE_REGION="koreacentral")

    def nodes_on(self):
        os.environ.update(PHONEME_REMOTE_URLS="https://pc1.ts.net", PHONEME_TOKEN="t" * 32)

    def test_node_ok_means_no_cloud_call(self):
        self.nodes_on(); self.cloud_on()
        with mock.patch.object(remote, "analyze", return_value={"status": "ok", "via": "remote"}), \
                mock.patch.object(cloud, "analyze") as c:
            self.assertEqual(chain.analyze(AUDIO, TARGET)["via"], "remote")
        c.assert_not_called()

    def test_all_nodes_failed_goes_to_cloud(self):
        self.nodes_on(); self.cloud_on()
        with mock.patch.object(remote, "analyze", return_value={"status": "unavailable", "reason": "all_nodes_failed"}), \
                mock.patch.object(cloud, "analyze", return_value={"status": "ok", "via": "azure"}):
            out = chain.analyze(AUDIO, TARGET)
        self.assertEqual((out["via"], out["fallback_from"]), ("azure", "all_nodes_failed"))

    def test_cloud_only_config(self):
        self.cloud_on()
        self.assertTrue(chain.configured())
        with mock.patch.object(cloud, "analyze", return_value={"status": "ok", "via": "azure"}):
            self.assertEqual(chain.analyze(AUDIO, TARGET)["fallback_from"], "no_nodes")

    def test_everything_failed_keeps_node_reason_and_cloud_reason(self):
        self.nodes_on(); self.cloud_on()
        with mock.patch.object(remote, "analyze", return_value={"status": "unavailable", "reason": "all_nodes_failed"}), \
                mock.patch.object(cloud, "analyze", return_value={"status": "unavailable", "reason": "cloud_daily_cap"}):
            out = chain.analyze(AUDIO, TARGET)
        self.assertEqual((out["status"], out["reason"], out["cloud"]["reason"]),
                         ("unavailable", "all_nodes_failed", "cloud_daily_cap"))

    def test_nothing_configured(self):
        self.assertFalse(chain.configured())
        self.assertEqual(chain.analyze(AUDIO, TARGET)["status"], "disabled")

    def test_timeout_adds_both_budgets(self):
        self.nodes_on(); self.cloud_on()
        self.assertAlmostEqual(chain.timeout(), remote.budget() + cloud.budget())


if __name__ == "__main__":
    unittest.main()
