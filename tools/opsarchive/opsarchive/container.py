"""MFA1 증거 봉인 컨테이너 — 앱과 CLI 가 똑같이 구현해야 하는 형식.

이 모듈은 **관리자 CLI 쪽 구현**이다. 앱(`backend/app/evidence.py`)은 같은 형식을
독립적으로 복제 구현한다(런타임 결합을 만들지 않기 위해). 형식이 어긋나면
**앱 훅을 넣을 때** 함께 추가하는 호환 검사(`backend/tests/test_evidence.py`)가 이 모듈의
`unseal` 로 실제로 열어보며 잡는다 — 그 테스트는 아직 없다(앱 훅이 아직 없다).

암호 설계
- 본문: AES-256-GCM (데이터키 32바이트, CSPRNG)
- 데이터키: 관리자 공개키(X25519)로 봉인 → 앱·네트워크에는 **봉인된 키**만 흐른다
- kek = HKDF-SHA256(공유비밀, salt=b"mfa1", info=b"mfa1-kek")
- 헤더 전체(magic|alg|ver|key_id|wrapped_len|wrapped|iv)를 AAD 로 묶어 변조를 감지한다
- 압축은 암호화 **전에** 한다(암호문은 압축이 안 된다)

압축 형식은 gzip 이다. 서로 다른 구현이 같은 파일을 만들어야 할 필요는 없다(한쪽이 쓰고
다른 쪽이 읽기만 하면 된다). 다만 **읽는 쪽이 쓰는 쪽보다 관대**해야 하므로 압축 해제는
`gzip.decompress` 로만 하고, 압축 방식은 헤더에 적지 않는다(alg=1 이 곧 gzip+봉투를 뜻한다).
"""

from __future__ import annotations

import gzip
import hashlib
import os
import struct
import subprocess
import zlib

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC = b"MFA1"
KEY_MAGIC = b"MFAK1"                                   # 5바이트
KEY_SALT_LEN = 16
KEY_PARAMS_LEN = 12                                    # n, r, p (4바이트씩)
KEY_HEAD = len(KEY_MAGIC) + 1 + KEY_SALT_LEN + KEY_PARAMS_LEN + 12   # 12 = AES-GCM nonce
KEY_SALT_AT = len(KEY_MAGIC) + 1                                            # 6
KEY_PARAMS_AT = KEY_SALT_AT + KEY_SALT_LEN                                  # 22
KEY_NONCE_AT = KEY_PARAMS_AT + KEY_PARAMS_LEN                               # 34
ALG = 1                      # X25519 + HKDF-SHA256 + AES-256-GCM + gzip
VERSION = 1
KEY_VERSION = 1
KEY_ID_LEN = 8
NONCE_LEN = 12
HEADER_FIXED = 4 + 1 + 1 + KEY_ID_LEN + 2      # magic|alg|ver|key_id|wrapped_len
HKDF_SALT = b"mfa1"
HKDF_INFO = b"mfa1-kek"
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 15, 8, 1
SCRYPT_MIN_N = 2 ** 14        # 파일에서 읽은 파라미터를 그대로 믿지 않는다(약한 KDF·KDF DoS 방지)
SCRYPT_MAX_N = 2 ** 20
SCRYPT_MAX_R = 16
SCRYPT_MAX_P = 4
MAX_PLAIN = 32 * 1024 * 1024  # 압축 폭탄 방어: 평문 상한(102KB → 100MB 팽창 실측)


