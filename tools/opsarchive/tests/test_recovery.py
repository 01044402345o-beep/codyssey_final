"""복구 키 — 단방향 커밋먼트, 브라우저 봉인과의 형식 호환, 관리자 대조, TLS 규칙."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import unittest
import urllib.request
from unittest import mock

from opsarchive import chain, commands, container as C, tls

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
PROOF_CRYPTO = os.path.join(REPO_ROOT, "mockup", "proof-crypto.js")
KEY = "wrk1-" + "00" * 32
# 브라우저 proof-crypto.js 와 같은 값이어야 한다(mockup/proof-enc.test.js 가 같은 벡터를 검사한다).
COMMITMENT = "cf5d8a7775351fcb9645d58784427a23c988be6a5a3e3c23a892918b8b3651b8"


class CommitmentTest(unittest.TestCase):
    def test_known_vector(self):
        self.assertEqual(chain.recovery_commitment(KEY), COMMITMENT)

    def test_rejects_malformed_key(self):
        for bad in ("", "wrk1-abc", "wrk1-" + "zz" * 32, "00" * 32):
            self.assertEqual(chain.recovery_commitment(bad), "", bad)

    def test_report_with_key_proves_possession_without_echoing_it(self):
        entries = [{"kind": "attempt", "challenge": COMMITMENT, "seq": 1, "digest": "d", "outcome": "pending"}]
        report = chain.challenge_report(entries, KEY, {"head_seq": 5})
        self.assertEqual(report["verdict"], "anchored")
        self.assertTrue(report["key_proven"])
        self.assertNotIn(KEY, json.dumps(report))

    def test_report_with_commitment_only_finds_but_does_not_prove(self):
        entries = [{"kind": "attempt", "challenge": COMMITMENT, "seq": 1, "digest": "d", "outcome": "pending"}]
        report = chain.challenge_report(entries, COMMITMENT, {"head_seq": 5})
        self.assertEqual(report["verdict"], "anchored")
        self.assertFalse(report["key_proven"])

    def test_wrong_key_is_missing_and_bad_shape_is_flagged(self):
        entries = [{"kind": "attempt", "challenge": COMMITMENT, "seq": 1, "digest": "d", "outcome": "pending"}]
        wrong = chain.challenge_report(entries, "wrk1-" + "01" * 32, {"head_seq": 5})
        self.assertEqual(wrong["verdict"], "missing_from_chain")
        self.assertFalse(wrong["key_proven"])
        self.assertEqual(chain.challenge_report(entries, "wrk1-zz", {"head_seq": 5})["verdict"], "bad_recovery_key")


class OpenReportTest(unittest.TestCase):
    def setUp(self):
        self.private, self.public = C.keypair()

    def report(self, key=KEY, commitment=COMMITMENT, trigger="recovery_report"):
        inner = C.seal(json.dumps({"recovery_key": key, "requested_at": "t", "receipt": None}).encode(), self.public)
        return {"trigger": trigger, "extra": {"commitment": commitment, "sealed_recovery_hex": inner.hex()}}

    def test_matching_key_opens(self):
        checked = commands.open_recovery_report(self.report(), self.private)
        self.assertEqual(checked["commitment"], COMMITMENT)
        self.assertEqual(checked["_recovery_key"], KEY)

    def test_key_that_does_not_hash_to_the_commitment_is_rejected(self):
        with self.assertRaises(commands.CommandError) as ctx:
            commands.open_recovery_report(self.report(commitment="9" * 64), self.private)
        self.assertEqual(ctx.exception.code, "recovery_key_mismatch")

    def test_other_archive_is_rejected(self):
        with self.assertRaises(commands.CommandError) as ctx:
            commands.open_recovery_report(self.report(trigger="erase_failed"), self.private)
        self.assertEqual(ctx.exception.code, "not_recovery_report")

    def test_verify_never_returns_the_key(self):
        with mock.patch.object(commands, "decrypt_archive", return_value=self.report()), \
                mock.patch.object(commands.C, "load_private_key", return_value=self.private), \
                mock.patch.object(commands, "verify_chain",
                                  return_value={"ok": True, "challenge_check": {"verdict": "anchored"}}) as verify:
            result = commands.verify_recovery_report("p", "s", "a", "k", "pw", "pin")
        self.assertEqual(verify.call_args.kwargs["challenge"], KEY)
        self.assertTrue(result["ok"])
        self.assertNotIn(KEY, json.dumps(result))


@unittest.skipUnless(shutil.which("node"), "node 필요")
class BrowserSealCompatibilityTest(unittest.TestCase):
    """브라우저 코드가 봉인한 것을 관리자 CLI 의 unseal 로 실제로 연다(명세가 갈라지면 실패한다)."""

    SCRIPT = """
      const PC = require(process.argv[1]);
      (async () => {
        const made = await PC.newRecoveryKey();
        const vector = await PC.commitmentOf(process.argv[3]);
        const r = await PC.sealForAdmin({ recovery_key: made.key, commitment: made.commitment }, process.argv[2]);
        console.log(JSON.stringify({ made, vector, r }));
      })().catch(e => { console.error(e); process.exit(1); });
    """

    def test_browser_seal_opens_in_the_cli(self):
        private, public = C.keypair()
        done = subprocess.run(["node", "-e", self.SCRIPT, PROOF_CRYPTO, C.pack_public_key(public), KEY],
                              capture_output=True, text=True, timeout=60, check=True)
        out = json.loads(done.stdout)
        self.assertTrue(out["r"]["ok"], out["r"])
        self.assertEqual(out["vector"], COMMITMENT)
        self.assertEqual(chain.recovery_commitment(out["made"]["key"]), out["made"]["commitment"])
        raw = out["r"]["sealed"]
        blob = __import__("base64").urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
        self.assertEqual(blob[6:14], C.key_id(public))
        self.assertEqual(json.loads(C.unseal(blob, private))["recovery_key"], out["made"]["key"])
        other, _ = C.keypair()
        with self.assertRaises(C.ContainerError):
            C.unseal(blob, other)


class TlsTest(unittest.TestCase):
    def test_https_and_loopback_only(self):
        for ok in ("https://codyssey-final.onrender.com/health", "http://localhost:8000/health", "http://127.0.0.1/x"):
            self.assertEqual(tls.check_url(ok), ok)
        for bad in ("http://codyssey-final.onrender.com/health", "ftp://x/y", "http://localhost.evil.test/", "x"):
            with self.assertRaises(tls.InsecureUrl, msg=bad):
                tls.check_url(bad)

    def test_context_verifies_and_sets_a_floor(self):
        import ssl
        ctx = tls.context()
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(ctx.check_hostname)
        self.assertGreaterEqual(ctx.minimum_version, ssl.TLSVersion.TLSv1_2)

    def test_redirect_to_plain_http_is_refused(self):
        req = urllib.request.Request("https://a.test/health")
        with self.assertRaises(tls.InsecureUrl):
            tls._NoDowngrade().redirect_request(req, None, 302, "Found", {}, "http://a.test/health")

    def test_health_command_reports_insecure_url(self):
        with self.assertRaises(commands.CommandError) as ctx:
            commands.health("http://codyssey-final.onrender.com")
        self.assertEqual(ctx.exception.code, "insecure_url")


if __name__ == "__main__":
    unittest.main()
