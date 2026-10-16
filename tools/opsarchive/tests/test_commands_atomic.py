"""commands.deploy 와 anchor 의 원자성·경합 방지 — **오프라인**(네트워크 없음).

- `commands.deploy`: render.service_id / render.deploy 를 patch 해 성공·소프트실패·설정오류 매핑을 본다.
- `commands.anchor`: 잠금(.lock)으로 경합을 막고, 임시 파일+os.replace 로 원자적으로 쓴다.
  gcp.Firestore 와 서명키 로드, archives/chain_entries 는 mock 해 로컬 파일만 검증한다.
- CLI: `deploy` 서브커맨드와 `env-set`(인자 충돌 회귀) 파싱.

실행: `tools/opsarchive` 에서
`$env:PYTHONPATH="."; .venv\\Scripts\\python.exe -m unittest tests.test_commands_atomic -v`
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from opsarchive import cli, commands, container as C


class DeployTest(unittest.TestCase):
    """render 를 patch 해 commands.deploy 의 계약(예외 대신 ok/note, 설정오류는 CommandError)을 본다."""

    def test_success_returns_ok_true(self):
        with mock.patch.object(commands.render, "service_id", return_value="srv-1"), \
             mock.patch.object(commands.render, "deploy",
                               return_value={"ok": True, "note": "재배포 완료"}) as dep:
            out = commands.deploy("codyssey_final")
        self.assertEqual(out, {"service_id": "srv-1", "ok": True, "note": "재배포 완료"})
        self.assertEqual(dep.call_args.args[0], "srv-1")

    def test_soft_failure_is_passed_through(self):
        with mock.patch.object(commands.render, "service_id", return_value="srv-1"), \
             mock.patch.object(commands.render, "deploy",
                               return_value={"ok": False, "note": "재배포가 아직 진행 중입니다"}):
            out = commands.deploy("x")
        self.assertFalse(out["ok"])
        self.assertEqual(out["service_id"], "srv-1")
        self.assertEqual(out["note"], "재배포가 아직 진행 중입니다")

    def test_no_cli_becomes_command_error(self):
        with mock.patch.object(commands.render, "service_id", return_value="srv-1"), \
             mock.patch.object(commands.render, "deploy",
                               side_effect=commands.render.RenderError("no_cli")):
            with self.assertRaises(commands.CommandError) as caught:
                commands.deploy("x")
        self.assertEqual(caught.exception.code, "no_cli")

    def test_not_found_from_service_id_becomes_command_error(self):
        with mock.patch.object(commands.render, "service_id",
                               side_effect=commands.render.RenderError("not_found('x')")):
            with self.assertRaises(commands.CommandError) as caught:
                commands.deploy("x")
        self.assertTrue(str(caught.exception.code).startswith("not_found"))

    def test_timeout_is_forwarded(self):
        with mock.patch.object(commands.render, "service_id", return_value="srv-1"), \
             mock.patch.object(commands.render, "deploy",
                               return_value={"ok": True, "note": ""}) as dep:
            commands.deploy("x", timeout=15)
        self.assertEqual(dep.call_args.kwargs["timeout"], 15)


class EnvSetTest(unittest.TestCase):
    """item 3 확인 — env_set 이 빈 값을 거부하고, 값이 있으면 올리는지(기존 동작 고정)."""

    def test_blank_value_rejected_as_empty_value(self):
        with self.assertRaises(commands.CommandError) as caught:
            commands.env_set("svc", "K", "   ", api_key_value="k")
        self.assertTrue(str(caught.exception.code).startswith("empty_value"))

    def test_non_empty_value_is_pushed(self):
        with mock.patch.object(commands.render, "service_id", return_value="srv"), \
             mock.patch.object(commands.render, "put_env") as put:
            out = commands.env_set("svc", " K ", "v", api_key_value="k")
        put.assert_called_once()
        self.assertEqual(out["key"], "K")
        self.assertEqual(out["value_length"], 1)


class AnchorAtomicTest(unittest.TestCase):
    """anchor 의 잠금·원자적 쓰기 — gcp.Firestore/서명키/목록 조회는 mock 한다."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="opsarchive-atomic-")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.seed, _ = C.sign_keypair()
        self.patches = [
            mock.patch.object(commands.gcp, "Firestore", return_value=mock.MagicMock()),
            mock.patch.object(commands, "archives", return_value=[]),
            mock.patch.object(commands, "chain_entries", return_value=[]),
            mock.patch.object(commands.C, "load_private_key", return_value=self.seed),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def _anchor(self, out_dir):
        return commands.anchor("proj", "sa.json", "sign.key", "phrase", out_dir=out_dir)

    def test_existing_lock_blocks_and_leaves_checkpoint_intact(self):
        checkpoint = os.path.join(self.dir, "1.json")
        with open(checkpoint, "w", encoding="utf-8") as fh:
            fh.write("SENTINEL")
        with open(os.path.join(self.dir, commands.LOCK_NAME), "w", encoding="utf-8") as fh:
            fh.write("held")
        with mock.patch.object(commands, "LOCK_TIMEOUT", 0.2):
            with self.assertRaises(commands.CommandError) as caught:
                self._anchor(self.dir)
        self.assertTrue(str(caught.exception.code).startswith("locked"))
        with open(checkpoint, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "SENTINEL")                 # 기존 파일을 건드리지 않는다

    def test_normal_path_writes_seq_and_leaves_no_temp_or_lock(self):
        out = self._anchor(self.dir)
        self.assertEqual(out["seq"], 1)
        checkpoint = os.path.join(self.dir, "1.json")
        anchor_file = os.path.join(self.dir, "anchors", "1.json")
        self.assertTrue(os.path.exists(checkpoint))
        self.assertTrue(os.path.exists(anchor_file))
        with open(checkpoint, encoding="utf-8") as fh:
            self.assertIn("signature", json.load(fh))               # 완성본이 남는다
        self.assertFalse(os.path.exists(os.path.join(self.dir, commands.LOCK_NAME)))
        leftovers = [n for n in os.listdir(self.dir) if n.startswith(".tmp")]
        self.assertEqual(leftovers, [])                            # 임시 파일이 남지 않는다

    def test_out_dir_is_created_when_missing(self):
        target = os.path.join(self.dir, "nested", "checkpoints")
        self.assertFalse(os.path.exists(target))
        out = self._anchor(target)
        self.assertTrue(os.path.isdir(target))
        self.assertTrue(os.path.exists(os.path.join(target, "%d.json" % out["seq"])))

    def test_failure_releases_lock(self):
        with mock.patch.object(commands.chain, "sign_checkpoint",
                               side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self._anchor(self.dir)
        self.assertFalse(os.path.exists(os.path.join(self.dir, commands.LOCK_NAME)))  # try/finally


class CliParserRegressionTest(unittest.TestCase):
    """deploy 파서가 제대로 붙었는지 / env-set 이 --from-file 없이 파싱되는지(인자 충돌 회귀)."""

    def test_deploy_subcommand_parses(self):
        args = cli.build_parser().parse_args(["deploy", "--service", "x"])
        self.assertEqual(args.cmd, "deploy")
        self.assertEqual(args.service, "x")
        self.assertEqual(args.timeout, 300)

    def test_deploy_timeout_override(self):
        args = cli.build_parser().parse_args(["deploy", "--service", "x", "--timeout", "15"])
        self.assertEqual(args.timeout, 15)

    def test_env_set_parses_without_from_file(self):
        args = cli.build_parser().parse_args(["env-set", "--service", "x", "--key", "K"])
        self.assertEqual(args.cmd, "env-set")
        self.assertEqual(args.from_file, "")
        self.assertFalse(args.stdin)


if __name__ == "__main__":
    unittest.main()
