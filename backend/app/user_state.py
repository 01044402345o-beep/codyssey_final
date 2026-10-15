"""계정별 진도 저장.

Render 디스크는 재시작되면 지워지므로 쓰지 않는다. 서비스 계정 JSON 도 쓰지 않는다.
확인된 Firebase ID 토큰을 Firestore 보안 규칙에 그대로 넘긴다.
문서는 users/{uid} 하나다. 담는 것은 진도, 복습 목록, 말하기 동의뿐이다.
여행·장소·문장 본문은 담지 않는다. 화면이 규칙으로 다시 만든다.

저장소는 테스트가 set_store 로 갈아 끼운다. 기본 구현은 Firestore REST 다.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Callable

MAX_STATE_BYTES = 100_000
EMPTY_STATE: dict[str, Any] = {"session": None, "weak": [], "consent": None}

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SCREEN = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
_ID = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_AT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$")
_UID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_MASK = "updateMask.fieldPaths=session&updateMask.fieldPaths=weak&updateMask.fieldPaths=consent"

Opener = Callable[..., Any]
_store: Any = None


class StoreError(Exception):
    def __init__(self, status: int, code: str) -> None:
        self.status = status
        self.code = code


class MissingDoc(Exception):
    """이 계정 문서가 아직 없다."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _default_opener(req: urllib.request.Request, timeout: float = 8):
    opener = urllib.request.build_opener(_NoRedirect)
    return opener.open(req, timeout=timeout)


def set_store(store: Any) -> None:
    """테스트가 네트워크 없이 저장소를 넣는다. None 이면 다음 요청이 Firestore 를 고른다."""
    global _store
    _store = store


def get_store() -> Any:
    if _store is not None:
        return _store
    project = (os.getenv("FIREBASE_PROJECT_ID") or "").strip()
    if not project:
        raise StoreError(503, "store_unavailable")
    return FirestoreUserStore(project)


def _fail() -> None:
    raise StoreError(400, "invalid_state")


def _num(value: Any, lo: int, hi: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < lo or value > hi:
        _fail()
    return value


def _card(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) - {"date", "i", "back", "flipped"}:
        _fail()
    date = value.get("date")
    if not isinstance(date, str) or not _DATE.fullmatch(date):
        _fail()
    back = value.get("back")
    if back is not None:
        back = _num(back, 0, 500)
    flipped_in = value.get("flipped")
    if not isinstance(flipped_in, list) or len(flipped_in) > 500:
        _fail()
    return {
        "date": date,
        "i": _num(value.get("i"), 0, 500),
        "back": back,
        "flipped": [_num(n, 0, 500) for n in flipped_in],
    }


def _session(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) - {"v", "at", "done", "screen", "studyDate", "card"}:
        _fail()
    if value.get("v") != 1:
        _fail()
    done_in = value.get("done")
    if not isinstance(done_in, dict) or len(done_in) > 400:
        _fail()
    done: dict[str, int] = {}
    for key, stamp in done_in.items():
        if not isinstance(key, str) or not _DATE.fullmatch(key):
            _fail()
        done[key] = _num(stamp, 0, 10**15)
    screen = value.get("screen")
    if not isinstance(screen, str) or not _SCREEN.fullmatch(screen):
        _fail()
    study = value.get("studyDate")
    if study is not None and (not isinstance(study, str) or not _DATE.fullmatch(study)):
        _fail()
    return {
        "v": 1,
        "at": _num(value.get("at"), 0, 10**15),
        "done": done,
        "screen": screen,
        "studyDate": study,
        "card": _card(value.get("card")),
    }


def _weak(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > 80:
        _fail()
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        cat, wid = item.get("category_id"), item.get("id")
        situation = item.get("situation")
        if not isinstance(cat, str) or not _ID.fullmatch(cat):
            continue
        if not isinstance(wid, str) or not _ID.fullmatch(wid) or wid.startswith("w_"):
            continue
        if not isinstance(situation, str) or not situation.strip() or len(situation) > 500:
            continue
        en = item.get("en") if isinstance(item.get("en"), str) else ""
        ko = item.get("ko") if isinstance(item.get("ko"), str) else ""
        if len(en) > 500 or len(ko) > 500:
            continue
        key = cat + "/" + wid
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "category_id": cat,
            "id": wid,
            "situation": situation.strip(),
            "en": en,
            "ko": ko,
            "demo": item.get("demo") is True,
        })
    return out


