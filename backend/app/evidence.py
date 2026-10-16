"""탈퇴 실패 증거 봉인 — 앱 훅(수집·봉인·보관·통보).

탈퇴가 **완료되지 않았거나 단계가 생략/실패**하면 그 순간의 상태를 모아 압축하고, 관리자 공개키로
봉인해 Firestore 에 넣고 GitHub 이슈로 **메타데이터만** 통보한다. 설계·위협 모델·한계는
`docs/ops/EVIDENCE_SEAL.md`(특히 §9). 관리자 CLI 는 `tools/opsarchive/` 다.

지키는 것
- **봉인 실패가 탈퇴 실패를 악화시키지 않는다**: 이 모듈의 어떤 함수도 예외를 밖으로 내보내지 않는다.
- **앱은 복호화할 수 없다**: 공개키만 있고 개인키는 관리자 로컬에만 있다.
- **자격증명은 기본 스크럽**한다(토큰·서비스 계정 JSON·환경변수 값). "전부 포함"을 택했지만
  한 번 복호화하면 살아 있는 자격증명이 되살아나는 것은 별개 문제다. `EVIDENCE_INCLUDE_SECRETS=1` 로 끌 수 있다.
- 형식(MFA1)은 CLI 구현과 **같은 바이트**여야 한다 — `backend/tests/test_evidence.py` 가 CLI 의
  `unseal` 로 실제로 열어보며 검증한다.

환경변수
- `EVIDENCE_PUBKEY` : 관리자 공개키(`x25519:<base64url>`). 없으면 이 기능 전체가 꺼진다(기본 꺼짐).
- `EVIDENCE_KEY_GENERATION` : 회전 세대(기본 1). `/health` 로 노출되어 핀 검증에 쓰인다.
- `EVIDENCE_GH_TOKEN` / `EVIDENCE_GH_REPO` : 이슈 통보용(없으면 보관만 하고 통보는 건너뛴다).
- `EVIDENCE_MAX_BYTES` / `EVIDENCE_MAX_SOURCE_BYTES` / `EVIDENCE_MAX_LOGS_BYTES` : 하드 캡.
- `EVIDENCE_PER_UID_SECONDS`(기본 3600) / `EVIDENCE_DAILY_CAP`(기본 5) : 남용 방지.
- `EVIDENCE_TTL_DAYS`(기본 90) : Firestore TTL(`expire_at`) — 이 기간이 지나면 자동 삭제된다.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import logging
import os
import platform
import re
import struct
import threading
import time
import traceback
import urllib.error
import urllib.request
import uuid
from collections import deque
from typing import Any

from . import firebase_admin

# ---------------------------------------------------------------- MFA1 (CLI container.py 와 같은 형식)

MAGIC = b"MFA1"
ALG = 1
VERSION = 1
KEY_ID_LEN = 8
NONCE_LEN = 12
HEADER_FIXED = 4 + 1 + 1 + KEY_ID_LEN + 2
HKDF_SALT = b"mfa1"
HKDF_INFO = b"mfa1-kek"
WRAP_SALT = b"mfa1-nonce"
WRAP_INFO = b"mfa1-wrap"
CHUNK_BYTES = 512 * 1024

LOGGER = logging.getLogger("app.evidence")


class EvidenceError(Exception):
    """code: no_key | bad_key | seal_failed | store_failed | bad_input"""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


def public_key() -> bytes | None:
    """관리자 공개키(32바이트). 없으면 None — 기능 전체가 꺼진다."""
    raw = (os.getenv("EVIDENCE_PUBKEY") or "").strip()
    if not raw:
        return None
    if raw.startswith("x25519:"):
        raw = raw[len("x25519:"):]
    raw += "=" * (-len(raw) % 4)
    try:
        key = base64.urlsafe_b64decode(raw.encode())
    except Exception:  # noqa: BLE001 — 값만 알린다
        return None
    return key if len(key) == 32 else None


def configured() -> bool:
    return public_key() is not None


def key_id_hex() -> str:
    key = public_key()
    return hashlib.sha256(key).digest()[:KEY_ID_LEN].hex() if key else ""


def fingerprint() -> str:
    key = public_key()
    return hashlib.sha256(key).hexdigest() if key else ""


def generation() -> int:
    return _int_env("EVIDENCE_KEY_GENERATION", 1)


def health_block() -> dict[str, Any]:
    """`/health` 에 넣는 공개 정보 — 키 지문·세대만. 키 자체는 노출하지 않는다."""
    if not configured():
        return {}
    return {"key_id": key_id_hex(), "fingerprint": fingerprint(), "generation": generation()}


def seal(data: bytes, recipient: bytes) -> bytes:
    """MFA1: gzip → AES-256-GCM → 데이터키를 X25519 로 봉인. 형식은 CLI 와 동일해야 한다."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    if len(recipient) != 32:
        raise EvidenceError("bad_key")
    ephemeral = X25519PrivateKey.generate()
    shared = ephemeral.exchange(X25519PublicKey.from_public_bytes(recipient))
    eph_pub = ephemeral.public_key().public_bytes(serialization.Encoding.Raw,
                                                  serialization.PublicFormat.Raw)

    def derive(salt: bytes, info: bytes, length: int) -> bytes:
        return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(shared)

    data_key = bytearray(os.urandom(32))
    try:
        wrapped = eph_pub + AESGCM(derive(HKDF_SALT, HKDF_INFO, 32)).encrypt(
            derive(WRAP_SALT, WRAP_INFO, NONCE_LEN), bytes(data_key), None)
        iv = os.urandom(NONCE_LEN)
        header = (MAGIC + bytes([ALG, VERSION])
                  + hashlib.sha256(recipient).digest()[:KEY_ID_LEN]
                  + struct.pack(">H", len(wrapped)) + wrapped + iv)
        body = AESGCM(bytes(data_key)).encrypt(iv, gzip.compress(data), header)
    finally:
        data_key[:] = b"\x00" * len(data_key)
    return header + body


