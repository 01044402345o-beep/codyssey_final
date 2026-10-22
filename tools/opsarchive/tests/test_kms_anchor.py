"""Cloud KMS 서명 + 자동 앵커(CI). KMS·Firestore·GitHub·Google 은 모두 가짜 — 실제 호출 없음.

실행: cd tools/opsarchive && python -m unittest tests.test_kms_anchor
"""
from __future__ import annotations

import base64
import importlib.util
import io
import json
import os
import shutil
import tempfile
import unittest
import urllib.error
from unittest import mock

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from opsarchive import chain, commands, container as C, gcp, kms, pins
from tests.test_chain import chain_of

KEY = "projects/demo-project-123/locations/asia-northeast3/keyRings/opsarchive/cryptoKeys/checkpoint-signer/cryptoKeyVersions/1"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeKms:
    """KMS REST 가짜: publicKey·asymmetricSign. 실제 Ed25519 키로 서명한다."""

    def __init__(self, algorithm=kms.ALGORITHM, tamper=False, wrong_name=False):
        self.private = Ed25519PrivateKey.generate()
        self.algorithm = algorithm
        self.tamper = tamper
        self.wrong_name = wrong_name
        self.calls = []

    @property
    def public_raw(self):
        return self.private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)

    def __call__(self, req, timeout):
        self.calls.append((req.get_method(), req.full_url, req.get_header("Authorization")))
        if req.full_url.endswith("/publicKey"):
            pem = self.private.public_key().public_bytes(serialization.Encoding.PEM,
                                                         serialization.PublicFormat.SubjectPublicKeyInfo).decode()
            return Resp(json.dumps({"pem": pem, "algorithm": self.algorithm,
                                    "pemCrc32c": str(kms.crc32c(pem.encode()))}).encode())
        body = json.loads(req.data)
        data = base64.b64decode(body["data"])
        assert int(body["dataCrc32c"]) == kms.crc32c(data)
        sig = self.private.sign(data if not self.tamper else data + b"x")
        return Resp(json.dumps({"name": "other" if self.wrong_name else KEY, "verifiedDataCrc32c": True,
                                "signature": base64.b64encode(sig).decode(),
                                "signatureCrc32c": str(kms.crc32c(sig))}).encode())


def signer(fake):
    return kms.Signer(KEY, access_token="tok", opener=fake)


class KmsSignerTest(unittest.TestCase):
    def test_crc32c_known_vector(self):
        self.assertEqual(kms.crc32c(b"123456789"), 0xE3069283)   # RFC 3720 검사값

    def test_sign_round_trip_and_request_shape(self):
        fake = FakeKms()
        s = signer(fake)
        sig = s.sign(b"hello")
        self.assertTrue(C.verify_signature(fake.public_raw, b"hello", sig))
        self.assertEqual(s.public(), fake.public_raw)
        self.assertTrue(fake.calls[0][1].endswith(KEY + ":asymmetricSign"))
        self.assertEqual(fake.calls[0][2], "Bearer tok")

    def test_rejects_wrong_algorithm_bad_name_tampered_and_misrouted(self):
        with self.assertRaises(kms.KmsError) as c:
            signer(FakeKms(algorithm="EC_SIGN_P256_SHA256")).public()
        self.assertEqual(c.exception.code, "wrong_algorithm")
        with self.assertRaises(kms.KmsError) as c:
            kms.Signer("projects/x/keyRings/y", access_token="t")
        self.assertEqual(c.exception.code, "bad_key_name")
        with self.assertRaises(kms.KmsError) as c:
            signer(FakeKms(tamper=True)).sign(b"m")
        self.assertEqual(c.exception.code, "bad_signature")      # 받은 서명을 다시 검증한다
        with self.assertRaises(kms.KmsError) as c:
            signer(FakeKms(wrong_name=True)).sign(b"m")
        self.assertEqual(c.exception.code, "crc_mismatch")

    def test_forbidden_is_a_code(self):
        def denied(req, timeout):
            raise urllib.error.HTTPError(req.full_url, 403, "x", None, io.BytesIO(b"{}"))
        with self.assertRaises(kms.KmsError) as c:
            kms.Signer(KEY, access_token="t", opener=denied).public()
        self.assertEqual(c.exception.code, "forbidden")

    def test_env_token_for_ci(self):
        with mock.patch.dict(os.environ, {"GCP_ACCESS_TOKEN": "short-lived"}):
            self.assertEqual(gcp.token("env:GCP_ACCESS_TOKEN"), "short-lived")
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(gcp.GcpError) as c:
                gcp.token("env:GCP_ACCESS_TOKEN")
        self.assertEqual(c.exception.code, "no_env_token")


