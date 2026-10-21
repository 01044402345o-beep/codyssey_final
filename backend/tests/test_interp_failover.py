"""실시간 통역 자동 전환과 자체 엔진(local).

- 시작 전에 실패한 엔진 → 다음 엔진('switch' 알림 뒤 'ready')
- 모두 실패 → all_failed(화면은 검수 문장 통역으로 안내)
- 통역 중 끊김 → provider_lost(화면이 그 엔진을 빼고 다시 연결)
- 자체 엔진: 말이 끝나면(조용해지면) 받아쓰고 번역해 자막을 보낸다. 준비 전이면 다음 엔진으로
실행: cd backend && python -m unittest tests.test_interp_failover
"""
import math
import os
import struct
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from app import firebase_auth, interp, interp_local, main

CLEAR = {k: "" for k in ("INTERP_PROVIDER", "SONIOX_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "DEEPL_API_KEY",
                          "AZURE_SPEECH_KEY", "AZURE_SPEECH_REGION", "INTERP_ALLOW_FAKE", "INTERP_PROVIDERS")}
LOGIN = {"uid": "u1", "provider": "google.com"}


def tone(seconds, amp=0.3):
    n = int(16000 * seconds)
    return struct.pack(f"<{n}h", *(int(amp * 32767 * math.sin(2 * math.pi * 440 * i / 16000)) for i in range(n)))


def silence(seconds):
    return b"\x00\x00" * int(16000 * seconds)


