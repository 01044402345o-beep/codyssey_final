"""프록시 뒤에서 속도 제한이 사용자별로 걸리는지.  실행: cd backend && python -m unittest discover -s tests -t ."""
import os
import threading
import unittest
from unittest import mock

from fastapi.testclient import TestClient
from starlette.requests import Request

from app import main


def req(peer, xff=None):
    headers = [(b"x-forwarded-for", xff.encode())] if xff is not None else []
    return Request({"type": "http", "client": (peer, 1234), "headers": headers})


class ClientIp(unittest.TestCase):
    def ip(self, hops, peer, xff=None):
        with mock.patch.object(main, "TRUSTED_PROXY_HOPS", hops):
            return main.client_ip(req(peer, xff))

    def test_default_uses_peer_and_ignores_header(self):
        self.assertEqual(self.ip(0, "10.0.0.5", "1.1.1.1"), "10.0.0.5")

    def test_one_hop_takes_last_entry(self):
        self.assertEqual(self.ip(1, "10.0.0.5", "203.0.113.7"), "203.0.113.7")

    def test_spoofed_leading_entries_are_ignored(self):
        # 사용자가 보낸 X-Forwarded-For 뒤에 프록시가 실제 IP 를 붙인다
        self.assertEqual(self.ip(1, "10.0.0.5", "6.6.6.6, 203.0.113.7"), "203.0.113.7")
        self.assertEqual(self.ip(2, "10.0.0.5", "6.6.6.6, 203.0.113.7, 172.16.0.9"), "203.0.113.7")

    def test_short_or_missing_chain_falls_back_to_peer(self):
        self.assertEqual(self.ip(1, "10.0.0.5"), "10.0.0.5")
        self.assertEqual(self.ip(1, "10.0.0.5", " , "), "10.0.0.5")
        self.assertEqual(self.ip(2, "10.0.0.5", "203.0.113.7"), "10.0.0.5")


class ProxyLog(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(main, "_proxy_logged", False)
        p.start(); self.addCleanup(p.stop)
        self.http = TestClient(main.app)

    def test_health_request_logs_once_with_ips_masked(self):
        with self.assertLogs("app.ratelimit", "INFO") as cm:
            self.http.get("/health", headers={"X-Forwarded-For": "8.8.4.4, 172.16.0.9"})
            self.http.get("/health", headers={"X-Forwarded-For": "1.1.1.1"})
        self.assertEqual(len(cm.output), 1)
        line = cm.output[0]
        self.assertIn("8.8.4.x(공인) , 172.16.0.x(사설)", line)
        self.assertNotIn("8.8.4.4", line)

    def test_not_logged_without_header(self):
        self.http.get("/health")
        self.assertFalse(main._proxy_logged)


class RateLimitBehindProxy(unittest.TestCase):
    def setUp(self):
        main._hits.clear()
        self.addCleanup(main._hits.clear)
        for p in (mock.patch.object(main, "RATE_LIMIT", 2), mock.patch.dict(os.environ, {}, clear=False)):
            p.start(); self.addCleanup(p.stop)
        os.environ.pop("GEMINI_API_KEY", None)   # 키 없음 = 샘플 응답, 외부 호출 없음
        self.http = TestClient(main.app)

    def post(self, xff):
        return self.http.post("/generate", json={"category_id": "restaurant"},
                              headers={"X-Forwarded-For": xff}).status_code

    def test_without_hops_all_users_share_one_bucket(self):
        with mock.patch.object(main, "TRUSTED_PROXY_HOPS", 0):
            self.assertEqual([self.post(f"203.0.113.{i}") for i in range(3)], [200, 200, 429])

    def test_with_hops_each_user_has_own_bucket(self):
        with mock.patch.object(main, "TRUSTED_PROXY_HOPS", 1):
            self.assertEqual([self.post(f"203.0.113.{i}") for i in range(3)], [200, 200, 200])
            # 첫 사용자는 이미 1회 썼다: 한 번 더 허용, 그다음 거절
            self.assertEqual([self.post("203.0.113.0") for _ in range(2)], [200, 429])

    def test_rotating_spoofed_prefix_does_not_bypass(self):
        with mock.patch.object(main, "TRUSTED_PROXY_HOPS", 1):
            codes = [self.post(f"6.6.6.{i}, 203.0.113.50") for i in range(3)]
        self.assertEqual(codes, [200, 200, 429])

    def test_stale_ips_are_dropped_when_many(self):
        old = main.time.time() - main.RATE_WINDOW - 1
        for i in range(10_001):
            main._hits[f"198.51.100.{i}"].append(old)
        with mock.patch.object(main, "TRUSTED_PROXY_HOPS", 1):
            self.assertEqual(self.post("203.0.113.9"), 200)
        self.assertEqual(list(main._hits), ["203.0.113.9"])


class RateLimitThreads(unittest.TestCase):
    """/generate 는 스레드풀에서 동시에 돈다. 오래된 IP 정리와 새 IP 추가가 겹쳐도 죽지 않아야 한다.
    잠금을 빼면 'dictionary changed size during iteration' 이 난다(10/10 3회 재현)."""

    def test_concurrent_cleanup_and_inserts(self):
        main._hits.clear(); self.addCleanup(main._hits.clear)
        old = main.time.time() - main.RATE_WINDOW - 1
        for i in range(10_001):
            main._hits[f"198.51.{i // 250}.{i % 250}"].append(old)
        errors = []

        def worker(base):
            try:
                for i in range(2000):
                    main.rate_limit(req(f"10.{base}.{i // 250}.{i % 250}"))
            except Exception as e:  # noqa: BLE001
                errors.append(repr(e))

        with mock.patch.object(main, "RATE_LIMIT", 10**9):
            ts = [threading.Thread(target=worker, args=(b,)) for b in range(8)]
            for t in ts: t.start()
            for t in ts: t.join()
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
