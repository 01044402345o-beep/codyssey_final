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
import tempfile
import time
import urllib.request
import uuid

from . import container as C
from . import chain, config, firebase, gcp, pins, render, witness

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
            api_key_value: str | None = None, redeploy: bool = True, base_url: str = "",
            on_step=None, deploy_timeout: int = 300) -> dict:
    """공개키를 Render 환경변수에 넣고 재배포한 뒤, 런타임 /health 의 지문과 대조한다.

    `on_step(문자열)` 을 주면 각 단계를 알려준다 — 재배포는 몇 분 걸리고 출력이 늦게 나오므로,
    진행 상황이 보이지 않으면 "응답 없음" 처럼 보인다(GUI 에서 실제로 그렇게 보였다).
    """
    def step(message: str) -> None:
        if on_step is not None:
            on_step(message)

    step("① 개인키 열기(패스프레이즈 확인)")
    private = C.load_private_key(key_file, passphrase)
    public = C.public_from_private(private)
    want = C.fingerprint(public)
    step("② Render 서비스 확인")
    sid = render.service_id(service)
    step("③ 환경변수 %s 설정(REST API)" % env_key)
    render.put_env(sid, env_key, C.pack_public_key(public), api_key_value=api_key_value)
    deploy_note = ""
    if redeploy:
        step("④ 재배포 시작 — 빌드·배포가 끝날 때까지 몇 분 걸릴 수 있습니다")
        outcome = render.deploy(sid, timeout=deploy_timeout)
        deploy_note = outcome["note"]
        step("④ 재배포: " + deploy_note)
    step("⑤ 환경변수·지문 확인")
    applied = render.get_env(sid, env_key, api_key_value=api_key_value)
    result = {"service_id": sid, "key_id": C.key_id(public).hex(), "fingerprint": want,
              "env_set": bool(applied), "deploy": deploy_note, "health_has_evidence": False,
              "health_fingerprint": "", "match": None}
    if base_url:
        result["health_has_evidence"], result["health_fingerprint"] = _health_block(base_url)
        result["match"] = (result["health_fingerprint"] == want)
    return result


_CONFIG_ERROR_CODES = ("no_cli", "no_api_key", "not_found")


def _as_command_error(exc: render.RenderError) -> CommandError | None:
    """설정 오류(CLI 없음·키 없음·서비스 못 찾음)는 사용자가 조치할 수 있게 CommandError 로 올린다."""
    code = str(exc.code)
    for prefix in _CONFIG_ERROR_CODES:
        if code == prefix or code.startswith(prefix):
            return CommandError(code)
    return None


def deploy(service: str, *, api_key_value: str | None = None, timeout: int = 300) -> dict:
    """Render 서비스를 이름으로 찾아 재배포한다(환경변수 발행 뒤 반영용).

    `render.deploy` 는 이미 dict(`{"ok","note"}`)를 돌려준다 — 예외를 올리지 않고 그대로 전달한다.
    다만 `no_cli`/`no_api_key`/`not_found` 같은 **설정 오류**는 사용자가 조치해야 하므로
    `CommandError` 로 올린다(그래야 CLI/GUI 가 원인을 코드로 보여줄 수 있다).
    """
    try:
        sid = render.service_id(service)
    except render.RenderError as exc:
        mapped = _as_command_error(exc)
        if mapped is not None:
            raise mapped from exc
        return {"service_id": "", "ok": False, "note": "서비스 조회 실패: " + str(exc.code)}
    try:
        outcome = render.deploy(sid, timeout=timeout)
    except render.RenderError as exc:
        mapped = _as_command_error(exc)
        if mapped is not None:
            raise mapped from exc
        return {"service_id": sid, "ok": False, "note": "재배포 실패: " + str(exc.code)}
    return {"service_id": sid, "ok": bool(outcome.get("ok")),
            "note": str(outcome.get("note", ""))}


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
           base_url: str = "", redeploy: bool = True, pass_new: str | None = None) -> dict:
    """새 키를 만들고 발행한다. **이전 개인키 파일은 지우지 않는다** — 옛 아카이브를 열어야 한다.

    새 키 경로는 **발행 전에** 돌려주는 값에 넣는다 — 재배포가 실패해도 운영자가 새 키 파일을
    찾을 수 있어야 한다(환경변수는 이미 새 키를 가리키고 있을 수 있다).
    `pass_new` 를 주면 새 키 패스프레이즈를 묻지 않는다(GUI 가 입력 창으로 먼저 받는다).
    """
    old = C.load_private_key(key_file, passphrase)
    new_phrase = pass_new if pass_new is not None else ask_passphrase(confirm=True, prompt="새 개인키 패스프레이즈: ")
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