# ---------------------------------------------------------------- 자격증명 스크럽

_SECRET_ENV = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|AUTH)", re.I)
_PATTERNS = [
    re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]{8,}"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{20,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\brnd_[A-Za-z0-9]{10,}"),
    re.compile(r"\bsk-[A-Za-z0-9]{16,}"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{5,}"),
    re.compile(r'"private_key"\s*:\s*"-----BEGIN[^"]{0,4096}"'),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]{0,4096}?-----END [A-Z ]*PRIVATE KEY-----"),
]


def scrub_text(text: str) -> str:
    """자격증명을 `[MASKED]` 로 바꾼다(환경변수 '값'도 함께 지운다)."""
    if os.getenv("EVIDENCE_INCLUDE_SECRETS") == "1":
        return text
    out = text
    for pattern in _PATTERNS:
        out = pattern.sub(lambda m: (m.group(1) if m.groups() else "") + "[MASKED]", out)
    for name, value in os.environ.items():
        if not value or len(value) < 8 or not _SECRET_ENV.search(name):
            continue
        out = out.replace(value, "[MASKED]")
    return out


def _scrub(value: Any) -> Any:
    if isinstance(value, str):
        return scrub_text(value)
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


# ---------------------------------------------------------------- 로그 링 버퍼

class RingHandler(logging.Handler):
    """최근 로그를 메모리에 조금만 들고 있는다(증거에 넣기 위해). 개수·길이 상한이 있다."""

    def __init__(self, capacity: int = 400, width: int = 2000) -> None:
        super().__init__(level=logging.INFO)
        self.capacity = capacity
        self.width = width
        self.records: deque[str] = deque(maxlen=capacity)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created))
            line = "%s %s %s %s" % (stamp, record.levelname, record.name, record.getMessage())
            self.records.append(line[: self.width])
            if record.exc_info:
                self.records.append(self.format(record)[: self.width])
        except Exception:  # noqa: BLE001 — 로그 수집이 앱을 방해하면 안 된다
            pass


