"""사용자 데이터 탭(관리자) — 조회·상세·통역 기록·내보내기·삭제·열람 기록.

Firestore·Auth 는 가짜로 바꾼다. 실행: cd tools/opsarchive && python -m unittest tests.test_users
"""
from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import unittest
import urllib.error
from unittest import mock

from opsarchive import users

UID = "uidAlice_123"
EMAIL = "alice@example.com"
CITY = "보스턴"
SECRET_LINE = "제 카드 번호는 비밀이에요"


def sv(value):
    return {"stringValue": json.dumps(value, ensure_ascii=False)}


DOC = {
    "name": "projects/p/databases/(default)/documents/users/" + UID,
    "createTime": "2026-10-01T00:00:00Z", "updateTime": "2026-10-22T01:00:00Z",
    "fields": {
        "session": sv({"v": 1, "at": 1, "done": {"2026-10-20": 1, "2026-10-21": 2}, "screen": "u-home"}),
        "weak": sv([{"situation": "주문", "en": "Water", "ko": "물"}]),
        "consent": sv({"version": 6, "voice": True, "at": "2026-10-15T00:00:00Z"}),
        "trip": sv({"country": "미국", "cities": [{"name": CITY, "start": "2026-11-10", "end": "2026-11-12"}], "studyStart": "2026-10-01"}),
        "ilog": sv({"v": 1, "consent": {"version": "2026-10-22", "at": 1761100000000},
                    "list": [{"id": "s1", "at": 1761100000000, "a": "ko", "b": "en", "trip": {"route": "미국 · " + CITY},
                              "lines": [{"src": SECRET_LINE, "dst": "My card number is secret", "s": "ko", "t": "en", "at": 1761100001000},
                                        {"src": "OK.", "dst": "알겠어요.", "s": "en", "t": "ko", "at": 1761100002000}]}]}),
    },
}


class FakeStore:
    """gcp.Firestore 자리 — 경로별 응답을 돌려주고 호출을 기록한다."""

    def __init__(self, docs=None, deleted=(), pages=None):
        self.docs = dict(docs or {})
        self.deleted = set(deleted)
        self.pages = pages
        self.calls = []

    def _root(self):
        return "ROOT/"

    def _call(self, method, url, body=None):
        from opsarchive import gcp
        path = url[len("ROOT/"):]
        self.calls.append((method, path, body))
        if path.startswith("users?"):
            if self.pages is not None:
                return self.pages.pop(0)
            if not self.docs:
                raise gcp.GcpError("not_found")
            return {"documents": list(self.docs.values())}
        if path.startswith("deleted/"):
            if path.split("/", 1)[1] in self.deleted:
                return {"name": path}
            raise gcp.GcpError("not_found")
        if path.startswith("users/"):
            uid = path.split("/", 1)[1].split("?", 1)[0]
            if uid not in self.docs:
                raise gcp.GcpError("not_found")
            if method == "PATCH":
                doc = dict(self.docs[uid]); doc["fields"] = {k: v for k, v in doc["fields"].items() if k != "ilog"}
                self.docs[uid] = doc
            return self.docs[uid]
        raise gcp.GcpError("http_error")


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="users-")
        self.log = os.path.join(self.dir, "access-log.jsonl")
        patcher = mock.patch.object(users, "audit_path", return_value=self.log)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.store = FakeStore({UID: DOC})
        self.users = users.Users("demo-project-123", "sa.json", store=self.store)

    def audit_text(self):
        try:
            with open(self.log, encoding="utf-8") as fh:
                return fh.read()
        except OSError:
            return ""


class ListTest(Base):
    def test_list_shows_only_counts_not_personal_details(self):
        rows = self.users.list_users()
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual((r["uid"], r["study_days"], r["weak"], r["trip"], r["ilog_sessions"], r["ilog_lines"]),
                         (UID, 2, 1, True, 1, 2))
        flat = json.dumps(rows, ensure_ascii=False)
        for pii in (CITY, SECRET_LINE, EMAIL, "주문"):
            self.assertNotIn(pii, flat)
        self.assertEqual(self.audit_text(), "")       # 요약 목록은 열람 기록 대상이 아니다

    def test_empty_collection_and_pagination(self):
        self.assertEqual(users.Users("p-12345", "sa", store=FakeStore({})).list_users(), [])
        other = dict(DOC, name=DOC["name"].replace(UID, "uidBob"), updateTime="2026-10-23T00:00:00Z")
        store = FakeStore(pages=[{"documents": [DOC], "nextPageToken": "t2"}, {"documents": [other]}])
        rows = users.Users("p-12345", "sa", store=store).list_users()
        self.assertEqual([r["uid"] for r in rows], ["uidBob", UID])          # 최근 변경 순
        self.assertIn("pageToken=t2", store.calls[1][1])

    def test_broken_field_is_flagged_not_crashing(self):
        doc = json.loads(json.dumps(DOC)); doc["fields"]["weak"] = {"stringValue": "{not json"}
        self.assertEqual(users.summarize(UID, doc)["broken"], ["weak"])


