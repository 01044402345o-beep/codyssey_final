"""통역 기록 계정 저장(동의한 사용자만). 실행: cd backend && python -m unittest tests.test_interp_log_server"""
import json
import os
import re
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from app import firebase_admin, firebase_auth, main, user_state
from tests.test_user_state import BODY, ENV, REPO_ROOT, Resp, Script, claims_for, http_error

AT = 1_761_100_000_000
ILOG = {
    "v": 1,
    "consent": {"version": "2026-10-22", "at": AT},
    "list": [{
        "id": "smh2abc",
        "at": AT,
        "a": "ko",
        "b": "en",
        "trip": {"id": "t1", "route": "뉴욕 → 보스턴"},
        "lines": [
            {"src": "화장실이 어디예요?", "dst": "Where is the restroom?", "s": "ko", "t": "en", "at": AT + 1000},
            {"src": "It's on the left.", "dst": "왼쪽에 있어요.", "s": "en", "t": "ko", "at": AT + 2000},
        ],
    }],
}


def ilog_with(**changes):
    data = json.loads(json.dumps(ILOG))
    data.update(changes)
    return data


class T(unittest.TestCase):
    def setUp(self):
        self.mem = user_state.MemoryUserStore()
        user_state.set_store(self.mem)
        self.http = TestClient(main.app, raise_server_exceptions=False)

    def tearDown(self):
        user_state.set_store(None)
        firebase_admin.set_admin(None)
        firebase_admin.reset_cache()

    def call(self, method, claims, path="/user/interp-log", body=None, token="signed-token"):
        with mock.patch.dict(os.environ, ENV), mock.patch.object(
            firebase_auth.id_token, "verify_firebase_token", return_value=claims,
        ):
            kw = {"headers": {"Authorization": "Bearer " + token}}
            if body is not None:
                kw["json"] = body
            return self.http.request(method, path, **kw)

    # --- 엔드포인트 ---

    def test_needs_a_login(self):
        with mock.patch.dict(os.environ, ENV):
            for method in ("GET", "PUT", "DELETE"):
                res = self.http.request(method, "/user/interp-log", json=ILOG if method == "PUT" else None)
                self.assertEqual(res.status_code, 401, method)
        self.assertEqual(self.mem.ilogs, {})

    def test_anonymous_cannot_store_a_log(self):
        res = self.call("PUT", claims_for("uid-1", "anonymous"), body=ILOG)
        self.assertEqual(res.status_code, 403)
        self.assertEqual(self.mem.ilogs, {})

    def test_round_trip_is_scoped_to_the_token_uid(self):
        self.assertEqual(self.call("GET", claims_for("uid-1")).json(), {"ilog": None})
        saved = self.call("PUT", claims_for("uid-1"), body=ILOG)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json(), {"saved": True, "sessions": 1, "lines": 2})
        mine = self.call("GET", claims_for("uid-1")).json()["ilog"]
        self.assertEqual(mine["list"][0]["lines"][0]["dst"], "Where is the restroom?")
        self.assertEqual(mine["list"][0]["trip"], {"route": "뉴욕 → 보스턴"})   # 여행 id 는 저장하지 않는다
        self.assertEqual(self.call("GET", claims_for("uid-2")).json(), {"ilog": None})

    def test_consent_is_required(self):
        for bad in (ilog_with(consent=None), ilog_with(consent={"at": AT}), ilog_with(consent={"version": "", "at": AT})):
            if bad["consent"] is None:
                del bad["consent"]
            res = self.call("PUT", claims_for("uid-1"), body=bad)
            self.assertEqual(res.status_code, 400, res.text)
            self.assertEqual(res.json()["detail"], "ilog_consent_required")
        self.assertEqual(self.mem.ilogs, {})

    def test_malformed_logs_are_rejected(self):
        line = ILOG["list"][0]["lines"][0]
        bad_sessions = [
            {**ILOG["list"][0], "id": "../uid-2"},
            {**ILOG["list"][0], "a": "ja"},
            {**ILOG["list"][0], "lines": []},
            {**ILOG["list"][0], "lines": [{**line, "audio": "base64…"}]},     # 음성은 받지 않는다
            {**ILOG["list"][0], "lines": [{**line, "src": "가" * 501}]},
            {**ILOG["list"][0], "lines": [{**line, "at": "어제"}]},
            {**ILOG["list"][0], "uid": "uid-2"},
        ]
        for bad in bad_sessions:
            res = self.call("PUT", claims_for("uid-1"), body=ilog_with(list=[bad]))
            self.assertEqual(res.status_code, 400, bad)
            self.assertEqual(res.json()["detail"], "invalid_ilog")
        self.assertEqual(self.call("PUT", claims_for("uid-1"), body=ilog_with(v=2)).status_code, 400)
        self.assertEqual(self.mem.ilogs, {})

    def test_caps_match_the_screen(self):
        many = [{**ILOG["list"][0], "id": f"s{i}"} for i in range(user_state.ILOG_SESSIONS + 1)]
        self.assertEqual(self.call("PUT", claims_for("uid-1"), body=ilog_with(list=many)).status_code, 400)
        line = ILOG["list"][0]["lines"][0]
        long = [{**ILOG["list"][0], "id": f"s{i}", "lines": [line] * 30} for i in range(11)]   # 330 문장
        res = self.call("PUT", claims_for("uid-1"), body=ilog_with(list=long))
        self.assertEqual(res.status_code, 413)
        self.assertEqual(res.json()["detail"], "ilog_too_large")
        big = [{**ILOG["list"][0], "id": f"s{i}", "lines": [{**line, "src": "가" * 500, "dst": "나" * 500}] * 10}
               for i in range(25)]
        self.assertEqual(self.call("PUT", claims_for("uid-1"), body=ilog_with(list=big)).status_code, 413)
        self.assertEqual(self.mem.ilogs, {})

    def test_saving_progress_does_not_clear_the_log(self):
        self.call("PUT", claims_for("uid-1"), body=ILOG)
        res = self.call("PUT", claims_for("uid-1"), path="/user/state", body=BODY)
        self.assertEqual(res.status_code, 200, res.text)
        self.assertIsNotNone(self.call("GET", claims_for("uid-1")).json()["ilog"])
        state = self.call("GET", claims_for("uid-1"), path="/user/state").json()
        self.assertNotIn("ilog", state)   # 진도 읽기에는 기록이 섞여 나오지 않는다

    def test_delete_clears_only_the_log_and_account_delete_clears_both(self):
        self.call("PUT", claims_for("uid-1"), path="/user/state", body=BODY)
        self.call("PUT", claims_for("uid-1"), body=ILOG)
        res = self.call("DELETE", claims_for("uid-1"))
        self.assertEqual(res.json(), {"deleted": True})
        self.assertEqual(self.call("GET", claims_for("uid-1")).json(), {"ilog": None})
        self.assertIn("uid-1", self.mem.docs)                       # 진도는 그대로
        self.assertEqual(self.call("DELETE", claims_for("uid-1")).status_code, 200)   # 다시 지워도 성공
        self.call("PUT", claims_for("uid-1"), body=ILOG)
        self.call("DELETE", claims_for("uid-1"), path="/user/state")   # 탈퇴
        self.assertEqual(self.call("GET", claims_for("uid-1")).json(), {"ilog": None})

    def test_erased_account_cannot_write_or_read(self):
        class Erased:
            def read_tombstone(self, uid):
                return True

        firebase_admin.set_admin(Erased())
        for method in ("GET", "PUT"):
            res = self.call(method, claims_for("uid-1"), body=ILOG if method == "PUT" else None)
            self.assertEqual(res.status_code, 403, method)
            self.assertEqual(res.json()["detail"], "account_deleted")
        self.assertEqual(self.mem.docs, {})

    # --- Firestore 요청 모양 ---

    def test_firestore_write_patches_only_the_ilog_field(self):
        script = Script([Resp(b'{"name":"x","fields":{}}'), Resp(b"{}")])
        user_state.FirestoreUserStore("demo-project", script).write_ilog("uid-1", "signed-token", user_state.parse_ilog(ILOG))
        self.assertEqual([c[0] for c in script.calls], ["GET", "PATCH"])
        self.assertTrue(script.calls[1][1].endswith("/users/uid-1?updateMask.fieldPaths=ilog"), script.calls[1][1])
        self.assertEqual(script.calls[1][2], "Bearer signed-token")

    def test_firestore_write_creates_a_full_document_when_missing(self):
        """PATCH 가 ilog 하나뿐인 문서를 만들면 규칙(session·weak·consent 필수)에 막힌다 — 빈 진도와 함께 만든다."""
        sent = []
        script = Script([http_error(404, 'Document "projects/demo-project/databases/(default)/documents/users/uid-1" not found.'),
                         Resp(b"{}")])

        def opener(req, timeout):
            if req.data:
                sent.append(json.loads(req.data))
            return script(req, timeout)

        user_state.FirestoreUserStore("demo-project", opener).write_ilog("uid-1", "signed-token", user_state.parse_ilog(ILOG))
        self.assertEqual([c[0] for c in script.calls], ["GET", "POST"])
        self.assertIn("documentId=uid-1", script.calls[1][1])
        for name in ("session", "weak", "consent", "ilog"):
            self.assertIn(name, sent[0]["fields"])

    def test_firestore_read_and_delete(self):
        stored = json.dumps(user_state.parse_ilog(ILOG), ensure_ascii=False)
        doc = json.dumps({"name": "x", "fields": {"ilog": {"stringValue": stored}}}).encode()
        script = Script([Resp(doc)])
        got = user_state.FirestoreUserStore("demo-project", script).read_ilog("uid-1", "signed-token")
        self.assertEqual(got["list"][0]["id"], "smh2abc")
        self.assertIn("mask.fieldPaths=ilog", script.calls[0][1])

        empty = Script([Resp(b'{"name":"x"}')])
        self.assertIsNone(user_state.FirestoreUserStore("demo-project", empty).read_ilog("uid-1", "signed-token"))

        gone = Script([http_error(404, 'Document "projects/demo-project/databases/(default)/documents/users/uid-1" not found.')])
        user_state.FirestoreUserStore("demo-project", gone).delete_ilog("uid-1", "signed-token")
        self.assertEqual([c[0] for c in gone.calls], ["GET"])        # 없는 문서에 빈 PATCH 를 보내지 않는다

        clear = Script([Resp(b'{"name":"x"}'), Resp(b"{}")])
        user_state.FirestoreUserStore("demo-project", clear).delete_ilog("uid-1", "signed-token")
        self.assertEqual([c[0] for c in clear.calls], ["GET", "PATCH"])
        self.assertTrue(clear.calls[1][1].endswith("?updateMask.fieldPaths=ilog"))

    def test_state_read_ignores_the_ilog_field(self):
        doc = user_state.encode_document(user_state.parse_state(BODY))
        doc["fields"]["ilog"] = {"stringValue": "{}"}
        self.assertNotIn("ilog", user_state.decode_document(doc))

    def test_firestore_rules_allow_ilog_as_an_optional_string(self):
        text = (REPO_ROOT / "firestore.rules").read_text(encoding="utf-8")
        self.assertRegex(
            text,
            r"!\s*\(\s*'ilog'\s+in\s+request\.resource\.data\s*\)\s*\|\|\s*request\.resource\.data\.ilog\s+is\s+string",
        )
        size = int(re.search(r"request\.resource\.size\(\)\s*<\s*(\d+)", text).group(1))
        self.assertGreaterEqual(size, 100_000 + user_state.ILOG_MAX_BYTES)


if __name__ == "__main__":
    unittest.main()
