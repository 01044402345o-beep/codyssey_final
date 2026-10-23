"""Firebase 관리자(서비스 계정) 작업 — 탈퇴 전용.

원칙: 이 프로젝트는 원래 서비스 계정 키를 쓰지 않았다(사용자 ID 토큰만 Firestore 규칙에 넘겼다).
탈퇴는 예외다. 계정 자체(Auth)와 그 토큰을 지우려면 관리자 권한이 필요하다.
  - 계정 삭제: 관리자 삭제는 최근 로그인(requires-recent-login)을 요구하지 않는다
    → 화면의 deleteUser 가 자주 실패하던 벽을 없앤다.
  - 토큰 취소: validSince 를 지금으로 올려, 다른 기기의 미만료 ID 토큰을 무효로 만든다.
  - 기록 삭제: Firestore 문서를 관리자 토큰으로 지운다(규칙과 무관).

키는 환경변수 FIREBASE_SERVICE_ACCOUNT_JSON(JSON 문자열) 하나로만 받는다. 코드·저장소에는 두지 않는다.
키가 없으면 configured() 가 False 이고, 호출부는 503 admin_unavailable 로 답한다.
그때 화면은 기존 경로(규칙 삭제 + 클라이언트 deleteUser)로 되돌아간다.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Any, Callable

IDENTITY = "https://identitytoolkit.googleapis.com/v1"
FIRESTORE = "https://firestore.googleapis.com/v1"
# 최소 권한. Identity Toolkit 서비스가 광고하는 스코프는 firebase/cloud-platform 이고,
# 메서드 문서는 identitytoolkit 도 받는다 — 두 출처를 모두 덮도록 firebase + identitytoolkit 을 함께 넣는다
# (cloud-platform 전체는 쓰지 않는다). Firestore 삭제는 datastore.
SCOPES = [
    "https://www.googleapis.com/auth/firebase",
    "https://www.googleapis.com/auth/identitytoolkit",
    "https://www.googleapis.com/auth/datastore",
]

Opener = Callable[..., Any]
_admin: Any = None          # 테스트가 set_admin 으로 갈아 끼운다


class AdminError(Exception):
    """관리자 경로를 쓸 수 없거나 호출이 실패했다. code 로 원인을 나눈다."""

    def __init__(self, status: int, code: str) -> None:
        self.status = status
        self.code = code


def set_admin(admin: Any) -> None:
    """테스트가 네트워크 없이 관리자 구현을 넣는다. None 이면 다음 호출이 서비스 계정을 고른다."""
    global _admin
    _admin = admin


def service_account_info() -> dict[str, Any] | None:
    raw = (os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON") or "").strip()
    if not raw:
        return None
    try:
        info = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(info, dict):
        return None
    if not isinstance(info.get("project_id"), str) or not info.get("project_id"):
        return None
    if not isinstance(info.get("private_key"), str) or not info.get("private_key"):
        return None
    # client_email 이 없으면 자격증명을 만들 수 없다 — configured() 가 참이어도 실제 호출은 실패한다.
    if not isinstance(info.get("client_email"), str) or not info.get("client_email"):
        return None
    return info


def _project() -> str:
    info = service_account_info() or {}
    return (os.getenv("FIREBASE_PROJECT_ID") or "").strip() or str(info.get("project_id") or "").strip()


def configured() -> bool:
    """탈퇴 관리자 경로를 쓸 수 있는가 — 서비스 계정 JSON 과 프로젝트 id 가 모두 있어야 한다."""
    return service_account_info() is not None and bool(_project())


def get_admin() -> Any:
    if _admin is not None:
        return _admin
    if not configured():
        raise AdminError(503, "admin_unavailable")
    project = _project()
    info = service_account_info() or {}
    sa_project = str(info.get("project_id") or "").strip()
    if sa_project and sa_project != project:
        # 프로젝트가 다르면 엉뚱한 곳을 지울 수 있다. 어느 쪽을 대상으로 하는지만 남긴다(키·이메일은 남기지 않는다).
        logging.getLogger("app.firebase_admin").warning(
            "서비스 계정 project_id 와 FIREBASE_PROJECT_ID 가 다릅니다 — %s 를 대상으로 합니다", project)
    return ServiceAccountAdmin(project, info)


def erase_account(uid: str, ledger: list[dict[str, Any]] | None = None) -> None:
    """탈퇴: 흔적 → 토큰 취소 → 기록 삭제 → 계정 삭제. uid 는 호출부가 검증한 토큰에서 온다."""
    get_admin().erase(uid, ledger)


def verify_erased(uid: str) -> dict[str, Any]:
    """탈퇴가 실제로 끝났는지 사후 검증한다.

    "성공했다고 응답했는데 남아 있는" 경우를 잡기 위한 것이다(단계 생략·부분 실패).
    관리자 권한이 없으면 검증할 수 없으므로 `configured: false` 로 돌려준다.
    """
    if _admin is None and not configured():
        return {"configured": False, "tombstone": None, "document_gone": None,
                "account_gone": None, "ok": None}
    admin = get_admin()
    try:
        tombstone = bool(admin.read_tombstone(uid))
        document_gone = not bool(admin.firestore("GET", "users/" + urllib.request.quote(uid, safe="")))
        account_gone = not bool(admin.lookup_user(uid))
    except Exception:  # noqa: BLE001 — 검증 실패가 "성공한 탈퇴"를 500 으로 만들면 안 된다
        return {"configured": True, "tombstone": None, "document_gone": None,
                "account_gone": None, "ok": None, "error": "verify_failed"}
    return {"configured": True, "tombstone": tombstone, "document_gone": document_gone,
            "account_gone": account_gone, "ok": bool(tombstone and document_gone and account_gone)}


# ---------------------------------------------------------------- 탈퇴 흔적(tombstone)
# 왜 필요한가: 관리자 삭제는 갱신 토큰을 즉시 무효화하지만, 이미 발급된 ID 토큰은 만료(≤1h)까지 유효하다.
# 그 창 안에 다른 기기가 PUT /user/state 를 보내면 users/{uid} 문서가 다시 만들어진다.
# 탈퇴한 uid 를 흔적(deleted/{uid})으로 남겨 그 uid 의 쓰기를 거부한다.
#   - 흔적은 서비스 계정(관리자)으로만 읽고 쓴다 → 흔적 자체의 읽기·쓰기는 Firestore 규칙을 거치지 않는다.
#   - firestore.rules 는 흔적이 있는 uid 의 users/{uid} create/update 를 거부한다(10/23) — 컬렉션 이름 'deleted' 를 바꾸면 규칙도 같이.
#   - 담는 것은 uid 와 시각뿐이다(개인정보 없음).
TOMBSTONE_TTL = 3600        # 양성 캐시 수명. 탈퇴는 되돌리지 않으므로 길게 잡아도 안전하다
FAIL_TTL = 5                # 흔적 조회 실패를 잠깐 기억한다(저장소 장애 때 요청마다 재시도로 몰리지 않게)
CACHE_MAX = 4096            # 캐시가 이보다 커지면 만료분을 정리한다
_erased: dict[str, float] = {}     # uid -> 캐시 만료 시각(양성만)
_failed: dict[str, float] = {}     # uid -> 마지막 조회 실패 시각


def reset_cache() -> None:
    """테스트가 캐시를 비운다."""
    _erased.clear()
    _failed.clear()


def _drop_expired(now: float) -> None:
    for box, ttl in ((_erased, TOMBSTONE_TTL), (_failed, FAIL_TTL)):
        if len(box) < CACHE_MAX:
            continue
        for key, stamp in list(box.items()):
            if stamp + ttl <= now:
                box.pop(key, None)


def mark_erased(uid: str) -> None:
    """이 프로세스가 탈퇴를 처리했음을 캐시에 남긴다(같은 인스턴스는 즉시 차단)."""
    _remember(uid, time.time())
    _failed.pop(uid, None)


def _remember(uid: str, now: float) -> None:
    if len(_erased) >= CACHE_MAX:
        _drop_expired(now)
        if len(_erased) >= CACHE_MAX:      # 만료분이 없으면 절반을 버린다(다시 읽으면 그만이다)
            for key in list(_erased)[: CACHE_MAX // 2]:
                _erased.pop(key, None)
    _erased[uid] = now + TOMBSTONE_TTL


def is_erased(uid: str) -> bool:
    """이 uid 가 탈퇴했는가.

    **양성만 캐시한다.** 탈퇴는 되돌리지 않으므로 '흔적 있음'은 안전하게 캐시할 수 있지만,
    '흔적 없음'을 캐시하면 다른 인스턴스가 방금 쓴 흔적을 그 시간 동안 못 보고 통과시킨다(재생성 창).
    흔적을 읽지 못하면 통과시킨다(fail-open) — 일시적 저장소 장애가 앱 전체 쓰기를 막지 않게.
    """
    if _admin is None and not configured():
        return False
    now = time.time()
    if _erased.get(uid, 0) > now:
        return True
    if now - _failed.get(uid, 0) < FAIL_TTL:
        return False
    try:
        found = bool(get_admin().read_tombstone(uid))
    except AdminError:
        _failed[uid] = now
        _drop_expired(now)
        logging.getLogger("app.firebase_admin").warning("탈퇴 흔적을 읽지 못했습니다 — 이번 요청은 통과시킵니다")
        return False
    _failed.pop(uid, None)
    if not found:
        return False
    _remember(uid, now)
    return True


def _http_message(exc: urllib.error.HTTPError) -> str:
    try:
        parsed = json.loads(exc.read().decode("utf-8", "replace"))
        message = parsed.get("error", {}).get("message", "")
        return message if isinstance(message, str) else ""
    except Exception:  # noqa: BLE001 — 본문이 없거나 JSON 이 아니면 빈 메시지
        return ""


def _missing(message: str) -> bool:
    """이미 없는 계정/문서를 지우는 것은 성공으로 본다(탈퇴 재시도). 문구를 좁게 본다."""
    text = message.upper()
    if "USER_NOT_FOUND" in text:
        return True
    return "DOCUMENTS/" in text and "NOT FOUND" in text   # Firestore 문서 없음(404)


def _default_opener(req: urllib.request.Request, timeout: float = 10):
    return urllib.request.urlopen(req, timeout=timeout)  # noqa: S310 — 주소는 코드가 만든 값


class ServiceAccountAdmin:
    """서비스 계정으로 Identity Toolkit(계정 취소·삭제) 과 Firestore(문서 삭제) 를 부른다."""

    def __init__(self, project_id: str, info: dict[str, Any], opener: Opener | None = None) -> None:
        self.project_id = project_id
        self._info = info
        self._opener = opener or _default_opener
        self._creds: Any = None

    def _token(self) -> str:
        from google.auth.transport.requests import Request
        from google.oauth2 import service_account

        if self._creds is None:
            self._creds = service_account.Credentials.from_service_account_info(self._info, scopes=SCOPES)
        if not self._creds.valid:
            self._creds.refresh(Request())
        return str(self._creds.token)

    def _call(self, method: str, url: str, body: dict[str, Any] | None = None,
              already_there: bool = False) -> dict[str, Any]:
        """`already_there` 는 '이미 있으면 그대로 둔다'는 호출(흔적 만들기)에만 켠다.

        계정 취소·삭제에 409 를 성공으로 삼키면 토큰이 그대로 살아 있는데 성공으로 보고하게 된다.
        """
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(url, data=data, method=method)
        try:
            token = self._token()          # 키가 잘못됐거나 갱신에 실패하면 AdminError 로 감싼다(500 금지)
        except AdminError:
            raise
        except Exception as exc:  # noqa: BLE001 — 자격증명 오류는 예외 문자열에 키를 담지 않는다
            raise AdminError(503, "admin_failed") from exc
        req.add_header("Authorization", "Bearer " + token)
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with self._opener(req, timeout=10) as res:
                raw = res.read()
        except urllib.error.HTTPError as exc:
            if exc.code in (400, 404) and _missing(_http_message(exc)):
                return {}   # 이미 없는 대상(계정·문서) — 성공으로 본다
            if exc.code == 409 and already_there:
                return {}   # 이미 있는 대상(흔적 중복) — 원하는 상태이므로 성공으로 본다
            raise AdminError(503, "admin_failed") from exc
        except AdminError:
            raise
        except Exception as exc:  # noqa: BLE001 — 주소·토큰은 예외 문자열에 넣지 않는다
            raise AdminError(503, "admin_failed") from exc
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def revoke(self, uid: str) -> None:
        """validSince 를 지금으로 올려 이 계정의 갱신 토큰을 무효로 만든다(다른 기기 토큰 차단)."""
        base = IDENTITY + "/projects/" + urllib.request.quote(self.project_id, safe="")
        self._call("POST", base + "/accounts:update", {"localId": uid, "validSince": str(int(time.time()))})

    def delete_document(self, uid: str) -> None:
        url = (FIRESTORE + "/projects/" + urllib.request.quote(self.project_id, safe="")
               + "/databases/(default)/documents/users/" + urllib.request.quote(uid, safe=""))
        self._call("DELETE", url)

    def delete_user(self, uid: str) -> None:
        base = IDENTITY + "/projects/" + urllib.request.quote(self.project_id, safe="")
        self._call("POST", base + "/accounts:delete", {"localId": uid})

    def _tombstone_url(self, uid: str) -> str:
        return (FIRESTORE + "/projects/" + urllib.request.quote(self.project_id, safe="")
                + "/databases/(default)/documents/deleted/" + urllib.request.quote(uid, safe=""))

    def write_tombstone(self, uid: str) -> None:
        """탈퇴 흔적을 남긴다(uid + 시각). 이미 있으면(409) 그대로 둔다."""
        url = (FIRESTORE + "/projects/" + urllib.request.quote(self.project_id, safe="")
               + "/databases/(default)/documents/deleted?documentId=" + urllib.request.quote(uid, safe=""))
        body = {"fields": {"at": {"stringValue": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}}}
        self._call("POST", url, body, already_there=True)

    def remove_tombstone(self, uid: str) -> None:
        """흔적을 되돌린다(탈퇴가 도중 실패해 계정이 살아 있을 때). 없는 흔적(404)은 성공이다."""
        self._call("DELETE", self._tombstone_url(uid))

    def read_tombstone(self, uid: str) -> bool:
        """흔적이 있으면 True. 없는 문서(404)는 False 로 온다."""
        return bool(self._call("GET", self._tombstone_url(uid)))

    def firestore(self, method: str, subpath: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        """관리자 권한으로 Firestore 문서를 다룬다(규칙을 거치지 않는다). `users/{uid}`·`evidence_archives/...`."""
        url = (FIRESTORE + "/projects/" + urllib.request.quote(self.project_id, safe="")
               + "/databases/(default)/documents/" + subpath.lstrip("/"))
        return self._call(method, url, body)

    def lookup_user(self, uid: str) -> dict[str, Any]:
        """Auth 계정이 남아 있는지 본다(탈퇴 사후 검증). 없으면 빈 dict."""
        base = IDENTITY + "/projects/" + urllib.request.quote(self.project_id, safe="")
        got = self._call("POST", base + "/accounts:lookup", {"localId": [uid]})
        users = got.get("users") if isinstance(got, dict) else None
        return users[0] if isinstance(users, list) and users else {}

    def erase(self, uid: str, ledger: list[dict[str, Any]] | None = None) -> None:
        """순서: 흔적 남김 → 토큰 취소 → 기록 삭제 → 계정 삭제.

        흔적을 가장 먼저 남긴다 — 뒤 단계가 실패해도 이미 발급된 ID 토큰이 문서를 되살리지 못하게.
        계정 삭제가 마지막이라 도중 실패해도 다시 시도할 수 있다.
        도중에 실패하면 흔적을 **되돌린다** — 계정이 아직 살아 있는데 흔적만 남으면 그 사용자는
        로그인한 채로 기록을 올릴 수 없고(403), 화면은 그것을 탈퇴로 오인해 로컬 기록까지 지운다.

        `ledger` 를 주면 단계별 성공/실패를 기록한다(실패 증거 봉인이 "어디까지 갔는지"를 남기기 위해).
        """
        logger = logging.getLogger("app.firebase_admin")

        def step(name: str, action) -> None:
            started = time.time()
            try:
                action()
            except AdminError as exc:
                if ledger is not None:
                    ledger.append({"step": name, "ok": False, "code": exc.code,
                                   "ms": int((time.time() - started) * 1000)})
                raise
            if ledger is not None:
                ledger.append({"step": name, "ok": True, "code": "",
                               "ms": int((time.time() - started) * 1000)})

        step("tombstone", lambda: self.write_tombstone(uid))
        try:
            step("revoke", lambda: self.revoke(uid))
            step("document", lambda: self.delete_document(uid))
            step("user", lambda: self.delete_user(uid))
        except AdminError:
            rolled_back = True
            try:
                self.remove_tombstone(uid)
            except AdminError:
                rolled_back = False
                logger.warning("탈퇴 흔적을 되돌리지 못했습니다 — 그 계정의 기록 저장이 막힐 수 있습니다")
            if ledger is not None:
                ledger.append({"step": "rollback", "ok": rolled_back,
                               "code": "" if rolled_back else "rollback_failed", "ms": 0})
            raise
        mark_erased(uid)
