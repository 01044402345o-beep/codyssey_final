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
4. 자동 실행은 **봉인/삭제 같은 되돌릴 수 없는 일을 하지 않는다** — 여기서는 조회·검증·앵커만 한다.
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
     "default": 50, "min": 1, "max": 100000,
     "desc": "하루에 봉인할 수 있는 증거(아카이브) 수 상한. 넘으면 추가 봉인을 막는다.",
     "env": "EVIDENCE_DAILY_CAP", "requires": [], "redeploy": True},
    {"id": "per_uid_seconds", "label": "사용자별 최소 간격(초)", "group": "탈퇴 대응", "kind": "number",
     "default": 60, "min": 1, "max": 86400,
     "desc": "같은 사용자의 탈퇴 시도 사이 최소 간격(초). 연속 시도를 제한한다.",
     "env": "EVIDENCE_PER_UID_SECONDS", "requires": [], "redeploy": True},
    {"id": "ttl_days", "label": "증거 보존 기간(일)", "group": "탈퇴 대응", "kind": "number",
     "default": 30, "min": 1, "max": 3650,
     "desc": "봉인한 증거를 TTL 로 자동 만료하기까지의 일수.",
     "env": "EVIDENCE_TTL_DAYS", "requires": [], "redeploy": True},
    {"id": "issue_notify", "label": "실패 시 이슈 알림", "group": "탈퇴 대응", "kind": "toggle",
     "default": True, "desc": "봉인·검증에서 이상이 생기면 GitHub 이슈로 알린다. "
     "저장소는 EVIDENCE_GH_REPO 환경변수로 지정한다(값을 밀어넣지는 않고 설정 안내만 한다).",
     "env": None, "requires": [], "redeploy": False},
    {"id": "client_report", "label": "사용자 결과 보고", "group": "탈퇴 대응", "kind": "toggle",
     "default": False, "desc": "탈퇴 처리 결과를 사용자에게 알리는 보고서(앱 기능 개념 — 밀어넣는 환경변수 없음).",
     "env": None, "requires": [], "redeploy": False},
    # -------------------------------------------------- 감시·증인
    {"id": "observe", "label": "접근로그 관측 창", "group": "감시·증인", "kind": "choice",
     "default": "60", "options": [("60", "60분"), ("360", "6시간"), ("1440", "24시간")],
     "desc": "플랫폼 접근 로그(앱 밖 증인)와 체인의 시도 수를 비교할 관측 창.",
     "env": None, "requires": ["project_id", "sa_path", "service"], "redeploy": False},
    {"id": "iam_check", "label": "삭제 권한 점검", "group": "감시·증인", "kind": "action",
     "default": True, "desc": "앱 서비스 계정이 증거를 지우거나 덮어쓸 수 있는지 카나리아로 시험한다.",
     "env": None, "requires": ["project_id", "sa_path"], "redeploy": False},
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
    # -------------------------------------------------- 안전
    {"id": "include_secrets", "label": "증거에 비밀 포함", "group": "안전", "kind": "toggle",
     "default": False, "desc": "봉인 증거에 비밀값을 포함할지(기본 꺼짐 — 켜면 유출 위험이 커진다).",
     "env": "EVIDENCE_INCLUDE_SECRETS", "requires": [], "redeploy": True},
]

# 노드 정의에서 파생한 기본 정책 값.
DEFAULTS: dict[str, Any] = {node["id"]: node["default"] for node in NODES}

# 노드 id -> 노드 정의
_BY_ID: dict[str, dict] = {node["id"]: node for node in NODES}

# 실행 순서: 정책 반영(env) → 관측 → 핀 → IAM → 앵커 → 체인 검증 → (안내 노드)
_PLAN_ORDER: list[str] = [
    "seal_failures", "daily_cap", "per_uid_seconds", "ttl_days", "include_secrets",
    "observe", "pin_check", "iam_check", "anchor", "verify_chain",
    "anchor_interval", "issue_notify", "client_report",
]

# 로컬에서 실제로 실행 가능한 노드(run_step 이 처리한다).
_RUNNABLE: set[str] = {"observe", "pin_check", "iam_check", "anchor", "verify_chain"}
# 값은 있으나 실행하지 않고 안내만 하는 노드.
_INFO: set[str] = {"anchor_interval", "issue_notify", "client_report"}

# number 노드의 사람이 읽는 단위(선택).
_UNITS: dict[str, str] = {"daily_cap": "회", "per_uid_seconds": "초", "ttl_days": "일"}

# 그래프 엣지: 기본 흐름 + 예외 분기(이상이면 이슈 알림 / 결과 보고).
_EDGES: list[tuple[str, str]] = [
    ("seal_failures", "daily_cap"),
    ("daily_cap", "per_uid_seconds"),
    ("per_uid_seconds", "ttl_days"),
    ("ttl_days", "include_secrets"),
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
    return default        # action = 값을 갖지 않는다


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
    except (OSError, json.JSONDecodeError):
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
            "editable": node["kind"] != "action",
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

def _plan_status(node: dict, policy: dict, settings: dict) -> tuple[bool, str]:
    node_id = node["id"]
    if node_id in _RUNNABLE:
        missing = [key for key in node.get("requires", []) if not _present(settings, key)]
        if missing:
            return False, "필수 설정 없음: " + ", ".join(missing)
        return True, ""
    if node_id in _INFO:
        return False, "실행 노드 아님(정책 안내)"
    value = policy.get(node_id, node["default"])
    if not _enabled(node, value):
        return False, "꺼짐"
    return True, ""


def plan(policy: dict) -> list[dict]:
    """이번 실행에서 할 일을 순서대로 돌려준다(실행 가능한 노드만 ok=True)."""
    policy = _normalize(policy)
    settings = _load_settings()
    items = []
    for node_id in _PLAN_ORDER:
        node = _node(node_id)
        if node is None:
            continue
        ok, reason = _plan_status(node, policy, settings)
        items.append({"id": node_id, "label": node["label"], "ok": ok, "reason": reason})
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
    return str(value)


def push_env(node_id: str, policy: dict, *, service: str,
             api_key_value: Optional[str] = None) -> dict:
    """정책 값을 Render 환경변수로 밀어넣는다. 실제 재배포는 호출자가 한다."""
    node = _node(node_id)
    if node is None:
        raise commands.CommandError("unknown_node")
    env = node.get("env")
    if not env:
        raise commands.CommandError("no_env")
    policy = _normalize(policy)
    value = _env_value(node, policy.get(node_id, node["default"]))
    result = commands.env_set(service, env, value, api_key_value=api_key_value)
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


def automation_loop(policy: dict, *, on_log: Optional[Callable[[str], None]] = None,
                    stop_event: Any = None, secrets: Optional[dict] = None,
                    max_cycles: Optional[int] = None) -> dict:
    """주기 실행. `stop_event`(threading.Event)로 즉시 멈추고, `max_cycles` 로 무한 루프를 막는다.

    예외는 삼키고 로그·violations 로만 남긴다(자동화가 앱을 방해하면 안 된다).
    """
    log = on_log if on_log is not None else (lambda _message: None)
    policy = _normalize(policy)
    cycles = 0
    violations: list[str] = []
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
            else:
                log("정상 %s" % item["id"])
        try:
            stopped = _nap(_delay_seconds(policy), stop_event)
        except Exception:        # noqa: BLE001
            stopped = False
        if stopped:
            break
    return {"cycles": cycles, "violations": violations, "last": last}


__all__ = [
    "NODES", "DEFAULTS", "load", "save", "workflow_path",
    "graph", "plan", "run_step", "push_env", "automation_loop",
]
