"""실시간 통역 제공자 표: 운영자가 켠 것만, 키 이름 비노출, DeepL 메시지 형식(공식 AsyncAPI).

실행: cd backend && python -m unittest tests.test_interp_providers
"""
import asyncio
import json
import os
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from app import firebase_auth, interp, main

CLEAR = {k: "" for k in ("INTERP_PROVIDER", "SONIOX_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "DEEPL_API_KEY",
                          "AZURE_SPEECH_KEY", "AZURE_SPEECH_REGION", "INTERP_ALLOW_FAKE")}


class FakeUp:
    """제공자 WebSocket 흉내. 오디오 한 조각을 받으면 준비한 메시지를 흘려보낸다."""

    def __init__(self, replies):
        self.sent, self.replies, self.got_audio = [], replies, asyncio.Event()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def send(self, raw):
        self.sent.append(raw)
        if "source_media_chunk" in raw:
            self.got_audio.set()

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        await asyncio.wait_for(self.got_audio.wait(), 5)
        for r in self.replies:
            yield json.dumps(r)


class T(unittest.TestCase):
    def setUp(self):
        interp._starts.clear()
        self.http = TestClient(main.app)

    def env(self, **kw):
        e = dict(CLEAR); e.update(kw)
        os.environ.pop("INTERP_PROVIDERS", None)
        return mock.patch.dict(os.environ, e)

    def test_gemini_key_alone_does_not_enable_interp(self):
        with self.env(GEMINI_API_KEY="app-key"):   # 문장 생성용 키가 있어도
            self.assertFalse(interp.provider_available("gemini"))
            self.assertEqual(interp.provider_choice("gemini"), "none")

    def test_allowlist_enables_provider(self):
        with self.env(GEMINI_API_KEY="k", INTERP_PROVIDERS="soniox,gemini"):
            self.assertTrue(interp.provider_available("gemini"))
            self.assertEqual(interp.provider_choice("gemini"), "gemini")

    def test_requested_provider_and_default_order(self):
        with self.env(SONIOX_API_KEY="s", OPENAI_API_KEY="o"):
            self.assertEqual(interp.provider_choice(None), "soniox")
            self.assertEqual(interp.provider_choice("openai"), "openai")
            self.assertEqual(interp.provider_choice("deepl"), "soniox")   # 꺼진 제공자를 고르면 켜진 첫 제공자

    def test_forced_provider_is_not_overridden(self):
        with self.env(SONIOX_API_KEY="s", OPENAI_API_KEY="o", INTERP_PROVIDER="openai"):
            self.assertEqual(interp.provider_choice("soniox"), "openai")

    def test_providers_endpoint_hides_key_names(self):
        with self.env(SONIOX_API_KEY="secret-value"):
            body = self.http.get("/interp/providers").text
        self.assertNotIn("SONIOX_API_KEY", body)
        self.assertNotIn("secret-value", body)
        rows = {p["id"]: p for p in json.loads(body)["providers"]}
        self.assertTrue(rows["soniox"]["available"])
        self.assertFalse(rows["gemini"]["available"])

    def test_deepl_messages_follow_asyncapi(self):
        up = FakeUp([
            {"source_transcript_update": {"concluded": [{"language": "ko", "text": "기차역이 "}], "tentative": [{"text": "어디"}]}},
            {"target_transcript_update": {"language": "en", "concluded": [{"text": "Where is the station?"}], "tentative": []}},
            {"end_of_stream": {}},
        ])
        resp = mock.Mock(status_code=200)
        resp.json.return_value = {"streaming_url": "wss://example.invalid/connect", "token": "t1"}
        cli = mock.AsyncMock()
        cli.__aenter__.return_value = cli
        cli.post.return_value = resp
        connected = []

        async def fake_connect(url, headers):
            connected.append(url)
            return up

        with self.env(DEEPL_API_KEY="d", INTERP_PROVIDERS="deepl"), \
             mock.patch.object(firebase_auth, "verify_bearer", return_value={"uid": "u1", "provider": "google.com"}), \
             mock.patch("httpx.AsyncClient", return_value=cli), mock.patch.object(interp, "_connect", fake_connect):
            with self.http.websocket_connect("/interp/stream") as ws:
                ws.send_json({"type": "start", "a": "ko", "b": "en", "token": "x", "provider": "deepl"})
                self.assertEqual(ws.receive_json()["provider"], "deepl")
                ws.send_bytes(b"\x00\x00" * 1600)
                caps = []
                while True:
                    m = ws.receive_json()
                    if m["type"] != "caption":
                        break
                    caps.append(m)
        body = cli.post.call_args.kwargs["json"]
        self.assertEqual(body["target_languages"], ["en"])
        self.assertNotIn("target_media_languages", body)                 # 음성은 요청하지 않는다(형식 불일치)
        self.assertEqual(cli.post.call_args.kwargs["headers"]["Authorization"], "DeepL-Auth-Key d")
        self.assertEqual(connected, ["wss://example.invalid/connect?token=t1"])
        chunk = json.loads(up.sent[0])
        self.assertEqual(list(chunk), ["source_media_chunk"])               # 최상위 키 하나로 구분
        self.assertTrue(chunk["source_media_chunk"]["data"])
        self.assertEqual(caps[0]["source"], "기차역이 ")
        self.assertEqual(caps[0]["source_partial"], "어디")
        self.assertEqual(caps[-1]["target"], "Where is the station?")


if __name__ == "__main__":
    unittest.main()