_ring = RingHandler()
_ring_installed = False
_ring_lock = threading.Lock()


def install_log_ring() -> RingHandler:
    """루트 로거에 링 버퍼를 한 번만 붙인다(설정이 없으면 붙이지 않는다)."""
    global _ring_installed
    if not configured():
        return _ring
    with _ring_lock:
        if not _ring_installed:
            logging.getLogger().addHandler(_ring)
            _ring_installed = True
    return _ring


def recent_logs(limit: int = 400) -> list[str]:
    return list(_ring.records)[-limit:]


# ---------------------------------------------------------------- 수집

def _tree(root: str, max_bytes: int) -> tuple[list[dict[str, Any]], dict[str, str], int, bool]:
    """소스 트리를 훑어 (파일 목록, 경로→텍스트, 담은 바이트, 잘렸는가)를 돌려준다."""
    files: list[dict[str, Any]] = []
    blobs: dict[str, str] = {}
    total = 0
    truncated = False
    skip = {".git", "__pycache__", ".venv", "node_modules", ".pytest_cache"}
    for base, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d not in skip]
        for name in sorted(names):
            path = os.path.join(base, name)
            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            rel = os.path.relpath(path, root).replace("\\", "/")
            files.append({"path": rel, "size": size})
            if truncated or size > 512 * 1024:
                continue
            try:
                with open(path, "rb") as fh:
                    raw = fh.read()
                text = raw.decode("utf-8", errors="replace")
            except OSError:
                continue
            if total + len(text) > max_bytes:
                truncated = True
                continue
            blobs[rel] = text
            total += len(text)
    return files, blobs, total, truncated


def collect(trigger: str, *, uid: str = "", ledger: list[dict[str, Any]] | None = None,
            verification: dict[str, Any] | None = None, error: BaseException | None = None,
            extra: dict[str, Any] | None = None, source_root: str = "") -> dict[str, Any]:
    """증거 묶음을 만든다(캡을 넘으면 잘라내고 표시한다)."""
    max_bytes = _int_env("EVIDENCE_MAX_BYTES", 1_000_000)
    max_source = _int_env("EVIDENCE_MAX_SOURCE_BYTES", 512 * 1024)
    max_logs = _int_env("EVIDENCE_MAX_LOGS_BYTES", 64 * 1024)
    report: dict[str, Any] = {
        "archive_id": uuid.uuid4().hex,
        "created_at": int(time.time()),
        "trigger": trigger,
        "uid_hash": hashlib.sha256(uid.encode()).hexdigest()[:16] if uid else "",
        "ledger": ledger or [],
        "verification": verification or {},
        "truncated": {},
        "runtime": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "env_names": sorted(os.environ.keys()),          # 값이 아니라 이름만
            "deploy_commit": os.getenv("RENDER_GIT_COMMIT", ""),
            "deploy_service": os.getenv("RENDER_SERVICE_NAME", ""),
        },
        "extra": extra or {},
    }

    logs = recent_logs()
    kept: list[str] = []
    used = 0
    for line in logs:
        if used + len(line) > max_logs:
            report["truncated"]["logs"] = True
            break
        kept.append(line)
        used += len(line)
    report["logs"] = kept

    if source_root and os.path.isdir(source_root):
        files, blobs, total, cut = _tree(source_root, max_source)
        report["source"] = {"root": os.path.basename(source_root), "files": files,
                            "bytes": total, "content": blobs}
        if cut:
            report["truncated"]["source"] = True

    if error is not None:
        report["error"] = {
            "type": type(error).__name__,
            "code": getattr(error, "code", ""),
            "message": str(error),
            "traceback": "".join(traceback.format_exception(type(error), error, error.__traceback__))[-8000:],
        }

    report = _scrub(report)
    raw = json.dumps(report, ensure_ascii=False, separators=(",", ":")).encode()
    if len(raw) > max_bytes:
        report["truncated"]["total"] = True
        report["logs"] = report["logs"][-50:]
        if "source" in report:
            report["source"]["content"] = {}
        report["error"] = {k: v for k, v in (report.get("error") or {}).items() if k != "traceback"}
        raw = json.dumps(report, ensure_ascii=False, separators=(",", ":")).encode()
        report["_raw_bytes"] = len(raw)
    return report


