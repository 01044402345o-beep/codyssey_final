"""계정별 진도 저장.

Render 디스크는 재시작되면 지워지므로 쓰지 않는다. 이 모듈은 서비스 계정 JSON 도 쓰지 않는다
(탈퇴 관리자 경로 `app/firebase_admin.py` 만 서비스 계정을 쓴다).
확인된 Firebase ID 토큰을 Firestore 보안 규칙에 그대로 넘긴다.
문서는 users/{uid} 하나다. 담는 것은 진도, 복습 목록, 말하기 동의, 그리고
여행 입력(나라·도시별 체류 날짜·학습 시작일), 그리고 사용자가 동의했을 때만 통역 기록(ilog)이다.
통역 기록은 진도와 **따로** 읽고 쓴다(PUT /user/state 의 updateMask 에 ilog 가 없어 진도 저장이 기록을 지우지 않는다).
장소·문장 본문은 담지 않는다. 화면이 그 입력으로 규칙을 다시 돌려 만든다.

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
EMPTY_STATE: dict[str, Any] = {"session": None, "weak": [], "consent": None, "trip": None}

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SCREEN = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
_ID = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_AT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$")
_UID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_MASK = ("updateMask.fieldPaths=session&updateMask.fieldPaths=weak"
         "&updateMask.fieldPaths=consent&updateMask.fieldPaths=trip")
_ILOG_MASK = "updateMask.fieldPaths=ilog"   # 이 필드만 바꾸거나(값 있음) 지운다(값 없음)

# 통역 기록(사용자 동의 시에만 서버 저장). 화면의 상한(30대화·300문장)과 같다. 음성은 담지 않는다.
ILOG_MAX_BYTES = 60_000
ILOG_SESSIONS = 30
ILOG_LINES = 300
ILOG_TEXT = 500
_ILOG_ID = re.compile(r"^s[a-z0-9]{1,20}$")
_LANGS = {"ko", "en"}

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
    # 홈처럼 학습 카드를 열지 않으면 화면은 date: null 을 보낸다. 그때는 카드 없음이다.
    # 날짜가 없는 카드의 다른 칸이 깨져 있으면 그대로 거절한다(여행을 같이 지우지 않되, 쓰레기는 받지 않는다).
    if date is None:
        if "i" in value:
            _num(value.get("i"), 0, 500)
        back = value.get("back")
        if back is not None:
            _num(back, 0, 500)
        flipped_in = value.get("flipped", [])
        if not isinstance(flipped_in, list) or len(flipped_in) > 500:
            _fail()
        [_num(n, 0, 500) for n in flipped_in]
        return None
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
    if not isinstance(value, dict) or set(value) - {"v", "at", "done", "pre", "act", "screen", "studyDate", "card"}:
        _fail()
    if value.get("v") != 1:
        _fail()
    done = _date_stamps(value.get("done"))
    # 미리 학습한 날짜(선택). 그날이 오면 화면이 완료로 옮긴다 — 없는 옛 화면도 그대로 통과한다.
    pre = _date_stamps(value.get("pre", {}))
    # 날짜별 학습 활동 수(선택) — 연속 학습·오늘 목표. 없는 옛 화면도 통과한다.
    act = _day_counts(value.get("act", {}))
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
        **({"pre": pre} if pre else {}),
        **({"act": act} if act else {}),
    }


def _date_stamps(value: Any) -> dict[str, int]:
    """{'YYYY-MM-DD': 시각(ms)} — 완료·미리 학습 기록이 같은 모양이다."""
    if not isinstance(value, dict) or len(value) > 400:
        _fail()
    out: dict[str, int] = {}
    for key, stamp in value.items():
        if not isinstance(key, str) or not _DATE.fullmatch(key):
            _fail()
        out[key] = _num(stamp, 0, 10**15)
    return out


def _day_counts(value: Any) -> dict[str, int]:
    """{'YYYY-MM-DD': 그날 뒤집은 카드 수(0~10000)} — 화면이 120일만 남긴다."""
    if not isinstance(value, dict) or len(value) > 400:
        _fail()
    out: dict[str, int] = {}
    for key, count in value.items():
        if not isinstance(key, str) or not _DATE.fullmatch(key):
            _fail()
        out[key] = int(_num(count, 0, 10000))
    return out


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


def _trip(value: Any) -> dict[str, Any] | None:
    """여행 입력(온보딩 1단계). 장소·문장은 담지 않는다 — 화면이 이 입력으로 규칙을 다시 돌린다.

    화면(ai.js cleanTrip)과 같은 규칙: 나라 1~80자, 도시 1~5곳, 도시마다 이름 1~80자와
    체류 시작·종료 날짜, 학습 시작일. 규칙 밖 값은 400 으로 거절한다(조용히 버리지 않는다).
    """
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) - {"countries"} != {"country", "cities", "studyStart"}:
        _fail()
    country = value.get("country")
    if not isinstance(country, str) or not 1 <= len(country.strip()) <= 80:
        _fail()
    # 여러 나라(최대 4): countries[0] == country, 도시마다 ci(속한 나라 순번). 나라가 하나면 예전 모양으로 돌려준다.
    countries = [country.strip()]
    if "countries" in value:
        raw = value["countries"]
        if not isinstance(raw, list) or not 1 <= len(raw) <= 4:
            _fail()
        if not all(isinstance(n, str) and 1 <= len(n.strip()) <= 80 for n in raw):
            _fail()
        countries = [n.strip() for n in raw]
        if countries[0] != country.strip():
            _fail()
    multi = len(countries) > 1
    cities_in = value.get("cities")
    if not isinstance(cities_in, list) or not 1 <= len(cities_in) <= 5:
        _fail()
    cities: list[dict[str, Any]] = []
    for city in cities_in:
        if not isinstance(city, dict) or set(city) - {"ci"} != {"name", "start", "end"}:
            _fail()
        name = city.get("name")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
            _fail()
        start, end = city.get("start"), city.get("end")
        if not isinstance(start, str) or not _DATE.fullmatch(start):
            _fail()
        if not isinstance(end, str) or not _DATE.fullmatch(end):
            _fail()
        ci = city.get("ci", 0)
        if type(ci) is not int or not 0 <= ci < len(countries):
            _fail()
        cities.append({"name": name.strip(), "start": start, "end": end, **({"ci": ci} if multi else {})})
    if multi and any(not any(c["ci"] == i for c in cities) for i in range(len(countries))):
        _fail()   # 도시 없는 나라는 없다
    study = value.get("studyStart")
    if not isinstance(study, str) or not _DATE.fullmatch(study):
        _fail()
    out: dict[str, Any] = {"country": country.strip(), "cities": cities, "studyStart": study}
    if multi:
        out["countries"] = countries
    return out


def parse_state(body: Any) -> dict[str, Any]:
    """본문에서 진도·복습·동의·여행 입력만 남긴다. uid 는 받지 않는다.

    trip 은 나중에 붙은 항목이다. 예전 기록(문서)에는 없으므로 없으면 null 로 둔다.
    """
    if not isinstance(body, dict):
        raise StoreError(400, "invalid_state")
    if not {"session", "weak", "consent"} <= set(body) or (set(body) - {"session", "weak", "consent", "trip"}):
        raise StoreError(400, "invalid_state")
    state = {
        "session": _session(body.get("session")),
        "weak": _weak(body.get("weak")),
        "consent": _consent(body.get("consent")),
        "trip": _trip(body.get("trip")),
    }
    raw = json.dumps(state, ensure_ascii=False, separators=(",", ":")).encode()
    if len(raw) > MAX_STATE_BYTES:
        raise StoreError(413, "state_too_large")
    return state


def _ms(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 1_600_000_000_000 <= value <= 4_100_000_000_000:
        raise StoreError(400, "invalid_ilog")
    return value


def _text(value: Any) -> str:
    if not isinstance(value, str) or len(value) > ILOG_TEXT:
        raise StoreError(400, "invalid_ilog")
    return value


def _lang(value: Any) -> str:
    if value not in _LANGS:
        raise StoreError(400, "invalid_ilog")
    return value


def parse_ilog(body: Any) -> dict[str, Any]:
    """통역 기록: {v:1, consent:{version, at}, list:[대화…]}. 동의(consent)가 없으면 받지 않는다.

    대화 = {id, at, a, b, trip:{route}|null, lines:[{src, dst, s, t, at}]}. 모르는 키·긴 글·많은 줄은 거절한다.
    """
    if not isinstance(body, dict) or set(body) - {"v", "consent", "list"} or body.get("v") != 1:
        raise StoreError(400, "invalid_ilog")
    consent = body.get("consent")
    if (not isinstance(consent, dict) or set(consent) - {"version", "at"}
            or not isinstance(consent.get("version"), str) or not 1 <= len(consent["version"]) <= 40):
        raise StoreError(400, "ilog_consent_required")
    out_list: list[dict[str, Any]] = []
    raw_list = body.get("list")
    if not isinstance(raw_list, list) or len(raw_list) > ILOG_SESSIONS:
        raise StoreError(400, "invalid_ilog")
    lines_total = 0
    for x in raw_list:
        if not isinstance(x, dict) or set(x) - {"id", "at", "a", "b", "trip", "lines"}:
            raise StoreError(400, "invalid_ilog")
        if not isinstance(x.get("id"), str) or not _ILOG_ID.fullmatch(x["id"]):
            raise StoreError(400, "invalid_ilog")
        trip = x.get("trip")
        if trip is not None:
            if not isinstance(trip, dict) or set(trip) - {"id", "route"}:
                raise StoreError(400, "invalid_ilog")
            trip = {"route": _text(trip.get("route", ""))[:120]}
        lines = x.get("lines")
        if not isinstance(lines, list) or not lines:
            raise StoreError(400, "invalid_ilog")
        lines_total += len(lines)
        if lines_total > ILOG_LINES:
            raise StoreError(413, "ilog_too_large")
        clean = []
        for ln in lines:
            if not isinstance(ln, dict) or set(ln) - {"src", "dst", "s", "t", "at"}:
                raise StoreError(400, "invalid_ilog")
            clean.append({"src": _text(ln.get("src", "")), "dst": _text(ln.get("dst", "")),
                          "s": _lang(ln.get("s")), "t": _lang(ln.get("t")), "at": _ms(ln.get("at"))})
        out_list.append({"id": x["id"], "at": _ms(x.get("at")), "a": _lang(x.get("a")), "b": _lang(x.get("b")),
                         "trip": trip, "lines": clean})
    ilog = {"v": 1, "consent": {"version": consent["version"], "at": _ms(consent.get("at"))}, "list": out_list}
    if len(json.dumps(ilog, ensure_ascii=False, separators=(",", ":")).encode()) > ILOG_MAX_BYTES:
        raise StoreError(413, "ilog_too_large")
    return ilog


def encode_document(state: dict[str, Any]) -> dict[str, Any]:
    def as_string(value: Any) -> dict[str, str]:
        return {"stringValue": json.dumps(value, ensure_ascii=False, separators=(",", ":"))}

    return {"fields": {
        "session": as_string(state["session"]),
        "weak": as_string(state["weak"]),
        "consent": as_string(state["consent"]),
        "trip": as_string(state["trip"]),
    }}


def decode_document(doc: dict[str, Any]) -> dict[str, Any]:
    fields = doc.get("fields") if isinstance(doc, dict) else None
    if not isinstance(fields, dict):
        raise StoreError(503, "store_unavailable")

    def one(name: str) -> Any:
        raw = fields.get(name)
        # trip 은 trip 지원 전에 쓰인 문서에는 없다. 그때는 None 으로 본다(나머지는 그대로 엄격하게).
        if raw is None and name == "trip":
            return None
        if not isinstance(raw, dict) or not isinstance(raw.get("stringValue"), str):
            raise StoreError(503, "store_unavailable")
        try:
            return json.loads(raw["stringValue"])
        except json.JSONDecodeError as exc:
            raise StoreError(503, "store_unavailable") from exc

    return parse_state({"session": one("session"), "weak": one("weak"),
                        "consent": one("consent"), "trip": one("trip")})


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
        self.ilogs: dict[str, Any] = {}   # 통역 기록: 같은 문서의 다른 필드라 진도 쓰기와 서로 덮지 않는다

    def read(self, uid: str, token: str) -> dict[str, Any] | None:
        doc = self.docs.get(uid)
        return None if doc is None else json.loads(json.dumps(doc))

    def write(self, uid: str, token: str, state: dict[str, Any]) -> None:
        self.docs[uid] = json.loads(json.dumps(state))

    def delete(self, uid: str, token: str) -> None:
        self.docs.pop(uid, None)
        self.ilogs.pop(uid, None)

    def read_ilog(self, uid: str, token: str) -> dict[str, Any] | None:
        v = self.ilogs.get(uid)
        return None if v is None else json.loads(json.dumps(v))

    def write_ilog(self, uid: str, token: str, ilog: dict[str, Any]) -> None:
        self.docs.setdefault(uid, json.loads(json.dumps(EMPTY_STATE)))
        self.ilogs[uid] = json.loads(json.dumps(ilog))

    def delete_ilog(self, uid: str, token: str) -> None:
        self.ilogs.pop(uid, None)


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
                if method == "DELETE":
                    return None   # 이미 없는 문서를 지우는 것은 성공으로 본다(탈퇴 재시도)
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

    def delete(self, uid: str, token: str) -> None:
        self._check_uid(uid)
        self._call("DELETE", self._doc_url(uid), token)

    def read_ilog(self, uid: str, token: str) -> dict[str, Any] | None:
        self._check_uid(uid)
        doc = self._call("GET", self._doc_url(uid) + "?mask.fieldPaths=ilog", token)
        raw = ((doc or {}).get("fields") or {}).get("ilog")
        if not isinstance(raw, dict) or not isinstance(raw.get("stringValue"), str):
            return None
        try:
            return parse_ilog(json.loads(raw["stringValue"]))
        except (json.JSONDecodeError, StoreError) as exc:
            raise StoreError(503, "store_unavailable") from exc

    def write_ilog(self, uid: str, token: str, ilog: dict[str, Any]) -> None:
        self._check_uid(uid)
        field = {"ilog": {"stringValue": json.dumps(ilog, ensure_ascii=False, separators=(",", ":"))}}
        # Firestore PATCH 는 문서가 없으면 만든다(upsert). 그러면 ilog 하나뿐인 문서가 되어 보안 규칙(session·weak·consent 필수)에
        # 막힌다. 그래서 먼저 문서가 있는지 보고, 없으면 빈 진도와 함께 만든다.
        if self._call("GET", self._doc_url(uid) + "?mask.fieldPaths=consent", token) is None:
            doc = encode_document(EMPTY_STATE)
            doc["fields"].update(field)
            self._call("POST", self._create_url(uid), token, doc)
            return
        self._call("PATCH", self._doc_url(uid) + "?" + _ILOG_MASK, token, {"fields": field})

    def delete_ilog(self, uid: str, token: str) -> None:
        """기록 필드만 지운다(진도는 그대로). 문서가 없으면 지울 것도 없다(빈 PATCH 가 빈 문서를 만들지 않게 먼저 확인)."""
        self._check_uid(uid)
        if self._call("GET", self._doc_url(uid) + "?mask.fieldPaths=consent", token) is None:
            return
        self._call("PATCH", self._doc_url(uid) + "?" + _ILOG_MASK, token, {"fields": {}})


def read_for(uid: str, token: str) -> dict[str, Any] | None:
    return get_store().read(uid, token)


def write_for(uid: str, token: str, state: dict[str, Any]) -> None:
    get_store().write(uid, token, state)


def read_ilog_for(uid: str, token: str) -> dict[str, Any] | None:
    return get_store().read_ilog(uid, token)


def write_ilog_for(uid: str, token: str, ilog: dict[str, Any]) -> None:
    get_store().write_ilog(uid, token, ilog)


def delete_ilog_for(uid: str, token: str) -> None:
    get_store().delete_ilog(uid, token)


def delete_for(uid: str, token: str) -> None:
    """탈퇴: 이 계정의 기록 문서를 지운다. 없는 문서를 지우는 것은 성공으로 본다."""
    get_store().delete(uid, token)