class MultiKeyVerifyTest(unittest.TestCase):
    def setUp(self):
        self.admin_seed = os.urandom(32)
        self.admin = C.sign_public(self.admin_seed)
        self.fake = FakeKms()
        self.metas = chain_of(3)
        state = chain.check_chain(self.metas)
        self.body = lambda seq, count: chain.checkpoint_body(seq=seq, count=count, head_digest=state["head"],
                                                             archive_ids=[m["archive_id"] for m in self.metas],
                                                             created_at=1_761_000_000 + seq)

    def keys(self, with_auto=True):
        pin = {"schema": pins.SCHEMA, "signing_public_key": C.pack_public_key(self.admin)}
        if with_auto:
            pin = pins.add_auto_key(pin, self.fake.public_raw, KEY)
        return pins.signing_keys(pin)

    def test_admin_and_kms_checkpoints_both_verify_and_are_attributed(self):
        s = signer(self.fake)
        cps = [chain.sign_checkpoint(self.admin_seed, self.body(1, 3)),
               chain.sign_checkpoint_with(s.sign, s.public(), self.body(2, 3))]
        result = chain.verify_chain(cps, self.keys(), self.metas)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["signed_by"], {"admin": 1, "auto": 1})

    def test_kms_checkpoint_without_pinned_key_is_rejected(self):
        s = signer(self.fake)
        cps = [chain.sign_checkpoint_with(s.sign, s.public(), self.body(1, 3))]
        result = chain.verify_chain(cps, self.keys(with_auto=False), self.metas)
        self.assertFalse(result["ok"])
        self.assertEqual(result["problems"][0]["issue"], "unknown_signing_key")

    def test_old_single_key_call_still_works(self):
        cps = [chain.sign_checkpoint(self.admin_seed, self.body(1, 3))]
        self.assertTrue(chain.verify_chain(cps, self.admin, self.metas)["ok"])

    def test_add_auto_key_is_idempotent_and_keeps_generation(self):
        pin = {"schema": pins.SCHEMA, "generation": 4, "signing_public_key": C.pack_public_key(self.admin)}
        once = pins.add_auto_key(pin, self.fake.public_raw, KEY)
        twice = pins.add_auto_key(once, self.fake.public_raw, KEY)
        self.assertEqual(len(twice["auto_signing_keys"]), 1)
        self.assertEqual(twice["generation"], 4)
        self.assertEqual(twice["auto_signing_keys"][0]["kms_key"], KEY)


class FakeFirestore:
    """evidence_checkpoints 를 흉내 낸다. 문서 만들기(POST ?documentId=)는 이미 있으면 409."""

    def __init__(self, metas):
        self.metas = metas
        self.checkpoints = {}
        self.calls = []

    def _root(self):
        return "ROOT/"

    def list(self, collection, page_size=300):
        if collection == commands.CHECKPOINTS:
            return [dict(v) for v in self.checkpoints.values()]
        return []

    def _call(self, method, url, body=None):
        path = url[len("ROOT/"):]
        self.calls.append((method, path))
        if method == "POST" and path.startswith(commands.CHECKPOINTS + "?documentId="):
            seq = path.split("=", 1)[1]
            if seq in self.checkpoints:
                err = gcp.GcpError("http_error")
                err.status = 409
                raise err
            self.checkpoints[seq] = gcp.decode_fields(body["fields"])
            return {}
        raise AssertionError(path)


