"""Firestore 규칙 배포·대조(관리자 도구). 실행: cd tools/opsarchive && python -m unittest tests.test_rules_deploy

firebase CLI·Rules API 는 가짜로 바꾼다 — 실제 프로젝트에는 아무것도 보내지 않는다.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import urllib.error
from unittest import mock

from opsarchive import cli, commands, firebase

PROJECT = "demo-project-123"
RULES = "rules_version = '2';\nservice cloud.firestore {\n  match /databases/{database}/documents {\n    match /users/{uid} { allow read: if false; }\n  }\n}\n"


class Repo:
    """임시 저장소: firebase.json + firestore.rules + .firebaserc."""

    def __init__(self, rules=RULES, conf=None, rc=PROJECT):
        self.root = tempfile.mkdtemp(prefix="rules-")
        conf = conf if conf is not None else {"firestore": [{"database": "(default)", "rules": "firestore.rules"}]}
        with open(os.path.join(self.root, "firebase.json"), "w", encoding="utf-8") as fh:
            json.dump(conf, fh)
        with open(os.path.join(self.root, "firestore.rules"), "w", encoding="utf-8", newline="") as fh:
            fh.write(rules)
        if rc:
            with open(os.path.join(self.root, ".firebaserc"), "w", encoding="utf-8") as fh:
                json.dump({"projects": {"default": rc}}, fh)

    def close(self):
        shutil.rmtree(self.root, ignore_errors=True)


def done(stdout="", code=0, stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=code, stdout=stdout, stderr=stderr)


DEPLOY_OK = ("=== Deploying to 'demo-project-123'...\n\x1b[32m+  cloud.firestore:\x1b[39m rules file firestore.rules compiled successfully\n"
             "i  firestore: uploading rules firestore.rules...\n+  firestore: released rules firestore.rules to cloud.firestore\n+  Deploy complete!\n")


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def rules_api(text, *, status=200, calls=None):
    """Rules API 가짜 opener: release → ruleset 순서로 답한다."""
    def opener(req, timeout):
        if calls is not None:
            calls.append((req.get_method(), req.full_url, req.get_header("Authorization")))
        if status != 200:
            raise urllib.error.HTTPError(req.full_url, status, "x", None, io.BytesIO(b"{}"))
        if "/releases/" in req.full_url:
            return Resp(json.dumps({"rulesetName": "projects/%s/rulesets/abc" % PROJECT,
                                    "updateTime": "2026-10-22T00:43:52Z"}).encode())
        return Resp(json.dumps({"source": {"files": [{"name": "firestore.rules", "content": text}]}}).encode())
    return opener


class TargetTest(unittest.TestCase):
    def test_finds_the_default_database_rules(self):
        repo = Repo()
        try:
            got = firebase.rules_target(repo.root)
            self.assertEqual(os.path.basename(got["rules_file"]), "firestore.rules")
            self.assertEqual(got["database"], "(default)")
        finally:
            repo.close()

    def test_ignores_other_databases_and_rejects_escape(self):
        for conf, code in (({"firestore": [{"database": "other-db", "rules": "firestore.rules"}]}, "no_rules_target"),
                           ({"firestore": [{"database": "(default)", "rules": "../outside.rules"}]}, "no_rules_file"),
                           ({"hosting": {}}, "no_rules_target")):
            repo = Repo(conf=conf)
            try:
                with self.assertRaises(firebase.FirebaseError) as caught:
                    firebase.rules_target(repo.root)
                self.assertEqual(caught.exception.code, code)
            finally:
                repo.close()

    def test_crlf_and_trailing_space_are_the_same_rules(self):
        self.assertEqual(firebase.rules_sha(RULES), firebase.rules_sha(RULES.replace("\n", "  \r\n")))
        self.assertEqual(firebase.rules_sha(RULES), firebase.rules_sha("\ufeff" + RULES))   # 배포본에 남은 BOM
        self.assertNotEqual(firebase.rules_sha(RULES), firebase.rules_sha(RULES.replace("false", "true")))


class DeployTest(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()

    def tearDown(self):
        self.repo.close()

    def test_deploy_pins_project_and_runs_from_repo_root(self):
        with mock.patch.object(firebase, "_bin", return_value="firebase"), \
             mock.patch.object(firebase.subprocess, "run", return_value=done(DEPLOY_OK)) as run:
            got = firebase.rules_deploy(PROJECT, self.repo.root)
        argv, kw = run.call_args[0][0], run.call_args[1]
        self.assertEqual(argv[:4], ["firebase", "deploy", "--only", "firestore:rules"])
        self.assertEqual(argv[argv.index("--project") + 1], PROJECT)       # CLI 에 잡힌 다른 프로젝트로 가지 않는다
        self.assertIn("--non-interactive", argv)
        self.assertNotIn("--dry-run", argv)
        self.assertEqual(kw["cwd"], self.repo.root)                        # firebase.json 이 있는 곳에서
        self.assertFalse(kw["shell"])
        self.assertTrue(got["compiled"] and got["uploaded"] and got["released"] and got["complete"])
        self.assertNotIn("\x1b", got["output"])                            # 색 코드는 걷어낸다

    def test_dry_run_flag(self):
        with mock.patch.object(firebase, "_bin", return_value="firebase"), \
             mock.patch.object(firebase.subprocess, "run",
                               return_value=done("+ rules file firestore.rules compiled successfully\n+ Dry run complete!\n")) as run:
            got = commands.rules_deploy(PROJECT, root=self.repo.root, dry_run=True)
        self.assertIn("--dry-run", run.call_args[0][0])
        self.assertTrue(got["compiled"])
        self.assertFalse(got["released"])
        self.assertIsNone(got["verified"])

    def test_bad_project_id_never_reaches_the_cli(self):
        with mock.patch.object(firebase.subprocess, "run") as run:
            for bad in ("", "Bad_Project", "x; rm -rf /", "--project=evil"):
                got = commands.rules_deploy(bad, root=self.repo.root)
                self.assertEqual(got["error"], "bad_project", bad)
        run.assert_not_called()

    def test_compile_error_is_reported_with_cli_output(self):
        with mock.patch.object(firebase, "_bin", return_value="firebase"), \
             mock.patch.object(firebase.subprocess, "run",
                               return_value=done("Error: Compilation errors in firestore.rules:\n[E] 5:3 - Unexpected 'allow'.", 1)):
            got = commands.rules_deploy(PROJECT, root=self.repo.root)
        self.assertEqual(got["error"], "cli_failed")
        self.assertIn("Unexpected 'allow'", got["detail"])

    def test_verifies_the_release_after_deploy(self):
        """배포 직후 배포본이 아직 옛 규칙이면 잠깐 기다렸다 다시 읽는다 → 같아지면 반영 확인."""
        seen = iter([RULES.replace("false", "true"), RULES])
        sleeps = []

        def status(*a, **k):
            text = next(seen)
            return {"match": firebase.rules_sha(text) == firebase.rules_sha(RULES), "reason": "",
                    "deployed_sha256": firebase.rules_sha(text)[:16], "diff": []}

        with mock.patch.object(firebase, "_bin", return_value="firebase"), \
             mock.patch.object(firebase.subprocess, "run", return_value=done(DEPLOY_OK)), \
             mock.patch.object(commands, "rules_status", side_effect=status):
            got = commands.rules_deploy(PROJECT, "sa.json", root=self.repo.root, token_fn=lambda sa, scope: "tok", sleep=sleeps.append)
        self.assertTrue(got["verified"])
        self.assertNotIn("error", got)
        self.assertEqual(sleeps, [3])

    def test_still_different_after_waiting_is_an_error(self):
        def status(*a, **k):
            return {"match": False, "reason": "", "deployed_sha256": "x", "diff": ["-a", "+b"]}

        with mock.patch.object(firebase, "_bin", return_value="firebase"), \
             mock.patch.object(firebase.subprocess, "run", return_value=done(DEPLOY_OK)), \
             mock.patch.object(commands, "rules_status", side_effect=status):
            got = commands.rules_deploy(PROJECT, "sa.json", root=self.repo.root, verify_seconds=9, token_fn=lambda sa, scope: "tok", sleep=lambda s: None)
        self.assertEqual(got["error"], "deployed_rules_differ")
        self.assertEqual(got["diff"], ["-a", "+b"])

    def test_missing_release_line_still_verifies(self):
        """CLI 문구가 바뀌어 'released rules' 가 없어도, 배포본을 다시 읽어 같으면 성공으로 본다."""
        with mock.patch.object(firebase, "_bin", return_value="firebase"), \
             mock.patch.object(firebase.subprocess, "run", return_value=done("+ compiled successfully\n+ Deploy complete!\n")), \
             mock.patch.object(commands, "rules_status", return_value={"match": True, "reason": "", "deployed_sha256": "x", "diff": []}):
            got = commands.rules_deploy(PROJECT, "sa.json", root=self.repo.root, token_fn=lambda sa, scope: "tok", sleep=lambda s: None)
        self.assertTrue(got["verified"])
        self.assertNotIn("error", got)

    def test_timeout_is_not_called_a_failure_without_checking(self):
        """시간 초과여도 배포가 뒤에서 끝났을 수 있다 — 배포본을 읽어 실제 결과를 함께 알린다."""
        with mock.patch.object(firebase, "_bin", return_value="firebase"), \
             mock.patch.object(firebase.subprocess, "run", side_effect=subprocess.TimeoutExpired("firebase", 180)), \
             mock.patch.object(commands, "rules_status", return_value={"match": True, "reason": "", "deployed_sha256": "x", "diff": []}):
            got = commands.rules_deploy(PROJECT, "sa.json", root=self.repo.root, token_fn=lambda sa, scope: "tok", sleep=lambda s: None)
        self.assertEqual(got["error"], "cli_timeout")
        self.assertTrue(got["verified"])
        self.assertIn("대조", got["detail"])

    def test_transient_read_error_is_retried_but_permission_error_is_not(self):
        flaky = iter([{"match": None, "reason": "rules_http_error", "deployed_sha256": "", "diff": []},
                      {"match": True, "reason": "", "deployed_sha256": "x", "diff": []}])
        sleeps = []
        with mock.patch.object(firebase, "_bin", return_value="firebase"), \
             mock.patch.object(firebase.subprocess, "run", return_value=done(DEPLOY_OK)), \
             mock.patch.object(commands, "rules_status", side_effect=lambda *a, **k: next(flaky)):
            got = commands.rules_deploy(PROJECT, "sa.json", root=self.repo.root, token_fn=lambda sa, scope: "tok", sleep=sleeps.append)
        self.assertTrue(got["verified"])
        self.assertEqual(sleeps, [3])
        forbidden = {"match": None, "reason": "rules_forbidden — 권한", "deployed_sha256": "", "diff": []}
        with mock.patch.object(firebase, "_bin", return_value="firebase"), \
             mock.patch.object(firebase.subprocess, "run", return_value=done(DEPLOY_OK)), \
             mock.patch.object(commands, "rules_status", return_value=forbidden) as st:
            got = commands.rules_deploy(PROJECT, "sa.json", root=self.repo.root, token_fn=lambda sa, scope: "tok", sleep=lambda s: None)
        self.assertEqual(st.call_count, 1)
        self.assertIsNone(got["verified"])
        self.assertNotIn("error", got)          # 배포는 됐다(released) — 확인만 못 했다

    def test_alias_that_points_elsewhere_is_refused(self):
        repo = Repo(rc=None)
        try:
            with open(os.path.join(repo.root, ".firebaserc"), "w", encoding="utf-8") as fh:
                json.dump({"projects": {"default": "other-project-9", "staging-alias": "another-proj"}}, fh)
            with mock.patch.object(firebase.subprocess, "run") as run:
                for alias in ("default", "staging-alias"):
                    self.assertEqual(commands.rules_deploy(alias, root=repo.root)["error"], "project_is_alias", alias)
            run.assert_not_called()
        finally:
            repo.close()

    def test_multiple_databases_in_firebase_json_are_refused(self):
        """`--only firestore:rules` 는 모든 데이터베이스에 배포하는데 확인은 (default) 만 한다 — 말없이 덮어쓰지 않는다."""
        repo = Repo(conf={"firestore": [{"database": "(default)", "rules": "firestore.rules"},
                                        {"database": "other-db", "rules": "firestore.rules"}]})
        try:
            with mock.patch.object(firebase.subprocess, "run") as run:
                got = commands.rules_deploy(PROJECT, root=repo.root)
            self.assertEqual(got["error"], "multiple_rules_targets")
            run.assert_not_called()
        finally:
            repo.close()

    def test_no_release_line_is_not_success(self):
        with mock.patch.object(firebase, "_bin", return_value="firebase"), \
             mock.patch.object(firebase.subprocess, "run", return_value=done("+ compiled successfully\n")):
            got = commands.rules_deploy(PROJECT, root=self.repo.root)
        self.assertEqual(got["error"], "not_released")

    def test_without_service_account_verification_is_skipped_not_faked(self):
        with mock.patch.object(firebase, "_bin", return_value="firebase"), \
             mock.patch.object(firebase.subprocess, "run", return_value=done(DEPLOY_OK)):
            got = commands.rules_deploy(PROJECT, "", root=self.repo.root)
        self.assertIsNone(got["verified"])
        self.assertNotIn("error", got)


class StatusTest(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()

    def tearDown(self):
        self.repo.close()

    def status(self, deployed_text, **kw):
        calls = []
        with mock.patch.object(firebase.urllib.request, "urlopen", rules_api(deployed_text, calls=calls, **kw)):
            got = commands.rules_status(PROJECT, "sa.json", root=self.repo.root, token_fn=lambda sa, scope: "tok")
        return got, calls

    def test_match_reads_the_firestore_release_read_only(self):
        got, calls = self.status(RULES.replace("\n", "\r\n"))
        self.assertTrue(got["match"])
        self.assertEqual([c[0] for c in calls], ["GET", "GET"])
        self.assertIn("/projects/%s/releases/cloud.firestore" % PROJECT, calls[0][1])
        self.assertTrue(calls[1][1].endswith("/projects/%s/rulesets/abc" % PROJECT))
        self.assertEqual(calls[0][2], "Bearer tok")

    def test_console_edit_shows_up_as_drift_with_a_diff(self):
        """관리자가 콘솔에서 규칙을 바꾸면(드리프트) 대조가 다름과 차이를 보여 준다."""
        got, _ = self.status(RULES.replace("allow read: if false;", "allow read: if true;"))
        self.assertFalse(got["match"])
        self.assertTrue(any(ln.startswith("-") and "if true" in ln for ln in got["diff"]), got["diff"])
        self.assertTrue(any(ln.startswith("+") and "if false" in ln for ln in got["diff"]), got["diff"])

    def test_forbidden_is_unknown_not_a_match(self):
        got, _ = self.status(RULES, status=403)
        self.assertIsNone(got["match"])
        self.assertTrue(got["reason"].startswith("rules_forbidden"))
        self.assertIn("firebaserules.viewer", got["reason"])

    def test_named_database_release_keeps_the_slash(self):
        """이름 있는 데이터베이스의 release 는 cloud.firestore/<db> — / 를 %2F 로 바꾸면 API 가 400 을 낸다."""
        calls = []
        firebase.deployed_rules(PROJECT, "tok", database="native-db", opener=rules_api(RULES, calls=calls))
        self.assertTrue(calls[0][1].endswith("/releases/cloud.firestore/native-db"), calls[0][1])

    def test_ansi_including_private_sequences_is_stripped(self):
        self.assertEqual(firebase._ANSI.sub("", "\x1b[?25l\x1b[1mreleased rules\x1b[22m\x1b]8;;http://x\x07ok"), "released rulesok")

    def test_release_from_another_project_is_rejected(self):
        def opener(req, timeout):
            return Resp(json.dumps({"rulesetName": "projects/other/rulesets/zzz"}).encode())
        with mock.patch.object(firebase.urllib.request, "urlopen", opener):
            got = commands.rules_status(PROJECT, "sa.json", root=self.repo.root, token_fn=lambda sa, scope: "tok")
        self.assertEqual(got["reason"], "bad_release")

    def test_reads_firebaserc_default(self):
        self.assertEqual(commands.firebaserc_default(self.repo.root), PROJECT)


class CliTest(unittest.TestCase):
    def test_deploy_asks_for_the_project_id_before_deploying(self):
        with mock.patch("builtins.input", return_value="wrong-project"), \
             mock.patch.object(commands, "rules_deploy") as deploy, \
             mock.patch("sys.stderr", io.StringIO()):
            rc = cli.main(["rules-deploy", "--project", PROJECT])
        self.assertEqual(rc, 1)
        deploy.assert_not_called()

    def test_deploy_runs_when_the_project_id_is_typed(self):
        with mock.patch("builtins.input", return_value=PROJECT), \
             mock.patch.object(commands, "rules_deploy", return_value={"verified": True}) as deploy, \
             mock.patch("sys.stderr", io.StringIO()), mock.patch("sys.stdout", io.StringIO()):
            rc = cli.main(["rules-deploy", "--project", PROJECT, "--sa", "sa.json"])
        self.assertEqual(rc, 0)
        deploy.assert_called_once_with(PROJECT, "sa.json", dry_run=False)


if __name__ == "__main__":
    unittest.main()
