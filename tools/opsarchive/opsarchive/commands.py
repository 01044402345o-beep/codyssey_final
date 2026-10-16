"""opsarchive 명령 구현 — 키 수명주기, Render 발행, 아카이브 열람.

원칙(문서 `docs/ops/EVIDENCE_SEAL.md` §6)
- 패스프레이즈는 **TTY 입력으로만** 받는다. argv·환경변수 금지(프로세스 목록·크래시 덤프로 샌다).
- 개인키는 파일(0600)에만 있고, 어떤 출력·로그에도 키·패스프레이즈를 넣지 않는다. 지문만 보여준다.
- 네트워크로 나가는 것은 **공개키**와 **봉인된 아카이브**뿐이다.
- 이 프로세스는 앱과 독립이다(앱 모듈을 import 하지 않는다).
"""

from __future__ import annotations

import base64
import getpass
import json
import os
import time
import urllib.request
import uuid

from . import container as C
from . import firebase, gcp, pins, render

DEFAULT_ENV_KEY = "EVIDENCE_PUBKEY"
DEFAULT_DIR = os.path.join(os.path.expanduser("~"), ".opsarchive")
PUBKEY_PREFIX = "x25519:"


class CommandError(Exception):
    """code: cancelled | bad_key_file | key_mismatch | not_found | health_failed | ..."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


# ------------------------------------------------------------------ 입력

def ask_passphrase(confirm: bool = False, prompt: str = "개인키 패스프레이즈: ") -> str:
    """TTY 로만 받는다. 빈 값 금지, 생성 시에는 두 번 받아 대조한다."""
    first = getpass.getpass(prompt)
    if not first:
        raise CommandError("cancelled")
    if confirm and getpass.getpass("다시 입력: ") != first:
        raise CommandError("cancelled")
    return first


def key_path(key_id: str, out_dir: str | None = None) -> str:
    return os.path.join(out_dir or DEFAULT_DIR, "admin-%s.key" % key_id)


# ------------------------------------------------------------------ keygen / selftest

def keygen(out_dir: str | None = None, passphrase: str | None = None) -> dict:
    """키쌍을 만들어 개인키를 잠가 저장한다. 공개키 문자열과 지문을 돌려준다(개인키는 안 돌려준다)."""
    directory = out_dir or DEFAULT_DIR
    os.makedirs(directory, exist_ok=True)
    private, public = C.keypair()
    kid = C.key_id(public).hex()
    phrase = passphrase or ask_passphrase(confirm=True, prompt="새 개인키 패스프레이즈: ")
    path = key_path(kid, directory)
    if os.path.exists(path):
        raise CommandError("exists")
    narrowed = C.save_private_key(path, private, phrase)
    return {"key_id": kid, "public_key": C.pack_public_key(public),
            "fingerprint": C.fingerprint(public), "path": path,
            "permissions": "owner_only" if narrowed else "inherited_warning"}


def selftest() -> dict:
    """로컬 왕복 검증: 봉인→해제, 변조 감지, 패스프레이즈 잠금. 키 파일 없이 돈다."""
    private, public = C.keypair()
    payload = json.dumps({"hello": "탈퇴 실패 증거", "n": 1}, ensure_ascii=False).encode()
    sealed = C.seal(payload, public)
    ok_roundtrip = C.unseal(sealed, private) == payload

    tampered = bytearray(sealed)
    tampered[-1] ^= 0x01
    try:
        C.unseal(bytes(tampered), private)
        detected = False
    except C.ContainerError:
        detected = True

    other_private, _ = C.keypair()
    try:
        C.unseal(sealed, other_private)
        wrong_key_blocked = False
    except C.ContainerError:
        wrong_key_blocked = True

    path = os.path.join(os.environ.get("TEMP", "/tmp"), "opsarchive-selftest-%s.key" % uuid.uuid4().hex)
    try:
        C.save_private_key(path, private, "test-phrase")
        locked = C.load_private_key(path, "test-phrase") == private
        try:
            C.load_private_key(path, "wrong")
            locked_wrong = False
        except C.ContainerError:
            locked_wrong = True
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    return {"roundtrip": ok_roundtrip, "tamper": detected, "wrong_key": wrong_key_blocked,
            "key_file": locked, "key_file_wrong_phrase": locked_wrong}


# ------------------------------------------------------------------ publish / doctor

def health(base_url: str, timeout: int = 20) -> dict:
    """앱 /health(지문만 노출된다 — 키 자체는 나오지 않는다)."""
    try:
        with urllib.request.urlopen(base_url.rstrip("/") + "/health", timeout=timeout) as res:
            return json.loads(res.read().decode() or "{}")
    except Exception as exc:        # noqa: BLE001
        raise CommandError("health_failed") from exc


def _health_block(base_url: str) -> tuple[bool, str]:
    """(앱이 지문을 노출하는가, 지문). **앱 훅이 아직 없으면 노출되지 않는다** — 그 사실을 숨기지 않는다."""
    info = health(base_url)
    block = info.get("evidence")
    if isinstance(block, dict) and block.get("fingerprint"):
        return True, str(block["fingerprint"])
    return False, ""


def publish(service: str, key_file: str, passphrase: str, *, env_key: str = DEFAULT_ENV_KEY,
            api_key_value: str | None = None, redeploy: bool = True, base_url: str = "") -> dict:
    """공개키를 Render 환경변수에 넣고 재배포한 뒤, 런타임 /health 의 지문과 대조한다."""
    private = C.load_private_key(key_file, passphrase)
    public = C.public_from_private(private)
    want = C.fingerprint(public)
    sid = render.service_id(service)
    render.put_env(sid, env_key, C.pack_public_key(public), api_key_value=api_key_value)
    if redeploy:
        render.deploy(sid)
    applied = render.get_env(sid, env_key, api_key_value=api_key_value)
    result = {"service_id": sid, "key_id": C.key_id(public).hex(), "fingerprint": want,
              "env_set": bool(applied), "health_has_evidence": False,
              "health_fingerprint": "", "match": None}
    if base_url:
        result["health_has_evidence"], result["health_fingerprint"] = _health_block(base_url)
        result["match"] = (result["health_fingerprint"] == want)
    return result


def doctor(service: str, key_file: str, passphrase: str, *, base_url: str = "",
           api_key_value: str | None = None, env_key: str = DEFAULT_ENV_KEY,
           project_id: str = "", pin_file: str = "") -> dict:
    """로컬 개인키의 공개 절반과 (a) Render 환경변수 (b) 런타임 /health 지문을 대조한다.

    회전 뒤 "이 개인키로는 아카이브를 열 수 없다" 상태를 배포 전에 잡는 것이 목적이다.
    """
    private = C.load_private_key(key_file, passphrase)
    public = C.public_from_private(private)
    want = C.fingerprint(public)
    sid = render.service_id(service)
    env_value = render.get_env(sid, env_key, api_key_value=api_key_value)
    env_fp = ""
    if env_value:
        try:
            env_fp = C.fingerprint(C.unpack_public_key(env_value))
        except C.ContainerError:
            env_fp = "bad"
    out = {"key_id": C.key_id(public).hex(), "fingerprint": want, "env_fingerprint": env_fp,
           "env_match": env_fp == want, "health_has_evidence": False,
           "health_fingerprint": "", "health_match": None,
           "firebase_cli": firebase.available()}
    if project_id:
        out["firebase_project_ok"] = firebase.has_project(project_id)
    if base_url:
        out["health_has_evidence"], out["health_fingerprint"] = _health_block(base_url)
        out["health_match"] = out["health_fingerprint"] == want
    if pin_file:
        out["pin"] = check_pin(pin_file, health_url=base_url)
    return out


def rotate(service: str, key_file: str, passphrase: str, *, out_dir: str | None = None,
           env_key: str = DEFAULT_ENV_KEY, api_key_value: str | None = None,
           base_url: str = "", redeploy: bool = True) -> dict:
    """새 키를 만들고 발행한다. **이전 개인키 파일은 지우지 않는다** — 옛 아카이브를 열어야 한다.

    새 키 경로는 **발행 전에** 돌려주는 값에 넣는다 — 재배포가 실패해도 운영자가 새 키 파일을
    찾을 수 있어야 한다(환경변수는 이미 새 키를 가리키고 있을 수 있다).
    """
    old = C.load_private_key(key_file, passphrase)
    new_phrase = ask_passphrase(confirm=True, prompt="새 개인키 패스프레이즈: ")
    made = keygen(out_dir=out_dir, passphrase=new_phrase)     # 프롬프트는 여기서 한 번만
    try:
        published = publish(service, made["path"], new_phrase, env_key=env_key,
                            api_key_value=api_key_value, redeploy=redeploy, base_url=base_url)
        error = ""
    except (CommandError, render.RenderError) as exc:
        published = {}
        error = getattr(exc, "code", str(exc))
    return {"old_key_id": C.key_id(C.public_from_private(old)).hex(), "new": made,
            "publish": published, "error": error}


# ------------------------------------------------------------------ 아카이브 열람

def firebase_preflight(project_id: str) -> dict:
    """firebase CLI 가 있고 그 프로젝트에 접근 가능한지 본다(사전 점검).

    없어도 아카이브 읽기는 계속한다 — CLI 는 점검·규칙 배포용이지 저장 경로가 아니다.
    """
    has_cli = firebase.available()
    return {"firebase_cli": has_cli,
            "firebase_project_ok": firebase.has_project(project_id) if has_cli else False}


# ------------------------------------------------------------------ 핀 고정(예상 밖 키 탐지)

def make_pin(key_file: str, passphrase: str, *, health_url: str, out: str,
             generation: int | None = None, commit: str = "", note: str = "") -> dict:
    """개인키에서 **역산한** 공개키로 핀 파일을 만든다.

    generation 을 주지 않으면 기존 핀의 다음 세대로 올린다. 앱이 알려준 값을 핀에 넣지 않는다
    (그러면 대조가 무의미해진다 — 핀은 관리자가 오프라인에서 정하는 신뢰 뿌리다).
    """
    private = C.load_private_key(key_file, passphrase)
    public = C.public_from_private(private)
    if generation is None:
        try:
            generation = int(pins.read(out).get("generation", 0)) + 1
        except (FileNotFoundError, pins.PinError):
            generation = 1
    document = pins.make(public, C.fingerprint(public), C.key_id(public).hex(),
                         generation=generation, health_url=health_url, commit=commit,
                         armed=True, note=note)
    return pins.write(out, document)


def check_pin(pin_file: str, *, health_url: str = "") -> dict:
    """핀 파일과 배포된 앱의 /health 보고를 대조한다(CI 가 cron 으로 도는 것과 같은 검사)."""
    pin = pins.read(pin_file)
    url = (health_url or pin.get("health_url", "")).strip()
    if not pin.get("armed"):
        return {"armed": False, "ok": None, "reasons": ["unarmed"], "pin_fingerprint": pin.get("fingerprint_sha256", "")}
    if not url:
        return {"armed": True, "ok": False, "reasons": ["health_url_missing"]}
    try:
        health = pins.fetch_health(url)
    except Exception as exc:        # noqa: BLE001 — 값으로만 알린다
        return {"armed": True, "ok": False, "reasons": ["health_unreachable:" + type(exc).__name__]}
    return pins.compare(pin, health)


# ------------------------------------------------------------------ IAM 점검(삭제 예방)

def iam_check(project_id: str, sa_path: str, *, canary_id: str = "") -> dict:
    """앱 서비스 계정이 증거 아카이브를 **지울 수 있는지** 실제로 시험한다.

    목표 상태: 앱은 만들 수 있고(create) 읽을 수 있지만 **지우거나 덮어쓸 수 없다**.
    그래서 카나리아 문서를 하나 만들어 (a) 생성 성공 (b) 삭제 거부 (c) 덮어쓰기 거부를 확인한다.
    카나리아는 `iam-canary-` 로 시작해 실제 아카이브와 섞이지 않고, `expire_at` 을 넣어 TTL 로 스스로 사라진다.
    """
    store = gcp.Firestore(project_id, sa_path)
    cid = canary_id or ("iam-canary-" + uuid.uuid4().hex[:12])
    path = "evidence_archives/" + cid
    now = int(time.time())
    out = {"canary": cid, "created": False, "delete_blocked": None, "update_blocked": None,
           "verdict": "", "note": "카나리아는 expire_at 으로 TTL 삭제된다(정책이 걸려 있으면)"}
    try:
        store.set(path, {"canary": True, "created_at": now, "expire_at": now + 3600,
                         "trigger": "iam_check"})
        out["created"] = True
    except gcp.GcpError as exc:
        out["verdict"] = "create_failed:" + exc.code
        return out
    try:
        store.delete(path)
        out["delete_blocked"] = False     # 앱이 증거를 지울 수 있다 = 목표 미달
    except gcp.GcpError:
        out["delete_blocked"] = True
    try:
        store.set(path, {"canary": True, "tampered": True, "expire_at": now + 3600})
        out["update_blocked"] = False
    except gcp.GcpError:
        out["update_blocked"] = True
    if out["delete_blocked"] and out["update_blocked"]:
        out["verdict"] = "ok"
    elif not out["delete_blocked"]:
        out["verdict"] = "app_can_delete"
    else:
        out["verdict"] = "app_can_overwrite"
    return out



def list_archives(project_id: str, sa_path: str, *, limit: int = 200) -> list[dict]:
    """Firestore 의 봉인 아카이브 목록(최신 먼저). 본문은 받지 않는다(메타만)."""
    store = gcp.Firestore(project_id, sa_path)
    items = store.list("evidence_archives", page_size=limit)
    for item in items:
        item["age_seconds"] = int(time.time() - float(item.get("created_at", 0) or 0))
    items.sort(key=lambda d: float(d.get("created_at", 0) or 0), reverse=True)
    return items


def fetch_sealed(project_id: str, sa_path: str, archive_id: str) -> bytes:
    """청크를 순서대로 모아 봉인 아카이브 바이트를 만든다."""
    store = gcp.Firestore(project_id, sa_path)
    meta = store.get("evidence_archives/" + archive_id)
    if meta is None:
        raise CommandError("not_found")
    parts = store.list("evidence_archives/%s/parts" % archive_id, page_size=300)
    parts.sort(key=lambda d: int(d.get("seq", 0)))
    blob = b"".join(base64.b64decode(p.get("data", "")) for p in parts)
    if not blob:
        raise CommandError("not_found")
    return blob


def decrypt_archive(project_id: str, sa_path: str, archive_id: str, key_file: str,
                    passphrase: str, *, out_dir: str | None = None) -> dict:
    """내려받아 개인키로 열고 요약을 돌려준다. 평문은 out_dir 를 줄 때만 파일로 남긴다."""
    private = C.load_private_key(key_file, passphrase)
    blob = fetch_sealed(project_id, sa_path, archive_id)
    try:
        raw = C.unseal(blob, private)
    except C.ContainerError as exc:
        raise CommandError(exc.code) from exc
    try:
        report = json.loads(raw)
    except json.JSONDecodeError:
        report = {"_raw_bytes": len(raw)}
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, "%s.json" % archive_id)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
        report["_written"] = path
    return report
