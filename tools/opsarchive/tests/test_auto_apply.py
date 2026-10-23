"""자동 반영(정책 저장 → Render 반영) — GUI·CLI·TUI 공통 함수와 CLI 명령.

설정은 settings.json 의 auto_apply(기본 켜짐), 환경변수 OPSARCHIVE_AUTO_APPLY 가 있으면 그것이 우선한다.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

from opsarchive import cli, config, workflow


class Isolated(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="opsarchive-auto-")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.p1 = mock.patch.object(config, "config_dir", return_value=self.dir)
        self.p2 = mock.patch.object(config, "settings_path", return_value=os.path.join(self.dir, "settings.json"))
        self.p1.start(); self.p2.start()
        self.addCleanup(self.p1.stop); self.addCleanup(self.p2.stop)
        self.env = mock.patch.dict(os.environ, {}, clear=False)
        self.env.start(); self.addCleanup(self.env.stop)
        os.environ.pop(workflow.AUTO_APPLY_ENV, None)

    def settings_file(self) -> dict:
        with open(config.settings_path(), encoding="utf-8") as fh:
            return json.load(fh)


class StateTest(Isolated):
    def test_default_is_on(self):
        self.assertEqual(workflow.auto_apply_state(), {"on": True, "source": "default"})

    def test_settings_value_is_used_and_persists(self):
        workflow.set_auto_apply(False)
        self.assertEqual(workflow.auto_apply_state(), {"on": False, "source": "settings"})
        workflow.set_auto_apply(True)
        self.assertEqual(workflow.auto_apply_state()["on"], True)

    def test_set_keeps_other_settings_untouched(self):
        with open(config.settings_path(), "w", encoding="utf-8") as fh:
            json.dump({"service": "my_svc", "base_url": "https://x"}, fh)
        workflow.set_auto_apply(False)
        data = self.settings_file()
        self.assertEqual((data["service"], data["base_url"], data["auto_apply"]), ("my_svc", "https://x", False))
        self.assertNotIn("pin_path", data)             # 유도 경로를 파일에 섞어 넣지 않는다

    def test_env_overrides_settings(self):
        workflow.set_auto_apply(True)
        os.environ[workflow.AUTO_APPLY_ENV] = "off"
        self.assertEqual(workflow.auto_apply_state(), {"on": False, "source": "env"})
        out = workflow.set_auto_apply(True)
        self.assertIn("note", out)                     # 환경변수가 우선한다고 알린다
        os.environ[workflow.AUTO_APPLY_ENV] = "1"
        self.assertEqual(workflow.auto_apply_state(), {"on": True, "source": "env"})
        os.environ[workflow.AUTO_APPLY_ENV] = "garbage"
        self.assertEqual(workflow.auto_apply_state()["source"], "settings")   # 모르는 값은 무시


class ValueTest(Isolated):
    def test_parse_rejects_instead_of_silently_resetting(self):
        with self.assertRaises(ValueError):
            workflow.parse_value("daily_cap", "abc")
        with self.assertRaises(ValueError):
            workflow.parse_value("gh_repo", "not a repo; rm -rf")
        with self.assertRaises(ValueError):
            workflow.parse_value("gh_token", "x")        # 비밀 노드는 정책에 값을 두지 않는다
        with self.assertRaises(ValueError):
            workflow.parse_value("no_such_node", "1")
        self.assertIs(workflow.parse_value("issue_notify", "off"), False)
        self.assertEqual(workflow.parse_value("daily_cap", " 9 "), 9)

    def test_set_value_saves_and_reports_change(self):
        policy = workflow.load()
        policy, value, changed = workflow.set_value(policy, "daily_cap", "9")
        self.assertEqual((value, changed), (9, True))
        self.assertEqual(workflow.load()["daily_cap"], 9)
        _, _, changed = workflow.set_value(policy, "daily_cap", "9")
        self.assertFalse(changed)

    def test_auto_targets_are_env_value_nodes_only(self):
        self.assertTrue(workflow.is_auto_target("daily_cap"))
        self.assertFalse(workflow.is_auto_target("gh_token"))      # 비밀: 사람이 가려진 칸으로
        self.assertFalse(workflow.is_auto_target("pubkey"))        # 키: 발행 흐름


class CommitTest(Isolated):
    def test_on_saves_and_applies_once(self):
        calls = []
        out = workflow.commit_change(workflow.load(), "daily_cap", "7", service="svc",
                                     apply_fn=lambda policy, **kw: calls.append((policy["daily_cap"], kw)) or {"verified": True})
        self.assertEqual(out["applied"], "done")
        self.assertEqual(calls[0][0], 7)
        self.assertEqual((calls[0][1]["service"], calls[0][1]["redeploy"]), ("svc", True))

    def test_off_only_saves(self):
        workflow.set_auto_apply(False)
        fn = mock.Mock()
        out = workflow.commit_change(workflow.load(), "daily_cap", "8", service="svc", apply_fn=fn)
        self.assertEqual(out["applied"], "off")
        fn.assert_not_called()
        self.assertEqual(workflow.load()["daily_cap"], 8)

    def test_explicit_apply_flag_wins(self):
        workflow.set_auto_apply(False)
        fn = mock.Mock(return_value={})
        workflow.commit_change(workflow.load(), "daily_cap", "8", service="svc", apply=True, apply_fn=fn)
        fn.assert_called_once()

    def test_non_env_node_is_saved_not_pushed(self):
        fn = mock.Mock()
        node = next(n for n in workflow.NODES if n["kind"] in workflow.VALUE_KINDS and not n.get("env"))
        value = {"toggle": "on", "number": str(node.get("min") or 1)}.get(node["kind"], str(node.get("default")))
        out = workflow.commit_change(workflow.load(), node["id"], value, service="svc", apply_fn=fn)
        self.assertEqual(out["applied"], "not_env_node")
        fn.assert_not_called()


class CliTest(Isolated):
    def run_cli(self, *argv) -> tuple[int, dict]:
        buf = io.StringIO()
        with mock.patch.object(config, "bootstrap", return_value={}), redirect_stdout(buf):
            code = cli.main(list(argv))
        text = buf.getvalue().strip()
        return code, (json.loads(text) if text.startswith("{") else {"raw": text})

    def test_auto_apply_commands(self):
        self.assertEqual(self.run_cli("auto-apply", "status")[1]["on"], True)
        self.assertEqual(self.run_cli("auto-apply", "off")[1], {"on": False, "source": "settings"})
        self.assertEqual(self.run_cli("policy-show")[1]["auto_apply"]["on"], False)

    def test_policy_set_respects_auto_apply(self):
        with mock.patch.object(workflow, "apply_env", return_value={"verified": True}) as fn:
            code, out = self.run_cli("policy-set", "daily_cap", "6", "--service", "svc")
        self.assertEqual((code, out["applied"]), (0, "done"))
        fn.assert_called_once()
        self.run_cli("auto-apply", "off")
        with mock.patch.object(workflow, "apply_env") as fn:
            code, out = self.run_cli("policy-set", "daily_cap", "5")
        self.assertEqual(out["applied"], "off")
        fn.assert_not_called()

    def test_policy_set_bad_value_exit_2(self):
        code, out = self.run_cli("policy-set", "daily_cap", "abc", "--no-apply")
        self.assertEqual(code, 2)
        self.assertIn("bad_number", out["error"])


if __name__ == "__main__":
    unittest.main()
