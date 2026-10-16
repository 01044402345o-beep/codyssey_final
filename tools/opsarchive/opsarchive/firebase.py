"""firebase CLI 래퍼 — 이 도구가 firebase CLI 를 실제로 쓰는 지점을 한 곳에 모은다.

firebase CLI 로 **되는 것**: 프로젝트/로그인 확인(`projects:list`), Firestore 규칙 배포
(`deploy --only firestore:rules`), 데이터 export/import, 에뮬레이터.
**안 되는 것**: 임의 Storage 객체 업로드·임의 Firestore 문서 쓰기 → 그건 서비스 계정 REST 로 한다.

그래서 이 도구는 (a) **사전 점검**(프로젝트에 접근 가능한가)과 (b) 운영자가 쓰는 **규칙 배포**에
firebase CLI 를 쓰고, 아카이브 읽기는 서비스 계정 REST(`gcp.py`)로 한다.
"""

from __future__ import annotations

import json
import shutil
import subprocess

TIMEOUT = 120


class FirebaseError(Exception):
    """code: no_cli | cli_failed | bad_json"""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def available() -> bool:
    return bool(shutil.which("firebase"))


def _bin() -> str:
    found = shutil.which("firebase")
    if not found:
        raise FirebaseError("no_cli")
    return found


def run_cli(args: list[str], timeout: int = TIMEOUT) -> str:
    """`firebase` CLI 실행(shell=False). 실패는 값으로만 알린다."""
    try:
        done = subprocess.run([_bin()] + args, capture_output=True, text=True,
                              encoding="utf-8", errors="replace",   # Windows 로케일(cp949) 디코딩 오류 방지
                              timeout=timeout, shell=False)   # noqa: S603
    except subprocess.TimeoutExpired as exc:
        raise FirebaseError("cli_failed") from exc
    if done.returncode != 0:
        raise FirebaseError("cli_failed")
    return done.stdout


def projects() -> list[dict]:
    """접근 가능한 Firebase 프로젝트 목록(`firebase projects:list --json`)."""
    raw = run_cli(["projects:list", "--json"])
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FirebaseError("bad_json") from exc
    out = []
    for item in data.get("result", []) if isinstance(data, dict) else []:
        pid = item.get("projectId") if isinstance(item, dict) else None
        if pid:
            out.append({"project_id": pid, "name": item.get("displayName", "")})
    return out


def has_project(project_id: str) -> bool:
    """이 프로젝트에 접근할 수 있는가(사전 점검). CLI 가 없으면 False."""
    try:
        return any(p["project_id"] == project_id for p in projects())
    except FirebaseError:
        return False


def rules_deploy() -> str:
    """Firestore 규칙 배포 — 운영자가 런북에서 함께 쓰는 명령(`firebase deploy --only firestore:rules`)."""
    return run_cli(["deploy", "--only", "firestore:rules"])
