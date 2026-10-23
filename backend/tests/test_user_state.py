"""계정 기록 읽기·쓰기. 실행: cd backend && python -m unittest tests.test_user_state"""
import io
import json
import os
import re
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from app import firebase_admin, firebase_auth, main, user_state

REPO_ROOT = Path(__file__).resolve().parents[2]

ENV = {
    "FIREBASE_API_KEY": "public-web-key",
    "FIREBASE_AUTH_DOMAIN": "demo-project.firebaseapp.com",
    "FIREBASE_PROJECT_ID": "demo-project",
    "FIREBASE_APP_ID": "1:1:web:abc",
}
CLAIMS = {
    "sub": "uid-1",
    "iss": "https://securetoken.google.com/demo-project",
    "aud": "demo-project",
    "email": "traveler@example.com",
    "name": "김여행",
    "firebase": {"sign_in_provider": "google.com"},
}
SESSION = {
    "v": 1,
    "at": 1_700_000_000_000,
    "done": {"2026-09-22": 1_700_000_000_100},
    "screen": "u-study",
    "studyDate": "2026-09-22",
    "card": {"date": "2026-09-22", "i": 1, "back": None, "flipped": [0, 1]},
}
BODY = {
    "session": SESSION,
    "weak": [{
        "category_id": "restaurant",
        "id": "order_menu",
        "situation": "주문",
        "en": "Water, please.",
        "ko": "물 주세요.",
        "demo": False,
    }],
    "consent": {"version": 6, "voice": True, "at": "2026-10-15T00:00:00.000Z"},
}
TRIP = {
    "country": "미국",
    "cities": [
        {"name": "뉴욕", "start": "2026-11-10", "end": "2026-11-13"},
        {"name": "보스턴", "start": "2026-11-13", "end": "2026-11-15"},
    ],
    "studyStart": "2026-10-01",
}


def claims_for(uid, provider="google.com"):
    data = json.loads(json.dumps(CLAIMS))
    data["sub"] = uid
    data["firebase"]["sign_in_provider"] = provider
    return data


def http_error(code, message):
    raw = json.dumps({"error": {"code": code, "message": message, "status": "NOT_FOUND"}}).encode()
    return urllib.error.HTTPError(
        url="https://firestore.googleapis.com/v1/example",
        code=code,
        msg="error",
        hdrs=None,
        fp=io.BytesIO(raw),
    )