# ------------------------------------------------------------------ 서명 키 · 체크포인트 앵커((b)+(d))

def signkey(out_dir: str | None = None, passphrase: str | None = None) -> dict:
    """관리자 **서명 키**(Ed25519). 봉투 키(X25519)와 용도가 다르다 — 이 키는 체크포인트에 서명한다."""
    directory = out_dir or DEFAULT_DIR
    os.makedirs(directory, exist_ok=True)
    seed, public = C.sign_keypair()
    kid = C.key_id(public).hex()
    phrase = passphrase or ask_passphrase(confirm=True, prompt="새 서명키 패스프레이즈: ")
    path = os.path.join(directory, "sign-%s.key" % kid)
    if os.path.exists(path):
        raise CommandError("exists")
    narrowed = C.save_private_key(path, seed, phrase)
    return {"key_id": kid, "public_key": C.pack_public_key(public),
            "fingerprint": C.fingerprint(public), "path": path,
            "permissions": "owner_only" if narrowed else "inherited_warning"}


# ------------------------------------------------------------------ 체크포인트 잠금 · 원자적 쓰기

LOCK_NAME = ".lock"
LOCK_TIMEOUT = 5.0          # 잠금을 잡지 못하면 이만큼 기다린 뒤 실패한다(초)
LOCK_POLL = 0.05            # 재시도 간격(초)


def _acquire_lock(out_dir: str, timeout: float | None = None) -> int:
    """`out_dir/.lock` 을 `O_CREAT|O_EXCL` 로 **원자적으로** 만든다(경합 방지).

    이미 있으면 최대 `timeout`(기본 `LOCK_TIMEOUT`) 초 동안 재시도하고, 그래도 못 잡으면
    `CommandError("locked")` 로 실패한다. 성공하면 fd 를 돌려준다(호출자가 finally 에서 해제).
    """
    if timeout is None:
        timeout = LOCK_TIMEOUT
    path = os.path.join(out_dir, LOCK_NAME)
    deadline = time.monotonic() + max(0.0, float(timeout))
    while True:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise CommandError("locked — 다른 anchor 가 %s 를 쓰고 있습니다" % path)
            time.sleep(LOCK_POLL)
        except OSError as exc:
            raise CommandError("lock_failed") from exc
        else:
            try:
                os.write(fd, str(os.getpid()).encode("ascii"))
            except OSError:
                pass
            return fd


def _release_lock(out_dir: str, fd: int) -> None:
    """fd 를 닫고 잠금 파일을 지운다(없어도 조용히 넘어간다 — finally 에서 부른다)."""
    try:
        os.close(fd)
    except OSError:
        pass
    try:
        os.remove(os.path.join(out_dir, LOCK_NAME))
    except OSError:
        pass


