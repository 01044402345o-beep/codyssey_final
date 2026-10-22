"""사용자별 계정 기록 조회·관리(관리자) — Firestore `users/{uid}` 와 Firebase Authentication.

이 도구는 앱(`backend/`)을 import 하지 않는다. 문서 형식(필드마다 JSON 문자열)은 앱의
`user_state.encode_document` 와 같고, 필드는 session·weak·consent·trip·ilog 다.

원칙(개인정보)
- **목록은 요약만** 보여 준다(uid·최근 변경·개수·있음/없음). 여행 도시·이메일·통역 문장은 목록에 없다.
- **상세 보기·통역 기록 내용·내보내기·통역 기록 삭제는 사유를 받아야** 하고, 이 PC의
  `~/.opsarchive/access-log.jsonl` 에 남긴다(누가·언제·무엇을·왜. uid 는 해시 앞 16자만, 내용은 남기지 않는다).
- 이 탭은 **계정을 지우지 않는다.** 탈퇴는 앱의 탈퇴 흐름(흔적·증거 봉인·Auth 삭제)을 거쳐야 한다.
  관리자가 지울 수 있는 것은 통역 기록(ilog) 필드 하나다 — 사용자의 삭제 요청 처리용.
- 서비스 계정 권한이 모자라면 코드로 알린다(Firestore 읽기·쓰기, Auth 조회는 따로다).
"""

from __future__ import annotations

import datetime
import getpass
import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

from . import config, gcp

FIELDS = ("session", "weak", "consent", "trip", "ilog")
AUTH_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
AUDIT_NAME = "access-log.jsonl"
TIMEOUT = 20
_UID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,253}\.[^@\s]{1,63}$")


class UserError(Exception):
    """code: bad_uid | bad_query | reason_required | not_found | forbidden | http_error | auth_forbidden | auth_http_error"""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def check_uid(uid: str) -> str:
    if not isinstance(uid, str) or not _UID.fullmatch(uid):
        raise UserError("bad_uid")
    return uid


def check_reason(reason: str) -> str:
    text = " ".join(str(reason or "").split())
    if len(text) < 2:
        raise UserError("reason_required")
    return text[:200]


def uid_hash(uid: str) -> str:
    return hashlib.sha256(str(uid).encode("utf-8")).hexdigest()[:16]


# ------------------------------------------------------------------ 열람 기록(이 PC)
def audit_path() -> str:
    return os.path.join(config.config_dir(), AUDIT_NAME)


def audit(action: str, uid: str, reason: str, *, result: str = "", path: str | None = None) -> dict:
    """열람·내보내기·삭제를 한 줄씩 남긴다. 개인정보(이메일·내용)는 넣지 않고 uid 는 해시만 넣는다."""
    entry = {"at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
             "action": action, "uid_hash": uid_hash(uid) if uid else "", "reason": reason,
             "admin": _admin_name(), "result": result}
    target = path or audit_path()
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def read_audit(limit: int = 50, path: str | None = None) -> list[dict]:
    try:
        with open(path or audit_path(), "r", encoding="utf-8") as fh:
            lines = fh.readlines()[-limit:]
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _admin_name() -> str:
    try:
        return getpass.getuser()[:64]
    except Exception:                   # noqa: BLE001
        return ""


# ------------------------------------------------------------------ 문서 해석
def parse_fields(fields: dict) -> dict:
    """{필드: {stringValue: JSON}} → {필드: 값}. 깨진 필드는 {"_broken": True} 로 표시한다."""
    out: dict = {}
    for name in FIELDS:
        raw = (fields or {}).get(name)
        if not isinstance(raw, dict) or "stringValue" not in raw:
            continue
        try:
            out[name] = json.loads(raw["stringValue"])
        except (TypeError, json.JSONDecodeError):
            out[name] = {"_broken": True}
    return out


def _bytes(fields: dict) -> int:
    return sum(len(str((v or {}).get("stringValue", "")).encode("utf-8")) for v in (fields or {}).values())


