"""Firebase Auth 확인.

화면 로그인은 Firebase Authentication 이다. 문장 생성과 말하기는 이 모듈을
거치지 않고 기존 Render 경로에 남는다. 로그인한 계정의 진도·복습·동의와
여행 입력(나라·도시·날짜·학습 시작일)은 user_state 가 맡고, 장소·문장 본문은
브라우저가 규칙으로 다시 만든다. (Firestore 쓰기 필드는 firestore.rules 의
hasOnly 목록과 같아야 한다 — backend/tests/test_user_state.py 가 교차검증한다.)

웹 설정(apiKey, authDomain, projectId)은 공개 값이다. 서비스 계정 키는
읽지 않는다 — 예외는 `app/firebase_admin.py` 의 탈퇴 경로(`POST /account/erase`)뿐이고,
그 키는 환경변수 `FIREBASE_SERVICE_ACCOUNT_JSON` 으로만 받는다. 토큰 서명은 Google 공개 인증서로 확인한다.
"""
from __future__ import annotations

import os
from typing import Any

from google.auth.transport import requests
from google.oauth2 import id_token


class AuthError(Exception):
    def __init__(self, status: int, code: str) -> None:
        self.status = status
        self.code = code


def _project_id() -> str:
    return (os.getenv("FIREBASE_PROJECT_ID") or "").strip()


def configured() -> bool:
    """로그인에 필요한 공개 설정 세 값이 모두 있을 때."""
    return bool(
        (os.getenv("FIREBASE_API_KEY") or "").strip()
        and (os.getenv("FIREBASE_AUTH_DOMAIN") or "").strip()
        and _project_id()
    )


def public_config() -> dict[str, Any]:
    """브라우저가 Firebase 를 초기화할 때 쓰는 값. 없으면 enabled 만 false."""
    if not configured():
        return {"enabled": False}
    body: dict[str, Any] = {
        "enabled": True,
        "apiKey": os.environ["FIREBASE_API_KEY"].strip(),
        "authDomain": os.environ["FIREBASE_AUTH_DOMAIN"].strip(),
        "projectId": _project_id(),
    }
    app_id = (os.getenv("FIREBASE_APP_ID") or "").strip()
    if app_id:
        body["appId"] = app_id
    return body


def verify_bearer(header: str) -> dict[str, str]:
    """Authorization 헤더의 Firebase ID 토큰을 확인하고 계정 요약을 돌려준다."""
    if not configured():
        raise AuthError(503, "firebase_unconfigured")
    scheme, _, token = (header or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AuthError(401, "missing_token")
    project = _project_id()
    try:
        claims = id_token.verify_firebase_token(
            token.strip(), requests.Request(), audience=project,
        )
    except Exception as exc:  # noqa: BLE001 — 토큰 본문은 로그에 남기지 않는다
        raise AuthError(401, "invalid_token") from exc
    if claims.get("iss") != f"https://securetoken.google.com/{project}":
        raise AuthError(401, "invalid_token")
    uid = claims.get("sub") or claims.get("user_id")
    if not isinstance(uid, str) or not uid:
        raise AuthError(401, "invalid_token")
    email = claims.get("email") if isinstance(claims.get("email"), str) else ""
    name = claims.get("name") if isinstance(claims.get("name"), str) else ""
    if not name:
        name = email.split("@", 1)[0] if email else "회원"
    firebase = claims.get("firebase")
    provider = ""
    if isinstance(firebase, dict) and isinstance(firebase.get("sign_in_provider"), str):
        provider = firebase["sign_in_provider"]
    return {"uid": uid, "email": email, "name": name, "provider": provider}
