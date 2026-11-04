"""음소 노드 여러 대 — 페일오버·서킷브레이커·복구. 가짜 노드는 실제 소켓·실제 타임아웃을 쓴다.

실행: cd backend && python -m unittest tests.test_acoustic_failover
"""
from __future__ import annotations

import json
import os
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

import numpy as np

from app.acoustic import remote

AUDIO = np.zeros(16000, dtype=np.float32)
TOKEN = "t" * 32
OK_BODY = {"status": "ok", "phoneme_accuracy": 95.0, "phonemes": [],
           "focus": {"ipa": "iː", "word": "seat", "heard_as": "ɪ", "tip": "길게"}}


class _Handler(BaseHTTPRequestHandler):
    mode = "ok"
    posts = 0
    gets = 0

    def log_message(self, *a):
        pass

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        type(self).gets += 1
        if type(self).mode in ("down", "notready"):
            self._json(503 if type(self).mode == "down" else 200, {"status": "ok", "ready": False})
        else:
            self._json(200, {"status": "ok", "ready": True})

    def do_POST(self):
        type(self).posts += 1
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        mode = type(self).mode
        if self.headers.get("X-Phoneme-Token") != TOKEN or mode == "unauthorized":
            return self._json(401, {"detail": "bad token"})
        if mode == "down":
            return self._json(503, {"detail": "down"})
        if mode == "notready":
            return self._json(200, {"status": "unavailable", "reason": "model_not_ready"})
        if mode == "slow":
            time.sleep(2.0)
        self._json(200, OK_BODY)


