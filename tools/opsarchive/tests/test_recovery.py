"""복구 키 — 단방향 커밋먼트, 브라우저 봉인과의 형식 호환, 관리자 대조, TLS 규칙."""

from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
import unittest
import urllib.error
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


class AvalancheTest(unittest.TestCase):
    """입력 한 글자·한 비트 변경 → 해시 비트의 평균 50% 가 뒤집혀야 한다.

    평균만 본다. 개별 값은 128±8비트로 흩어지는 것이 정상이라 "매번 50% 이상"은 좋은 해시도 떨어진다.
    시드를 고정해 결과가 매번 같다.
    """

    @staticmethod
    def flipped(a: str, b: str) -> int:
        return bin(int(a, 16) ^ int(b, 16)).count("1")

    def assert_avalanche(self, samples: list) -> None:
        self.assertNotIn(0, samples, "같은 해시가 나오면 안 된다")
        mean = sum(samples) / len(samples) / 256 * 100
        self.assertGreater(mean, 49.0)
        self.assertLess(mean, 51.0)

    def test_one_hex_character_of_the_key(self):
        rng = random.Random(20261107)
        samples = []
        for _ in range(50):
            text = rng.randbytes(32).hex()
            base = chain.recovery_commitment("wrk1-" + text)
            for i, ch in enumerate(text):
                other = rng.choice([c for c in "0123456789abcdef" if c != ch])
                samples.append(self.flipped(base, chain.recovery_commitment("wrk1-" + text[:i] + other + text[i + 1:])))
        self.assert_avalanche(samples)

    def test_one_bit_of_the_key(self):
        rng = random.Random(20261108)
        samples = []
        for _ in range(20):
            raw = bytearray(rng.randbytes(32))
            base = chain.recovery_commitment("wrk1-" + raw.hex())
            for bit in range(256):
                raw[bit // 8] ^= 1 << (bit % 8)
                samples.append(self.flipped(base, chain.recovery_commitment("wrk1-" + raw.hex())))
                raw[bit // 8] ^= 1 << (bit % 8)
        self.assert_avalanche(samples)


class SealedTamperTest(unittest.TestCase):
    def test_flipping_any_byte_of_the_envelope_is_rejected(self):
        """AES-GCM 암호문은 해시와 달리 한 비트 변경이 그 자리만 바꾼다. 변조를 잡는 것은 인증 태그다."""
        private, public = C.keypair()
        blob = C.seal(json.dumps({"recovery_key": KEY}).encode(), public)
        for i in range(len(blob)):
            bad = bytearray(blob)
            bad[i] ^= 1
            with self.assertRaises(C.ContainerError, msg="byte %d" % i):
                C.unseal(bytes(bad), private)


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
                                  return_value={"ok": True, "challenge_check": {"verdict": "anchored", "key_proven": True}}) as verify:
            result = commands.verify_recovery_report("p", "s", "a", "k", "pw", "pin")
        self.assertEqual(verify.call_args.kwargs["challenge"], KEY)
        self.assertTrue(result["ok"])
        self.assertNotIn(KEY, json.dumps(result))

    def test_entry_after_the_anchor_is_not_trusted_even_if_the_key_matches(self):
        """침해된 앱은 자기 복구 키로 체인에 새 시도를 쓸 수 있다 — 앵커 밖이면 키가 맞아도 믿지 않는다."""
        with mock.patch.object(commands, "decrypt_archive", return_value=self.report()), \
                mock.patch.object(commands.C, "load_private_key", return_value=self.private), \
                mock.patch.object(commands, "verify_chain",
                                  return_value={"ok": True, "challenge_check": {"verdict": "after_anchor", "key_proven": True}}):
            result = commands.verify_recovery_report("p", "s", "a", "k", "pw", "pin")
        self.assertFalse(result["ok"])
        self.assertTrue(result["note"])


@unittest.skipUnless(shutil.which("node"), "node 필요")
class BrowserSealCompatibilityTest(unittest.TestCase):
    """브라우저 코드가 봉인한 것을 관리자 CLI 의 unseal 로 실제로 연다(명세가 갈라지면 실패한다)."""

    SCRIPT = """
      const PC = require(process.argv[1]);
      (async () => {
        const made = await PC.newRecoveryKey();
        const vector = await PC.commitmentOf(process.argv[3]);
        const r = await PC.sealForAdmin({ recovery_key: made.key, commitment: made.commitment }, process.argv[2], process.argv[4]);
        console.log(JSON.stringify({ made, vector, r }));
      })().catch(e => { console.error(e); process.exit(1); });
    """

    def test_browser_seal_opens_in_the_cli(self):
        private, public = C.keypair()
        done = subprocess.run(["node", "-e", self.SCRIPT, PROOF_CRYPTO, C.pack_public_key(public), KEY, C.fingerprint(public)],
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


class _Res:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


class PinRouteTest(unittest.TestCase):
    """침해된 앱은 /health 에는 맞는 지문을 보이고 /withdraw/recovery-key 로만 다른 키를 줄 수 있다."""

    def setUp(self):
        _, self.public = C.keypair()
        self.pin = {"schema": 1, "armed": True, "fingerprint_sha256": C.fingerprint(self.public), "generation": 1,
                    "health_url": "https://app.test"}
        self.health = {"evidence": {"fingerprint": C.fingerprint(self.public), "generation": 1}}

    def run_check(self, recovery):
        def opener(url, timeout=20):
            if url.endswith("/health"):
                return _Res(self.health)
            if isinstance(recovery, Exception):
                raise recovery
            return _Res(recovery)

        with mock.patch.object(commands.pins, "read", return_value=self.pin), \
                mock.patch.object(commands.config, "resolve", side_effect=lambda p: p), \
                mock.patch.object(tls, "open_url", side_effect=opener):
            return commands.check_pin("pin.json")

    def test_same_key_passes(self):
        result = self.run_check({"public_key": C.pack_public_key(self.public)})
        self.assertTrue(result["ok"], result)

    def test_other_key_on_the_recovery_route_fails_even_with_a_good_health(self):
        _, attacker = C.keypair()
        result = self.run_check({"public_key": C.pack_public_key(attacker)})
        self.assertFalse(result["ok"])
        self.assertIn("recovery_key_mismatch", result["reasons"])

    def test_route_absent_or_off_is_not_a_failure(self):
        for code in (404, 503):
            gone = urllib.error.HTTPError("https://app.test", code, "x", {}, None)
            self.assertTrue(self.run_check(gone)["ok"], code)

    def test_other_errors_fail_closed(self):
        gone = urllib.error.HTTPError("https://app.test", 500, "x", {}, None)
        self.assertFalse(self.run_check(gone)["ok"])


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
