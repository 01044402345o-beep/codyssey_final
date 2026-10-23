"""Cloud Run 반영 — 바뀐 키만 고치고(다른 변수·비밀 참조 보존), 새 리비전을 기다리고, 다시 읽어 확인한다.

실제 Cloud Run 대신 REST 호출(cloudrun._call)을 가짜로 바꾼다. gcloud 는 토큰만 받는다(고정 인자).
"""
from __future__ import annotations

import copy
import unittest
from unittest import mock

from opsarchive import cloudrun, workflow

NAME = "projects/p1/locations/asia-northeast3/services/codyssey-api"


class FakeRun:
    def __init__(self, env=None, fail_op=False):
        self.service = {
            "name": NAME, "etag": "e1", "uid": "u", "generation": "3", "uri": "https://api-x.a.run.app",
            "latestReadyRevision": "r3", "conditions": [],
            "template": {"containers": [{"image": "img", "env": list(env or []) + [
                {"name": "GEMINI_API_KEY", "valueSource": {"secretKeyRef": {"secret": "gemini", "version": "latest"}}},
                {"name": "OTHER", "value": "keep"}]}]},
        }
        self.patches, self.fail_op = [], fail_op

    def call(self, method, url, token, body=None):
        assert token == "tok"
        if method == "GET" and url.endswith(NAME):
            return copy.deepcopy(self.service)
        if method == "PATCH":
            self.patches.append(body)
            self.service["template"] = copy.deepcopy(body["template"])
            return {"name": "projects/p1/locations/asia-northeast3/operations/op1", "done": False}
        if method == "GET" and "/operations/" in url:
            return {"done": True, **({"error": {"message": "boom"}} if self.fail_op else {})}
        raise AssertionError((method, url))


class HelpersTest(unittest.TestCase):
    def test_with_env_changes_only_target_keys_and_keeps_secret_refs(self):
        fake = FakeRun([{"name": "EVIDENCE_TTL_DAYS", "value": "30"}])
        body = cloudrun.with_env(fake.service, {"EVIDENCE_TTL_DAYS": "90", "EVIDENCE_NOTIFY": "1"})
        env = {e["name"]: e for e in body["template"]["containers"][0]["env"]}
        self.assertEqual(env["EVIDENCE_TTL_DAYS"]["value"], "90")
        self.assertEqual(env["EVIDENCE_NOTIFY"]["value"], "1")
        self.assertEqual(env["OTHER"]["value"], "keep")
        self.assertIn("valueSource", env["GEMINI_API_KEY"])            # 비밀 참조는 그대로
        self.assertEqual(fake.service["template"]["containers"][0]["env"][0]["value"], "30")   # 원본 불변

    def test_plain_env_skips_secret_refs(self):
        self.assertEqual(cloudrun.plain_env(FakeRun().service), {"OTHER": "keep"})

    def test_service_name_rejects_path_tricks(self):
        self.assertEqual(cloudrun.service_name("p1", "asia-northeast3", "codyssey-api"), NAME)
        for bad in (("p1/x", "r", "s"), ("p", "", "s"), ("p", "r", "s?x=1")):
            with self.assertRaises(cloudrun.CloudRunError):
                cloudrun.service_name(*bad)

    def test_access_token_uses_fixed_argv_only(self):
        seen = {}

        def run(argv, **kw):
            seen["argv"], seen["shell"] = argv, kw.get("shell")
            return mock.Mock(returncode=0, stdout="ya29.token\n")
        with mock.patch.object(cloudrun, "gcloud_bin", return_value=r"C:\sdk\gcloud.cmd"), \
             mock.patch.object(cloudrun.subprocess, "run", side_effect=run):
            self.assertEqual(cloudrun.access_token(), "ya29.token")
        self.assertEqual(seen["argv"][-3:], [r"C:\sdk\gcloud.cmd", "auth", "print-access-token"][-3:])
        self.assertIs(seen["shell"], False)

    def test_update_env_strips_output_fields_keeps_etag_and_waits(self):
        fake = FakeRun()
        with mock.patch.object(cloudrun, "_call", side_effect=fake.call), mock.patch.object(cloudrun.time, "sleep"):
            out = cloudrun.update_env(NAME, {"EVIDENCE_NOTIFY": "0"}, "tok")
        self.assertTrue(out["ok"])
        body = fake.patches[0]
        self.assertEqual(body["etag"], "e1")
        for field in ("uid", "generation", "uri", "latestReadyRevision", "conditions"):
            self.assertNotIn(field, body)

    def test_failed_revision_is_reported(self):
        fake = FakeRun(fail_op=True)
        with mock.patch.object(cloudrun, "_call", side_effect=fake.call), mock.patch.object(cloudrun.time, "sleep"):
            out = cloudrun.update_env(NAME, {"EVIDENCE_NOTIFY": "0"}, "tok")
        self.assertFalse(out["ok"])


class ApplyCloudRunTest(unittest.TestCase):
    def setUp(self):
        self.policy = workflow.load("missing-workflow.json")

    def apply(self, fake, generation=1):
        with mock.patch.object(cloudrun, "_call", side_effect=fake.call), mock.patch.object(cloudrun.time, "sleep"), \
             mock.patch.object(workflow.commands, "health", return_value={"status": "ok", "evidence": {"generation": generation}}):
            return workflow.apply_env_cloudrun(self.policy, project="p1", region="asia-northeast3",
                                               service="codyssey-api", token="tok")

    def test_only_changed_keys_one_revision_verified(self):
        current = [{"name": k, "value": v} for k, v in workflow.desired_env(self.policy).items()]
        current[0]["value"] = "stale"
        fake = FakeRun(current)
        out = self.apply(fake)
        self.assertEqual(len(fake.patches), 1)
        self.assertEqual(out["changed"], [current[0]["name"]])
        self.assertTrue(out["verified"])

    def test_nothing_changed_means_no_revision(self):
        fake = FakeRun([{"name": k, "value": v} for k, v in workflow.desired_env(self.policy).items()])
        out = self.apply(fake)
        self.assertEqual((fake.patches, out["verified"]), ([], True))

    def test_generation_mismatch_on_health(self):
        out = self.apply(FakeRun(), generation=2)
        self.assertIn("EVIDENCE_KEY_GENERATION(/health)", out["mismatch"])
        self.assertFalse(out["verified"])

    def test_secrets_are_never_pushed(self):
        fake = FakeRun()
        self.apply(fake)
        names = {e["name"] for e in fake.patches[0]["template"]["containers"][0]["env"] if "value" in e}
        self.assertNotIn("EVIDENCE_GH_TOKEN", names)


if __name__ == "__main__":
    unittest.main()
