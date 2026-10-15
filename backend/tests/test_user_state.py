"""계정 기록 읽기·쓰기. 실행: cd backend && python -m unittest tests.test_user_state"""
import io
import json
import os
import unittest
import urllib.error
from unittest import mock

from fastapi.testclient import TestClient

from app import firebase_auth, main, user_state

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