class DetailTest(Base):
    def test_detail_needs_a_reason(self):
        for bad in ("", " ", "a"):
            with self.assertRaises(users.UserError) as caught:
                users.detail(self.users, UID, bad)
            self.assertEqual(caught.exception.code, "reason_required")
        self.assertEqual(self.audit_text(), "")

    def test_detail_is_audited_without_personal_data(self):
        info = users.detail(self.users, UID, "사용자 열람 요청 10/22", auth={"email": EMAIL})
        self.assertEqual(info["trip"]["country"], "미국")
        self.assertEqual(info["progress"]["study_days"], 2)
        self.assertEqual(info["ilog"]["sessions"][0]["lines"], 2)
        self.assertNotIn(SECRET_LINE, json.dumps(info, ensure_ascii=False))   # 본문은 상세에 없다
        entry = json.loads(self.audit_text().splitlines()[-1])
        self.assertEqual(entry["action"], "view")
        self.assertEqual(entry["uid_hash"], users.uid_hash(UID))
        self.assertEqual(entry["reason"], "사용자 열람 요청 10/22")
        for pii in (UID, EMAIL, CITY, SECRET_LINE):
            self.assertNotIn(pii, self.audit_text())

    def test_tombstone_and_missing_document(self):
        self.store.deleted.add("uidGone");
        info = users.detail(self.users, "uidGone", "장애 확인")
        self.assertFalse(info["document"])
        self.assertTrue(info["tombstone"])

    def test_ilog_text_is_a_separate_audited_view(self):
        text = users.ilog_text(self.users, UID, "삭제 요청 전 확인")
        self.assertIn(SECRET_LINE, text)
        self.assertIn("상대", text)
        self.assertEqual(json.loads(self.audit_text().splitlines()[-1])["action"], "view_ilog")

    def test_bad_uid_never_reaches_the_store(self):
        for bad in ("../users/x", "a/b", "a?b", "", "x" * 129):
            with self.assertRaises(users.UserError):
                users.detail(self.users, bad, "사유 있음")
        self.assertEqual(self.store.calls, [])


class ManageTest(Base):
    def test_export_writes_the_whole_record_and_audits(self):
        out = os.path.join(self.dir, "export.json")
        result = users.export(self.users, UID, "열람 요구 10/22", out, auth={"email": EMAIL})
        with open(out, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data["uid"], UID)
        self.assertEqual(data["document"]["ilog"]["list"][0]["lines"][0]["src"], SECRET_LINE)
        self.assertTrue(result["document"])
        self.assertEqual(json.loads(self.audit_text().splitlines()[-1])["action"], "export")

    def test_delete_ilog_only_touches_the_ilog_field_and_never_creates(self):
        result = users.delete_ilog(self.users, UID, "사용자 삭제 요청")
        self.assertTrue(result["deleted"])
        method, path, body = [c for c in self.store.calls if c[0] == "PATCH"][0]
        self.assertIn("updateMask.fieldPaths=ilog", path)
        self.assertIn("currentDocument.exists=true", path)     # 없는 문서를 만들지 않는다
        self.assertEqual(body, {"fields": {}})
        self.assertNotIn("ilog", self.store.docs[UID]["fields"])
        self.assertIn("session", self.store.docs[UID]["fields"])
        actions = [json.loads(x)["action"] for x in self.audit_text().splitlines()]
        self.assertEqual(actions, ["delete_ilog_request", "delete_ilog_result"])
        missing = users.delete_ilog(self.users, "uidNobody", "사용자 삭제 요청")
        self.assertFalse(missing["deleted"])

    def test_no_account_deletion_api(self):
        self.assertFalse(hasattr(users.Users, "delete"))
        self.assertFalse([c for c in self.store.calls if c[0] == "DELETE"])


