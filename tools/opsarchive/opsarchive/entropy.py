"""무작위 값 생성 — 운영체제별 CSPRNG 명령을 감지해 실행하고, 실패하면 파이썬 `secrets` 로 폴백한다.

왜 OS 명령을 쓰는가(요구사항): 관리자가 쓰는 도구는 OS 표준 수단과 같은 값을 내야 신뢰가 생긴다.
- Linux/macOS: `openssl rand -hex 32` (없으면 `/dev/urandom` 파이프)
- Windows: PowerShell 의 `RandomNumberGenerator`(.NET CSPRNG)

원칙
- **명령어는 사용자가 편집할 수 있다**(요구사항). 그래서 명령은 셸에서 그대로 실행되며, 우리는
  그 사실을 화면에 알린다. 대신 명령 자체에는 비밀이 들어가지 않는다(값을 *만드는* 명령이다).
- 출력은 화이트리스트(16진수/base64/영숫자)로 좁히고 길이를 검사한다 — 명령이 (오타·프롬프트·경고
  같은) 다른 것을 뱉으면 값을 쓰지 않고 폴백한다.
- 실패해도 **침묵하지 않는다**: 어떤 출처(명령 vs 폴백)로 만들었는지와 이유를 함께 돌려준다.
"""

from __future__ import annotations

import os
import re
import secrets
import shutil
import subprocess
import sys
from typing import Any

TIMEOUT = 20
ALPHABETS = {
    "hex": re.compile(r"^[0-9a-fA-F]+$"),
    "base64": re.compile(r"^[A-Za-z0-9+/=_-]+$"),
    "chars": re.compile(r"^[A-Za-z0-9!@#$%^&*()_+\-=\[\]{};:?><,./~]+$"),
}


class EntropyError(Exception):
    """code: bad_encoding | empty | bad_chars"""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def os_kind() -> str:
    if os.name == "nt":
        return "windows"
    name = (sys.platform or "").lower()
    if name.startswith("darwin"):
        return "macos"
    if name.startswith("linux"):
        return "linux"
    return "other"


def default_command(*, length: int = 32, encoding: str = "hex", kind: str = "") -> str:
    """이 OS 에서 쓸 기본 명령어(사용자가 화면에서 고칠 수 있다)."""
    kind = kind or os_kind()
    if kind == "windows":
        size = max(8, length)
        if encoding == "base64":
            return ("$b = New-Object Byte[] %d; "
                    "[System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); "
                    "[System.Convert]::ToBase64String($b)" % size)
        return ("$b = New-Object Byte[] %d; "
                "[System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); "
                "[System.BitConverter]::ToString($b) -replace '-'" % size)
    if encoding == "chars":
        return "tr -dc 'A-Za-z0-9' < /dev/urandom | head -c %d" % max(8, length)
    if shutil.which("openssl"):
        return "openssl rand -%s %d" % ("base64" if encoding == "base64" else "hex", max(8, length))
    return "tr -dc 'A-Fa-f0-9' < /dev/urandom | head -c %d" % max(16, length * 2)


def shell_argv(command: str) -> list[str]:
    """셸 기능(파이프·리다이렉션)을 쓰는 명령을 안전하게 띄운다(shell=True 대신 셸을 명시)."""
    if os.name == "nt":
        return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c",
                # PowerShell 코드를 cmd 로 넘기면 따옴표가 깨진다 → powershell 을 명시적으로 경유
                "powershell", "-NoProfile", "-NonInteractive", "-Command", command]
    return ["/bin/sh", "-c", command]


def sanitize(raw: str, encoding: str) -> str:
    """출력에서 값 하나만 뽑는다(프롬프트·경고·공백 제거 + 화이트리스트 검사)."""
    pattern = ALPHABETS.get(encoding)
    if pattern is None:
        raise EntropyError("bad_encoding")
    candidates = []
    for line in (raw or "").splitlines():
        text = line.strip().strip('"').strip("'")
        if not text:
            continue
        # PowerShell 이 빈 줄·머리말을 섞어도 값 줄만 취한다.
        for token in re.split(r"\s+", text):
            if pattern.match(token):
                candidates.append(token)
    if not candidates:
        raise EntropyError("empty")
    best = max(candidates, key=len)
    if len(best) < 8:
        raise EntropyError("bad_chars")
    return best


def run_command(command: str, *, encoding: str = "hex", timeout: int = TIMEOUT) -> str:
    """명령을 실행해 값을 하나 돌려준다. 실패는 EntropyError 로만 알린다(stderr 는 값에 담지 않는다)."""
    if not (command or "").strip():
        raise EntropyError("empty")
    try:
        done = subprocess.run(shell_argv(command), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout)  # noqa: S603
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        raise EntropyError("empty") from exc
    if done.returncode != 0:
        raise EntropyError("empty")
    return sanitize(done.stdout or "", encoding)


def generate(*, length: int = 32, encoding: str = "hex", command: str | None = None,
             kind: str = "", allow_fallback: bool = True) -> dict[str, Any]:
    """값을 만든다. `command` 를 주면 그 명령을, 없으면 OS 기본 명령을 쓴다.

    돌려주는 값: {"value", "source": "command"|"fallback", "command", "os", "note"}
    """
    kind = kind or os_kind()
    used = command if command is not None else default_command(length=length, encoding=encoding, kind=kind)
    note = ""
    if (used or "").strip():
        try:
            value = run_command(used, encoding=encoding)
            return {"value": value, "source": "command", "command": used, "os": kind, "note": ""}
        except EntropyError as exc:
            note = "명령 실패(%s) — 파이썬 secrets 로 대체" % exc.code
            if not allow_fallback:
                raise
    else:
        note = "명령이 비어 있어 파이썬 secrets 로 생성"
    value = (secrets.token_urlsafe(length)[:length] if encoding == "base64"
             else secrets.token_hex(length))
    return {"value": value, "source": "fallback", "command": used, "os": kind, "note": note}