class AutoAnchorTest(unittest.TestCase):
    def setUp(self):
        self.admin_seed = os.urandom(32)
        self.fake = FakeKms()
        self.metas = chain_of(3)
        self.fs = FakeFirestore(self.metas)
        self.env = {"EVIDENCE_PIN_SIGNING_KEYS": json.dumps({
            "admin": C.pack_public_key(C.sign_public(self.admin_seed)),
            "auto": [C.pack_public_key(self.fake.public_raw)]})}
        self.dir = tempfile.mkdtemp(prefix="kms-")
        self.addCleanup(shutil.rmtree, self.dir, True)
        p = [mock.patch.object(commands, "archives", return_value=self.metas),
             mock.patch.object(commands, "chain_entries", return_value=[]),
             mock.patch.object(commands.gcp, "Firestore", return_value=self.fs),
             mock.patch.object(commands.config, "resolve", side_effect=lambda x: x or self.dir)]
        for x in p:
            x.start()
            self.addCleanup(x.stop)

    def run_once(self, **kw):
        return commands.auto_anchor("demo-project-123", "env:GCP_ACCESS_TOKEN", KEY, env=self.env,
                                    signer=signer(self.fake), **kw)

    def test_first_run_anchors_then_next_run_verifies_and_anchors(self):
        first = self.run_once()
        self.assertTrue(first["anchored"])
        self.assertEqual(first["anchor"]["seq"], 1)
        self.assertIn("00000001", self.fs.checkpoints)
        second = self.run_once()
        self.assertTrue(second["verified"], second)
        self.assertEqual(second["verify"]["signed_by"], {"auto": 1})
        self.assertEqual(second["anchor"]["seq"], 2)
        self.assertTrue(all(c[0] == "POST" and "?documentId=" in c[1] for c in self.fs.calls))   # 만들기만(덮어쓰기 불가)

    def test_missing_archive_after_anchor_fails_and_does_not_anchor(self):
        self.run_once()
        self.metas.pop()                                        # 앵커 뒤 아카이브가 사라졌다(삭제 의심)
        result = self.run_once()
        self.assertFalse(result["anchored"])
        self.assertEqual(result["error"], "verify_failed")
        self.assertEqual(len(self.fs.checkpoints), 1)           # 문제를 덮는 새 체크포인트를 만들지 않는다

    def test_stale_anchor_is_flagged(self):
        self.run_once()
        with mock.patch.object(commands.time, "time", return_value=10 ** 10):
            result = self.run_once(max_age_hours=13)
        self.assertFalse(result["anchored"])
        self.assertTrue(any(p.get("issue") == "anchor_stale" for p in result["verify"]["problems"]))

    def test_conflicting_seq_is_retried(self):
        self.fs.checkpoints["00000001"] = {"checkpoint": json.dumps({"seq": 1}), "archive_ids": "null"}   # 다른 실행이 먼저 썼다
        state = chain.check_chain(self.metas)
        s = signer(self.fake)
        real_list = self.fs.list
        calls = {"n": 0}

        def stale_list(collection, page_size=300):
            calls["n"] += 1
            return [] if calls["n"] == 1 else real_list(collection)   # 첫 번째는 낡은 목록 → 409 → 다시
        self.fs.list = stale_list
        out = commands._anchor_firestore(store_=self.fs, metas=self.metas, entries=[], chain_state=state,
                                         sign=lambda b: chain.sign_checkpoint_with(s.sign, s.public(), b))
        self.assertEqual(out["seq"], 2)                         # 낡은 목록으로 1 을 시도 → 409 → 다시 정해 2
        self.assertGreaterEqual(calls["n"], 2)

    def test_pin_variables_are_required(self):
        with self.assertRaises(commands.CommandError):
            commands.pin_from_variables({})
        self.assertEqual(len(commands.pin_from_variables(self.env)["auto_signing_keys"]), 1)

    def test_pin_variables_publish_signing_keys(self):
        pin = pins.add_auto_key({"schema": pins.SCHEMA, "generation": 1, "fingerprint_sha256": "f", "key_id": "k",
                                 "signing_public_key": C.pack_public_key(C.sign_public(self.admin_seed))},
                                self.fake.public_raw, KEY)
        path = os.path.join(self.dir, "pin.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(pin, fh)
        values = commands.pin_variables(path)
        keys = json.loads(values["EVIDENCE_PIN_SIGNING_KEYS"])
        self.assertEqual(keys["auto"], [C.pack_public_key(self.fake.public_raw)])

    def test_kms_pin_add_writes_the_pin(self):
        path = os.path.join(self.dir, "pin.json")
        pins.write(path, {"schema": pins.SCHEMA, "generation": 2,
                          "signing_public_key": C.pack_public_key(C.sign_public(self.admin_seed))})
        out = commands.kms_pin_add(path, KEY, "sa.json", signer=signer(self.fake))
        self.assertTrue(out["test_signature_ok"])
        self.assertEqual(pins.read(path)["auto_signing_keys"][0]["fingerprint_sha256"], C.fingerprint(self.fake.public_raw))


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, ".github", "scripts", name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class WifScriptTest(unittest.TestCase):
    PROVIDER = "projects/123456789/locations/global/workloadIdentityPools/github-pool/providers/github-repo"
    SA = "evidence-anchor@demo-project-123.iam.gserviceaccount.com"

    def test_three_step_exchange(self):
        wif = load_script("gcp_wif_token")
        seen = []

        def opener(req, timeout):
            seen.append((req.full_url, req.data, req.get_header("Authorization")))
            if "token.actions" in req.full_url:
                return Resp(b'{"value": "oidc-jwt"}')
            if "sts.googleapis.com" in req.full_url:
                body = json.loads(req.data)
                assert body["audience"] == "//iam.googleapis.com/" + self.PROVIDER
                assert body["subjectToken"] == "oidc-jwt"
                return Resp(b'{"access_token": "federated"}')
            return Resp(b'{"accessToken": "sa-token"}')
        env = {"ACTIONS_ID_TOKEN_REQUEST_URL": "https://token.actions.example/x?api=1", "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "r"}
        self.assertEqual(wif.access_token(self.PROVIDER, self.SA, env, opener), "sa-token")
        self.assertIn("audience=https%3A%2F%2Fiam.googleapis.com%2Fprojects", seen[0][0])
        self.assertTrue(seen[2][0].endswith(self.SA + ":generateAccessToken"))
        self.assertEqual(seen[2][2], "Bearer federated")

    def test_bad_inputs(self):
        wif = load_script("gcp_wif_token")
        for provider, sa, env in (("x", self.SA, {}), (self.PROVIDER, "nope", {}), (self.PROVIDER, self.SA, {})):
            with self.assertRaises(wif.WifError):
                wif.access_token(provider, sa, env, lambda r, timeout: None)


class IssueScriptTest(unittest.TestCase):
    def test_comments_on_existing_issue_or_opens_one(self):
        issue = load_script("anchor_issue")
        calls = []

        def opener(found):
            def call(req, timeout):
                calls.append((req.get_method(), req.full_url))
                if "/search/issues" in req.full_url:
                    return Resp(json.dumps({"items": found}).encode())
                return Resp(b'{"number": 7}')
            return call
        self.assertEqual(issue.report("o/r", "t", "run", "x", opener([{"title": issue.TITLE, "number": 3}])), "commented #3")
        self.assertTrue(calls[-1][1].endswith("/repos/o/r/issues/3/comments"))
        self.assertEqual(issue.report("o/r", "t", "run", "x", opener([])), "opened #7")

    def test_summary_tolerates_missing_file(self):
        issue = load_script("anchor_issue")
        self.assertIn("결과 파일", issue.summary(os.path.join(tempfile.gettempdir(), "nope-%d.json" % os.getpid())))


if __name__ == "__main__":
    unittest.main()