# ---------------------------------------------------------------- 보관(청크) · 통보

def _encode_fields(data: dict[str, Any]) -> dict[str, Any]:
    def value(item: Any) -> dict[str, Any]:
        if isinstance(item, bool):
            return {"booleanValue": item}
        if isinstance(item, int):
            return {"integerValue": str(item)}
        if isinstance(item, float):
            return {"doubleValue": item}
        if isinstance(item, str):
            return {"stringValue": item}
        return {"stringValue": json.dumps(item, ensure_ascii=False, separators=(",", ":"))}

    return {"fields": {k: value(v) for k, v in data.items()}}


def store(blob: bytes, meta: dict[str, Any]) -> dict[str, Any]:
    """청크로 나눠 Firestore 에 넣는다(문서 1MiB 제한 회피). 규칙을 거치지 않는다(관리자)."""
    admin = firebase_admin.get_admin()
    archive_id = meta["archive_id"]
    parts = [blob[i:i + CHUNK_BYTES] for i in range(0, len(blob), CHUNK_BYTES)] or [b""]
    document = dict(meta)
    document.update({"sha256": hashlib.sha256(blob).hexdigest(), "size": len(blob),
                     "chunks": len(parts)})
    admin.firestore("PATCH", "evidence_archives/%s" % archive_id, _encode_fields(document))
    for index, part in enumerate(parts):
        admin.firestore("PATCH", "evidence_archives/%s/parts/%d" % (archive_id, index),
                        _encode_fields({"seq": index, "expire_at": document.get("expire_at", 0),
                                        "data": base64.b64encode(part).decode()}))
    return document


def notify(document: dict[str, Any]) -> bool:
    """GitHub 이슈로 **메타데이터만** 보낸다(본문·키 없음). 토큰/리포가 없으면 건너뛴다."""
    token = (os.getenv("EVIDENCE_GH_TOKEN") or "").strip()
    repo = (os.getenv("EVIDENCE_GH_REPO") or "").strip()
    if not token or not repo:
        return False
    body = "\n".join([
        "탈퇴 실패 증거가 봉인되었습니다(메타데이터만; 본문은 관리자만 열 수 있습니다).",
        "",
        "- archive_id: `%s`" % document.get("archive_id", ""),
        "- trigger: `%s`" % document.get("trigger", ""),
        "- key_id: `%s`" % document.get("key_id", ""),
        "- commit: `%s`" % document.get("commit", ""),
        "- sha256: `%s`" % document.get("sha256", ""),
        "- size: %s bytes · chunks: %s" % (document.get("size"), document.get("chunks")),
        "- ledger: %s" % json.dumps(document.get("ledger", []), ensure_ascii=False),
        "- verification: %s" % json.dumps(document.get("verification", {}), ensure_ascii=False),
        "- Firestore: `evidence_archives/%s` (TTL %s)" % (document.get("archive_id", ""),
                                                          document.get("expire_at", "")),
    ])
    payload = json.dumps({"title": "[evidence-seal] 탈퇴 실패 봉인 %s" % document.get("archive_id", "")[:12],
                          "body": body, "labels": ["evidence-seal"]}).encode()
    request = urllib.request.Request("https://api.github.com/repos/%s/issues" % repo, data=payload,
                                     method="POST")
    request.add_header("Authorization", "Bearer " + token)
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("Content-Type", "application/json")
    request.add_header("User-Agent", "codyssey-evidence-seal")
    try:
        with urllib.request.urlopen(request, timeout=15) as res:
            return 200 <= int(res.status) < 300
    except Exception:  # noqa: BLE001 — 통보 실패는 보관을 되돌리지 않는다
        LOGGER.warning("증거 이슈 통보에 실패했습니다")
        return False