class ContainerError(Exception):
    """봉인/해제 실패. 열 수 없는 이유를 값으로 구분한다(부분 평문 노출 금지)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


# ------------------------------------------------------------------ 키

def keypair() -> tuple[bytes, bytes]:
    """(개인키 32바이트, 공개키 32바이트). CSPRNG 는 라이브러리가 OS 엔트로피에서 가져온다."""
    private = X25519PrivateKey.generate()
    return (
        private.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                              serialization.NoEncryption()),
        private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw),
    )


def key_id(public_key: bytes) -> bytes:
    """공개키 지문 앞 8바이트 — 어느 관리자 키로 열어야 하는지 표시한다(비밀 아님)."""
    return hashlib.sha256(public_key).digest()[:KEY_ID_LEN]


def public_from_private(private_key: bytes) -> bytes:
    """개인키에서 공개키를 유도한다(doctor 가 로컬 키로 지문을 대조할 때 쓴다)."""
    private = X25519PrivateKey.from_private_bytes(private_key)
    return private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def pack_public_key(public_key: bytes) -> str:
    """환경변수에 넣는 문자열 표현: `x25519:<base64url(no padding)>`."""
    import base64
    return "x25519:" + base64.urlsafe_b64encode(public_key).decode().rstrip("=")


def unpack_public_key(text: str) -> bytes:
    import base64
    raw = (text or "").strip()
    if raw.startswith("x25519:"):
        raw = raw[len("x25519:"):]
    raw += "=" * (-len(raw) % 4)
    try:
        key = base64.urlsafe_b64decode(raw.encode())
    except Exception as exc:    # noqa: BLE001
        raise ContainerError("bad_public_key") from exc
    if len(key) != 32:
        raise ContainerError("bad_public_key")
    return key


def fingerprint(public_key: bytes) -> str:
    """사람이 비교하는 지문(doctor·/health). 전체 sha256 hex."""
    return hashlib.sha256(public_key).hexdigest()


def _kek(shared: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=HKDF_SALT, info=HKDF_INFO).derive(shared)


def _wrap_nonce(shared: bytes) -> bytes:
    """데이터키를 감쌀 때 쓰는 nonce 를 공유비밀에서 유도한다.

    임시 키쌍을 매번 새로 만들기 때문에 이 KEK 는 메시지마다 다르다 → nonce 를 저장하지 않아도
    재사용이 생기지 않는다(헤더에 12바이트를 더 넣지 않기 위한 선택).
    """
    return HKDF(algorithm=hashes.SHA256(), length=NONCE_LEN, salt=b"mfa1-nonce",
                info=b"mfa1-wrap").derive(shared)


# ------------------------------------------------------------------ 봉인/해제

def seal(data: bytes, public_key: bytes) -> bytes:
    """압축 → 데이터키로 암호화 → 데이터키를 공개키로 봉인. data_key 는 즉시 덮어쓴다."""
    if len(public_key) != 32:
        raise ContainerError("bad_public_key")
    ephemeral = X25519PrivateKey.generate()
    shared = ephemeral.exchange(X25519PublicKey.from_public_bytes(public_key))
    eph_pub = ephemeral.public_key().public_bytes(serialization.Encoding.Raw,
                                                  serialization.PublicFormat.Raw)
    data_key = bytearray(os.urandom(32))
    try:
        wrapped = eph_pub + AESGCM(_kek(shared)).encrypt(_wrap_nonce(shared), bytes(data_key), None)
        iv = os.urandom(NONCE_LEN)
        header = (MAGIC + bytes([ALG, VERSION]) + key_id(public_key)
                  + struct.pack(">H", len(wrapped)) + wrapped + iv)
        body = AESGCM(bytes(data_key)).encrypt(iv, gzip.compress(data), header)
    finally:
        data_key[:] = b"\x00" * len(data_key)
    return header + body


def unseal(blob: bytes, private_key: bytes, max_plain: int = MAX_PLAIN) -> bytes:
    """봉인 해제. 실패는 ContainerError 로만 알린다(부분 결과를 돌려주지 않는다).

    `max_plain` 은 **압축 폭탄 방어**다 — gzip 은 100KB 를 100MB 로 부풀릴 수 있으므로
    상한을 넘으면 `too_large` 로 끊는다.
    """
    if len(blob) < HEADER_FIXED + NONCE_LEN + 16:
        raise ContainerError("too_short")
    if blob[:4] != MAGIC:
        raise ContainerError("bad_magic")
    alg, ver = blob[4], blob[5]
    if alg != ALG or ver != VERSION:
        raise ContainerError("unsupported")
    wrapped_len = struct.unpack(">H", blob[14:16])[0]
    end = HEADER_FIXED + wrapped_len
    if end + NONCE_LEN + 16 > len(blob):
        raise ContainerError("too_short")
    header = blob[:end + NONCE_LEN]
    wrapped = blob[HEADER_FIXED:end]
    if len(wrapped) < 32 + 16:
        raise ContainerError("bad_wrapped_key")
    eph_pub, sealed = wrapped[:32], wrapped[32:]
    try:
        private = X25519PrivateKey.from_private_bytes(private_key)
        shared = private.exchange(X25519PublicKey.from_public_bytes(eph_pub))
        data_key = bytearray(AESGCM(_kek(shared)).decrypt(_wrap_nonce(shared), sealed, None))
    except ContainerError:
        raise
    except Exception as exc:    # noqa: BLE001 — 암호 오류는 값으로만 구분한다
        raise ContainerError("key_mismatch") from exc
    try:
        plain = AESGCM(bytes(data_key)).decrypt(header[-NONCE_LEN:], blob[end + NONCE_LEN:], header)
    except Exception as exc:    # noqa: BLE001 — 인증 실패·변조를 구분해 알린다
        raise ContainerError("corrupt") from exc
    finally:
        data_key[:] = b"\x00" * len(data_key)
    return _inflate(plain, max_plain)


def _inflate(data: bytes, limit: int) -> bytes:
    """gzip 을 **상한을 두고** 푼다(폭탄 방어). 상한을 넘으면 too_large."""
    obj = zlib.decompressobj(16 + zlib.MAX_WBITS)
    try:
        out = obj.decompress(data, limit)
    except zlib.error as exc:
        raise ContainerError("corrupt") from exc
    if obj.unconsumed_tail or not obj.eof:
        raise ContainerError("too_large")
    return out


# ------------------------------------------------------------------ 개인키 파일

def _check_scrypt(n: int, r: int, p: int) -> None:
    """파일에서 읽은 KDF 파라미터를 검사한다.

    그대로 믿으면 공격자가 만든 키 파일이 (a) n=2 로 사실상 무잠금이 되거나
    (b) n=2³²-1 로 KDF 비용을 폭발시켜 열람을 막을 수 있다(실측 3초/회).
    """
    if n < SCRYPT_MIN_N or n > SCRYPT_MAX_N or (n & (n - 1)):
        raise ContainerError("weak_kdf")
    if not 1 <= r <= SCRYPT_MAX_R or not 1 <= p <= SCRYPT_MAX_P:
        raise ContainerError("weak_kdf")


def _restrict_to_owner(path: str) -> bool:
    """파일을 소유자만 읽을 수 있게 좁힌다(가능하면 True).

    POSIX 는 `os.open(..., 0o600)` 으로 끝나지만 **Windows 에서 mode 는 ACL 을 바꾸지 않는다**
    (실측 0o666 — 상속된 Users/Everyone 이 그대로 남는다). 그래서 Windows 에서는 icacls 로
    상속을 끊고 현재 사용자만 남긴다. 실패해도 저장은 끝난 것으로 보고 결과만 알린다.
    """
    if os.name != "nt":
        try:
            os.chmod(path, 0o600)
        except OSError:
            return False
        return True
    user = os.environ.get("USERNAME", "")
    if not user:
        return False
    try:
        done = subprocess.run(["icacls", path, "/inheritance:r", "/grant:r", user + ":F"],
                              capture_output=True, timeout=20, shell=False)  # noqa: S603
        return done.returncode == 0
    except Exception:               # noqa: BLE001 — 권한 강화 실패가 저장 자체를 막지는 않는다
        return False


def save_private_key(path: str, private_key: bytes, passphrase: str, *, overwrite: bool = False,
                     n: int = SCRYPT_N, r: int = SCRYPT_R, p: int = SCRYPT_P) -> bool:
    """개인키를 패스프레이즈로 잠가 저장한다(소유자 전용 권한).

    돌려주는 값은 '권한을 소유자 전용으로 좁혔는가'다 — Windows 에서 icacls 가 실패하면 False.
    """
    _check_scrypt(n, r, p)
    if os.path.exists(path) and not overwrite:
        raise ContainerError("exists")
    salt = os.urandom(KEY_SALT_LEN)
    nonce = os.urandom(NONCE_LEN)
    key = Scrypt(salt=salt, length=32, n=n, r=r, p=p).derive(passphrase.encode())
    header = KEY_MAGIC + bytes([KEY_VERSION]) + salt + struct.pack(">III", n, r, p) + nonce
    blob = header + AESGCM(key).encrypt(nonce, private_key, header)
    tmp = path + ".tmp"
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | (getattr(os, "O_BINARY", 0))
        fd = os.open(tmp, flags, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(blob)
        os.replace(tmp, path)          # 같은 디렉터리 → 원자적 교체
    except Exception:
        try:
            os.remove(tmp)             # 실패하면 잠긴 키의 임시 사본을 남기지 않는다
        except OSError:
            pass
        raise
    return _restrict_to_owner(path)


def load_private_key(path: str, passphrase: str) -> bytes:
    """잠긴 개인키를 연다. 패스프레이즈가 틀리면 key_mismatch, KDF 파라미터가 이상하면 weak_kdf."""
    with open(path, "rb") as fh:
        blob = fh.read()
    if len(blob) < KEY_HEAD + 16 or blob[:len(KEY_MAGIC) + 1] != KEY_MAGIC + bytes([KEY_VERSION]):
        raise ContainerError("bad_key_file")
    salt = blob[KEY_SALT_AT:KEY_PARAMS_AT]
    n, r, p = struct.unpack(">III", blob[KEY_PARAMS_AT:KEY_NONCE_AT])
    _check_scrypt(n, r, p)
    nonce = blob[KEY_NONCE_AT:KEY_HEAD]
    header = blob[:KEY_HEAD]
    try:
        key = Scrypt(salt=salt, length=32, n=n, r=r, p=p).derive(passphrase.encode())
        return AESGCM(key).decrypt(nonce, blob[KEY_HEAD:], header)
    except Exception as exc:    # noqa: BLE001 — 패스프레이즈 오류·손상을 구분해 알린다
        raise ContainerError("key_mismatch") from exc