def _write_json_atomic(path: str, data: dict, *, sort_keys: bool = True) -> None:
    """임시 파일에 쓰고 `flush`+`fsync` 한 뒤 `os.replace` 로 교체한다.

    전원이 나가도 반쪽 파일이 남지 않고, 독자는 항상 완성본을 본다(원자적 교체).
    """
    directory = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2, sort_keys=sort_keys)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def anchor(project_id: str, sa_path: str, sign_key_file: str, passphrase: str, *,
           out_dir: str = "checkpoints") -> dict:
    """지금 저장소의 아카이브 체인을 확인하고, (seq, count, head, 집합 해시)를 **서명해 앵커**한다.

    체크포인트를 로컬/저장소에 남긴다 — 앱이 나중에 개수를 줄이거나 head 를 바꾸면 검증에서 걸린다.

    **경합 방지**: seq 를 정하는 일과 쓰기가 동시에 일어나면 같은 seq 를 덮어쓸 수 있다. 그래서
    `out_dir/.lock` 을 `O_CREAT|O_EXCL` 로 잡고(있으면 최대 `LOCK_TIMEOUT` 초 대기) 그 안에서
    seq 결정·쓰기를 끝낸다. 파일은 임시 파일에 쓰고 `os.replace` 로 교체하며, `flush`+`fsync` 로
    전원이 나가도 반쪽 파일이 남지 않게 한다.
    """
    store = gcp.Firestore(project_id, sa_path)
    metas = archives(project_id, sa_path)
    entries = chain_entries(project_id, sa_path)                    # 시도·결과 항목(사전 커밋먼트)
    chain_state = chain.check_chain(metas + entries)               # 한 체인으로 이어진다
    if not chain_state["ok"]:
        # 매니페스트가 아닌 문서나 끊긴 체인을 그대로 서명하면 **나중에 검증이 계속 실패**한다.
        # 그래서 기본은 거부한다(문제를 먼저 해결해야 한다).
        raise CommandError("chain_broken: " + "; ".join(
            "%s/%s" % (p.get("issue"), p.get("archive_id") or "-") for p in chain_state["problems"][:3]))
    seed = C.load_private_key(sign_key_file, passphrase)
    out_dir = config.resolve(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    lock_fd = _acquire_lock(out_dir)
    try:
        seq = 1
        for name in os.listdir(out_dir):
            if name.endswith(".json") and name[:-5].isdigit():
                seq = max(seq, int(name[:-5]) + 1)
        ids = sorted(str(m.get("archive_id", "")) for m in metas)
        body = chain.checkpoint_body(seq=seq, count=chain_state["count"],
                                     head_digest=chain_state["head"], archive_ids=ids,
                                     created_at=int(time.time()),
                                     entry_ids=[str(e.get("seq", "")) for e in entries],
                                     head_seq=chain_state.get("max_seq"))
        signed = chain.sign_checkpoint(seed, body)
        path = os.path.join(out_dir, "%d.json" % seq)
        _write_json_atomic(path, signed, sort_keys=True)
        # 개별 대조용 목록(아이디만 — 개인정보 없음). 나중에 "앵커한 뒤 사라진 아카이브"와
        # "이 챌린지가 앵커 범위 안이었는가"를 찾는다.
        anchor_dir = os.path.join(out_dir, "anchors")
        os.makedirs(anchor_dir, exist_ok=True)
        _write_json_atomic(os.path.join(anchor_dir, "%d.json" % seq),
                           {"seq": seq, "archive_ids": ids,
                            "challenges": sorted({str(e.get("challenge", "")) for e in entries
                                                  if e.get("challenge")})}, sort_keys=False)
    finally:
        _release_lock(out_dir, lock_fd)                             # 실패해도 반드시 지운다
    return {"seq": seq, "path": path, "count": chain_state["count"], "archives": len(metas),
            "entries": len(entries), "head": chain_state["head"], "head_seq": chain_state.get("max_seq"),
            "chain_ok": chain_state["ok"], "problems": chain_state["problems"],
            "forks": chain_state["forks"], "signing_key_id": signed["signing_key_id"]}


def verify_chain(project_id: str, sa_path: str, pin_file: str, *, out_dir: str = "checkpoints",
                 challenge: str = "") -> dict:
    """체크포인트 서명·연속성·롤백을 검증하고, 앵커한 뒤 **사라진 아카이브**와
    **제시된 챌린지(사전 커밋먼트)** 가 앵커 범위 안에 있는지 본다."""
    try:
        pin = pins.read(config.resolve(pin_file))
    except FileNotFoundError as exc:
        raise CommandError("no_pin_file") from exc
    packed = pin.get("signing_public_key", "")
    if not packed:
        # 신뢰 뿌리(핀의 서명 공개키)가 없으면 체크포인트 서명을 검증할 수 없다.
        raise CommandError("no_signing_key — Render 탭 ⑤ '핀 만들기'에서 **서명 키를 포함해** 핀을 다시 만드세요")
    signing_public = C.unpack_public_key(packed)
    out_dir = config.resolve(out_dir)
    checkpoints = []
    for name in sorted(os.listdir(out_dir)) if os.path.isdir(out_dir) else []:
        if name.endswith(".json") and name[:-5].isdigit():
            with open(os.path.join(out_dir, name), encoding="utf-8") as fh:
                checkpoints.append(json.load(fh))
    if not checkpoints:
        raise CommandError("not_found")
    store = gcp.Firestore(project_id, sa_path)
    metas = archives(project_id, sa_path)
    entries = chain_entries(project_id, sa_path)
    result = chain.verify_chain(checkpoints, signing_public, metas + entries)
    result["archives"] = len(metas)
    result["entries"] = len(entries)

    latest = max(checkpoints, key=lambda c: int(c.get("seq", 0)))
    anchor_path = os.path.join(out_dir, "anchors", "%s.json" % latest.get("seq"))
    if os.path.exists(anchor_path):
        anchored = set(chain.load_archive_ids(anchor_path))
        present = {str(m.get("archive_id", "")) for m in metas}
        result["missing_now"] = sorted(anchored - present)      # 앵커한 뒤 사라졌다 = 삭제 의심
        result["new_since_anchor"] = sorted(present - anchored)
        result["ok"] = bool(result["ok"] and not result["missing_now"])
    else:
        result["missing_now"] = None
        result["note"] = "anchors/<seq>.json 이 없어 개별 누락 대조를 건너뛰었다"

    if challenge:
        check = chain.challenge_report(entries, challenge, latest)
        result["challenge_check"] = check
        if check["verdict"] in ("missing_from_chain",):
            result["ok"] = False                                # 누락 의심은 실패로 올린다
    return result


def archives(project_id: str, sa_path: str, *, limit: int = 300) -> list[dict]:
    """증거 아카이브(매니페스트가 있는 문서)만 고른다.

    IAM 검사 카나리아(`iam-canary-*`)는 증거가 아니다 — 섞이면 목록 개수가 부풀고,
    체인 검사에서 매니페스트가 없어 `digest_mismatch` 로 보고된다(실제로 그랬다).
    """
    store = gcp.Firestore(project_id, sa_path)
    items = store.list("evidence_archives", page_size=limit)
    return [item for item in items
            if item.get("schema") == "SEAL-SIG-v1"
            and not str(item.get("_id", "")).startswith("iam-canary-")]


def chain_entries(project_id: str, sa_path: str, *, limit: int = 300) -> list[dict]:
    """시도·결과 체인 항목(문서가 없으면 빈 목록 — 404 를 오류로 보지 않는다)."""
    return gcp.Firestore(project_id, sa_path).list("evidence_chain/entries", page_size=limit)


def observe_requests(project_id: str, sa_path: str, service: str, *, path: str = "/account/erase",
                     since_minutes: int = 60, tolerance: int = 0) -> dict:
    """**앱 밖 증인**: 플랫폼 접근 로그(앱이 지울 수 없다)와 체인의 시도 항목 수를 비교한다.

    사전 커밋먼트는 사용자가 챌린지를 제시해야 작동한다. 이 명령은 그 요구 없이 **개수 수준**으로
    "요청은 왔는데 체인에 시도가 없다"를 드러낸다. 로그 보존 기간이 곧 관측 범위이므로 자주 돌린다.
    """
    store = gcp.Firestore(project_id, sa_path)
    entries = store.list("evidence_chain/entries", page_size=300)
    cutoff = int(time.time()) - max(1, int(since_minutes)) * 60
    attempts = [e for e in entries
                if str(e.get("kind", "")) == "attempt"
                and int(e.get("created_at", 0) or 0) >= cutoff]
    sid = render.service_id(service)
    logs = render.logs(sid, text=path, limit=1000)         # render CLI — 앱과 독립된 관찰자
    observed = witness.count_requests(logs, path)
    result = witness.compare(observed=observed, attempts=len(attempts), tolerance=int(tolerance))
    result.update({
        "service_id": sid, "path": path, "since_minutes": int(since_minutes),
        "window_start": cutoff,
        "attempt_challenges": sorted(str(e.get("challenge", "")) for e in attempts)[:20],
        "caveat": "플랫폼 로그 보존 기간만큼만 관측된다(짧으면 그 구간은 보이지 않는다). 로그에는 헤더가 없어 개별 요청을 챌린지에 연결하지는 못한다.",
    })
    return result


def env_set(service: str, key: str, value: str, *, api_key_value: str | None = None) -> dict:
    """Render 서비스의 환경변수 하나를 올린다(REST API).

    **값을 명령줄 인자로 받지 않는 경로를 쓰는 게 안전하다** — 인자는 셸 히스토리·프로세스 목록에
    남는다. CLI 는 `--from-file`(파일) 또는 표준입력만 허용하고, 화면·로그에는 값 대신 **길이만** 남긴다.
    여러 줄 값(서비스 계정 JSON 등)은 대시보드 복붙보다 이쪽이 실수가 적다.
    """
    if not key.strip():
        raise CommandError("bad_input:key")
    if not value.strip():
        # 빈 값을 올리면 Render 가 400 을 돌려주고 원인을 알기 어렵다(실제로 겪었다).
        raise CommandError("empty_value — 값이 비었습니다(.env 에 넣었는지, 셸 변수가 실제로 있는지 확인하세요)")
    sid = render.service_id(service)
    render.put_env(sid, key.strip(), value, api_key_value=api_key_value)
    return {"service_id": sid, "key": key.strip(), "value_length": len(value),
            "note": "값은 화면·로그에 남기지 않았습니다. 재배포해야 앱에 반영됩니다."}


def env_read(service: str, key: str, *, api_key_value: str | None = None) -> dict:
    """환경변수가 설정돼 있는지만 확인한다(값은 길이만)."""
    sid = render.service_id(service)
    value = render.get_env(sid, key.strip(), api_key_value=api_key_value)
    return {"service_id": sid, "key": key.strip(), "set": bool(value),
            "value_length": len(value or "")}


def firebase_preflight(project_id: str) -> dict:
    """firebase CLI 가 있고 그 프로젝트에 접근 가능한지 본다(사전 점검).

    없어도 아카이브 읽기는 계속한다 — CLI 는 점검·규칙 배포용이지 저장 경로가 아니다.
    """
    has_cli = firebase.available()
    return {"firebase_cli": has_cli,
            "firebase_project_ok": firebase.has_project(project_id) if has_cli else False}


# ------------------------------------------------------------------ 핀 고정(예상 밖 키 탐지)

def make_pin(key_file: str, passphrase: str, *, health_url: str, out: str,
             generation: int | None = None, commit: str = "", note: str = "",
             signing_public: bytes | None = None) -> dict:
    """개인키에서 **역산한** 공개키로 핀 파일을 만든다.

    generation 을 주지 않으면 기존 핀의 다음 세대로 올린다. 앱이 알려준 값을 핀에 넣지 않는다
    (그러면 대조가 무의미해진다 — 핀은 관리자가 오프라인에서 정하는 신뢰 뿌리다).
    """
    private = C.load_private_key(key_file, passphrase)
    public = C.public_from_private(private)
    if generation is None:
        try:
            generation = int(pins.read(config.resolve(out)).get("generation", 0)) + 1
        except (FileNotFoundError, pins.PinError):
            generation = 1
    document = pins.make(public, C.fingerprint(public), C.key_id(public).hex(),
                         generation=generation, health_url=health_url, commit=commit,
                         armed=True, note=note, signing_public=signing_public)
    return pins.write(config.resolve(out), document)


def check_pin(pin_file: str, *, health_url: str = "") -> dict:
    """핀 파일과 배포된 앱의 /health 보고를 대조한다(CI 가 cron 으로 도는 것과 같은 검사)."""
    try:
        pin = pins.read(config.resolve(pin_file))
    except FileNotFoundError as exc:
        raise CommandError("no_pin_file") from exc          # 경로를 뭉뚱그리지 않고 코드로 알린다
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
    # 카나리아는 **별도 컬렉션**에 둔다: 증거 아카이브 목록·체인 앵커를 오염시키지 않으려고.
    # (삭제가 막혀 있는 것이 정상이므로 다 쓴 뒤 스스로 지울 수 없다 — 그래서 섞이면 안 된다.)
    path = "evidence_iam_canary/" + cid
    now = int(time.time())
    out = {"canary": cid, "created": False, "delete_blocked": None, "update_blocked": None,
           "verdict": "", "note": "카나리아는 별도 컬렉션이라 증거 목록·체인에 섞이지 않는다"}
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
    items = archives(project_id, sa_path, limit=limit)
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
