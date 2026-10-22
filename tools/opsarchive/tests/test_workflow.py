"""자동화 워크플로우 테스트 — 오프라인(네트워크 없음).

`commands.*` 와 `workflow._load_settings`/`workflow._nap` 을 패치해 호출 인자와 흐름만 검증한다.

실행: `tools/opsarchive` 에서
`$env:PYTHONPATH="."; .venv\\Scripts\\python.exe -m unittest tests.test_workflow -v`
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from unittest import mock

from opsarchive import commands, workflow


REQUIRED_IDS = {
    "seal_failures", "daily_cap", "per_uid_seconds", "ttl_days", "issue_notify", "client_report",
    "observe", "iam_check", "pin_check",
    "anchor_interval", "anchor", "verify_chain",
    "include_secrets",
    # 앱(evidence.py)이 실제로 읽는 변수에 대응하는 노드들 — 모두 실제 환경변수에 연결된다(개념 노드 없음).
    "max_bytes", "key_generation", "gh_repo", "gh_token", "pubkey", "max_source_bytes", "max_logs_bytes",
    "iam_check_enabled",
}

SETTINGS = {
    "project_id": "proj-test",
    "sa_path": "sa.json",
    "service": "codyssey_final",
    "base_url": "https://example.test",
    "pin_path": "security/evidence-key-pin.json",
    "checkpoints_dir": "checkpoints",
}


class NodeSchemaTest(unittest.TestCase):
    def test_no_duplicate_ids(self):
        ids = [node["id"] for node in workflow.NODES]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_node_has_required_fields(self):
        for node in workflow.NODES:
            for key in ("id", "label", "group", "kind", "default", "desc", "env", "requires", "redeploy"):
                self.assertIn(key, node, node.get("id"))
            self.assertIn(node["kind"], ("toggle", "number", "choice", "action", "text", "secret", "key"), node["id"])
            self.assertTrue(node["desc"].strip(), node["id"])

    def test_choice_nodes_have_options(self):
        for node in workflow.NODES:
            if node["kind"] == "choice":
                self.assertTrue(node.get("options"), node["id"])
                for key, label in node["options"]:
                    self.assertTrue(str(key) and str(label), node["id"])

    def test_number_nodes_have_min_max(self):
        for node in workflow.NODES:
            if node["kind"] == "number":
                self.assertIn("min", node, node["id"])
                self.assertIn("max", node, node["id"])
                self.assertLess(node["min"], node["max"], node["id"])

    def test_env_names_are_upper_snake(self):
        for node in workflow.NODES:
            env = node.get("env")
            if env:
                self.assertRegex(env, r"^[A-Z][A-Z0-9_]*$", node["id"])

    def test_at_least_three_groups_and_all_required_nodes(self):
        groups = {node["group"] for node in workflow.NODES}
        self.assertGreaterEqual(len(groups), 3)
        self.assertTrue(REQUIRED_IDS.issubset({node["id"] for node in workflow.NODES}))

    def test_defaults_derived_from_nodes(self):
        self.assertEqual(workflow.DEFAULTS["ttl_days"], 90)   # 앱(evidence.py)의 기본 TTL 과 맞춘다
        self.assertEqual(workflow.DEFAULTS["include_secrets"], False)
        self.assertEqual(workflow.DEFAULTS["observe"], "60")
        self.assertEqual(workflow.DEFAULTS["max_bytes"], 1000000)
        self.assertEqual(workflow.DEFAULTS["key_generation"], 1)

    def test_new_nodes_match_app_env_vars(self):
        by_id = {node["id"]: node for node in workflow.NODES}
        max_bytes = by_id["max_bytes"]
        self.assertEqual(max_bytes["kind"], "number")
        self.assertEqual(max_bytes["env"], "EVIDENCE_MAX_BYTES")
        self.assertEqual((max_bytes["min"], max_bytes["max"]), (100000, 10000000))
        self.assertTrue(max_bytes["redeploy"])
        generation = by_id["key_generation"]
        self.assertEqual(generation["kind"], "number")
        self.assertEqual(generation["env"], "EVIDENCE_KEY_GENERATION")
        self.assertEqual((generation["min"], generation["max"]), (1, 100000))
        self.assertTrue(generation["redeploy"])
        self.assertIn("핀 세대", generation["desc"])     # 핀 세대와 같아야 한다는 경고
        # 값이 owner/repo 문자열인 노드는 값을 받지 않고 안내만 한다(env 없음).
        self.assertEqual((by_id["gh_repo"]["kind"], by_id["gh_repo"]["env"]), ("text", "EVIDENCE_GH_REPO"))
        self.assertIn("owner/repo", by_id["gh_repo"]["desc"])
        self.assertEqual((by_id["gh_token"]["kind"], by_id["gh_token"]["env"]), ("secret", "EVIDENCE_GH_TOKEN"))
        self.assertEqual((by_id["pubkey"]["kind"], by_id["pubkey"]["env"]), ("key", "EVIDENCE_PUBKEY"))
        self.assertEqual(by_id["max_source_bytes"]["env"], "EVIDENCE_MAX_SOURCE_BYTES")
        self.assertEqual(by_id["max_logs_bytes"]["env"], "EVIDENCE_MAX_LOGS_BYTES")
        self.assertEqual((by_id["max_source_bytes"]["default"], by_id["max_logs_bytes"]["default"]), (524288, 65536))


class LoadSaveTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="opsarchive-wf-")
        self.path = os.path.join(self.dir, "workflow.json")

    def test_roundtrip(self):
        policy = workflow.load(self.path)
        policy["daily_cap"] = 7
        policy["observe"] = "360"
        saved = workflow.save(policy, self.path)
        self.assertEqual(saved, self.path)
        back = workflow.load(self.path)
        self.assertEqual(back["daily_cap"], 7)
        self.assertEqual(back["observe"], "360")

    def test_missing_file_is_defaults(self):
        self.assertEqual(workflow.load(self.path), workflow.DEFAULTS)

    def test_unknown_keys_dropped_and_missing_filled(self):
        workflow.save({"daily_cap": 9, "bogus": 123, "another": "x"}, self.path)
        back = workflow.load(self.path)
        self.assertNotIn("bogus", back)
        self.assertNotIn("another", back)
        self.assertEqual(back["daily_cap"], 9)
        self.assertEqual(back["include_secrets"], workflow.DEFAULTS["include_secrets"])

    def test_type_errors_revert_to_default(self):
        workflow.save({"seal_failures": "yes", "daily_cap": "abc", "observe": "999"}, self.path)
        back = workflow.load(self.path)
        self.assertEqual(back["seal_failures"], workflow.DEFAULTS["seal_failures"])
        self.assertEqual(back["daily_cap"], workflow.DEFAULTS["daily_cap"])
        self.assertEqual(back["observe"], workflow.DEFAULTS["observe"])

    def test_number_is_clamped_to_range(self):
        workflow.save({"daily_cap": 999999999, "ttl_days": -5}, self.path)
        back = workflow.load(self.path)
        self.assertEqual(back["daily_cap"], 100000)
        self.assertEqual(back["ttl_days"], 1)

    def test_toggle_false_is_preserved(self):
        workflow.save({"include_secrets": False, "seal_failures": False}, self.path)
        back = workflow.load(self.path)
        self.assertFalse(back["include_secrets"])
        self.assertFalse(back["seal_failures"])


class GraphTest(unittest.TestCase):
    def setUp(self):
        self.patcher = mock.patch.object(workflow, "_load_settings", return_value=dict(SETTINGS))
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_edges_reference_existing_ids(self):
        ids = {node["id"] for node in workflow.NODES}
        graph = workflow.graph(workflow.load("missing-workflow.json"))
        self.assertTrue(graph["edges"])
        for src, dst in graph["edges"]:
            self.assertIn(src, ids)
            self.assertIn(dst, ids)

    def test_state_is_non_empty_string(self):
        graph = workflow.graph(workflow.DEFAULTS)
        self.assertEqual(len(graph["nodes"]), len(workflow.NODES))
        for node in graph["nodes"]:
            self.assertIsInstance(node["state"], str)
            self.assertTrue(node["state"])
            self.assertIn(node["group"], [g["name"] for g in graph["groups"]])

    def test_missing_reported_when_settings_absent(self):
        with mock.patch.object(workflow, "_load_settings", return_value={}):
            graph = workflow.graph(workflow.DEFAULTS)
        observe = next(n for n in graph["nodes"] if n["id"] == "observe")
        self.assertIn("project_id", observe["missing"])
        pin = next(n for n in graph["nodes"] if n["id"] == "pin_check")
        self.assertIn("pin_path", pin["missing"])

    def test_toggle_state_korean(self):
        graph = workflow.graph(workflow.DEFAULTS)
        include = next(n for n in graph["nodes"] if n["id"] == "include_secrets")
        self.assertEqual(include["state"], "꺼짐")
        seal = next(n for n in graph["nodes"] if n["id"] == "seal_failures")
        self.assertEqual(seal["state"], "켜짐")


class PlanTest(unittest.TestCase):
    def test_missing_required_settings_mark_not_ok(self):
        with mock.patch.object(workflow, "_load_settings", return_value={}):
            items = workflow.plan(workflow.DEFAULTS)
        observe = next(i for i in items if i["id"] == "observe")
        self.assertFalse(observe["ok"])
        self.assertIn("필수 설정", observe["reason"])

    def test_required_settings_present_marks_runnable_ok(self):
        with mock.patch.object(workflow, "_load_settings", return_value=dict(SETTINGS)):
            items = workflow.plan(workflow.DEFAULTS)
        by_id = {i["id"]: i for i in items}
        for node_id in ("observe", "pin_check", "iam_check", "anchor", "verify_chain"):
            self.assertTrue(by_id[node_id]["ok"], node_id)
            self.assertEqual(by_id[node_id]["reason"], "")

    def test_disabled_toggle_is_not_ok(self):
        with mock.patch.object(workflow, "_load_settings", return_value=dict(SETTINGS)):
            items = workflow.plan(workflow.DEFAULTS)        # include_secrets 기본 꺼짐
        include = next(i for i in items if i["id"] == "include_secrets")
        self.assertFalse(include["ok"])
        self.assertEqual(include["reason"], "꺼짐")

    def test_enabled_env_node_is_ok(self):
        with mock.patch.object(workflow, "_load_settings", return_value=dict(SETTINGS)):
            items = workflow.plan(workflow.DEFAULTS)        # seal_failures/daily_cap 기본 켜짐
        by_id = {i["id"]: i for i in items}
        for node_id in ("seal_failures", "daily_cap", "per_uid_seconds", "ttl_days"):
            self.assertTrue(by_id[node_id]["ok"], node_id)

    def test_info_nodes_are_not_runnable(self):
        with mock.patch.object(workflow, "_load_settings", return_value=dict(SETTINGS)):
            items = workflow.plan(workflow.DEFAULTS)
        by_id = {i["id"]: i for i in items}
        for node_id in ("anchor_interval", "iam_check_enabled", "gh_token", "pubkey"):
            self.assertFalse(by_id[node_id]["ok"], node_id)

    def test_every_plan_item_has_an_action(self):
        with mock.patch.object(workflow, "_load_settings", return_value=dict(SETTINGS)):
            items = workflow.plan(workflow.DEFAULTS)
        for item in items:
            self.assertIn("action", item)
            self.assertIn(item["action"], ("run", "env", "info", "manual"), item["id"])

    def test_runnable_nodes_are_action_run(self):
        with mock.patch.object(workflow, "_load_settings", return_value=dict(SETTINGS)):
            items = workflow.plan(workflow.DEFAULTS)
        by_id = {i["id"]: i for i in items}
        for node_id in ("observe", "pin_check", "iam_check", "anchor", "verify_chain"):
            self.assertEqual(by_id[node_id]["action"], "run", node_id)

    def test_env_nodes_are_action_env(self):
        # 실행이 아니라 '환경변수 밀어넣기' 대상임을 action 으로 구분한다(run_step 은 이들을 실행하지 않는다).
        with mock.patch.object(workflow, "_load_settings", return_value=dict(SETTINGS)):
            items = workflow.plan(workflow.DEFAULTS)
        by_id = {i["id"]: i for i in items}
        for node_id in ("seal_failures", "daily_cap", "per_uid_seconds", "ttl_days",
                        "include_secrets", "max_bytes", "key_generation"):
            self.assertEqual(by_id[node_id]["action"], "env", node_id)

    def test_info_nodes_are_action_info_with_reason(self):
        with mock.patch.object(workflow, "_load_settings", return_value=dict(SETTINGS)):
            items = workflow.plan(workflow.DEFAULTS)
        by_id = {i["id"]: i for i in items}
        for node_id in ("anchor_interval", "iam_check_enabled"):
            self.assertEqual(by_id[node_id]["action"], "info", node_id)
            self.assertFalse(by_id[node_id]["ok"], node_id)
            self.assertEqual(by_id[node_id]["reason"], "안내 노드", node_id)
        # 예전 개념 노드는 이제 실제 환경변수 노드다
        for node_id in ("issue_notify", "client_report", "gh_repo", "max_source_bytes", "max_logs_bytes"):
            self.assertEqual(by_id[node_id]["action"], "env", node_id)
        for node_id in ("gh_token", "pubkey"):
            self.assertEqual(by_id[node_id]["action"], "manual", node_id)

    def test_env_action_node_is_not_locally_runnable(self):
        # action="env" 인 노드는 run_step 이 실행하지 못한다(즉시 not_runnable) — 계획의 ok 와 실제가 어긋나지 않게 구분한다.
        with self.assertRaises(commands.CommandError) as caught:
            workflow.run_step("max_bytes", workflow.DEFAULTS)
        self.assertEqual(caught.exception.code, "not_runnable")

    def test_order_is_policy_then_observe_then_checks_then_anchor_then_verify(self):
        with mock.patch.object(workflow, "_load_settings", return_value=dict(SETTINGS)):
            items = workflow.plan(workflow.DEFAULTS)
        order = [i["id"] for i in items]
        self.assertLess(order.index("seal_failures"), order.index("observe"))
        self.assertLess(order.index("observe"), order.index("pin_check"))
        self.assertLess(order.index("pin_check"), order.index("iam_check"))
        self.assertLess(order.index("iam_check"), order.index("anchor"))
        self.assertLess(order.index("anchor"), order.index("verify_chain"))


class RunStepTest(unittest.TestCase):
    def setUp(self):
        self.patcher = mock.patch.object(workflow, "_load_settings", return_value=dict(SETTINGS))
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.policy = workflow.load("missing-workflow.json")

    def test_observe_passes_policy_minutes(self):
        self.policy["observe"] = "360"
        with mock.patch.object(workflow.commands, "observe_requests",
                               return_value={"verdict": "ok"}) as fn:
            out = workflow.run_step("observe", self.policy)
        self.assertEqual(fn.call_args.args[:3], ("proj-test", "sa.json", "codyssey_final"))
        self.assertEqual(fn.call_args.kwargs["since_minutes"], 360)
        self.assertEqual(out["id"], "observe")
        self.assertEqual(out["label"], "접근로그 관측 창")

    def test_pin_check_uses_settings_paths(self):
        with mock.patch.object(workflow.commands, "check_pin", return_value={"ok": True}) as fn:
            workflow.run_step("pin_check", self.policy)
        self.assertEqual(fn.call_args.args[0], "security/evidence-key-pin.json")
        self.assertEqual(fn.call_args.kwargs["health_url"], "https://example.test")

    def test_iam_check_uses_project_and_sa(self):
        with mock.patch.object(workflow.commands, "iam_check", return_value={"verdict": "ok"}) as fn:
            workflow.run_step("iam_check", self.policy)
        self.assertEqual(fn.call_args.args, ("proj-test", "sa.json"))

    def test_verify_chain_uses_pin_and_out_dir(self):
        with mock.patch.object(workflow.commands, "verify_chain", return_value={"ok": True}) as fn:
            workflow.run_step("verify_chain", self.policy)
        self.assertEqual(fn.call_args.args[:3], ("proj-test", "sa.json", "security/evidence-key-pin.json"))
        self.assertEqual(fn.call_args.kwargs["out_dir"], "checkpoints")

    def test_non_runnable_node_raises(self):
        with self.assertRaises(commands.CommandError) as caught:
            workflow.run_step("daily_cap", self.policy)
        self.assertEqual(caught.exception.code, "not_runnable")

    def test_unknown_node_raises(self):
        with self.assertRaises(commands.CommandError) as caught:
            workflow.run_step("does_not_exist", self.policy)
        self.assertEqual(caught.exception.code, "unknown_node")

    def test_anchor_without_secrets_requires_them(self):
        with mock.patch.object(workflow.commands, "anchor") as fn:
            with self.assertRaises(commands.CommandError) as caught:
                workflow.run_step("anchor", self.policy)
        self.assertEqual(caught.exception.code, "secrets_required")
        fn.assert_not_called()

    def test_anchor_uses_secrets(self):
        with mock.patch.object(workflow.commands, "anchor", return_value={"chain_ok": True}) as fn:
            workflow.run_step("anchor", self.policy,
                              secrets={"sign_key_file": "sign.key", "passphrase": "p"})
        self.assertEqual(fn.call_args.args, ("proj-test", "sa.json", "sign.key", "p"))
        self.assertEqual(fn.call_args.kwargs["out_dir"], "checkpoints")


class PushEnvTest(unittest.TestCase):
    def setUp(self):
        self.policy = workflow.load("missing-workflow.json")

    def test_node_without_env_raises(self):
        with self.assertRaises(commands.CommandError) as caught:
            workflow.push_env("observe", self.policy, service="codyssey_final")
        self.assertEqual(caught.exception.code, "no_env")

    def test_toggle_true_becomes_one(self):
        self.policy["seal_failures"] = True
        with mock.patch.object(workflow.commands, "env_set", return_value={"key": "x"}) as fn:
            out = workflow.push_env("seal_failures", self.policy, service="codyssey_final")
        self.assertEqual(fn.call_args.args, ("codyssey_final", "EVIDENCE_SEAL_FAILURES", "1"))
        self.assertTrue(out["needs_redeploy"])
        self.assertEqual(out["env"], "EVIDENCE_SEAL_FAILURES")

    def test_toggle_false_becomes_zero(self):
        self.policy["include_secrets"] = False
        with mock.patch.object(workflow.commands, "env_set", return_value={}) as fn:
            workflow.push_env("include_secrets", self.policy, service="codyssey_final")
        self.assertEqual(fn.call_args.args, ("codyssey_final", "EVIDENCE_INCLUDE_SECRETS", "0"))

    def test_number_is_stringified(self):
        self.policy["daily_cap"] = 77
        with mock.patch.object(workflow.commands, "env_set", return_value={}) as fn:
            workflow.push_env("daily_cap", self.policy, service="codyssey_final")
        self.assertEqual(fn.call_args.args, ("codyssey_final", "EVIDENCE_DAILY_CAP", "77"))

    def test_needs_redeploy_true_for_env_node(self):
        with mock.patch.object(workflow.commands, "env_set", return_value={}):
            out = workflow.push_env("daily_cap", self.policy, service="codyssey_final")
        self.assertTrue(out["needs_redeploy"])        # daily_cap 은 재배포가 필요하다

    def test_new_env_nodes_are_pushable(self):
        self.policy["max_bytes"] = 2000000
        with mock.patch.object(workflow.commands, "env_set", return_value={}) as fn:
            out = workflow.push_env("max_bytes", self.policy, service="codyssey_final")
        self.assertEqual(fn.call_args.args, ("codyssey_final", "EVIDENCE_MAX_BYTES", "2000000"))
        self.assertTrue(out["needs_redeploy"])
        self.policy["key_generation"] = 3
        with mock.patch.object(workflow.commands, "env_set", return_value={}) as fn2:
            workflow.push_env("key_generation", self.policy, service="codyssey_final")
        self.assertEqual(fn2.call_args.args, ("codyssey_final", "EVIDENCE_KEY_GENERATION", "3"))

    def test_info_nodes_have_no_env(self):
        for node_id in ("anchor_interval", "iam_check_enabled"):
            with self.assertRaises(commands.CommandError) as caught:
                workflow.push_env(node_id, self.policy, service="codyssey_final")
            self.assertEqual(caught.exception.code, "no_env", node_id)

    def test_former_concept_nodes_push_real_env(self):
        self.policy.update({"issue_notify": False, "client_report": False, "gh_repo": "owner/private-repo"})
        for node_id, env, value in (("issue_notify", "EVIDENCE_NOTIFY", "0"),
                                    ("client_report", "EVIDENCE_CLIENT_REPORTS", "0"),
                                    ("gh_repo", "EVIDENCE_GH_REPO", "owner/private-repo")):
            with mock.patch.object(workflow.commands, "env_set", return_value={}) as fn:
                workflow.push_env(node_id, self.policy, service="codyssey_final")
            self.assertEqual(fn.call_args.args, ("codyssey_final", env, value), node_id)

    def test_secret_is_never_stored_and_key_goes_through_publish(self):
        self.assertIsNone(workflow._normalize({"gh_token": "ghp_secret"})["gh_token"])   # 정책 파일에 남지 않는다
        with mock.patch.object(workflow.commands, "env_set", return_value={}) as fn:
            workflow.push_env("gh_token", self.policy, service="codyssey_final", secret_value="tok")
        self.assertEqual(fn.call_args.args, ("codyssey_final", "EVIDENCE_GH_TOKEN", "tok"))
        with self.assertRaises(commands.CommandError) as caught:
            workflow.push_env("pubkey", self.policy, service="codyssey_final")
        self.assertTrue(caught.exception.code.startswith("use_publish"))

    def test_bad_repo_text_is_rejected(self):
        self.assertEqual(workflow._normalize({"gh_repo": "not a repo; rm -rf"})["gh_repo"], "")
        self.assertEqual(workflow._normalize({"gh_repo": "a/b"})["gh_repo"], "a/b")


class FakeRender:
    """Render 환경변수 저장소 + 재배포 가짜."""

    def __init__(self, env=None, deploy_ok=True, drop=()):
        self.env = dict(env or {})
        self.deploy_ok = deploy_ok
        self.drop = set(drop)          # 재배포 뒤 이 키는 다른 값으로 보인다(반영 실패 흉내)
        self.puts, self.deploys = [], 0

    def service_id(self, name):
        return "srv-1"

    def get_env(self, sid, key, api_key_value=None):
        if self.deploys and key in self.drop:
            return "other"
        return self.env.get(key)

    def put_env(self, sid, key, value, api_key_value=None):
        self.puts.append(key)
        self.env[key] = value

    def deploy(self, sid, timeout=300):
        self.deploys += 1
        return {"ok": self.deploy_ok, "note": "재배포 완료" if self.deploy_ok else "실패"}


class ApplyEnvTest(unittest.TestCase):
    def setUp(self):
        self.policy = workflow.load("missing-workflow.json")

    def run_apply(self, fake, **kw):
        from opsarchive import render
        with mock.patch.multiple(render, service_id=fake.service_id, get_env=fake.get_env, put_env=fake.put_env,
                                 deploy=fake.deploy), \
             mock.patch.object(workflow.commands, "health", return_value={"status": "ok", "evidence": {"generation": 1}}):
            return workflow.apply_env(self.policy, service="codyssey_final", base_url="https://x", **kw)

    def test_only_changed_values_are_pushed_then_one_redeploy_and_verified(self):
        current = workflow.desired_env(self.policy)
        current["EVIDENCE_DAILY_CAP"] = "9"            # Render 에는 옛 값
        fake = FakeRender(current)
        out = self.run_apply(fake)
        self.assertEqual(fake.puts, ["EVIDENCE_DAILY_CAP"])
        self.assertEqual(fake.deploys, 1)
        self.assertTrue(out["verified"])
        self.assertNotIn("error", out)

    def test_nothing_changed_means_no_redeploy(self):
        fake = FakeRender(workflow.desired_env(self.policy))
        out = self.run_apply(fake)
        self.assertEqual((fake.puts, fake.deploys, out["verified"]), ([], 0, True))

    def test_value_not_applied_after_redeploy_is_an_error(self):
        fake = FakeRender({}, drop={"EVIDENCE_TTL_DAYS"})
        out = self.run_apply(fake)
        self.assertFalse(out["verified"])
        self.assertIn("EVIDENCE_TTL_DAYS", out["error"])

    def test_failed_redeploy_is_not_verified(self):
        out = self.run_apply(FakeRender({}, deploy_ok=False))
        self.assertTrue(out["error"].startswith("redeploy_unconfirmed"))

    def test_generation_mismatch_on_health_is_caught(self):
        self.policy["key_generation"] = 2
        fake = FakeRender({})
        out = self.run_apply(fake)
        self.assertIn("EVIDENCE_KEY_GENERATION(/health)", out["mismatch"])

    def test_values_only_without_redeploy(self):
        fake = FakeRender({})
        out = self.run_apply(fake, redeploy=False)
        self.assertEqual(fake.deploys, 0)
        self.assertIsNone(out["verified"])
        self.assertIn("재배포", out["note"])

    def test_secret_value_is_pushed_but_not_reported(self):
        fake = FakeRender(workflow.desired_env(self.policy))
        out = self.run_apply(fake, node_ids=[], secrets={"EVIDENCE_GH_TOKEN": "ghp_xyz"})
        self.assertEqual(fake.env["EVIDENCE_GH_TOKEN"], "ghp_xyz")
        self.assertEqual(out["changed"], ["EVIDENCE_GH_TOKEN(비밀)"])
        self.assertNotIn("ghp_xyz", json.dumps(out, ensure_ascii=False))

    def test_empty_text_node_is_not_pushed(self):
        self.assertNotIn("EVIDENCE_GH_REPO", workflow.desired_env(self.policy))    # 빈 저장소 이름으로 덮지 않는다


class AutomationLoopTest(unittest.TestCase):
    def setUp(self):
        self.patcher = mock.patch.object(workflow, "_load_settings", return_value=dict(SETTINGS))
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.nap = mock.patch.object(workflow, "_nap", return_value=False)
        self.nap.start()
        self.addCleanup(self.nap.stop)
        self.policy = workflow.load("missing-workflow.json")

    def test_max_cycles_stops_the_loop(self):
        good = {"id": "observe", "label": "x", "result": {"verdict": "ok", "ok": True}}
        with mock.patch.object(workflow, "run_step", return_value=good):
            out = workflow.automation_loop(self.policy, max_cycles=2)
        self.assertEqual(out["cycles"], 2)

    def test_pre_set_stop_event_runs_zero_cycles(self):
        event = threading.Event()
        event.set()
        with mock.patch.object(workflow, "run_step") as fn:
            out = workflow.automation_loop(self.policy, stop_event=event)
        self.assertEqual(out["cycles"], 0)
        fn.assert_not_called()

    def test_run_step_exception_does_not_kill_loop(self):
        with mock.patch.object(workflow, "run_step", side_effect=RuntimeError("boom")):
            out = workflow.automation_loop(self.policy, max_cycles=2)
        self.assertEqual(out["cycles"], 2)
        self.assertTrue(out["violations"])

    def test_violation_is_recorded(self):
        bad = {"id": "observe", "label": "x", "result": {"verdict": "missing_attempts", "ok": False}}
        with mock.patch.object(workflow, "run_step", return_value=bad):
            out = workflow.automation_loop(self.policy, max_cycles=1)
        self.assertEqual(out["cycles"], 1)
        self.assertTrue(any("관측 위반" in v for v in out["violations"]))

    def test_logs_are_emitted(self):
        lines: list[str] = []
        good = {"id": "observe", "label": "x", "result": {"verdict": "ok", "ok": True}}
        with mock.patch.object(workflow, "run_step", return_value=good):
            workflow.automation_loop(self.policy, on_log=lines.append, max_cycles=1)
        self.assertTrue(any("주기 1 시작" in line for line in lines))

    @staticmethod
    def _runner(overrides):
        def run(node_id, *args, **kwargs):
            result = overrides.get(node_id, {"ok": True})
            return {"id": node_id, "label": node_id, "result": result}
        return run

    def test_notices_key_is_always_present(self):
        good = {"id": "observe", "label": "x", "result": {"verdict": "ok", "ok": True}}
        with mock.patch.object(workflow, "run_step", return_value=good):
            out = workflow.automation_loop(self.policy, max_cycles=1)
        self.assertIn("notices", out)
        self.assertEqual(out["notices"], [])

    def test_pin_check_ok_none_is_a_notice_not_a_violation(self):
        # 핀 미활성(armed=False) → ok=None. 위반은 아니지만 '확인 못 함'으로 남겨야 한다.
        runner = self._runner({"pin_check": {"ok": None, "armed": False, "reasons": ["unarmed"]}})
        with mock.patch.object(workflow, "run_step", side_effect=runner):
            out = workflow.automation_loop(self.policy, max_cycles=1)
        self.assertTrue(any("pin_check" in n for n in out["notices"]))
        self.assertFalse(any("pin_check" in v for v in out["violations"]))

    def test_observe_empty_result_is_a_notice(self):
        runner = self._runner({"observe": {}})
        with mock.patch.object(workflow, "run_step", side_effect=runner):
            out = workflow.automation_loop(self.policy, max_cycles=1)
        self.assertEqual(out["violations"], [])
        self.assertTrue(any("observe" in n for n in out["notices"]))

    def test_clear_failure_is_violation_not_notice(self):
        runner = self._runner({"pin_check": {"ok": False}})
        with mock.patch.object(workflow, "run_step", side_effect=runner):
            out = workflow.automation_loop(self.policy, max_cycles=1)
        self.assertTrue(any("pin_check" in v for v in out["violations"]))
        self.assertFalse(any("pin_check" in n for n in out["notices"]))

    def test_notices_are_logged_with_caution_prefix(self):
        lines: list[str] = []
        runner = self._runner({"pin_check": {"ok": None, "armed": False, "reasons": ["unarmed"]}})
        with mock.patch.object(workflow, "run_step", side_effect=runner):
            workflow.automation_loop(self.policy, on_log=lines.append, max_cycles=1)
        self.assertTrue(any(line.startswith("주의:") for line in lines))


if __name__ == "__main__":
    unittest.main()
