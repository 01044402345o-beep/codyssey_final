"""Cloud KMS 서명기 — 체크포인트(앵커)를 **KMS 안의 Ed25519 키**로 서명한다.

왜: 자동 앵커(CI cron)는 사람이 패스프레이즈를 칠 수 없다. 개인키 파일을 CI 비밀로 넣으면
저장소·CI 를 장악한 공격자가 그 키를 가져간다. KMS 키는 **밖으로 나오지 않고**, 서명 호출만
IAM(`roles/cloudkms.signer`)으로 허락된다 — 침해되면 '서명 호출'은 될 수 있어도 키 자체는 남지 않는다.

- 알고리즘은 `EC_SIGN_ED25519`(PureEdDSA)만 받는다 — 관리자 로컬 서명 키와 같은 Ed25519 라서
  검증 코드(`container.verify_signature`)를 그대로 쓴다. 다른 알고리즘 키는 거절한다.
- 서명 요청은 다이제스트가 아니라 **원문(data)** 을 보낸다(PureEdDSA). 무결성: 요청에 CRC32C 를 붙이고
  응답의 `verifiedDataCrc32c`·`signatureCrc32c` 를 확인한 뒤, **받은 서명을 공개키로 다시 검증**한다.
- 신뢰 뿌리는 여전히 **핀**이다. KMS 에서 받은 공개키를 그대로 믿지 않는다 — 관리자가 `kms-pin-add` 로
  핀에 넣은 공개키만 검증에 쓴다.
- 토큰: 서비스 계정 JSON(로컬) 또는 CI 의 Workload Identity Federation 으로 받은 단기 토큰(`gcp.token`).

한계(숨기지 않는다): KMS 는 **누가 서명을 요청했는지**를 막지 못한다. signer 권한을 가진 주체가
침해되면 그 주체는 그럴듯한 체크포인트를 서명할 수 있다. 그래서 자동 키는 핀에서 역할을 'auto' 로
구분하고, verify-chain 이 어느 키가 서명했는지 보고한다. 관리자 로컬 키 체크포인트가 상위 근거다.
"""

from __future__ import annotations

import base64
import json
import re
import urllib.error
import urllib.request

from . import container as C
from . import gcp

KMS_API = "https://cloudkms.googleapis.com/v1"
KMS_SCOPE = "https://www.googleapis.com/auth/cloudkms"
ALGORITHM = "EC_SIGN_ED25519"
TIMEOUT = 20
_NAME = re.compile(r"^projects/[a-z][a-z0-9-]{4,61}[a-z0-9]/locations/[a-z0-9-]{2,40}/keyRings/[A-Za-z0-9_-]{1,63}"
                   r"/cryptoKeys/[A-Za-z0-9_-]{1,63}/cryptoKeyVersions/[0-9]{1,10}$")


class KmsError(Exception):
    """code: bad_key_name | wrong_algorithm | forbidden | not_found | http_error | crc_mismatch | bad_signature | bad_response"""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def check_name(name: str) -> str:
    if not isinstance(name, str) or not _NAME.fullmatch(name.strip()):
        raise KmsError("bad_key_name")
    return name.strip()


# ------------------------------------------------------------------ CRC32C (Castagnoli) — 추가 의존성 없이
def _table() -> list[int]:
    out = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = (c >> 1) ^ 0x82F63B78 if c & 1 else c >> 1
        out.append(c)
    return out


_CRC = _table()


def crc32c(data: bytes) -> int:
    c = 0xFFFFFFFF
    for b in data:
        c = _CRC[(c ^ b) & 0xFF] ^ (c >> 8)
    return c ^ 0xFFFFFFFF


# ------------------------------------------------------------------ 호출
def _call(method: str, url: str, access_token: str, body=None, opener=None) -> dict:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", "Bearer " + access_token)
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with (opener or urllib.request.urlopen)(req, timeout=TIMEOUT) as res:
            raw = res.read()
    except urllib.error.HTTPError as exc:
        raise KmsError({401: "forbidden", 403: "forbidden", 404: "not_found"}.get(exc.code, "http_error")) from exc
    except Exception as exc:            # noqa: BLE001 — 토큰을 메시지에 담지 않는다
        raise KmsError("http_error") from exc
    try:
        parsed = json.loads(raw or b"{}")
    except json.JSONDecodeError as exc:
        raise KmsError("bad_response") from exc
    return parsed if isinstance(parsed, dict) else {}


class Signer:
    """KMS 키 버전 하나로 서명한다. `public()` 은 Raw 32바이트 Ed25519 공개키."""

    def __init__(self, key_name: str, *, sa_path: str = "", access_token: str = "", token_fn=None,
                 opener=None) -> None:
        self.name = check_name(key_name)
        self._sa = sa_path
        self._token = access_token
        self._token_fn = token_fn or gcp.token
        self._opener = opener
        self._public = b""

    def _access(self) -> str:
        if not self._token:
            self._token = self._token_fn(self._sa, KMS_SCOPE)
        return self._token

    def public(self) -> bytes:
        if self._public:
            return self._public
        data = _call("GET", "%s/%s/publicKey" % (KMS_API, self.name), self._access(), opener=self._opener)
        if data.get("algorithm") != ALGORITHM:
            raise KmsError("wrong_algorithm")
        pem = str(data.get("pem", ""))
        if "pemCrc32c" in data and int(data["pemCrc32c"]) != crc32c(pem.encode()):
            raise KmsError("crc_mismatch")
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        try:
            key = serialization.load_pem_public_key(pem.encode())
        except Exception as exc:        # noqa: BLE001
            raise KmsError("bad_response") from exc
        if not isinstance(key, Ed25519PublicKey):
            raise KmsError("wrong_algorithm")
        self._public = key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        return self._public

    def sign(self, message: bytes) -> bytes:
        body = {"data": base64.b64encode(message).decode(), "dataCrc32c": str(crc32c(message))}
        data = _call("POST", "%s/%s:asymmetricSign" % (KMS_API, self.name), self._access(), body, opener=self._opener)
        if data.get("name") != self.name or data.get("verifiedDataCrc32c") is not True:
            raise KmsError("crc_mismatch")      # 요청이 손상됐거나 다른 키가 서명했다
        try:
            signature = base64.b64decode(str(data.get("signature", "")), validate=True)
        except ValueError as exc:
            raise KmsError("bad_response") from exc
        if "signatureCrc32c" in data and int(data["signatureCrc32c"]) != crc32c(signature):
            raise KmsError("crc_mismatch")
        if not C.verify_signature(self.public(), message, signature):
            raise KmsError("bad_signature")     # 받은 서명을 공개키로 다시 검증한다
        return signature