class T(unittest.TestCase):
    def setUp(self):
        interp._starts.clear()
        self.http = TestClient(main.app)

    def tearDown(self):
        interp_local.transcribe_fn = interp_local.translate_fn = None

    def env(self, **kw):
        e = dict(CLEAR); e.update(kw)
        return mock.patch.dict(os.environ, e)

    def run_ws(self, first, frames=(), until=("ready",), limit=20):
        out = []
        with mock.patch.object(firebase_auth, "verify_bearer", return_value=LOGIN):
            with self.http.websocket_connect("/interp/stream") as ws:
                ws.send_json({"type": "start", "a": "ko", "b": "en", "token": "t", **first})
                for _ in range(limit):
                    m = ws.receive_json()
                    out.append(m)
                    if m.get("type") == "ready" and frames:
                        for f in frames:
                            ws.send_bytes(f)
                        frames = ()
                    if "caption" in until and m.get("type") == "caption" and m.get("target"):
                        break
                    if (m.get("type") in until and m.get("type") != "caption") or m.get("type") in ("error", "closed"):
                        break
        return out

    def test_chain_order_exclude_forced(self):
        with self.env(SONIOX_API_KEY="s", OPENAI_API_KEY="o", INTERP_ALLOW_FAKE="1"):
            self.assertEqual(interp.provider_chain(None), ["soniox", "openai", "fake"])
            self.assertEqual(interp.provider_chain("openai"), ["openai", "soniox", "fake"])
            self.assertEqual(interp.provider_chain(None, ("soniox",)), ["openai", "fake"])
        with self.env(SONIOX_API_KEY="s", OPENAI_API_KEY="o", INTERP_PROVIDER="openai"):
            self.assertEqual(interp.provider_chain("soniox"), ["openai"])          # 고정이면 넘어갈 곳 없음
            self.assertEqual(interp.provider_chain(None, ("openai",)), [])

    def test_setup_failure_switches_to_next_engine(self):
        with self.env(SONIOX_API_KEY="s", INTERP_ALLOW_FAKE="1"), \
             mock.patch.object(interp, "_connect", side_effect=OSError("down")):
            ev = self.run_ws({})
        self.assertEqual(ev[0], {"type": "switch", "failed": "soniox", "next": "fake"})
        self.assertEqual(ev[1]["type"], "ready")
        self.assertEqual(ev[1]["provider"], "fake")

    def test_all_engines_fail(self):
        with self.env(SONIOX_API_KEY="s", OPENAI_API_KEY="o"), \
             mock.patch.object(interp, "_connect", side_effect=OSError("down")):
            ev = self.run_ws({})
        self.assertEqual([e["type"] for e in ev], ["switch", "error"])
        self.assertEqual(ev[-1]["code"], "all_failed")
        self.assertIn("검수 문장", ev[-1]["message"])

    def test_excluded_engines_are_skipped(self):
        with self.env(SONIOX_API_KEY="s", INTERP_ALLOW_FAKE="1"), \
             mock.patch.object(interp, "_connect", side_effect=AssertionError("soniox 를 다시 쓰면 안 된다")):
            ev = self.run_ws({"exclude": ["soniox"]})
        self.assertEqual(ev[0]["provider"], "fake")
        with self.env(SONIOX_API_KEY="s"):
            ev = self.run_ws({"exclude": ["soniox"]})
        self.assertEqual(ev[0]["code"], "all_failed")

    def test_failure_after_ready_is_provider_lost(self):
        async def boom(self):
            await self.announce({"type": "ready", "provider": "fake", "pair": [self.a, self.b]})
            raise RuntimeError("stream dropped")

        with self.env(SONIOX_API_KEY="s", INTERP_ALLOW_FAKE="1", INTERP_PROVIDERS="fake,soniox"), \
             mock.patch.object(interp._Session, "run_fake", boom), \
             mock.patch.object(interp, "_connect", side_effect=AssertionError("끊긴 뒤에 서버가 다른 엔진으로 넘어가면 안 된다")):
            ev = self.run_ws({}, until=())
        self.assertEqual(ev[0]["type"], "ready")
        self.assertEqual(ev[1]["code"], "provider_lost")
        self.assertEqual(ev[1]["failed"], "fake")

    def test_login_required_when_chain_has_real_engine(self):
        with self.env(SONIOX_API_KEY="s", INTERP_ALLOW_FAKE="1"), \
             mock.patch.object(firebase_auth, "verify_bearer", side_effect=firebase_auth.AuthError(401, "x")):
            with self.http.websocket_connect("/interp/stream") as ws:
                ws.send_json({"type": "start", "a": "ko", "b": "en"})
                self.assertEqual(ws.receive_json()["code"], "login_required")

    def test_in_band_provider_error_is_provider_lost(self):
        """엔진이 ready 뒤 스스로 오류(키 만료 등)를 보내면 화면이 다음 엔진으로 다시 붙도록 provider_lost(리뷰 #1)."""
        class Up:
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def send(self, raw): pass
            def __aiter__(self): return self._g()
            async def _g(self):
                yield '{"error_code": 401, "error_message": "Invalid API key"}'

        async def conn(url, headers):
            return Up()

        with self.env(SONIOX_API_KEY="s", INTERP_ALLOW_FAKE="1"), mock.patch.object(interp, "_connect", conn):
            ev = self.run_ws({}, until=())
        self.assertEqual(ev[0]["provider"], "soniox")
        self.assertEqual(ev[1]["code"], "provider_lost")
        self.assertEqual(ev[1]["failed"], "soniox")

    def test_connect_timeout_switches_not_too_long(self):
        """엔진 접속 시간 초과(TimeoutError)는 세션 상한이 아니라 엔진 실패 — 다음 엔진으로(리뷰 #2)."""
        with self.env(SONIOX_API_KEY="s", INTERP_ALLOW_FAKE="1"),              mock.patch.object(interp, "_connect", side_effect=TimeoutError("open_timeout")):
            ev = self.run_ws({})
        self.assertEqual(ev[0]["type"], "switch")
        self.assertEqual(ev[1]["provider"], "fake")

    def test_session_cap_still_too_long(self):
        with self.env(INTERP_ALLOW_FAKE="1", INTERP_PROVIDERS="fake"), mock.patch.object(interp, "MAX_SECONDS", -4):
            ev = self.run_ws({}, until=())
        self.assertEqual(ev[0]["type"], "ready")
        self.assertEqual(ev[1]["code"], "too_long")

    def test_closed_sent_once(self):
        with self.env(INTERP_ALLOW_FAKE="1", INTERP_PROVIDERS="fake"):
            with mock.patch.object(firebase_auth, "verify_bearer", return_value=LOGIN):
                with self.http.websocket_connect("/interp/stream") as ws:
                    ws.send_json({"type": "start", "a": "ko", "b": "en"})
                    ws.receive_json()
                    ws.send_json({"type": "stop"})
                    kinds = []
                    try:
                        while True:
                            kinds.append(ws.receive_json()["type"])
                    except Exception:      # noqa: BLE001 — 서버가 닫음
                        pass
        self.assertEqual(kinds.count("closed"), 1, kinds)

    # ---- 자체 엔진 ----
    def test_local_engine_transcribes_and_translates_each_utterance(self):
        seen = []
        interp_local.transcribe_fn = lambda pcm, langs: (seen.append(len(pcm)) or ("기차역이 어디예요?", "ko"))
        interp_local.translate_fn = lambda text, src, dst: f"[{src}->{dst}] Where is the train station?"
        with self.env(INTERP_PROVIDERS="local"), mock.patch.object(interp_local, "deps_ok", return_value=True):
            ev = self.run_ws({}, frames=[tone(0.6), silence(1.0)], until=("caption",), limit=6)
        caps = [e for e in ev if e.get("type") == "caption" and e.get("target")]
        self.assertEqual(ev[0]["provider"], "local")
        self.assertEqual(caps[0]["source"], "기차역이 어디예요?")
        self.assertEqual(caps[0]["target"], "[ko->en] Where is the train station?")
        self.assertTrue(seen and seen[0] >= 0.6 * 16000 * 2)   # 말한 부분이 통째로 넘어갔다

    def test_local_engine_not_ready_falls_back(self):
        with self.env(INTERP_PROVIDERS="local,fake", INTERP_ALLOW_FAKE="1", INTERP_LOCAL_WAIT="0"), \
             mock.patch.object(interp_local, "deps_ok", return_value=True), \
             mock.patch.dict(interp_local._state, {"status": "idle"}):
            ev = self.run_ws({})
        self.assertEqual(ev[0], {"type": "switch", "failed": "local", "next": "fake"})
        self.assertEqual(ev[1]["provider"], "fake")

    def test_local_engine_unavailable_after_load_error(self):
        with self.env(INTERP_PROVIDERS="local"), mock.patch.object(interp_local, "deps_ok", return_value=True), \
             mock.patch.dict(interp_local._state, {"status": "error"}):
            self.assertFalse(interp.provider_available("local"))

    def test_health_reports_local_status(self):
        with self.env(INTERP_PROVIDERS="soniox,local"):
            h = self.http.get("/health").json()["interp_local"]
        self.assertTrue(h["enabled"])
        self.assertIn(h["status"], ("idle", "loading", "ready", "error"))

    def test_safe_extract_blocks_path_traversal(self):
        import io
        import tempfile
        import zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("../evil.txt", "x")
        with tempfile.TemporaryDirectory() as d, zipfile.ZipFile(buf) as z:
            from pathlib import Path
            with self.assertRaises(ValueError):
                interp_local._safe_extract(z, Path(d))


if __name__ == "__main__":
    unittest.main()
