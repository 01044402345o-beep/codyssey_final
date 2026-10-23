"""Cloud Run 환경변수 반영 — Firebase Hosting + Cloud Run 배포 경로(docs/ops/FIREBASE_DEPLOY.md)용.

Render 처럼 REST API 로 값을 바꾼다. gcloud CLI 는 **로그인 토큰을 받는 데만** 쓴다(`gcloud auth print-access-token`,
고정 인자). 값을 명령줄에 싣지 않는다 — Windows 의 gcloud 는 `gcloud.cmd`(배치 파일)라 인자 주입에 약하고,
명령줄은 프로세스 목록에 남는다(render.py 와 같은 규칙).

- Cloud Run 은 env 목록을 **통째로** 바꾼다(`--set-env-vars` 와 REST 모두). 그래서 지금 서비스를 읽고 → 바꿀 키만
  고치고 → 나머지(다른 변수·Secret Manager 참조)는 그대로 둔 채 다시 쓴다. etag 로 그 사이 다른 변경을 덮지 않는다.
- 값을 바꾸면 새 리비전이 생긴다 = 재배포. 별도 재배포가 없다. 작업(Operation)이 끝날 때까지 기다린다.
- 비밀(EVIDENCE_GH_TOKEN 등)은 여기서 올리지 않는다 — Secret Manager 에 두고 서비스에는 참조만 둔다(문서 참고).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

API = "https://run.googleapis.com/v2"
TIMEOUT = 30
_WIN_DEFAULT = r"C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"


class CloudRunError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def gcloud_bin() -> str:
    found = shutil.which("gcloud") or (os.name == "nt" and os.path.isfile(_WIN_DEFAULT) and _WIN_DEFAULT) or ""
    if not found:
        raise CloudRunError("no_gcloud — Google Cloud CLI 를 설치하고 `gcloud auth login` 하세요")
    return found


def access_token() -> str:
    """gcloud 로그인 계정의 짧은 접근 토큰. 인자는 고정이다(값을 싣지 않는다). 토큰은 로그·결과에 남기지 않는다."""
    binary = gcloud_bin()
    argv = ([os.environ.get("COMSPEC", "cmd.exe"), "/c", binary] if binary.lower().endswith((".cmd", ".bat"))
            else [binary]) + ["auth", "print-access-token"]
    try:
        done = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=60, shell=False)  # noqa: S603
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CloudRunError("gcloud_failed") from exc
    token = (done.stdout or "").strip().splitlines()[-1:] or [""]
    if done.returncode != 0 or not token[0]:
        raise CloudRunError("gcloud_auth — `gcloud auth login` 으로 로그인하세요")
    return token[0]


def service_name(project: str, region: str, service: str) -> str:
    for part in (project, region, service):
        if not part or "/" in part or not all(c.isalnum() or c in "-_." for c in part):
            raise CloudRunError("bad_input:%s" % part)
    return "projects/%s/locations/%s/services/%s" % (project, region, service)


def _call(method: str, url: str, token: str, body: Any = None) -> dict:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
            raw = res.read()
    except urllib.error.HTTPError as exc:
        raise CloudRunError({404: "not_found", 403: "forbidden", 401: "unauthenticated",
                             409: "conflict", 412: "conflict"}.get(exc.code, "http_%d" % exc.code)) from exc
    except Exception as exc:        # noqa: BLE001
        raise CloudRunError("http_error") from exc
    try:
        parsed = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        parsed = {}
    return parsed if isinstance(parsed, dict) else {}


def get_service(name: str, token: str) -> dict:
    return _call("GET", API + "/" + name, token)


def plain_env(service: dict) -> dict:
    """첫 컨테이너의 일반 값 환경변수 {이름: 값}. Secret Manager 참조(valueSource)는 값이 없으므로 뺀다."""
    containers = ((service.get("template") or {}).get("containers") or [{}])
    return {e["name"]: e.get("value", "") for e in containers[0].get("env") or []
            if isinstance(e, dict) and "name" in e and "valueSource" not in e}


def with_env(service: dict, changes: dict) -> dict:
    """서비스 정의에서 바꿀 키만 고친 사본. 다른 변수·비밀 참조·순서는 그대로 둔다."""
    body = json.loads(json.dumps(service))
    containers = body.setdefault("template", {}).setdefault("containers", [{}])
    env = containers[0].setdefault("env", [])
    seen = set()
    for item in env:
        if isinstance(item, dict) and item.get("name") in changes:
            item.pop("valueSource", None)
            item["value"] = changes[item["name"]]
            seen.add(item["name"])
    for key, value in changes.items():
        if key not in seen:
            env.append({"name": key, "value": value})
    return body


def update_env(name: str, changes: dict, token: str, timeout: int = 600) -> dict:
    """바꿀 키만 고쳐 서비스를 갱신하고(새 리비전), 작업이 끝날 때까지 기다린다."""
    current = get_service(name, token)
    body = with_env(current, changes)
    for field in ("uid", "generation", "createTime", "updateTime", "creator", "lastModifier", "observedGeneration",
                  "terminalCondition", "conditions", "latestReadyRevision", "latestCreatedRevision",
                  "trafficStatuses", "uri", "urls", "reconciling", "satisfiesPzs"):
        body.pop(field, None)              # 출력 전용 필드는 보내지 않는다(etag 는 남긴다 — 동시 변경 방지)
    op = _call("PATCH", API + "/" + name, token, body)
    deadline = time.time() + timeout
    while not op.get("done"):
        if time.time() > deadline:
            return {"ok": False, "note": "새 리비전이 아직 준비 중입니다(%d초 대기 후 중단)" % timeout}
        time.sleep(3)
        op = _call("GET", API + "/" + op["name"], token) if op.get("name") else {"done": True}
    if op.get("error"):
        return {"ok": False, "note": "리비전 실패: %s" % (op["error"].get("message") or "")[:160]}
    return {"ok": True, "note": "새 리비전 배포 완료"}


def service_url(service: dict) -> str:
    return str(service.get("uri") or "")
