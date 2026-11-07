import importlib.util
import unittest
from unittest import mock


SPEC = importlib.util.spec_from_file_location("offsite_anchor", ".github/scripts/offsite_anchor.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class OffsiteAnchorTest(unittest.TestCase):
    def test_health_record_keeps_deploy_but_not_unlisted_secrets(self):
        record = MODULE.health_record({
            "status": "ok",
            "deploy": {"commit": "abc123", "platform": "render"},
            "service_account_private_key": "must-not-appear",
        })
        self.assertEqual(record["public"]["deploy"]["commit"], "abc123")
        self.assertNotIn("status", record["public"])
        self.assertNotIn("service_account_private_key", repr(record))
        self.assertEqual(len(record["sha256"]), 64)

    def test_hosting_record_keeps_hashes_and_security_headers_only(self):
        def fake_fetch(url):
            payload = b"function devOrigin() {}" if url.endswith("/ai.js") else b"public asset " + url.encode()
            return 200, {
                "content-security-policy": "default-src 'self'",
                "cache-control": "no-cache",
                "etag": '"etag"',
                "x-secret": "should-not-be-recorded",
            }, payload

        with mock.patch.object(MODULE, "fetch_bytes", side_effect=fake_fetch):
            record = MODULE.hosting_record("https://example.web.app")

        self.assertEqual(record["base"], "https://example.web.app")
        self.assertEqual(len(record["assets"]), 6)
        self.assertEqual(record["assets"][0]["csp"], "enforce")
        self.assertEqual(record["assets"][0]["cache_control"], "no-cache")
        self.assertNotIn("x-secret", repr(record))
        self.assertEqual(len(record["assets"][0]["sha256"]), 64)

    def test_validate_hosting_accepts_enforced_fresh_guarded_release(self):
        record = {
            "assets": [
                {"path": "/", "status": 200, "csp": "enforce", "cache_control": "no-cache, max-age=0, must-revalidate"},
                {"path": "/index.html", "status": 200, "csp": "enforce", "cache_control": "no-cache"},
                {"path": "/ai.js", "status": 200, "csp": "enforce", "cache_control": "no-cache", "hosted_api_guard": True},
                {"path": "/auth.js", "status": 200, "csp": "enforce", "cache_control": "no-cache"},
                {"path": "/app.js", "status": 200, "csp": "enforce", "cache_control": "no-cache"},
            ]
        }
        MODULE.validate_hosting(record)


if __name__ == "__main__":
    unittest.main()