class AuthTest(unittest.TestCase):
    def opener(self, payload, status=200, seen=None):
        class R(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def call(req, timeout):
            if seen is not None:
                seen.append((req.full_url, json.loads(req.data), req.get_header("Authorization")))
            if status != 200:
                raise urllib.error.HTTPError(req.full_url, status, "x", None, io.BytesIO(b"{}"))
            return R(json.dumps(payload).encode())
        return call

    def test_lookup_by_email_and_by_uid(self):
        seen = []
        got = users.auth_lookup("demo-project-123", "sa", email=EMAIL, token_fn=lambda sa, sc: "tok",
                                opener=self.opener({"users": [{"localId": UID, "email": EMAIL, "createdAt": "1761000000000",
                                                               "providerUserInfo": [{"providerId": "google.com"}]}]}, seen=seen))
        self.assertEqual((got["uid"], got["email"], got["providers"]), (UID, EMAIL, ["google.com"]))
        self.assertTrue(seen[0][0].endswith("/projects/demo-project-123/accounts:lookup"))
        self.assertEqual(seen[0][1], {"email": [EMAIL]})
        self.assertEqual(seen[0][2], "Bearer tok")
        self.assertIsNone(users.auth_lookup("demo-project-123", "sa", uid=UID, token_fn=lambda sa, sc: "tok",
                                            opener=self.opener({})))

    def test_forbidden_and_bad_query(self):
        with self.assertRaises(users.UserError) as caught:
            users.auth_lookup("demo-project-123", "sa", uid=UID, token_fn=lambda sa, sc: "tok", opener=self.opener({}, 403))
        self.assertEqual(caught.exception.code, "auth_forbidden")
        with self.assertRaises(users.UserError) as caught:
            users.auth_lookup("demo-project-123", "sa", email="not-an-email", token_fn=lambda sa, sc: "tok")
        self.assertEqual(caught.exception.code, "bad_query")

    def test_find_uid(self):
        self.assertEqual(users.find_uid("p-12345", "sa", UID), UID)    # uid 는 그대로(조회 없이)
        with mock.patch.object(users, "auth_lookup", return_value={"uid": UID}) as look:
            self.assertEqual(users.find_uid("p-12345", "sa", EMAIL), UID)
        look.assert_called_once()
        with mock.patch.object(users, "auth_lookup", return_value=None):
            with self.assertRaises(users.UserError):
                users.find_uid("p-12345", "sa", EMAIL)


class GuiTest(unittest.TestCase):
    """화면이 있는 곳에서만(CI 리눅스에는 디스플레이가 없다): 탭·버튼이 있고 상세 문구가 만들어지는지."""

    def test_tab_and_detail_format(self):
        import tkinter as tk
        try:
            root = tk.Tk()
        except tk.TclError:
            self.skipTest("디스플레이 없음")
        root.withdraw()
        try:
            from opsarchive import gui
            with mock.patch.object(gui.config, "write_settings"), mock.patch.object(gui.config, "save_env"):
                app = gui.App(root)
            nb = [w for w in root.winfo_children() if w.winfo_class() == "TNotebook"][0]
            tabs = [nb.tab(t, "text") for t in nb.tabs()]
            self.assertIn("사용자 데이터", tabs)
            tmp = tempfile.mkdtemp(prefix="users-gui-")
            self.addCleanup(shutil.rmtree, tmp, True)
            with mock.patch.object(users, "audit_path", return_value=os.path.join(tmp, "log.jsonl")):
                info = users.detail(users.Users("p-12345", "sa", store=FakeStore({UID: DOC})), UID, "테스트 사유",
                                    auth={"email": EMAIL, "name": "A", "providers": ["google.com"], "created": "c",
                                          "last_login": "l", "disabled": False})
            text = app._format_detail(info)
            for want in (EMAIL, "학습: 2일", CITY, "1대화", "[통역 기록 내용]"):
                self.assertIn(want, text)
            self.assertNotIn(SECRET_LINE, text)
            gone = app._format_detail({"uid": UID, "auth": None, "tombstone": True, "document": False})
            self.assertIn("탈퇴 흔적(deleted/uid): 있음", gone)
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
