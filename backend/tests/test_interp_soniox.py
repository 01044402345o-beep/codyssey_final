"""Soniox 자막 조립 — 확정은 한 번만 오므로 이어 붙이고, 임시는 갈아 끼우고, <end> 는 화면에 내보내지 않는다.

10/21 실기기: 무엇을 말해도 '내가 한 말' 칸에 '<end>' 만 남고 번역이 비었다.
원인: 응답마다 그 응답의 확정 토큰만 보내 마지막 '<end>' 가 앞 문장을 덮었다.
실행: cd backend && python -m unittest tests.test_interp_soniox
"""
import json
import os
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from app import firebase_auth, interp, main


def tok(text, final, tr=False):
    t = {"text": text, "is_final": final}
    if tr:
        t["translation_status"] = "translation"
    else:
        t["translation_status"] = "original"
    return t


# 실제 순서를 흉내: 임시 → 확정 일부 → 끝점(<end>) → 번역이 뒤따라옴 → 다음 말
STREAM = [
    {"tokens": [tok("기차", False)]},
    {"tokens": [tok("기차역이", True), tok(" 어디", False)]},
    {"tokens": [tok(" 어디예요?", True), tok("<end>", True)]},
    {"tokens": [tok("Where is", False, tr=True)]},
    {"tokens": [tok("Where is the train station?", True, tr=True)]},
    {"tokens": [tok("Thank", False)]},
    {"tokens": [tok("Thank you.", True), tok("<end>", True), tok("고마워요.", True, tr=True)]},
    {"finished": True},
]


class T(unittest.TestCase):
    def test_caption_assembly(self):
        c = interp.SonioxCaptions()
        outs = [c.feed(e.get("tokens") or []) for e in STREAM[:-1]]
        self.assertEqual(outs[0]["source_partial"], "기차")
        self.assertEqual(outs[1]["source"], "기차역이")
        self.assertEqual(outs[2]["source"], "기차역이 어디예요?")          # <end> 가 덮지 않는다
        self.assertNotIn("<end>", json.dumps(outs, ensure_ascii=False))
        self.assertEqual(outs[3]["source"], "기차역이 어디예요?")          # 번역 임시가 와도 원문은 그대로
        self.assertEqual(outs[3]["target_partial"], "Where is")
        self.assertEqual(outs[4]["target"], "Where is the train station?")
        self.assertEqual(outs[5]["source"], "")                            # 다음 말 → 새 문장
        self.assertEqual(outs[5]["source_partial"], "Thank")
        self.assertEqual(outs[6]["source"], "Thank you.")
        self.assertEqual(outs[6]["target"], "고마워요.")

    def test_end_only_response_sends_nothing(self):
        c = interp.SonioxCaptions()
        self.assertIsNone(c.feed([tok("<end>", True)]))

    def test_websocket_relays_assembled_captions(self):
        class Up:
            def __init__(self):
                self.sent = []

            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False

            async def send(self, raw):
                self.sent.append(raw)

            def __aiter__(self): return self._g()

            async def _g(self):
                for e in STREAM:
                    yield json.dumps(e)

        up = Up()

        async def conn(url, headers):
            return up

        env = {"SONIOX_API_KEY": "s", "INTERP_PROVIDERS": "soniox", "INTERP_PROVIDER": ""}
        with mock.patch.dict(os.environ, env), mock.patch.object(interp, "_connect", conn), \
             mock.patch.object(firebase_auth, "verify_bearer", return_value={"uid": "u1", "provider": "google.com"}):
            interp._starts.clear()
            with TestClient(main.app).websocket_connect("/interp/stream") as ws:
                ws.send_json({"type": "start", "a": "ko", "b": "en", "token": "t"})
                caps = []
                while True:
                    m = ws.receive_json()
                    if m["type"] == "caption":
                        caps.append(m)
                    if m["type"] in ("closed", "error"):
                        break
        self.assertTrue(any(c["source"] == "기차역이 어디예요?" and c["target"] == "Where is the train station?" for c in caps), caps)
        self.assertFalse(any("<end>" in (c["source"] + c["source_partial"] + c["target"]) for c in caps))
        cfg = json.loads(up.sent[0])
        self.assertEqual(cfg["translation"], {"type": "two_way", "language_a": "ko", "language_b": "en"})


if __name__ == "__main__":
    unittest.main()
