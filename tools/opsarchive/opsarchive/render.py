"""Render 호출 — `render` CLI 래퍼와 REST API.

**중요**: Render CLI 에는 기존 서비스의 환경변수를 바꾸는 명령이 없다(`services update` 에
`--env-var` 가 없고, `services create` 에만 있다 — 공식 CLI 레퍼런스 확인). 그래서

- 서비스 ID 조회·재배포·로그 확인은 **render CLI** 로 하고(요구사항),
- 환경변수 발행만 **REST API**(`PUT /v1/services/{id}/env-vars/{key}`, `RENDER_API_KEY`)로 한다.

규칙
- subprocess 는 `shell=False` 로만 실행한다(argv 주입 방지). 인자에 시크릿을 넣지 않는다.
- 실패는 RenderError(code) 로 값만 남긴다. 응답 본문·토큰을 메시지에 담지 않는다.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.render.com/v1"
TIMEOUT = 30
CLI_TIMEOUT = 600


class RenderError(Exception):
    """code: no_cli | cli_failed | no_api_key | bad_json | http_error | not_found"""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def api_key() -> str:
    """API 키는 환경변수에서만 읽는다(명령줄 인자로 받지 않는다 — 프로세스 목록에 남는다)."""
    key = os.environ.get("RENDER_API_KEY", "").strip()
    if not key:
        raise RenderError("no_api_key")
    return key


def render_bin() -> str:
    found = shutil.which("render")
    if not found:
        raise RenderError("no_cli")
    return found


def _argv(binary: str, args: list[str]) -> list[str]:
    """Windows 에서 `render` 는 `render.cmd` 다 — .cmd/.bat 은 CreateProcess 로 직접 못 띄우므로
    `cmd.exe /c` 를 거친다(이걸 빼면 'cli_failed' 만 보이고 원인을 알 수 없다)."""
    if os.name == "nt" and binary.lower().endswith((".cmd", ".bat")):
        return [os.environ.get("COMSPEC", "cmd.exe"), "/c", binary] + args
    return [binary] + args


def run_cli(args: list[str], timeout: int = CLI_TIMEOUT) -> str:
    """`render` CLI 실행(비대화형). 출력만 돌려주고 실패는 값으로 알린다.

    실패 시 `stderr` 의 **첫 줄을 정리해** 힌트로 담는다(토큰·경로 노출은 마스킹). 운영자가
    "왜 실패했는지"를 볼 수 없으면 도구가 쓸모없다 — 다만 자격증명은 절대 담지 않는다.
    """
    env = dict(os.environ, RENDER_OUTPUT=os.environ.get("RENDER_OUTPUT", "text"))
    command = _argv(render_bin(), args)
    try:
        done = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout, shell=False, env=env)  # noqa: S603
    except FileNotFoundError as exc:
        raise RenderError("no_cli") from exc
    except subprocess.TimeoutExpired as exc:
        raise RenderError("cli_timeout") from exc
    if done.returncode != 0:
        raise RenderError("cli_failed:" + _hint(done.stderr or done.stdout))
    return done.stdout


def _hint(text: str, width: int = 160) -> str:
    """stderr 에서 사람이 읽을 한 줄만 남긴다(시크릿·긴 경로 마스킹)."""
    import re
    line = ""
    for candidate in (text or "").splitlines():
        cleaned = candidate.strip()
        if cleaned:
            line = cleaned
            break
    line = re.sub(r"(rnd_|ghp_|github_pat_|AIza)[A-Za-z0-9_\-]{6,}", "[MASKED]", line)
    return line[:width]


def services() -> list[dict]:
    """워크스페이스의 서비스 목록(render CLI, JSON)."""
    raw = run_cli(["services", "-o", "json", "--confirm"])
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RenderError("bad_json") from exc
    out = []
    for item in data if isinstance(data, list) else []:
        svc = item.get("service", item) if isinstance(item, dict) else {}
        if isinstance(svc, dict) and svc.get("id"):
            out.append({"id": svc["id"], "name": svc.get("name", ""), "type": svc.get("type", "")})
    return out


def _norm(name: str) -> str:
    """이름 비교용 정규화 — 대소문자·하이픈/밑줄 차이를 흡수한다.

    앱 호스트는 `codyssey-final.onrender.com`(하이픈)인데 Render **서비스 이름**은
    `codyssey_final`(밑줄)이다. 사람이 자주 바꿔 쓰고, 그 차이로 not_found 가 나면 원인을 찾기 어렵다.
    """
    return (name or "").strip().lower().replace("-", "_").replace(" ", "_")


def service_names() -> list[str]:
    """이 워크스페이스의 서비스 이름(선택 창에서 쓰라고 그대로 노출한다)."""
    return [s["name"] for s in services()]


def service_id(name: str) -> str:
    """이름으로 서비스 ID 찾기(정규화 후 부분 일치 허용). 못 찾으면 **후보 목록을 함께** 알린다."""
    items = services()
    exact = [s["id"] for s in items if s["name"] == name]
    if len(exact) == 1:
        return exact[0]
    wanted = _norm(name)
    near = [s["id"] for s in items if wanted and wanted in _norm(s["name"])]
    if len(near) == 1:
        return near[0]
    hint = ", ".join(s["name"] for s in items)[:180]
    raise RenderError("not_found('%s') — 사용 가능: %s" % (name, hint or "(없음)"))


def _call(method: str, url: str, body=None, key: str | None = None) -> dict:
    token = key or api_key()
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
        if exc.code == 404:
            raise RenderError("not_found") from exc
        raise RenderError("http_error") from exc
    except Exception as exc:        # noqa: BLE001
        raise RenderError("http_error") from exc
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def put_env(sid: str, key: str, value: str, *, api_key_value: str | None = None) -> None:
    """환경변수 하나를 추가/갱신한다(직접 설정한 변수만 — 환경 그룹 변수는 건드리지 않는다)."""
    url = API + "/services/" + sid + "/env-vars/" + urllib.parse.quote(key, safe="")
    _call("PUT", url, {"value": value}, api_key_value)


def get_env(sid: str, key: str, *, api_key_value: str | None = None) -> str | None:
    """환경변수 값 하나(없으면 None). 값은 호출자가 화면에 그대로 찍지 않는다."""
    url = API + "/services/" + sid + "/env-vars/" + urllib.parse.quote(key, safe="")
    try:
        got = _call("GET", url, None, api_key_value)
    except RenderError as exc:
        if exc.code == "not_found":
            return None
        raise
    return got.get("value") if isinstance(got, dict) else None


def deploy(sid: str, timeout: int = 300) -> dict:
    """재배포를 트리거하고 (가능하면) 끝날 때까지 기다린다.

    **소프트 실패**: `--wait` 는 빌드·배포가 끝날 때까지 수 분 걸리고 출력도 그때 한꺼번에 나온다.
    그래서 기다리다 끊겨도 예외로 올리지 않고 결과로 알린다 — 환경변수는 이미 설정됐기 때문에
    재배포가 진행 중이어도 다음 단계(지문 대조)는 할 수 있다.
    """
    try:
        run_cli(["deploys", "create", sid, "--wait", "--confirm", "-o", "text"], timeout=timeout)
        return {"ok": True, "note": "재배포 완료"}
    except RenderError as exc:
        if exc.code == "cli_timeout":
            return {"ok": False, "note": "재배포가 아직 진행 중입니다(%d초 대기 후 중단) — 대시보드에서 확인하세요" % timeout}
        if str(exc.code).startswith("cli_failed"):
            return {"ok": False, "note": "재배포 실패: %s" % exc.code}
        raise


def logs(sid: str, text: str = "", limit: int = 50) -> str:
    """최근 로그(render CLI). text 로 좁힌다."""
    args = ["logs", "--resources", sid, "--limit", str(limit), "-o", "json"]
    if text:
        args += ["--text", text]
    return run_cli(args, timeout=120)