def _ms_date(ms) -> str:
    try:
        return datetime.datetime.fromtimestamp(int(ms) / 1000, datetime.timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def _short_time(rfc: str) -> str:
    try:
        return datetime.datetime.fromisoformat(str(rfc).replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return str(rfc)[:16]


def summarize(uid: str, doc: dict) -> dict:
    """목록 한 줄 — 개수와 있음/없음만(도시·문장·이메일 없음)."""
    fields = doc.get("fields") or {}
    data = parse_fields(fields)
    session = data.get("session") if isinstance(data.get("session"), dict) else {}
    ilog = data.get("ilog") if isinstance(data.get("ilog"), dict) else {}
    sessions = ilog.get("list") if isinstance(ilog.get("list"), list) else []
    consent = data.get("consent") if isinstance(data.get("consent"), dict) else {}
    return {
        "uid": uid,
        "updated": _short_time(doc.get("updateTime", "")),
        "created": _short_time(doc.get("createTime", "")),
        "study_days": len(session.get("done") or {}) if isinstance(session.get("done"), dict) else 0,
        "weak": len(data["weak"]) if isinstance(data.get("weak"), list) else 0,
        "trip": bool(data.get("trip")),
        "voice_consent": bool(consent.get("voice")),
        "ilog_sessions": len(sessions),
        "ilog_lines": sum(len(x.get("lines") or []) for x in sessions if isinstance(x, dict)),
        "ilog_consent": bool(ilog.get("consent")),
        "bytes": _bytes(fields),
        "broken": sorted(k for k, v in data.items() if isinstance(v, dict) and v.get("_broken")),
    }


# ------------------------------------------------------------------ 저장소(관리자 REST)
class Users:
    """Firestore `users`·`deleted` 컬렉션. 서비스 계정 토큰으로 규칙을 거치지 않는다(그래서 사유·기록이 필요하다)."""

    def __init__(self, project_id: str, sa_path: str, store: gcp.Firestore | None = None) -> None:
        self.project_id = project_id
        self.sa_path = sa_path
        self.store = store or gcp.Firestore(project_id, sa_path)

    def _call(self, method: str, path: str, body=None) -> dict | None:
        try:
            return self.store._call(method, self.store._root() + path, body)
        except gcp.GcpError as exc:
            if exc.code == "not_found":
                return None
            raise UserError("http_error") from exc

    def list_users(self, page_size: int = 300, max_pages: int = 20) -> list[dict]:
        rows: list[dict] = []
        token = ""
        for _ in range(max_pages):
            path = "users?pageSize=%d" % page_size + ("&pageToken=" + urllib.parse.quote(token, safe="") if token else "")
            data = self._call("GET", path)
            if data is None:              # 문서가 하나도 없는 컬렉션은 404
                return rows
            for doc in data.get("documents") or []:
                uid = str(doc.get("name", "")).rsplit("/", 1)[-1]
                rows.append(summarize(uid, doc))
            token = str(data.get("nextPageToken") or "")
            if not token:
                break
        rows.sort(key=lambda r: r["updated"], reverse=True)
        return rows

    def get(self, uid: str) -> dict | None:
        return self._call("GET", "users/" + urllib.parse.quote(check_uid(uid), safe=""))

    def tombstone(self, uid: str) -> bool:
        """탈퇴 흔적(deleted/{uid})이 있는가 — 있으면 앱이 그 uid 의 읽기·쓰기를 거부한다."""
        return self._call("GET", "deleted/" + urllib.parse.quote(check_uid(uid), safe="")) is not None

    def delete_ilog(self, uid: str) -> bool:
        """통역 기록 필드만 지운다(진도는 그대로). 문서가 없으면 만들지 않는다(currentDocument.exists)."""
        path = ("users/" + urllib.parse.quote(check_uid(uid), safe="")
                + "?updateMask.fieldPaths=ilog&currentDocument.exists=true")
        return self._call("PATCH", path, {"fields": {}}) is not None


def auth_lookup(project_id: str, sa_path: str, *, uid: str = "", email: str = "", token_fn=None,
                opener=None) -> dict | None:
    """Firebase Authentication 계정 조회(accounts:lookup, 읽기 전용). 없으면 None."""
    if uid:
        body = {"localId": [check_uid(uid)]}
    elif email and _EMAIL.fullmatch(email.strip()):
        body = {"email": [email.strip()]}
    else:
        raise UserError("bad_query")
    access = (token_fn or gcp.token)(sa_path, AUTH_SCOPE)
    url = "https://identitytoolkit.googleapis.com/v1/projects/%s/accounts:lookup" % urllib.parse.quote(project_id, safe="")
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST")
    req.add_header("Authorization", "Bearer " + access)
    req.add_header("Content-Type", "application/json")
    try:
        with (opener or urllib.request.urlopen)(req, timeout=TIMEOUT) as res:
            data = json.loads(res.read() or b"{}")
    except urllib.error.HTTPError as exc:
        raise UserError("auth_forbidden" if exc.code in (401, 403) else "auth_http_error") from exc
    except Exception as exc:            # noqa: BLE001 — 토큰을 메시지에 담지 않는다
        raise UserError("auth_http_error") from exc
    users = data.get("users") if isinstance(data, dict) else None
    if not users:
        return None
    u = users[0]
    return {"uid": str(u.get("localId", "")), "email": str(u.get("email", "")),
            "name": str(u.get("displayName", "")),
            "providers": [str(p.get("providerId", "")) for p in u.get("providerUserInfo") or []] or ["password" if u.get("passwordHash") else ""],
            "created": _ms_date(u.get("createdAt")), "last_login": _ms_date(u.get("lastLoginAt")),
            "disabled": bool(u.get("disabled"))}


# ------------------------------------------------------------------ 관리자 동작(사유 + 기록)
def find_uid(project_id: str, sa_path: str, query: str, **kw) -> str:
    """uid 또는 이메일 → uid. 이메일 검색은 Auth 조회를 쓴다."""
    q = str(query or "").strip()
    if _UID.fullmatch(q):
        return q
    found = auth_lookup(project_id, sa_path, email=q, **kw)
    if not found:
        raise UserError("not_found")
    return found["uid"]


def detail(users: Users, uid: str, reason: str, *, auth=None) -> dict:
    """한 사용자의 상세(통역 문장 본문은 빼고). auth 는 auth_lookup 결과(없으면 None) 또는 오류 코드 문자열."""
    reason = check_reason(reason)
    doc = users.get(uid)
    gone = users.tombstone(uid)
    audit("view", uid, reason, result="found" if doc else "no_document")
    out = {"uid": uid, "document": bool(doc), "tombstone": gone, "auth": auth}
    if not doc:
        return out
    data = parse_fields(doc.get("fields") or {})
    out["summary"] = summarize(uid, doc)
    session = data.get("session") if isinstance(data.get("session"), dict) else {}
    done = sorted((session.get("done") or {}).keys()) if isinstance(session.get("done"), dict) else []
    out["progress"] = {"study_days": len(done), "first": done[0] if done else "", "last": done[-1] if done else "",
                       "screen": session.get("screen", ""), "weak": [w.get("situation", "") for w in data.get("weak") or []
                                                                     if isinstance(w, dict)][:30]}
    consent = data.get("consent") if isinstance(data.get("consent"), dict) else {}
    out["consent"] = {"voice": bool(consent.get("voice")), "version": consent.get("version"), "at": consent.get("at")}
    trip = data.get("trip") if isinstance(data.get("trip"), dict) else None
    out["trip"] = None if not trip else {
        "country": trip.get("country", ""), "study_start": trip.get("studyStart", ""),
        "cities": ["%s %s~%s" % (c.get("name", ""), c.get("start", ""), c.get("end", "")) for c in trip.get("cities") or []
                   if isinstance(c, dict)]}
    ilog = data.get("ilog") if isinstance(data.get("ilog"), dict) else None
    out["ilog"] = None if not ilog else {
        "consent_version": (ilog.get("consent") or {}).get("version"), "consent_at": _ms_date((ilog.get("consent") or {}).get("at")),
        "sessions": [{"at": _ms_date(x.get("at")), "route": (x.get("trip") or {}).get("route", ""), "lines": len(x.get("lines") or [])}
                     for x in ilog.get("list") or [] if isinstance(x, dict)]}
    return out


def ilog_text(users: Users, uid: str, reason: str) -> str:
    """통역 기록 본문(상대방 말 포함 — 가장 민감하다). 사유를 따로 받아 남긴다."""
    reason = check_reason(reason)
    doc = users.get(uid)
    ilog = parse_fields((doc or {}).get("fields") or {}).get("ilog")
    audit("view_ilog", uid, reason, result="found" if isinstance(ilog, dict) else "none")
    if not isinstance(ilog, dict):
        return "통역 기록이 없습니다(사용자가 계정 저장에 동의하지 않았거나 지웠습니다)."
    lines = []
    for x in ilog.get("list") or []:
        if not isinstance(x, dict):
            continue
        lines.append("■ %s · %s · %d문장" % (_ms_date(x.get("at")), (x.get("trip") or {}).get("route", "여행 없이"),
                                         len(x.get("lines") or [])))
        for ln in x.get("lines") or []:
            who = "나" if ln.get("s") == "ko" else "상대"
            lines.append("  [%s %s] %s → %s" % (_ms_date(ln.get("at"))[-5:], who, ln.get("src", ""), ln.get("dst", "")))
    return "\n".join(lines) or "통역 기록이 비어 있습니다."


def export(users: Users, uid: str, reason: str, out_path: str, *, auth=None) -> dict:
    """열람 요구 대응용 내보내기(이 사용자 문서 전체 + 계정 정보). 파일은 이 PC 에만 쓴다."""
    reason = check_reason(reason)
    doc = users.get(uid)
    payload = {"exported_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
               "uid": uid, "auth": auth if isinstance(auth, dict) else None,
               "document": parse_fields((doc or {}).get("fields") or {}) if doc else None,
               "document_updated": (doc or {}).get("updateTime", ""), "tombstone": users.tombstone(uid)}
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    try:
        os.chmod(out_path, 0o600)
    except OSError:
        pass
    audit("export", uid, reason, result="written" if doc else "no_document")
    return {"path": out_path, "document": bool(doc), "bytes": os.path.getsize(out_path)}


def delete_ilog(users: Users, uid: str, reason: str) -> dict:
    """사용자 요청으로 통역 기록 필드만 지운다. 기록을 먼저 남기고(시도), 결과도 남긴다."""
    reason = check_reason(reason)
    audit("delete_ilog_request", uid, reason)
    try:
        existed = users.delete_ilog(uid)
    except UserError as exc:
        audit("delete_ilog_result", uid, reason, result="failed:" + exc.code)
        raise
    audit("delete_ilog_result", uid, reason, result="deleted" if existed else "no_document")
    return {"uid": uid, "deleted": existed,
            "note": "진도·여행은 그대로입니다. 사용자의 기기에 남은 기록은 지워지지 않습니다(앱이 다음에 서버를 볼 때 계정 저장이 꺼집니다)."
            if existed else "문서가 없습니다(지울 것 없음)."}