# ---------------------------------------------------------------- 스로틀 · 오케스트레이션

_lock = threading.Lock()
_last_by_uid: dict[str, float] = {}
_daily = {"day": "", "count": 0}


def throttle_ok(uid: str) -> bool:
    """uid 당 1회/시간, 전역 하루 상한. 초과하면 False(아카이브를 만들지 않는다).

    프로세스 단위라 인스턴스가 여러 개면 상한이 느슨해진다 — 그 사실은 문서에 적혀 있다.
    """
    now = time.time()
    today = time.strftime("%Y-%m-%d", time.gmtime(now))
    with _lock:
        if _daily["day"] != today:
            _daily["day"], _daily["count"] = today, 0
        if _daily["count"] >= _int_env("EVIDENCE_DAILY_CAP", 5):
            return False
        window = _int_env("EVIDENCE_PER_UID_SECONDS", 3600)
        if uid and now - _last_by_uid.get(uid, 0) < window:
            return False
        _daily["count"] += 1
        if uid:
            _last_by_uid[uid] = now
    return True


def reset_state() -> None:
    """테스트용: 스로틀·링 버퍼를 비운다."""
    with _lock:
        _last_by_uid.clear()
        _daily["day"], _daily["count"] = "", 0
    _ring.records.clear()


def seal_and_report(trigger: str, *, uid: str = "", ledger: list[dict[str, Any]] | None = None,
                    verification: dict[str, Any] | None = None, error: BaseException | None = None,
                    extra: dict[str, Any] | None = None, source_root: str = "") -> dict[str, Any]:
    """모아서 봉인해 보관하고 통보한다. **어떤 경우에도 예외를 내보내지 않는다.**

    돌려주는 값은 테스트·로그용 요약이다(운영 응답에는 쓰지 않는다).
    """
    key = public_key()
    if key is None:
        return {"enabled": False, "reason": "no_key"}
    if not throttle_ok(uid):
        return {"enabled": True, "reason": "throttled"}
    try:
        report = collect(trigger, uid=uid, ledger=ledger, verification=verification,
                         error=error, extra=extra, source_root=source_root)
        plain = json.dumps(report, ensure_ascii=False, separators=(",", ":")).encode()
        blob = seal(plain, key)
        meta = {
            "archive_id": report["archive_id"],
            "created_at": report["created_at"],
            "expire_at": report["created_at"] + _int_env("EVIDENCE_TTL_DAYS", 90) * 86400,
            "trigger": trigger,
            "key_id": key_id_hex(),
            "commit": report["runtime"].get("deploy_commit", ""),
            "ledger": report.get("ledger", []),
            "verification": report.get("verification", {}),
            "truncated": report.get("truncated", {}),
            "plain_bytes": len(plain),
        }
        document = store(blob, meta)
        notified = notify(document)
        LOGGER.warning("탈퇴 실패 증거를 봉인했습니다(archive_id=%s, trigger=%s)",
                       document["archive_id"], trigger)
        return {"enabled": True, "archive_id": document["archive_id"], "size": document["size"],
                "chunks": document["chunks"], "notified": notified}
    except Exception:  # noqa: BLE001 — 봉인이 탈퇴 실패를 악화시키면 안 된다
        LOGGER.warning("탈퇴 실패 증거 봉인에 실패했습니다(원인은 로그 참조)", exc_info=True)
        return {"enabled": True, "reason": "failed"}
