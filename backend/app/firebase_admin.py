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


def erase_account(uid: str) -> None:
    """탈퇴: 토큰 취소 → 기록 삭제 → 계정 삭제. uid 는 호출부가 검증한 토큰에서 온다."""
    get_admin().erase(uid)


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

    def _call(self, method: str, url: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
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

    def erase(self, uid: str) -> None:
        """순서: 토큰 취소 → 기록 삭제 → 계정 삭제. 계정 삭제가 마지막이라 도중 실패해도 다시 시도할 수 있다."""
        self.revoke(uid)
        self.delete_document(uid)
        self.delete_user(uid)