def _consent(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        _fail()
    version = value.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or not 1 <= version <= 99:
        _fail()
    if value.get("voice") is not True:
        _fail()
    at = value.get("at")
    if not isinstance(at, str) or not _AT.fullmatch(at):
        _fail()
    return {"version": version, "voice": True, "at": at}


def parse_state(body: Any) -> dict[str, Any]:
    """본문에서 진도·복습·동의만 남긴다. uid 는 받지 않는다."""
    if not isinstance(body, dict) or set(body) != {"session", "weak", "consent"}:
        raise StoreError(400, "invalid_state")
    state = {
        "session": _session(body.get("session")),
        "weak": _weak(body.get("weak")),
        "consent": _consent(body.get("consent")),
    }
    raw = json.dumps(state, ensure_ascii=False, separators=(",", ":")).encode()
    if len(raw) > MAX_STATE_BYTES:
        raise StoreError(413, "state_too_large")
    return state


def encode_document(state: dict[str, Any]) -> dict[str, Any]:
    def as_string(value: Any) -> dict[str, str]:
        return {"stringValue": json.dumps(value, ensure_ascii=False, separators=(",", ":"))}

    return {"fields": {
        "session": as_string(state["session"]),
        "weak": as_string(state["weak"]),
        "consent": as_string(state["consent"]),
    }}


def decode_document(doc: dict[str, Any]) -> dict[str, Any]:
    fields = doc.get("fields") if isinstance(doc, dict) else None
    if not isinstance(fields, dict):
        raise StoreError(503, "store_unavailable")

    def one(name: str) -> Any:
        raw = fields.get(name)
        if not isinstance(raw, dict) or not isinstance(raw.get("stringValue"), str):
            raise StoreError(503, "store_unavailable")
        try:
            return json.loads(raw["stringValue"])
        except json.JSONDecodeError as exc:
            raise StoreError(503, "store_unavailable") from exc

    return parse_state({"session": one("session"), "weak": one("weak"), "consent": one("consent")})


def _http_message(exc: urllib.error.HTTPError) -> str:
    try:
        body = exc.read().decode("utf-8", "replace")
        parsed = json.loads(body)
        message = parsed.get("error", {}).get("message", "")
        return message if isinstance(message, str) else ""
    except Exception:  # noqa: BLE001 — 오류 본문에 토큰이 없어도 읽기 실패는 빈 메시지로 본다
        return ""


def _missing_document(message: str) -> bool:
    """문서 경로에는 databases 가 들어 있다. 데이터베이스 없음과 문서 없음을 그걸로 가르지 않는다."""
    text = message.lower()
    if "does not exist" in text:
        return False
    if "database" in text and "documents/" not in text:
        return False
    return "not found" in text and "documents/" in text


class MemoryUserStore:
    """테스트용. 프로세스 안에만 있고 재시작되면 사라진다."""

    def __init__(self) -> None:
        self.docs: dict[str, dict[str, Any]] = {}

    def read(self, uid: str, token: str) -> dict[str, Any] | None:
        doc = self.docs.get(uid)
        return None if doc is None else json.loads(json.dumps(doc))

    def write(self, uid: str, token: str, state: dict[str, Any]) -> None:
        self.docs[uid] = json.loads(json.dumps(state))


class FirestoreUserStore:
    def __init__(self, project_id: str, opener: Opener | None = None) -> None:
        self.project_id = project_id
        self._opener = opener or _default_opener

    def _root(self) -> str:
        # 같은 프로젝트의 firestore-native-mode 는 다른 앱이 쓴다. 계정 기록은 (default) 만 쓴다.
        project = urllib.request.quote(self.project_id, safe="")
        return f"https://firestore.googleapis.com/v1/projects/{project}/databases/(default)/documents/users"

    def _doc_url(self, uid: str) -> str:
        return self._root() + "/" + urllib.request.quote(uid, safe="")

    def _create_url(self, uid: str) -> str:
        return self._root() + "?documentId=" + urllib.request.quote(uid, safe="")

    def _check_uid(self, uid: str) -> None:
        if not isinstance(uid, str) or not _UID.fullmatch(uid):
            raise StoreError(503, "store_unavailable")

    def _call(self, method: str, url: str, token: str, body: dict[str, Any] | None = None) -> dict[str, Any] | None:
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", "Bearer " + token)
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with self._opener(req, timeout=8) as res:
                raw = res.read()
        except urllib.error.HTTPError as exc:
            message = _http_message(exc)
            if exc.code == 404 and _missing_document(message):
                if method == "GET":
                    return None
                if method == "PATCH":
                    raise MissingDoc from exc
            raise StoreError(503, "store_unavailable") from exc
        except StoreError:
            raise
        except Exception as exc:  # noqa: BLE001 — 주소·토큰은 예외 문자열에 넣지 않는다
            raise StoreError(503, "store_unavailable") from exc
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise StoreError(503, "store_unavailable") from exc
        return parsed if isinstance(parsed, dict) else {}

    def read(self, uid: str, token: str) -> dict[str, Any] | None:
        self._check_uid(uid)
        doc = self._call("GET", self._doc_url(uid), token)
        if doc is None:
            return None
        try:
            return decode_document(doc)
        except StoreError as exc:
            raise StoreError(503, "store_unavailable") from exc

    def write(self, uid: str, token: str, state: dict[str, Any]) -> None:
        self._check_uid(uid)
        body = encode_document(state)
        try:
            self._call("PATCH", self._doc_url(uid) + "?" + _MASK, token, body)
        except MissingDoc:
            self._call("POST", self._create_url(uid), token, body)


def read_for(uid: str, token: str) -> dict[str, Any] | None:
    return get_store().read(uid, token)


def write_for(uid: str, token: str, state: dict[str, Any]) -> None:
    get_store().write(uid, token, state)
