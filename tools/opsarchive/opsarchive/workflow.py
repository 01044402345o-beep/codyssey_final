"""자동화 워크플로우 — 관리자가 GUI 마인드맵에서 클릭 몇 번으로 정책을 바꾸고 실행하게 한다.

이 모듈은 **Tk 를 import 하지 않는다**(표현과 정책을 분리한다). 네트워크·파일은 `commands`/`config`
기존 모듈을 그대로 재사용한다:

- `NODES`/`DEFAULTS`  : 노드(정책 항목) 정의와 기본값. 순서가 곧 기본 흐름이다.
- `load`/`save`       : 정책을 `~/.opsarchive/workflow.json` 에 저장/복원(스키마 안정 — 모르는 키는 버린다).
- `graph(policy)`     : GUI 가 그릴 그래프(노드 상태·엣지·그룹).
- `plan(policy)`      : 이번 실행에서 할 일(순서 + 실행 가능/불가와 이유).
- `run_step(...)`     : 로컬에서 실제로 실행 가능한 노드(관측·핀·IAM·앵커·검증)만 실행.
- `push_env(...)`     : 정책 값을 Render 환경변수로 밀어넣는다(반영에는 재배포가 필요하다).
- `automation_loop()` : 주기 실행(관리자 PC 가 켜져 있을 때만 돈다).

정직한 한계(숨기지 않는다):
1. 주기 실행은 **관리자 PC 가 켜져 있을 때만** 돈다 — 서버측 스케줄러가 아니다.
2. 서버 정책(환경변수)을 바꾸면 **재배포가 필요**하다(값만 바꿔도 앱은 옛 값을 들고 돈다).
3. 관측(`observe`)은 **플랫폼 로그 보존 기간만큼만** 본다 — 그보다 오래된 구간은 보이지 않는다.
4. 자동 실행은 **되돌릴 수 없는 서버 변경은 하지 않는다**(iam_check 의 검사용 카나리아는 별도 컬렉션
   `evidence_iam_canary` 에 쓰고, 카나리아가 남아도 증거·체인과 무관하다).
   (증거 봉인·아카이브 삭제는 앱/관리자가 명시적으로 수행한다.)
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Callable, Optional

from . import commands, config


# ------------------------------------------------------------------ 노드 정의

# 각 노드: id, label, group, kind(toggle|number|choice|action), default,
#          options(choice), min/max(number), desc, env, requires, redeploy
NODES: list[dict] = [
    # -------------------------------------------------- 탈퇴 대응
    {"id": "seal_failures", "label": "실패 시 증거 봉인", "group": "탈퇴 대응", "kind": "toggle",
     "default": True, "desc": "탈퇴(계정 삭제) 처리에 실패하면 그 실패 증거를 봉인해 남긴다.",
     "env": "EVIDENCE_SEAL_FAILURES", "requires": [], "redeploy": True},
    {"id": "daily_cap", "label": "일일 봉인 상한", "group": "탈퇴 대응", "kind": "number",
     "default": 5, "min": 1, "max": 100000,
     "desc": "하루에 봉인할 수 있는 증거(아카이브) 수 상한. 넘으면 추가 봉인을 막는다.",
     "env": "EVIDENCE_DAILY_CAP", "requires": [], "redeploy": True},
    {"id": "per_uid_seconds", "label": "사용자별 최소 간격(초)", "group": "탈퇴 대응", "kind": "number",
     "default": 3600, "min": 1, "max": 86400,
     "desc": "같은 사용자의 탈퇴 시도 사이 최소 간격(초). 연속 시도를 제한한다.",
     "env": "EVIDENCE_PER_UID_SECONDS", "requires": [], "redeploy": True},
    {"id": "ttl_days", "label": "증거 보존 기간(일)", "group": "탈퇴 대응", "kind": "number",
     "default": 90, "min": 1, "max": 3650,
     "desc": "봉인한 증거를 TTL 로 자동 만료하기까지의 일수.",
     "env": "EVIDENCE_TTL_DAYS", "requires": [], "redeploy": True},
    {"id": "issue_notify", "label": "실패 시 이슈 알림", "group": "탈퇴 대응", "kind": "toggle",
     "default": True, "desc": "증거를 봉인하면 GitHub 이슈로 알린다(메타데이터만). 끄면 토큰·저장소가 있어도 알리지 않는다. "
     "알리려면 이슈 저장소·이슈 토큰 노드도 채워야 한다.",
     "env": "EVIDENCE_NOTIFY", "requires": [], "redeploy": True},
    {"id": "gh_repo", "label": "이슈 저장소", "group": "탈퇴 대응", "kind": "text",
     "default": "", "pattern": r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$", "placeholder": "owner/repo",
     "desc": "이슈를 올릴 GitHub 저장소(EVIDENCE_GH_REPO = owner/repo). 비공개 저장소를 권한다.",
     "env": "EVIDENCE_GH_REPO", "requires": [], "redeploy": True},
    {"id": "gh_token", "label": "이슈 토큰", "group": "탈퇴 대응", "kind": "secret",
     "default": None, "desc": "이슈를 올릴 GitHub 토큰(EVIDENCE_GH_TOKEN, 그 저장소의 Issues 쓰기만 있는 fine-grained 토큰). "
     "값은 [Render에 반영] 때 가려진 칸으로 묻고 **어디에도 저장하지 않는다**(정책 파일·로그에 남지 않음).",
     "env": "EVIDENCE_GH_TOKEN", "requires": [], "redeploy": True},
    {"id": "client_report", "label": "화면 불일치 보고 봉인", "group": "탈퇴 대응", "kind": "toggle",
     "default": True, "desc": "화면이 '탈퇴가 예상 밖 상태로 끝났다'고 보낸 보고(/diagnostics/withdraw)를 증거로 봉인할지. "
     "끄면 보고는 받기만 하고 봉인하지 않는다.",
     "env": "EVIDENCE_CLIENT_REPORTS", "requires": [], "redeploy": True},
    # -------------------------------------------------- 감시·증인
    {"id": "observe", "label": "접근로그 관측 창", "group": "감시·증인", "kind": "choice",
     "default": "60", "options": [("60", "60분"), ("360", "6시간"), ("1440", "24시간")],
     "desc": "플랫폼 접근 로그(앱 밖 증인)와 체인의 시도 수를 비교할 관측 창.",
     "env": None, "requires": ["project_id", "sa_path", "service"], "redeploy": False},
    {"id": "iam_check", "label": "삭제 권한 점검", "group": "감시·증인", "kind": "action",
     "default": True, "desc": "앱 서비스 계정이 증거를 지우거나 덮어쓸 수 있는지 카나리아로 시험한다.",
     "env": None, "requires": ["project_id", "sa_path"], "redeploy": False},
    {"id": "iam_check_enabled", "label": "삭제 권한 점검 사용", "group": "감시·증인", "kind": "toggle",
     "default": True, "desc": "자동 실행에 IAM 점검을 포함할지. 끄면 관리자가 [이 노드 실행] 으로만 확인한다"
     "(점검은 별도 컬렉션에 카나리아를 쓰므로 서버에 흔적이 남는다).",
     "env": None, "requires": [], "redeploy": False},
    {"id": "pin_check", "label": "핀 대조", "group": "감시·증인", "kind": "action",
     "default": True, "desc": "핀 파일과 배포된 앱 /health 지문을 대조해 예상 밖 키를 잡는다.",
     "env": None, "requires": ["pin_path", "base_url"], "redeploy": False},
    # -------------------------------------------------- 검증·앵커
    {"id": "anchor_interval", "label": "앵커 주기", "group": "검증·앵커", "kind": "choice",
     "default": "3600",
     "options": [("3600", "1시간"), ("21600", "6시간"), ("86400", "24시간"), ("0", "수동")],
     "desc": "자동 실행 루프가 체크포인트를 앵커할 주기(수동 = 자동 앵커 안 함).",
     "env": None, "requires": [], "redeploy": False},
    {"id": "anchor", "label": "체크포인트 앵커", "group": "검증·앵커", "kind": "action",
     "default": True, "desc": "지금 체인 상태를 서명해 앵커한다(뒤에 사라진 아카이브를 탐지).",
     "env": None, "requires": ["project_id", "sa_path"], "redeploy": False},
    {"id": "verify_chain", "label": "체인 검증", "group": "검증·앵커", "kind": "action",
     "default": True, "desc": "앵커된 체크포인트의 서명·연속성·롤백과 누락 아카이브를 검증한다.",
     "env": None, "requires": ["project_id", "sa_path", "pin_path"], "redeploy": False},
    {"id": "pubkey", "label": "봉인 공개키", "group": "검증·앵커", "kind": "key",
     "default": None, "desc": "EVIDENCE_PUBKEY — 앱이 증거를 봉인할 관리자 공개키. 값은 손으로 넣지 않고 **키 파일에서 역산**해 올린다. "
     "[Render에 반영] 또는 [이 노드 실행] = 공개키 발행(키 파일·패스프레이즈 → 환경변수 → 재배포 → 지문 대조).",
     "env": "EVIDENCE_PUBKEY", "requires": ["service"], "redeploy": True},
    {"id": "key_generation", "label": "키 세대", "group": "검증·앵커", "kind": "number",
     "default": 1, "min": 1, "max": 100000,
     "desc": "EVIDENCE_KEY_GENERATION — /health 로 노출되어 핀 검증에 쓰인다. **핀 세대와 같아야 한다**(다르면 핀 검사가 실패한다).",
     "env": "EVIDENCE_KEY_GENERATION", "requires": [], "redeploy": True},
    # -------------------------------------------------- 안전
    {"id": "include_secrets", "label": "증거에 비밀 포함", "group": "안전", "kind": "toggle",
     "default": False, "desc": "봉인 증거에 비밀값을 포함할지(기본 꺼짐 — 켜면 유출 위험이 커진다).",
     "env": "EVIDENCE_INCLUDE_SECRETS", "requires": [], "redeploy": True},
    {"id": "max_bytes", "label": "증거 전체 상한(바이트)", "group": "안전", "kind": "number",
     "default": 1000000, "min": 100000, "max": 10000000,
     "desc": "봉인 증거 묶음의 전체 바이트 상한(EVIDENCE_MAX_BYTES). 넘으면 로그·소스·트레이스백을 잘라낸다.",
     "env": "EVIDENCE_MAX_BYTES", "requires": [], "redeploy": True},
    {"id": "max_source_bytes", "label": "소스 캡(바이트)", "group": "안전", "kind": "number",
     "default": 524288, "min": 65536, "max": 4000000,
     "desc": "증거에 담는 소스 파일 묶음 상한(EVIDENCE_MAX_SOURCE_BYTES, 앱 기본 512KB). 전체 상한보다 크게 잡아도 전체 상한에서 잘린다.",
     "env": "EVIDENCE_MAX_SOURCE_BYTES", "requires": [], "redeploy": True},
    {"id": "max_logs_bytes", "label": "로그 캡(바이트)", "group": "안전", "kind": "number",
     "default": 65536, "min": 16384, "max": 1000000,
     "desc": "증거에 담는 최근 로그 상한(EVIDENCE_MAX_LOGS_BYTES, 앱 기본 64KB).",
     "env": "EVIDENCE_MAX_LOGS_BYTES", "requires": [], "redeploy": True},
]

# 노드 정의에서 파생한 기본 정책 값.
DEFAULTS: dict[str, Any] = {node["id"]: node["default"] for node in NODES}

# 노드 id -> 노드 정의
_BY_ID: dict[str, dict] = {node["id"]: node for node in NODES}

# 실행 순서: 정책 반영(env) → 관측 → 핀 → IAM → 앵커 → 체인 검증 → (안내 노드)
_PLAN_ORDER: list[str] = [
    "pubkey", "seal_failures", "daily_cap", "per_uid_seconds", "ttl_days",
    "max_bytes", "max_source_bytes", "max_logs_bytes", "key_generation", "include_secrets",
    "issue_notify", "gh_repo", "gh_token", "client_report",
    "observe", "pin_check", "iam_check_enabled", "iam_check", "anchor", "verify_chain",
    "anchor_interval",
]

# 로컬에서 실제로 실행 가능한 노드(run_step 이 처리한다).
_RUNNABLE: set[str] = {"observe", "pin_check", "iam_check", "anchor", "verify_chain"}
# 값도 실행도 없이 안내만 하는 노드(env 없음).
_INFO: set[str] = {"anchor_interval", "iam_check_enabled"}
# 값을 정책 파일에 두지 않고 반영할 때 받는 노드: secret(가려진 입력), key(키 파일에서 역산 — 공개키 발행)
_MANUAL: set[str] = {"gh_token", "pubkey"}

# number 노드의 사람이 읽는 단위(선택).
_UNITS: dict[str, str] = {"daily_cap": "회", "per_uid_seconds": "초", "ttl_days": "일",
                          "max_bytes": "바이트", "key_generation": "세대",
                          "max_source_bytes": "바이트", "max_logs_bytes": "바이트"}

# 그래프 엣지: 기본 흐름 + 예외 분기(이상이면 이슈 알림 / 결과 보고).
_EDGES: list[tuple[str, str]] = [
    ("seal_failures", "daily_cap"),
    ("daily_cap", "per_uid_seconds"),
    ("per_uid_seconds", "ttl_days"),
    ("ttl_days", "max_bytes"),
    ("max_bytes", "key_generation"),
    ("key_generation", "include_secrets"),
    ("include_secrets", "observe"),
    ("observe", "pin_check"),
    ("pin_check", "iam_check"),
    ("iam_check", "anchor"),
    ("anchor", "verify_chain"),
    # 예외 분기
    ("seal_failures", "issue_notify"),
    ("observe", "issue_notify"),
    ("verify_chain", "issue_notify"),
    ("verify_chain", "client_report"),
    ("issue_notify", "gh_repo"),
    ("gh_repo", "gh_token"),
    ("max_bytes", "max_source_bytes"),
    ("max_source_bytes", "max_logs_bytes"),
    ("pubkey", "seal_failures"),
    ("pubkey", "key_generation"),
]


# ------------------------------------------------------------------ 설정 접근

def _load_settings() -> dict:
    """실행에 필요한 설정(config.read_settings)을 읽는다. 테스트는 이 함수를 패치한다."""
    try:
        return dict(config.read_settings())
    except Exception:        # noqa: BLE001 — 설정이 없어도 그래프/계획은 그릴 수 있어야 한다
        return {}


def _node(node_id: str) -> Optional[dict]:
    return _BY_ID.get(node_id)


def _present(settings: dict, key: str) -> bool:
    return settings.get(key) not in (None, "", False)


# ------------------------------------------------------------------ 정책 정규화

def _coerce(node: dict, value: Any) -> Any:
    """값을 노드 스키마에 맞춘다. 타입 오류면 기본값으로 되돌린다(스키마 안정)."""
    kind = node["kind"]
    default = node["default"]
    if kind == "toggle":
        return value if isinstance(value, bool) else default
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, int):
            return default
        low, high = node.get("min"), node.get("max")
        if low is not None and value < low:
            value = low
        if high is not None and value > high:
            value = high
        return value
    if kind == "choice":
        keys = [key for key, _label in node.get("options", [])]
        return str(value) if str(value) in keys else default
    if kind == "text":
        import re as _re
        text = str(value or "").strip() if isinstance(value, str) else ""
        pattern = node.get("pattern")
        return text if (not text or not pattern or _re.fullmatch(pattern, text)) else default
    return default        # action·secret·key = 정책 파일에 값을 두지 않는다


def _normalize(policy: Any) -> dict:
    """알 수 없는 키는 버리고 DEFAULTS 로 채운다(값은 _coerce 로 검증)."""
    data = dict(DEFAULTS)
    if isinstance(policy, dict):
        for node in NODES:
            key = node["id"]
            if key in policy:
                data[key] = _coerce(node, policy[key])
    return data


def workflow_path(path: Optional[str] = None) -> str:
    return path or os.path.join(config.config_dir(), "workflow.json")


def load(path: Optional[str] = None) -> dict:
    """정책을 읽는다. 없으면 DEFAULTS. 모르는 키는 버리고 빠진 키는 기본값으로 채운다."""
    try:
        with open(workflow_path(path), "r", encoding="utf-8-sig") as fh:
            got = json.load(fh)
    except (OSError, ValueError):     # JSONDecodeError·UnicodeDecodeError(손편집 cp949) 까지 포함
        got = None
    return _normalize(got)


def save(policy: dict, path: Optional[str] = None) -> str:
    """정책을 정규화해 저장하고 경로를 돌려준다."""
    target = workflow_path(path)
    directory = os.path.dirname(target)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(target, "w", encoding="utf-8") as fh:
        json.dump(_normalize(policy), fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    return target


# ------------------------------------------------------------------ 그래프

def _enabled(node: dict, value: Any) -> bool:
    kind = node["kind"]
    if kind == "toggle":
        return bool(value)
    if kind == "number":
        return value is not None
    if kind == "choice":
        return value not in (None, "")
    if kind == "text":
        return bool(value)
    return True


def _state(node: dict, value: Any) -> str:
    """사람이 읽는 현재 값 문자열(예: 켜짐/꺼짐, 5회, 6시간)."""
    kind = node["kind"]
    if kind == "toggle":
        return "켜짐" if value else "꺼짐"
    if kind == "choice":
        for key, label in node.get("options", []):
            if str(value) == key:
                return label
        return str(value)
    if kind == "number":
        return "%s%s" % (value, _UNITS.get(node["id"], ""))
    if kind == "text":
        return value or "(미설정)"
    if kind == "secret":
        return "반영 때 입력(저장 안 함)"
    if kind == "key":
        return "키 파일로 발행"
    return "대기"        # action = 값을 갖지 않는다


def graph(policy: dict) -> dict:
    """GUI 가 그릴 그래프(노드 상태 + 엣지 + 그룹)."""
    policy = _normalize(policy)
    settings = _load_settings()
    nodes = []
    groups: dict[str, list[str]] = {}
    for node in NODES:
        value = policy.get(node["id"], node["default"])
        missing = [key for key in node.get("requires", []) if not _present(settings, key)]
        nodes.append({
            "id": node["id"],
            "label": node["label"],
            "group": node["group"],
            "state": _state(node, value),
            "editable": node["kind"] in ("toggle", "number", "choice", "text"),
            "enabled": _enabled(node, value),
            "desc": node["desc"],
            "env": node.get("env"),
            "redeploy": bool(node.get("redeploy", False)),
            "missing": missing,
        })
        groups.setdefault(node["group"], []).append(node["id"])
    return {
        "nodes": nodes,
        "edges": [[src, dst] for src, dst in _EDGES],
        "groups": [{"name": name, "nodes": ids} for name, ids in groups.items()],
    }


# ------------------------------------------------------------------ 계획

def _plan_action(node: dict) -> str:
    """이 노드를 계획에서 어떻게 다루는가: run(실행) | env(환경변수 반영) | info(안내)."""
    if node["id"] in _RUNNABLE:
        return "run"
    if node["id"] in _INFO:
        return "info"
    if node["id"] in _MANUAL:
        return "manual"            # 반영할 때 사람이 입력한다(비밀 토큰·키 파일)
    if node.get("env") and node["kind"] in ("toggle", "number", "choice", "text"):
        return "env"
    return "info"


def _plan_status(node: dict, policy: dict, settings: dict) -> tuple[bool, str]:
    node_id = node["id"]
    action = _plan_action(node)
    if action == "run":
        missing = [key for key in node.get("requires", []) if not _present(settings, key)]
        if missing:
            return False, "필수 설정 없음: " + ", ".join(missing)
        return True, ""
    if action == "info":
        return False, "안내 노드"
    if action == "manual":
        return False, "반영할 때 입력 필요(가려진 칸·키 파일)"
    value = policy.get(node_id, node["default"])
    if not _enabled(node, value):
        return False, "꺼짐"
    return True, ""


def plan(policy: dict) -> list[dict]:
    """이번 실행에서 할 일을 순서대로 돌려준다.

    노드를 세 가지로 구분한다(호환을 위해 기존 `ok`/`reason` 은 그대로 두고 `action` 키를 더한다):
    - `action="run"`  : 로컬에서 실제로 실행하는 노드(관측·핀·IAM·앵커·검증). `ok=True` 면 실행한다.
    - `action="env"`  : 서버 정책(환경변수)을 밀어넣는 노드. 실행이 아니라 '반영 대상'이며 `ok=True` 다.
    - `action="info"` : 값도 실행도 없는 안내 노드(`ok=False`, `reason="안내 노드"`).
    """
    policy = _normalize(policy)
    settings = _load_settings()
    items = []
    for node_id in _PLAN_ORDER:
        node = _node(node_id)
        if node is None:
            continue
        ok, reason = _plan_status(node, policy, settings)
        items.append({"id": node_id, "label": node["label"], "ok": ok,
                      "reason": reason, "action": _plan_action(node)})
    return items


# ------------------------------------------------------------------ 실행

def _summarize(node_id: str, result: Any) -> dict:
    """commands 반환값에서 사람이 볼 만한 필드만 요약한다."""
    if not isinstance(result, dict):
        return {"value": str(result)[:200]}
    keys = {
        "observe": ("verdict", "ok", "observed", "attempts", "since_minutes", "note"),
        "pin_check": ("ok", "armed", "reasons", "pin_fingerprint"),
        "iam_check": ("verdict", "created", "delete_blocked", "update_blocked"),
        "anchor": ("seq", "count", "archives", "entries", "chain_ok", "head"),
        "verify_chain": ("ok", "count", "archives", "entries", "missing_now", "challenge_check", "note"),
    }.get(node_id, tuple(result.keys()))
    return {key: result[key] for key in keys if key in result}


def run_step(node_id: str, policy: dict, *, secrets: Optional[dict] = None,
             on_log: Optional[Callable[[str], None]] = None) -> dict:
    """로컬에서 실행 가능한 노드만 실제로 실행한다.

    서명 키 경로·패스프레이즈는 **정책에 저장하지 않는다** — `secrets` 로 따로 받는다.
    """
    node = _node(node_id)
    if node is None:
        raise commands.CommandError("unknown_node")
    if node_id not in _RUNNABLE:
        raise commands.CommandError("not_runnable")
    policy = _normalize(policy)
    settings = _load_settings()
    log = on_log if on_log is not None else (lambda _message: None)
    log("실행: %s" % node["label"])

    project_id = settings.get("project_id", "")
    sa_path = settings.get("sa_path", "")
    out_dir = settings.get("checkpoints_dir") or "checkpoints"

    if node_id == "observe":
        minutes = int(policy["observe"])
        result = commands.observe_requests(project_id, sa_path, settings.get("service", ""),
                                           since_minutes=minutes)
    elif node_id == "pin_check":
        result = commands.check_pin(settings.get("pin_path", ""),
                                    health_url=settings.get("base_url", ""))
    elif node_id == "iam_check":
        result = commands.iam_check(project_id, sa_path)
    elif node_id == "anchor":
        secrets = secrets or {}
        sign_key_file = secrets.get("sign_key_file")
        if not sign_key_file:
            raise commands.CommandError("secrets_required")
        result = commands.anchor(project_id, sa_path, sign_key_file,
                                 secrets.get("passphrase", ""), out_dir=out_dir)
    else:        # verify_chain
        result = commands.verify_chain(project_id, sa_path, settings.get("pin_path", ""), out_dir=out_dir)

    return {"id": node_id, "label": node["label"], "result": _summarize(node_id, result)}


# ------------------------------------------------------------------ 정책 반영(환경변수)

def _env_value(node: dict, value: Any) -> str:
    if node["kind"] == "toggle":
        return "1" if value else "0"
    return "" if value is None else str(value)


def push_env(node_id: str, policy: dict, *, service: str,
             api_key_value: Optional[str] = None, secret_value: Optional[str] = None) -> dict:
    """정책 값을 Render 환경변수로 밀어넣는다(한 노드). 재배포·반영 확인은 `apply_env` 가 한다."""
    node = _node(node_id)
    if node is None:
        raise commands.CommandError("unknown_node")
    env = node.get("env")
    if not env:
        raise commands.CommandError("no_env")
    if node["kind"] == "key":
        raise commands.CommandError("use_publish — 공개키는 키 파일에서 역산해 발행한다(Render 탭 ① 또는 이 노드 실행)")
    policy = _normalize(policy)
    value = secret_value if node["kind"] == "secret" else _env_value(node, policy.get(node_id, node["default"]))
    result = commands.env_set(service, env, value or "", api_key_value=api_key_value)
    out = dict(result) if isinstance(result, dict) else {"result": result}
    out["node"] = node_id
    out["env"] = env
    out["needs_redeploy"] = bool(node.get("redeploy"))
    return out


# ------------------------------------------------------------------ 주기 실행

def _delay_seconds(policy: dict) -> int:
    interval = policy.get("anchor_interval")
    if interval not in (None, "", "0", 0):
        try:
            return max(1, int(interval))
        except (TypeError, ValueError):
            pass
    try:
        return max(1, int(policy.get("observe")) * 60)
    except (TypeError, ValueError):
        return 3600


def _nap(delay: int, stop_event: Any) -> bool:
    """주기 사이에 쉰다. `stop_event` 가 있으면 즉시 깨어난다. 테스트는 이 함수를 패치한다."""
    seconds = max(0, int(delay))
    if stop_event is not None:
        return bool(stop_event.wait(seconds))
    time.sleep(seconds)
    return False


def _violation(node_id: str, result: Any) -> Optional[str]:
    if not isinstance(result, dict):
        return None
    if node_id == "observe":
        verdict = result.get("verdict")
        if verdict not in (None, "ok"):
            return "관측 위반 — observe verdict=%s" % verdict
        if result.get("ok") is False:
            return "관측 위반 — observe ok=False"
    elif node_id == "iam_check":
        verdict = result.get("verdict")
        if verdict not in (None, "ok"):
            return "IAM 위반 — %s" % verdict
    elif node_id in ("verify_chain", "pin_check"):
        if result.get("ok") is False:
            return "%s 위반 — ok=False" % node_id
    return None


def _notice(node_id: str, result: Any) -> Optional[str]:
    """명확한 위반은 아니지만 **확인하지 못한** 상태를 알린다(조용히 넘기면 '이상 없음'으로 오해한다).

    - 점검 노드(`pin_check`·`verify_chain` 등)가 `ok=None`(예: 핀 미활성 `unarmed`) → 확인 불가.
    - `observe` 결과가 빈 dict → 관측 자체가 이뤄지지 않음.
    """
    if not isinstance(result, dict):
        return None
    if node_id == "observe" and not result:
        return "확인 못 함: observe 관측 결과가 비어 있음(로그·설정을 확인하세요)"
    if "ok" in result and result["ok"] is None:
        reasons = result.get("reasons")
        detail = ", ".join(str(r) for r in reasons) if isinstance(reasons, list) and reasons else "ok=None"
        return "확인 못 함: %s %s" % (node_id, detail)
    return None


def automation_loop(policy: dict, *, on_log: Optional[Callable[[str], None]] = None,
                    stop_event: Any = None, secrets: Optional[dict] = None,
                    max_cycles: Optional[int] = None) -> dict:
    """주기 실행. `stop_event`(threading.Event)로 즉시 멈추고, `max_cycles` 로 무한 루프를 막는다.

    예외는 삼키고 로그·violations·notices 로만 남긴다(자동화가 앱을 방해하면 안 된다).
    - `violations` : 명확한 실패(`ok is False`, `verdict` 가 ok 아님).
    - `notices`    : 확인하지 못한 상태(핀 미활성 `ok=None`, 관측 결과 없음) — '이상 없음'으로 오해하지 않게 남긴다.
    """
    log = on_log if on_log is not None else (lambda _message: None)
    policy = _normalize(policy)
    # 앵커 주기가 '수동'이면 자동 앵커를 하지 않는다(설명과 실제가 어긋나면 안 된다).
    manual_anchor = str(policy.get("anchor_interval") or "0").strip() in ("0", "", "None")
    iam_enabled = bool(policy.get("iam_check_enabled", True))
    cycles = 0
    violations: list[str] = []
    notices: list[str] = []
    last: dict = {}
    while True:
        if stop_event is not None and stop_event.is_set():
            log("중지 신호 — 자동화를 멈춘다")
            break
        if max_cycles is not None and cycles >= max_cycles:
            break
        cycles += 1
        log("주기 %d 시작" % cycles)
        try:
            steps = plan(policy)
        except Exception as exc:        # noqa: BLE001
            log("계획 실패: %s" % getattr(exc, "code", exc))
            steps = []
        for item in steps:
            if manual_anchor and item.get("id") == "anchor":
                log("앵커 주기가 '수동'이라 이번 주기에는 앵커하지 않는다")
                continue
            if not iam_enabled and item.get("id") == "iam_check":
                log("IAM 점검이 정책에서 꺼져 있어 이번 주기에는 실행하지 않는다")
                continue
            if not item.get("ok"):
                if item.get("reason"):
                    log("건너뜀 %s — %s" % (item["id"], item["reason"]))
                continue
            try:
                outcome = run_step(item["id"], policy, secrets=secrets, on_log=log)
            except commands.CommandError as exc:
                code = str(getattr(exc, "code", ""))
                if code == "not_runnable":
                    log("정책 노드 %s — 로컬 실행 없음(값·환경변수 안내)" % item["id"])
                    continue
                message = "실행 실패 %s: %s" % (item["id"], code or str(exc))
                violations.append(message)
                log("경보: " + message)
                continue
            except Exception as exc:        # noqa: BLE001 — 자동화는 죽지 않는다
                message = "실행 오류 %s: %s" % (item["id"], type(exc).__name__)
                violations.append(message)
                log("경보: " + message)
                continue
            last = outcome
            problem = _violation(item["id"], outcome.get("result"))
            if problem:
                violations.append(problem)
                log("경보: " + problem)
                continue
            caution = _notice(item["id"], outcome.get("result"))
            if caution:
                notices.append(caution)
                log("주의: " + caution)
            else:
                log("정상 %s" % item["id"])
        try:
            stopped = _nap(_delay_seconds(policy), stop_event)
        except Exception:        # noqa: BLE001
            stopped = False
        if stopped:
            break
    return {"cycles": cycles, "violations": violations, "notices": notices, "last": last}


__all__ = [
    "NODES", "DEFAULTS", "load", "save", "workflow_path",
    "graph", "plan", "run_step", "push_env", "automation_loop",
]


# ------------------------------------------------------------------ 모아서 반영 → 재배포 → 반영 확인

def desired_env(policy: dict, node_ids: Optional[list] = None) -> dict:
    """정책에서 Render 로 보낼 값 {환경변수: 값}. 비어 있는 text 노드·secret·key 는 빼고(입력·발행이 따로다)."""
    policy = _normalize(policy)
    out = {}
    for node in NODES:
        if node_ids is not None and node["id"] not in node_ids:
            continue
        if not node.get("env") or node["kind"] not in ("toggle", "number", "choice", "text"):
            continue
        value = _env_value(node, policy.get(node["id"], node["default"]))
        if value != "":
            out[node["env"]] = value
    return out


def apply_env(policy: dict, *, service: str, node_ids: Optional[list] = None, secrets: Optional[dict] = None,
              redeploy: bool = True, base_url: str = "", api_key_value: Optional[str] = None,
              deploy_timeout: int = 600) -> dict:
    """정책을 Render 에 **바뀐 것만** 올리고, 한 번 재배포한 뒤, 실제로 반영됐는지 확인한다.

    확인: ① Render 에서 다시 읽은 값 == 정책 값(비밀은 같은지만 보고 값은 안 남김) ② 재배포 완료
    ③ 앱 /health 가 살아 있고 evidence.generation == key_generation 노드 값.
    바뀐 것이 없으면 재배포하지 않는다. secrets = {"EVIDENCE_GH_TOKEN": 값} (GUI 가 가려진 칸으로 받은 것).
    """
    from . import render
    sid = render.service_id(service)
    want = desired_env(policy, node_ids)
    for key, value in (secrets or {}).items():
        if value:
            want[key] = value
    secret_keys = set((secrets or {}).keys())
    changed, unchanged = [], []
    for key, value in want.items():
        current = render.get_env(sid, key, api_key_value=api_key_value)
        if current == value:
            unchanged.append(key)
            continue
        render.put_env(sid, key, value, api_key_value=api_key_value)
        changed.append(key)
    out: dict = {"service_id": sid, "changed": changed, "unchanged": unchanged, "redeployed": False,
                 "deploy": "", "verified": None, "mismatch": [], "health": {}}
    if not changed:
        out["verified"] = True
        out["note"] = "바뀐 값이 없어 재배포하지 않았습니다."
        return out
    if not redeploy:
        out["note"] = "값만 올렸습니다 — 재배포해야 앱에 적용됩니다."
        return out
    outcome = render.deploy(sid, timeout=deploy_timeout)
    out["redeployed"] = bool(outcome.get("ok"))
    out["deploy"] = str(outcome.get("note", ""))
    for key, value in want.items():
        if render.get_env(sid, key, api_key_value=api_key_value) != value:
            out["mismatch"].append(key)
    if base_url:
        try:
            health = commands.health(base_url)
            evidence = (health or {}).get("evidence") or {}
            out["health"] = {"status": (health or {}).get("status"), "generation": evidence.get("generation")}
            expected = _normalize(policy).get("key_generation")
            if node_ids is None or "key_generation" in node_ids:
                if evidence and evidence.get("generation") != expected:
                    out["mismatch"].append("EVIDENCE_KEY_GENERATION(/health)")
        except Exception as exc:        # noqa: BLE001 — 확인 실패는 '확인 못 함'으로만 알린다
            out["health"] = {"error": type(exc).__name__}
    out["verified"] = bool(out["redeployed"] and not out["mismatch"])
    if out["mismatch"]:
        out["error"] = "not_applied: " + ", ".join(out["mismatch"])
    elif not out["redeployed"]:
        out["error"] = "redeploy_unconfirmed — " + out["deploy"]
    out["changed"] = [k + ("(비밀)" if k in secret_keys else "") for k in changed]
    return out
