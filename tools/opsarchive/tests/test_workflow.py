"""자동화 워크플로우 테스트 — 오프라인(네트워크 없음).

`commands.*` 와 `workflow._load_settings`/`workflow._nap` 을 패치해 호출 인자와 흐름만 검증한다.

실행: `tools/opsarchive` 에서
`$env:PYTHONPATH="."; .venv\\Scripts\\python.exe -m unittest tests.test_workflow -v`
"""

from __future__ import annotations

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
            self.assertIn(node["kind"], ("toggle", "number", "choice", "action"), node["id"])
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
        for node_id in ("anchor_interval", "issue_notify", "client_report"):
            self.assertFalse(by_id[node_id]["ok"])

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


if __name__ == "__main__":
    unittest.main()
