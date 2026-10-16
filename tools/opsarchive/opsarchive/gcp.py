"""Google Cloud 호출 — 서비스 계정 토큰과 Firestore REST(아카이브 읽기·쓰기·삭제).

앱(`backend/app/firebase_admin.py`)과 같은 방식으로 REST 를 직접 부른다. 토큰은 google-auth 로
서비스 계정 JSON 에서 발급한다(스코프는 datastore 하나면 충분하다 — Storage 를 쓰지 않는다).

규칙
- 자격증명·응답 본문을 예외 메시지에 담지 않는다(로그·화면 노출 금지).
- 모든 호출에 타임아웃을 둔다.
- Firestore 문서 제한은 1MiB 다. 청크 단위는 호출자가 정한다(기본 512KB).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

FIRESTORE = "https://firestore.googleapis.com/v1"
SCOPE = "https://www.googleapis.com/auth/datastore"
TIMEOUT = 20


class GcpError(Exception):
    """code: no_credentials | token_failed | http_error | bad_document"""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def token(sa_path: str) -> str:
    """서비스 계정 JSON 으로 접근 토큰을 받는다. 필요할 때만 google-auth 를 import 한다."""
    try:
        from google.auth.transport.urllib3 import Request
        from google.oauth2 import service_account
    except ImportError as exc:      # 의존성이 없으면 이유를 값으로 알린다
        raise GcpError("no_credentials") from exc
    try:
        creds = service_account.Credentials.from_service_account_file(sa_path, scopes=[SCOPE])
        creds.refresh(Request())
        return creds.token
    except Exception as exc:        # noqa: BLE001 — 경로·키 내용을 메시지에 넣지 않는다
        raise GcpError("token_failed") from exc


# ------------------------------------------------------------------ 값 코덱
# Firestore REST 는 타입이 붙은 값을 쓴다. 앱(user_state.py)에도 같은 코덱이 있지만
# 이 CLI 는 앱과 독립 프로세스이므로 복제한다(형식은 테스트가 대조한다).

def encode_value(value):
    if value is None:
        return {"nullValue": None}
    if isinstance(value, bool):
        return {"booleanValue": value}
    if isinstance(value, int):
        return {"integerValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, bytes):
        import base64
        return {"bytesValue": base64.b64encode(value).decode()}
    if isinstance(value, str):
        return {"stringValue": value}
    if isinstance(value, list):
        return {"arrayValue": {"values": [encode_value(v) for v in value]}}
    if isinstance(value, dict):
        return {"mapValue": {"fields": {k: encode_value(v) for k, v in value.items()}}}
    raise GcpError("bad_document")


def encode_fields(data: dict) -> dict:
    return {"fields": {k: encode_value(v) for k, v in data.items()}}


def decode_value(raw: dict):
    if raw is None:
        return None
    for key, cast in (("stringValue", str), ("integerValue", int), ("doubleValue", float),
                      ("booleanValue", bool), ("bytesValue", str)):
        if key in raw:
            return cast(raw[key])
    if "nullValue" in raw:
        return None
    if "arrayValue" in raw:
        return [decode_value(v) for v in raw["arrayValue"].get("values", [])]
    if "mapValue" in raw:
        return decode_fields(raw["mapValue"].get("fields", {}))
    return None


def decode_fields(fields: dict) -> dict:
    return {k: decode_value(v) for k, v in (fields or {}).items()}


# ------------------------------------------------------------------ REST

class Firestore:
    """관리자 접근(규칙을 거치지 않는다). 경로는 `evidence_archives/...` 처럼 준다."""

    def __init__(self, project_id: str, sa_path: str) -> None:
        self.project_id = project_id
        self.sa_path = sa_path
        self._token = ""

    def _root(self) -> str:
        return (FIRESTORE + "/projects/" + urllib.parse.quote(self.project_id, safe="")
                + "/databases/(default)/documents/")

    def _call(self, method: str, url: str, body=None) -> dict:
        if not self._token:
            self._token = token(self.sa_path)
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", "Bearer " + self._token)
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
                raw = res.read()
        except urllib.error.HTTPError as exc:
            self._token = ""            # 만료·권한 문제는 다음 호출에서 다시 시도한다
            if exc.code == 404:
                raise GcpError("not_found") from exc    # '없음' 과 '실패' 를 구분한다
            raise GcpError("http_error") from exc
        except Exception as exc:        # noqa: BLE001
            raise GcpError("http_error") from exc
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def get(self, path: str) -> dict | None:
        """문서 하나. **없으면 None, 조회에 실패하면 예외** — 둘을 섞으면 일시 장애가 '없음'으로 보인다."""
        try:
            doc = self._call("GET", self._root() + path)
        except GcpError as exc:
            if exc.code == "not_found":
                return None
            raise
        return decode_fields(doc.get("fields", {})) if doc else None

    def set(self, path: str, data: dict) -> None:
        """문서 만들기/덮어쓰기(PATCH 는 없으면 만든다)."""
        self._call("PATCH", self._root() + path, encode_fields(data))

    def delete(self, path: str) -> None:
        self._call("DELETE", self._root() + path)

    def list(self, collection: str, page_size: int = 300) -> list[dict]:
        """컬렉션 문서 목록. **페이지를 끝까지 따라간다**(안 그러면 청크가 잘려 조용히 깨진다)."""
        out: list[dict] = []
        token = ""
        pages = 0
        while True:
            url = self._root() + collection + "?pageSize=" + str(page_size)
            if token:
                url += "&pageToken=" + urllib.parse.quote(token, safe="")
            data = self._call("GET", url)
            for doc in data.get("documents", []) or []:
                name = str(doc.get("name", ""))
                item = decode_fields(doc.get("fields", {}))
                item["_id"] = name.rsplit("/", 1)[-1] if name else ""
                out.append(item)
            token = str(data.get("nextPageToken", "") or "")
            pages += 1
            if not token or pages >= 50:      # 서버가 같은 토큰을 반복해도 멈춘다
                return out
