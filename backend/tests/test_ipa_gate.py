"""발음기호 1회 질문의 서버 저장 — 계정/IP 기준, 원본 IP 미저장, 만료, 프록시 IP 로 묶이지 않음."""
from __future__ import annotations

import importlib
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Path(self.tmp.name) / "gate.json"
        self.env = mock.patch.dict(os.environ, {"IPA_GATE_STORE": str(self.store)})
        self.env.start()
        import app.ipa_gate as m
        self.m = importlib.reload(m)

    def tearDown(self) -> None:
        self.env.stop()
        self.tmp.cleanup()


class StoreTest(Base):
    def test_marked_once_per_uid(self) -> None:
        m = self.m
        self.assertIsNone(m.seen("u1", "1.1.1.1"))
        m.mark("u1", "1.1.1.1", "course")
        self.assertEqual(m.seen("u1", "9.9.9.9"), "course")     # 계정은 IP 가 달라도 기억한다
        self.assertIsNone(m.seen("u2", "1.1.1.1"))

    def test_guest_uses_ip(self) -> None:
        m = self.m
        m.mark("", "2.2.2.2", "known")
        self.assertEqual(m.seen("", "2.2.2.2"), "known")
        self.assertIsNone(m.seen("", "3.3.3.3"))

    def test_guest_without_trusted_ip_is_not_stored(self) -> None:
        # 프록시 뒤라 IP 를 믿을 수 없으면('') 게스트는 서버에 기억하지 않는다 — 브라우저 칸만 쓴다
        m = self.m
        m.mark("", "", "known")
        self.assertIsNone(m.seen("", ""))
        self.assertFalse(self.store.exists())

    def test_raw_ip_not_stored(self) -> None:
        self.m.mark("", "203.0.113.7", "known")
        text = self.store.read_text()
        self.assertNotIn("203.0.113.7", text)
        self.assertNotIn("203.0", text)

    def test_expired_is_forgotten(self) -> None:
        m = self.m
        m.mark("u9", "4.4.4.4", "known")
        data = m._load()
        for k in data:
            data[k]["at"] = time.time() - m.TTL_SECONDS - 10
        m._save(data)
        self.assertIsNone(m.seen("u9", "4.4.4.4"))

    def test_bad_value_falls_back_to_known(self) -> None:
        self.m.mark("u3", "5.5.5.5", "<script>")
        self.assertEqual(self.m.seen("u3", "5.5.5.5"), "known")

    def test_invalid_uid_is_ignored(self) -> None:
        m = self.m
        self.assertEqual(m._uid("../../etc/passwd"), "")
        self.assertEqual(m._uid("a" * 200), "")
        self.assertEqual(m._uid("okUid_1-2"), "okUid_1-2")


class EndpointTest(Base):
    def setUp(self) -> None:
        super().setUp()
        from app import main
        self.main = main
        self.http = TestClient(main.app)

    def test_round_trip(self) -> None:
        self.assertFalse(self.http.get("/ipa/gate").json()["seen"])
        self.assertEqual(self.http.post("/ipa/gate", json={"value": "course"}).json()["value"], "course")
        self.assertEqual(self.http.get("/ipa/gate").json(), {"seen": True, "value": "course"})

    def test_managed_platform_without_proxy_hops_does_not_share_guests(self) -> None:
        # Render 인데 TRUSTED_PROXY_HOPS=0 이면 모든 게스트가 프록시 IP 하나로 보인다.
        # 한 사람이 답했다고 다른 사람에게 다시 안 묻는 일이 없어야 한다(계정은 그대로 기억).
        with mock.patch.dict(os.environ, {"RENDER": "true"}), mock.patch.object(self.main, "TRUSTED_PROXY_HOPS", 0):
            self.http.post("/ipa/gate", json={"value": "known"})
            self.assertFalse(self.http.get("/ipa/gate").json()["seen"])
            self.http.post("/ipa/gate", json={"uid": "acct1", "value": "known"})
            self.assertTrue(self.http.get("/ipa/gate", params={"uid": "acct1"}).json()["seen"])


if __name__ == "__main__":
    unittest.main()