class Resp:
    def __init__(self, raw):
        self.raw = raw

    def read(self):
        return self.raw

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class Script:
    def __init__(self, steps):
        self.steps = list(steps)
        self.calls = []

    def __call__(self, req, timeout):
        self.calls.append((req.get_method(), req.full_url, req.get_header("Authorization")))
        item = self.steps.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class T(unittest.TestCase):
    def setUp(self):
        self.mem = user_state.MemoryUserStore()
        user_state.set_store(self.mem)
        self.http = TestClient(main.app, raise_server_exceptions=False)

    def tearDown(self):
        user_state.set_store(None)
        firebase_admin.set_admin(None)
        firebase_admin.reset_cache()

    def test_put_is_rejected_for_an_erased_account(self):
        """다른 기기의 미만료 토큰이 탈퇴한 계정의 문서를 다시 만들지 못하게 한다(403 account_deleted)."""
        class Erased:
            def read_tombstone(self, uid):
                return True

        firebase_admin.set_admin(Erased())
        res = self.put(claims_for("uid-1"))
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.json()["detail"], "account_deleted")
        self.assertEqual(self.mem.docs, {})   # 문서가 만들어지지 않았다

    def test_get_is_rejected_for_an_erased_account(self):
        """읽기도 거부한다 — 아니면 화면이 '기록 없음'으로 보고 로컬 기록을 다시 올린다."""
        class Erased:
            def read_tombstone(self, uid):
                return True

        firebase_admin.set_admin(Erased())
        res = self.get(claims_for("uid-1"))
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.json()["detail"], "account_deleted")

    def test_put_is_allowed_when_no_tombstone(self):
        class Clean:
            def read_tombstone(self, uid):
                return False

        firebase_admin.set_admin(Clean())
        res = self.put(claims_for("uid-1"))
        self.assertEqual(res.status_code, 200, res.text)
        self.assertIn("uid-1", self.mem.docs)

    def put(self, claims, body=None, token="signed-token"):
        with mock.patch.dict(os.environ, ENV), mock.patch.object(
            firebase_auth.id_token, "verify_firebase_token", return_value=claims,
        ):
            return self.http.put(
                "/user/state",
                headers={"Authorization": "Bearer " + token},
                json=BODY if body is None else body,
            )

    def get(self, claims, token="signed-token"):
        with mock.patch.dict(os.environ, ENV), mock.patch.object(
            firebase_auth.id_token, "verify_firebase_token", return_value=claims,
        ):
            return self.http.get("/user/state", headers={"Authorization": "Bearer " + token})

    def delete(self, claims, token="signed-token"):
        with mock.patch.dict(os.environ, ENV), mock.patch.object(
            firebase_auth.id_token, "verify_firebase_token", return_value=claims,
        ):
            return self.http.delete("/user/state", headers={"Authorization": "Bearer " + token})

    def test_put_requires_a_bearer_token(self):
        with mock.patch.dict(os.environ, ENV):
            res = self.http.put("/user/state", json=BODY)
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.json()["detail"], "missing_token")
        self.assertEqual(self.mem.docs, {})

    def test_anonymous_does_not_get_a_record(self):
        res = self.put(claims_for("uid-1", "anonymous"))
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.json()["detail"], "anonymous_rejected")
        self.assertEqual(self.mem.docs, {})

    def test_round_trip_is_scoped_to_the_token_uid(self):
        saved = self.put(claims_for("uid-1"))
        self.assertEqual(saved.status_code, 200, saved.text)
        other = self.get(claims_for("uid-2"))
        self.assertEqual(other.status_code, 200)
        self.assertEqual(other.json(), user_state.EMPTY_STATE)
        mine = self.get(claims_for("uid-1"))
        self.assertEqual(mine.json()["session"]["screen"], "u-study")
        self.assertEqual(mine.json()["weak"][0]["id"], "order_menu")
        self.assertEqual(mine.json()["consent"]["version"], 6)
        self.assertNotIn("uid-2", self.mem.docs)

    def test_body_cannot_name_the_account(self):
        res = self.put(claims_for("uid-1"), {**BODY, "uid": "uid-2"})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["detail"], "invalid_state")
        self.assertEqual(self.mem.docs, {})

    def test_oversized_body_is_rejected(self):
        with mock.patch.dict(os.environ, ENV), mock.patch.object(
            firebase_auth.id_token, "verify_firebase_token", return_value=claims_for("uid-1"),
        ):
            res = self.http.put(
                "/user/state",
                headers={"Authorization": "Bearer signed-token", "Content-Type": "application/json"},
                content=b"{" + b"x" * (user_state.MAX_STATE_BYTES + 1),
            )
        self.assertEqual(res.status_code, 413)
        self.assertNotIn("signed-token", res.text)

    def test_generate_stays_open_without_a_token(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GEMINI_API_KEY", None)
            res = self.http.post("/generate", json={"category_id": "restaurant", "city": "뉴욕"})
        self.assertEqual(res.status_code, 200)

    def test_store_failure_is_unavailable(self):
        class Down:
            def read(self, uid, token):
                raise user_state.StoreError(503, "store_unavailable")

            def write(self, uid, token, state):
                raise user_state.StoreError(503, "store_unavailable")

        user_state.set_store(Down())
        res = self.get(claims_for("uid-1"))
        self.assertEqual(res.status_code, 503)
        self.assertEqual(res.json()["detail"], "store_unavailable")

    def test_document_encoding_round_trip(self):
        state = user_state.parse_state(BODY)
        self.assertEqual(user_state.decode_document(user_state.encode_document(state)), state)

    def test_trip_is_stored_with_the_progress(self):
        saved = self.put(claims_for("uid-1"), {**BODY, "trip": TRIP})
        self.assertEqual(saved.status_code, 200, saved.text)
        mine = self.get(claims_for("uid-1"))
        self.assertEqual(mine.json()["trip"], TRIP)

    def test_home_card_without_a_date_does_not_reject_the_trip(self):
        # 홈은 학습 카드를 열기 전에 date: null 을 보낸다. 이 객체 때문에 여행까지 400 이면 안 된다.
        session = {**SESSION, "screen": "u-home", "studyDate": None,
                   "card": {"date": None, "i": 0, "back": None, "flipped": []}}
        saved = self.put(claims_for("uid-1"), {**BODY, "session": session, "trip": TRIP})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertIsNone(saved.json()["session"]["card"])
        self.assertEqual(saved.json()["trip"], TRIP)
        bad = self.put(claims_for("uid-1"), {**BODY, "session": {**session, "card": {"date": None, "i": -1, "back": None, "flipped": []}}})
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(bad.json()["detail"], "invalid_state")

    def test_pre_study_dates_round_trip_and_are_validated(self):
        # 미리 학습한 날짜(pre)는 선택 항목이다 — 그날이 오면 화면이 완료로 옮긴다.
        session = {**SESSION, "pre": {"2026-09-25": 1_700_000_000_200}}
        saved = self.put(claims_for("uid-1"), {**BODY, "session": session})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(self.get(claims_for("uid-1")).json()["session"]["pre"], {"2026-09-25": 1_700_000_000_200})
        state = user_state.parse_state({**BODY, "session": session})
        self.assertEqual(user_state.decode_document(user_state.encode_document(state)), state)
        self.assertNotIn("pre", user_state.parse_state(BODY)["session"])   # 없는 옛 본문은 그대로
        for bad in ({"10/01": 1}, {"2026-09-25": "x"}, ["2026-09-25"]):
            res = self.put(claims_for("uid-1"), {**BODY, "session": {**SESSION, "pre": bad}})
            self.assertEqual(res.status_code, 400, bad)

    def test_activity_counts_round_trip_and_are_validated(self):
        # 날짜별 학습 활동 수(act)는 선택 항목이다 — 연속 학습·오늘 목표가 다른 기기에서도 이어진다.
        session = {**SESSION, "act": {"2026-10-19": 12, "2026-10-20": 3}}
        saved = self.put(claims_for("uid-1"), {**BODY, "session": session})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(self.get(claims_for("uid-1")).json()["session"]["act"], {"2026-10-19": 12, "2026-10-20": 3})
        state = user_state.parse_state({**BODY, "session": session})
        self.assertEqual(user_state.decode_document(user_state.encode_document(state)), state)
        self.assertNotIn("act", user_state.parse_state(BODY)["session"])   # 없는 옛 본문은 그대로
        too_many = {f"2025-{m:02d}-{d:02d}": 1 for m in range(1, 13) for d in range(1, 29)}   # 336일
        too_many.update({f"2024-{m:02d}-{d:02d}": 1 for m in range(1, 4) for d in range(1, 29)})  # +84 → 420 > 400
        for bad in ({"10/20": 1}, {"2026-10-20": "3"}, {"2026-10-20": -1}, {"2026-10-20": 10001}, {"2026-10-20": True},
                    {"2026-10-20": 1.5}, ["2026-10-20"], too_many):
            res = self.put(claims_for("uid-1"), {**BODY, "session": {**SESSION, "act": bad}})
            self.assertEqual(res.status_code, 400, str(bad)[:60])

    def test_state_without_trip_reads_as_empty(self):
        # trip 은 나중에 붙은 항목이라 예전 본문(키 없음)도 받아들인다.
        self.assertEqual(user_state.parse_state(BODY)["trip"], None)

    def test_malformed_trip_is_rejected(self):
        for bad_trip in (
            {"country": "미국", "cities": [], "studyStart": "2026-10-01"},          # 도시 0곳
            {"country": "", "cities": TRIP["cities"], "studyStart": "2026-10-01"},  # 나라 없음
            {"country": "미국", "cities": [{"name": "뉴욕", "start": "2026/11/10", "end": "2026-11-13"}],
             "studyStart": "2026-10-01"},                                            # 날짜 형식 오류
            {"country": "미국", "cities": [TRIP["cities"][0]] * 6, "studyStart": "2026-10-01"},  # 도시 6곳
            {**TRIP, "uid": "uid-2"},                                                # 모르는 키
        ):
            res = self.put(claims_for("uid-1"), {**BODY, "trip": bad_trip})
            self.assertEqual(res.status_code, 400, res.text)
            self.assertEqual(res.json()["detail"], "invalid_state")
        self.assertEqual(self.mem.docs, {})

    def test_firestore_rules_allow_exactly_the_fields_we_write(self):
        """보안 규칙과 쓰기 필드가 어긋나면 배포에서 조용히 거부된다(reload 뒤 여행이 사라진다).

        encode_document 가 쓰는 필드 이름 == firestore.rules 의 hasOnly 목록 이어야 한다.
        trip 을 붙일 때 규칙을 안 고치면 이 테스트가 잡는다.
        """
        text = (REPO_ROOT / "firestore.rules").read_text(encoding="utf-8")
        found = re.search(r"hasOnly\(\[([^\]]*)\]\)", text)
        self.assertIsNotNone(found, "firestore.rules 에서 hasOnly 목록을 찾지 못했습니다")
        allowed = [k.strip().strip("'\"") for k in found.group(1).split(",") if k.strip()]
        doc = user_state.encode_document(user_state.parse_state({**BODY, "trip": TRIP}))
        doc["fields"]["ilog"] = {"stringValue": "{}"}   # 통역 기록은 따로 쓰는 필드다(write_ilog)
        self.assertEqual(set(doc["fields"]), set(allowed), "쓰는 필드와 보안 규칙 허용 목록이 다릅니다")
        # 규칙은 각 필드가 문자열(JSON)이기를 요구한다 — 인코딩도 그렇게 해야 한다.
        for name in allowed:
            self.assertIsInstance(doc["fields"][name].get("stringValue"), str, name)

    def test_firestore_rules_reject_writes_after_erasure(self):
        """탈퇴 흔적(deleted/{uid})이 있으면 create/update 를 거부한다 — 남은 ID 토큰으로 직접 써서 되살리지 못하게(10/23 #8).

        흔적 컬렉션 이름은 firebase_admin 이 쓰는 이름과 같아야 한다. 삭제는 막지 않는다.
        """
        text = (REPO_ROOT / "firestore.rules").read_text(encoding="utf-8")
        self.assertRegex(text, r"!\s*exists\(/databases/\$\(database\)/documents/deleted/\$\(uid\)\)")
        self.assertRegex(text, r"allow create, update: if signedIn\(\) && notErased\(\)")
        self.assertRegex(text, r"allow delete: if signedIn\(\);")
        self.assertRegex(text, r"match /\{document=\*\*\} \{\s*allow read, write: if false;")
        import inspect
        from app import firebase_admin
        self.assertIn("/documents/deleted/", inspect.getsource(firebase_admin.ServiceAccountAdmin._tombstone_url))

    def test_firestore_rules_make_trip_optional(self):
        """규칙을 백엔드보다 먼저 배포해도 옛 백엔드(trip 을 쓰지 않음)의 쓰기가 막히면 안 된다.

        trip 을 무조건 `is string` 으로 요구하면, trip 필드가 없는 문서의 쓰기는 거부된다
        (없는 필드를 읽으면 규칙 평가가 실패한다). 'trip' in data 로 존재를 먼저 확인해야 한다.
        지금 배포된 백엔드(3필드)와 trip 을 넣는 백엔드(4필드)가 모두 통과하려면 이 형태여야 한다.
        """
        text = (REPO_ROOT / "firestore.rules").read_text(encoding="utf-8")
        self.assertRegex(
            text,
            r"!\s*\(\s*'trip'\s+in\s+request\.resource\.data\s*\)\s*\|\|\s*request\.resource\.data\.trip\s+is\s+string",
            "trip 은 '있으면 문자열'이어야 한다 — 무조건 요구하면 trip 없는 쓰기가 거부된다",
        )
        # session·weak·consent 는 옛 백엔드도 항상 쓰므로 필수로 남는다.
        for name in ("session", "weak", "consent"):
            self.assertRegex(text, rf"request\.resource\.data\.{name}\s+is\s+string")

    def test_firestore_rules_allow_the_owner_to_delete(self):
        """탈퇴는 본인 문서 삭제가 필요하다. 삭제에는 request.resource.data 가 없어 allow delete 로만 허용한다."""
        text = (REPO_ROOT / "firestore.rules").read_text(encoding="utf-8")
        self.assertRegex(text, r"allow delete:\s*if signedIn\(\);")
        self.assertRegex(text, r"allow create, update:\s*if signedIn\(\)")   # 쓰기 필드 검사는 create/update 에만

    def test_delete_removes_the_document_and_is_idempotent(self):
        self.put(claims_for("uid-1"), {**BODY, "trip": TRIP})
        self.assertIn("uid-1", self.mem.docs)
        first = self.delete(claims_for("uid-1"))
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json(), {"deleted": True})
        self.assertNotIn("uid-1", self.mem.docs)
        again = self.delete(claims_for("uid-1"))          # 이미 없는 문서를 지워도 성공(탈퇴 재시도)
        self.assertEqual(again.status_code, 200, again.text)

    def test_delete_requires_a_token(self):
        with mock.patch.dict(os.environ, ENV):
            res = self.http.delete("/user/state")
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.json()["detail"], "missing_token")

    def test_delete_rejects_anonymous(self):
        res = self.delete(claims_for("uid-1", "anonymous"))
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.json()["detail"], "anonymous_rejected")

    def test_delete_store_failure_is_unavailable(self):
        class Down:
            def read(self, uid, token):
                raise user_state.StoreError(503, "store_unavailable")

            def write(self, uid, token, state):
                raise user_state.StoreError(503, "store_unavailable")

            def delete(self, uid, token):
                raise user_state.StoreError(503, "store_unavailable")

        user_state.set_store(Down())
        res = self.delete(claims_for("uid-1"))
        self.assertEqual(res.status_code, 503)
        self.assertEqual(res.json()["detail"], "store_unavailable")

    def test_firestore_delete_request_shape_and_missing_doc(self):
        """DELETE 는 /users/{uid} 로, Bearer 토큰으로 나가고, 없는 문서는 성공으로 본다(탈퇴 재시도)."""
        ok = Script([Resp(b"{}")])
        user_state.FirestoreUserStore("demo-project", ok).delete("uid-1", "signed-token")
        self.assertEqual(ok.calls[0][0], "DELETE")
        self.assertTrue(ok.calls[0][1].endswith("/users/uid-1"), ok.calls[0][1])
        self.assertEqual(ok.calls[0][2], "Bearer signed-token")

        missing = Script([http_error(404, 'Document "projects/demo-project/databases/(default)/documents/users/uid-1" not found.')])
        self.assertIsNone(user_state.FirestoreUserStore("demo-project", missing).delete("uid-1", "signed-token"))

        denied = Script([http_error(403, "Missing or insufficient permissions.")])
        with self.assertRaises(user_state.StoreError) as caught:
            user_state.FirestoreUserStore("demo-project", denied).delete("uid-1", "signed-token")
        self.assertEqual(caught.exception.status, 503)   # 규칙 거부는 성공으로 넘기지 않는다

    def test_firestore_rules_bind_writes_and_deletes_to_the_owning_uid(self):
        """규칙 '문자열 존재'가 아니라 조건을 확인한다 — signedIn() 을 약화시키거나 allow 를 주석에만 둔 변형을 잡는다."""
        text = (REPO_ROOT / "firestore.rules").read_text(encoding="utf-8")
        body = re.search(r"function signedIn\(\) \{(.*?)\}", text, re.S)
        self.assertIsNotNone(body, "signedIn() 본문을 찾지 못했습니다")
        cond = body.group(1)
        self.assertRegex(cond, r"request\.auth\.uid\s*==\s*uid")            # 본인 문서만
        self.assertRegex(cond, r"sign_in_provider\s*!=\s*'anonymous'")      # 익명 거부
        code = re.sub(r"//[^\n]*", "", text)                               # 주석을 걷어낸 실제 규칙에서 찾는다
        self.assertRegex(code, r"allow delete:\s*if signedIn\(\);")
        self.assertRegex(code, r"allow create, update:\s*if signedIn\(\)")

    def test_firestore_get_missing_is_empty_and_database_missing_is_unavailable(self):
        missing = Script([http_error(404, 'Document "projects/demo-project/databases/(default)/documents/users/uid-1" not found.')])
        store = user_state.FirestoreUserStore("demo-project", missing)
        self.assertIsNone(store.read("uid-1", "signed-token"))
        self.assertIn("/users/uid-1", missing.calls[0][1])
        self.assertEqual(missing.calls[0][2], "Bearer signed-token")

        gone = Script([http_error(404, "The database (default) does not exist for project demo-project")])
        store = user_state.FirestoreUserStore("demo-project", gone)
        with self.assertRaises(user_state.StoreError) as caught:
            store.read("uid-1", "signed-token")
        self.assertEqual(caught.exception.status, 503)
        self.assertNotIn("signed-token", str(caught.exception))

    def test_firestore_patch_creates_the_document_when_it_is_missing(self):
        script = Script([
            http_error(404, 'Document "projects/demo-project/databases/(default)/documents/users/uid-1" not found.'),
            Resp(b"{}"),
        ])
        store = user_state.FirestoreUserStore("demo-project", script)
        store.write("uid-1", "signed-token", user_state.parse_state(BODY))
        self.assertEqual([call[0] for call in script.calls], ["PATCH", "POST"])
        self.assertIn("documentId=uid-1", script.calls[1][1])
        self.assertNotIn("uid-2", script.calls[1][1])


if __name__ == "__main__":
    unittest.main()
