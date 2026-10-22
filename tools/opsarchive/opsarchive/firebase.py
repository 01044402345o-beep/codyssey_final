"""firebase CLI 래퍼 — 이 도구가 firebase CLI 를 실제로 쓰는 지점을 한 곳에 모은다.

firebase CLI 로 **되는 것**: 프로젝트/로그인 확인(`projects:list`), Firestore 규칙 배포
(`deploy --only firestore:rules --project <id>`, 저장소 루트에서), 데이터 export/import, 에뮬레이터.
배포된 규칙 원문은 CLI 로 읽을 수 없어 Firebase Rules API(읽기 전용, 서비스 계정)로 읽어 저장소 파일과 대조한다.
**안 되는 것**: 임의 Storage 객체 업로드·임의 Firestore 문서 쓰기 → 그건 서비스 계정 REST 로 한다.

그래서 이 도구는 (a) **사전 점검**(프로젝트에 접근 가능한가)과 (b) 운영자가 쓰는 **규칙 배포**에
firebase CLI 를 쓰고, 아카이브 읽기는 서비스 계정 REST(`gcp.py`)로 한다.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT = 120


_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")   # CLI 색 코드 — 로그·문구 판별에 섞이지 않게 걷어낸다


class FirebaseError(Exception):
    """code: no_cli | cli_failed | bad_json | bad_project | no_firebase_json | no_rules_file | no_rules_target
    | rules_forbidden | rules_not_found | rules_unauthorized | rules_http_error | bad_release | empty_ruleset
    | cli_timeout | multiple_rules_targets | project_is_alias"""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code
        self.detail = ""


def available() -> bool:
    return bool(shutil.which("firebase"))


def _bin() -> str:
    found = shutil.which("firebase")
    if not found:
        raise FirebaseError("no_cli")
    return found


def run_cli(args: list[str], timeout: int = TIMEOUT, cwd: str | None = None) -> str:
    """`firebase` CLI 실행(shell=False). 실패는 값으로만 알린다."""
    env = dict(os.environ, NO_COLOR="1", FORCE_COLOR="0")   # 색 코드가 문구 판별에 섞이지 않게
    try:
        done = subprocess.run([_bin()] + args, capture_output=True, text=True,
                              encoding="utf-8", errors="replace",   # Windows 로케일(cp949) 디코딩 오류 방지
                              timeout=timeout, shell=False, cwd=cwd, env=env)   # noqa: S603
    except subprocess.TimeoutExpired as exc:
        # Windows 의 firebase.cmd 는 시간이 지나 cmd 가 끝나도 node 자식이 남아 배포를 마칠 수 있다.
        # 실패로 단정하지 않고 따로 알린다 — 호출자는 배포본을 다시 읽어 실제 결과를 확인한다.
        err = FirebaseError("cli_timeout")
        err.detail = "시간 초과 — 배포가 뒤에서 끝났을 수 있습니다. 배포된 규칙을 대조해 확인하세요."
        raise err from exc
    if done.returncode != 0:
        # 규칙 문법 오류 같은 원인을 운영자가 볼 수 있게 끝부분만 붙인다(CLI 출력에는 토큰이 없다).
        err = FirebaseError("cli_failed")
        err.detail = _tail(_ANSI.sub("", done.stdout or "") + "\n" + _ANSI.sub("", done.stderr or ""))
        raise err
    return _ANSI.sub("", done.stdout or "")


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


# ------------------------------------------------------------------ Firestore 규칙 배포·대조
# 예전 rules_deploy() 는 --project 도 작업 폴더도 정하지 않아, CLI 에 다른 프로젝트가 잡혀 있으면
# 그쪽에 배포될 수 있었다(10/22 실제로 다른 프로젝트가 잡혀 있었다). 그리고 GUI 의 작업 폴더는
# tools/opsarchive 라 firebase.json 이 있는 저장소 루트가 아니다. 그래서 둘 다 명시한다.

_PROJECT = re.compile(r"^[a-z][a-z0-9-]{4,61}[a-z0-9]$")
RULES_API = "https://firebaserules.googleapis.com/v1"
RULES_SCOPE = "https://www.googleapis.com/auth/firebase.readonly"


def _tail(text: str, lines: int = 12) -> str:
    keep = [ln.rstrip() for ln in str(text).splitlines() if ln.strip()]
    return "\n".join(keep[-lines:])[-1500:]


def check_project(project_id: str) -> str:
    if not isinstance(project_id, str) or not _PROJECT.fullmatch(project_id):
        raise FirebaseError("bad_project")
    return project_id


def rules_target(root: str) -> dict:
    """firebase.json 에서 (default) 데이터베이스의 규칙 파일을 찾는다. 다른 데이터베이스는 건드리지 않는다."""
    path = os.path.join(root, "firebase.json")
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            conf = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise FirebaseError("no_firebase_json") from exc
    entries = conf.get("firestore") if isinstance(conf, dict) else None
    if isinstance(entries, dict):
        entries = [entries]
    entries = entries if isinstance(entries, list) else []
    if len(entries) > 1:
        # `--only firestore:rules` 는 firebase.json 의 **모든** 데이터베이스 규칙을 배포하는데, 반영 확인은
        # (default) 만 읽는다. 다른 데이터베이스를 말없이 덮어쓰지 않게 대상이 하나일 때만 허용한다.
        raise FirebaseError("multiple_rules_targets")
    for item in entries:
        if isinstance(item, dict) and item.get("rules") and item.get("database", "(default)") == "(default)":
            rules = os.path.normpath(os.path.join(root, str(item["rules"])))
            if not rules.startswith(os.path.normpath(root) + os.sep) or not os.path.isfile(rules):
                raise FirebaseError("no_rules_file")
            return {"root": root, "firebase_json": path, "rules_file": rules,
                    "database": "(default)", "targets": len(entries)}
    raise FirebaseError("no_rules_target")


def normalize_rules(text: str) -> str:
    """CRLF·줄 끝 공백 차이는 같은 규칙으로 본다(Windows 체크아웃은 CRLF 다)."""
    text = str(text).lstrip("\ufeff")   # 로컬은 utf-8-sig 로 읽어 BOM 이 없고, 배포본에는 남는다
    return "\n".join(ln.rstrip() for ln in text.replace("\r\n", "\n").split("\n")).strip() + "\n"


def rules_sha(text: str) -> str:
    return hashlib.sha256(normalize_rules(text).encode("utf-8")).hexdigest()


def local_rules(root: str) -> dict:
    target = rules_target(root)
    with open(target["rules_file"], "r", encoding="utf-8-sig") as fh:
        text = fh.read()
    return {**target, "text": text, "sha256": rules_sha(text)}


def check_not_alias(project_id: str, root: str) -> None:
    """`--project X` 는 CLI 가 먼저 .firebaserc 의 **별칭**으로 찾는다. X 가 다른 프로젝트를 가리키는 별칭이면
    (예: "default" → 다른 ID) 엉뚱한 곳에 배포되는데 반영 확인은 X 를 읽어 알아채지 못한다. 그런 값은 거절한다."""
    try:
        with open(os.path.join(root, ".firebaserc"), "r", encoding="utf-8-sig") as fh:
            aliases = (json.load(fh) or {}).get("projects") or {}
    except (OSError, ValueError, AttributeError):
        return
    if isinstance(aliases, dict) and project_id in aliases and aliases[project_id] != project_id:
        raise FirebaseError("project_is_alias")


def rules_deploy(project_id: str, root: str, *, dry_run: bool = False, timeout: int = 180) -> dict:
    """`firebase deploy --only firestore:rules --project <id> --non-interactive [--dry-run]` 을 저장소 루트에서."""
    check_project(project_id)
    check_not_alias(project_id, root)
    local = local_rules(root)
    args = ["deploy", "--only", "firestore:rules", "--project", project_id, "--non-interactive"]
    if dry_run:
        args.append("--dry-run")
    out = run_cli(args, timeout=timeout, cwd=root)
    low = out.lower()
    return {
        "project": project_id, "dry_run": dry_run, "rules_file": local["rules_file"], "local_sha256": local["sha256"],
        "compiled": "compiled successfully" in low,
        "uploaded": "uploading rules" in low,
        "unchanged": "already up to date" in low,
        "released": "released rules" in low,
        "complete": ("deploy complete" in low) or ("dry run complete" in low),
        "output": _tail(out),
    }


def _rules_get(url: str, access_token: str, opener=None) -> dict:
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", "Bearer " + access_token)
    req.add_header("Accept", "application/json")
    try:
        with (opener or urllib.request.urlopen)(req, timeout=20) as res:
            raw = res.read()
    except urllib.error.HTTPError as exc:
        code = {401: "rules_unauthorized", 403: "rules_forbidden", 404: "rules_not_found"}.get(exc.code, "rules_http_error")
        raise FirebaseError(code) from exc
    except Exception as exc:            # noqa: BLE001 — 토큰을 메시지에 담지 않는다
        raise FirebaseError("rules_http_error") from exc
    try:
        data = json.loads(raw or b"{}")
    except json.JSONDecodeError as exc:
        raise FirebaseError("bad_json") from exc
    return data if isinstance(data, dict) else {}


def deployed_rules(project_id: str, access_token: str, *, database: str = "(default)", opener=None) -> dict:
    """지금 **배포(release)된** Firestore 규칙 원문을 Firebase Rules API 로 읽는다(읽기 전용).

    release 이름은 (default) 데이터베이스가 `cloud.firestore`, 이름 있는 데이터베이스는 `cloud.firestore/<db>` 다.
    """
    check_project(project_id)
    release = "cloud.firestore" if database == "(default)" else "cloud.firestore/" + database
    rel = _rules_get("%s/projects/%s/releases/%s" % (RULES_API, project_id, urllib.parse.quote(release, safe="/")),
                     access_token, opener)
    name = str(rel.get("rulesetName", ""))
    if not name.startswith("projects/%s/rulesets/" % project_id):
        raise FirebaseError("bad_release")
    ruleset = _rules_get("%s/%s" % (RULES_API, name), access_token, opener)
    files = (ruleset.get("source") or {}).get("files") or []
    text = "".join(str(f.get("content", "")) for f in files if isinstance(f, dict))
    if not text:
        raise FirebaseError("empty_ruleset")
    return {"release": release, "ruleset": name, "updated": str(rel.get("updateTime", "")),
            "text": text, "sha256": rules_sha(text)}


def rules_diff(deployed: str, local: str, limit: int = 80) -> list[str]:
    lines = list(difflib.unified_diff(normalize_rules(deployed).splitlines(), normalize_rules(local).splitlines(),
                                      "배포됨", "저장소", lineterm="", n=1))
    return lines[:limit] + (["… (%d줄 더)" % (len(lines) - limit)] if len(lines) > limit else [])