class FakeNode:
    def __init__(self, mode="ok"):
        self.handler = type(f"H{id(self)}", (_Handler,), {"mode": mode, "posts": 0, "gets": 0})
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), self.handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def set(self, mode):
        self.handler.mode = mode

    @property
    def posts(self):
        return self.handler.posts

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class FailoverTest(unittest.TestCase):
    def setUp(self):
        remote.reset_state()
        self.env = mock.patch.dict(os.environ, {
            "PHONEME_TOKEN": TOKEN, "PHONEME_REMOTE_URL": "", "PHONEME_REMOTE_URLS": "",
            "PHONEME_REMOTE_TIMEOUT": "1", "PHONEME_REMOTE_BUDGET": "5",
            "PHONEME_BREAKER_FAILS": "2", "PHONEME_BREAKER_COOLDOWN": "60"})
        self.env.start()
        self.prober = mock.patch.object(remote, "_ensure_prober")   # 백그라운드 스레드 대신 probe_resting() 을 직접 부른다
        self.prober.start()
        self.nodes: list[FakeNode] = []

    def tearDown(self):
        self.prober.stop()
        self.env.stop()
        for n in self.nodes:
            n.stop()
        remote.reset_state()

    def use(self, *modes):
        ns = [FakeNode(m) for m in modes]
        self.nodes += ns
        os.environ["PHONEME_REMOTE_URLS"] = ",".join(n.url for n in ns)
        return ns

    def test_first_healthy_node_only(self):
        a, b = self.use("ok", "ok")
        out = remote.analyze(AUDIO, "seat")
        self.assertEqual((out["status"], out["node"]), ("ok", 1))
        self.assertEqual(out["focus"]["word"], "seat")          # 노드 응답은 sanitize 를 거친다
        self.assertEqual(b.posts, 0)

    def test_failover_to_second(self):
        a, b = self.use("down", "ok")
        out = remote.analyze(AUDIO, "seat")
        self.assertEqual((out["status"], out["node"]), ("ok", 2))
        self.assertEqual(out["attempts"][0]["result"], "http_503")

    def test_node_answering_not_ready_fails_over(self):
        a, b = self.use("notready", "ok")
        out = remote.analyze(AUDIO, "seat")
        self.assertEqual((out["status"], out["node"]), ("ok", 2))
        self.assertEqual(out["attempts"][0]["result"], "model_not_ready")

    def test_all_down_is_unavailable_without_raising(self):
        self.use("down", "down")
        out = remote.analyze(AUDIO, "seat")
        self.assertEqual((out["status"], out["reason"]), ("unavailable", "all_nodes_failed"))
        self.assertEqual(len(out["attempts"]), 2)

    def test_breaker_skips_resting_node(self):
        a, b = self.use("down", "ok")
        remote.analyze(AUDIO, "1")
        remote.analyze(AUDIO, "2")                     # a 연속 2회 실패 → 쉼
        before = a.posts
        out = remote.analyze(AUDIO, "3")
        self.assertEqual(out["status"], "ok")
        self.assertEqual(a.posts, before, "쉬는 노드는 요청 경로에서 두드리지 않는다")
        self.assertNotIn("attempts", out)              # 곧바로 b 에서 성공 — 지연이 붙지 않는다
        self.assertEqual(out["node"], 2, "번호는 시도 순서가 아니라 설정 목록 기준")
        self.assertFalse(remote.status()["nodes"][0]["up"])

    def test_half_open_when_all_resting(self):
        (a,) = self.use("down")
        remote.analyze(AUDIO, "1")
        remote.analyze(AUDIO, "2")
        out = remote.analyze(AUDIO, "3")
        self.assertEqual(out["status"], "unavailable")
        self.assertEqual(a.posts, 3, "모두 쉬는 중이면 가장 먼저 풀릴 한 곳만 한 번 시도한다")

    def test_probe_restores_and_traffic_returns_to_first(self):
        a, b = self.use("down", "ok")
        remote.analyze(AUDIO, "1")
        remote.analyze(AUDIO, "2")
        self.assertFalse(remote.status()["nodes"][0]["up"])
        self.assertEqual(remote.probe_resting(), 0)          # 아직 죽어 있으면 되돌리지 않는다
        a.set("ok")
        self.assertEqual(remote.probe_resting(), 1)          # /healthz ready → 복구
        out = remote.analyze(AUDIO, "4")
        self.assertEqual(out["node"], 1, "복구되면 다시 목록 앞의 노드로")

    def test_probe_needs_ready_not_just_200(self):
        (a,) = self.use("down")
        remote.analyze(AUDIO, "1")
        remote.analyze(AUDIO, "2")
        a.set("notready")                                    # 200 이지만 ready=false
        self.assertEqual(remote.probe_resting(), 0)

    def test_bad_token_stops_without_trying_others(self):
        a, b = self.use("unauthorized", "ok")
        out = remote.analyze(AUDIO, "seat")
        self.assertEqual((out["status"], out["reason"]), ("unavailable", "unauthorized"))
        self.assertEqual(b.posts, 0)

    def test_budget_caps_total_wait(self):
        self.use("slow", "slow")
        os.environ.update(PHONEME_REMOTE_TIMEOUT="10", PHONEME_REMOTE_BUDGET="1.5")
        t = time.monotonic()
        out = remote.analyze(AUDIO, "seat")
        self.assertLess(time.monotonic() - t, 3.0)
        self.assertEqual(out["status"], "unavailable")

    def test_inflight_released_on_every_path(self):
        self.use("down", "ok")
        remote.analyze(AUDIO, "seat")
        self.assertTrue(all(n["inflight"] == 0 for n in remote.status()["nodes"]))

    def test_url_rules(self):
        os.environ["PHONEME_REMOTE_URLS"] = ("https://b.ts.net/, http://192.168.0.10:8443, https://a.ts.net,"
                                              "https://b.ts.net, http://100.64.0.2:8443, http://127.0.0.1:8443")
        # LAN·Tailscale IP 평문 http 는 버린다(Render 에서 닿지도 않고, 음성을 평문으로 보내지 않는다)
        self.assertEqual(remote.urls(), ["https://b.ts.net", "https://a.ts.net", "http://127.0.0.1:8443"])

    def test_single_url_backward_compatible(self):
        (a,) = [FakeNode("ok")]
        self.nodes.append(a)
        os.environ["PHONEME_REMOTE_URL"] = a.url
        self.assertEqual(remote.urls(), [a.url])
        self.assertEqual(remote.analyze(AUDIO, "seat")["status"], "ok")

    def test_status_shows_host_only(self):
        os.environ["PHONEME_REMOTE_URLS"] = "https://pc.tail1.ts.net"
        st = remote.status()
        self.assertEqual(st["nodes"][0]["host"], "pc.tail1.ts.net")
        self.assertNotIn("https://", json.dumps(st))
        self.assertNotIn(TOKEN, json.dumps(st))


if __name__ == "__main__":
    unittest.main()
