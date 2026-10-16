"""설정 로딩 — `.env`(비밀)과 `settings.json`(상세 설정). GUI·CLI 가 같은 것을 읽는다.

왜 직접 파싱하는가
- `python-dotenv` 를 쓰지 않는다: Windows 에서 이 저장소는 이미 `pip install -r` 인코딩 문제를
  겪었다(requirements.txt 가 cp949 로 읽힘). 의존성을 늘리지 않는 편이 재현이 쉽다.
- 비밀은 `.env` 에만, 나머지 상세 설정은 `settings.json` 에만 둔다(역할 분리).

값은 **환경변수로만** 흘려보낸다: 이미 설정된 환경변수를 덮어쓰지 않는다(명시적 지정이 우선).
"""

from __future__ import annotations

import json
import os
from typing import Any

ENV_NAME = ".env"
SETTINGS_NAME = "settings.json"

DEFAULTS: dict[str, Any] = {
    # 실제 Render 서비스 이름은 밑줄이다(`codyssey_final`). 앱 호스트(하이픈)와 다르니 주의.
    "service": "codyssey_final",
    "base_url": "https://codyssey-final.onrender.com",
    "project_id": "com-example-myapplicatio-3bb36",
    "sa_path": "",
    "env_key": "EVIDENCE_PUBKEY",
    "generation": 1,
    "key_dir": "",
    # 핀 파일은 저장소 안(관리자가 커밋해 이력을 남긴다) — read_settings 가 절대 경로로 채운다.
    "checkpoints_dir": "",
    "pin_path": "",
    "tsa_url": "https://freetsa.org/tsr",
}


def tool_dir() -> str:
    """이 패키지의 상위 폴더(= tools/opsarchive)."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def repo_root() -> str:
    """저장소 루트(= tools/opsarchive 의 두 단계 위)."""
    return os.path.dirname(os.path.dirname(tool_dir()))


def resolve(path: str) -> str:
    """상대 경로는 **저장소 루트** 기준으로 푼다.

    GUI 의 작업 폴더가 `tools/opsarchive` 라서 `security/evidence-key-pin.json` 같은 상대 경로가
    엉뚱한 곳을 가리켰다(FileNotFoundError). 경로 해석을 한 곳에 모아 그 실수를 없앤다.
    """
    if not path:
        return path
    if os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(repo_root(), path))


def config_dir() -> str:
    """사용자 설정·키가 사는 곳(저장소 밖)."""
    return os.path.join(os.path.expanduser("~"), ".opsarchive")


def env_path() -> str:
    """`.env` 위치: 저장소 안 `tools/opsarchive/.env` 우선, 없으면 `~/.opsarchive/.env`."""
    local = os.path.join(tool_dir(), ENV_NAME)
    return local if os.path.exists(local) else os.path.join(config_dir(), ENV_NAME)


def settings_path() -> str:
    return os.path.join(config_dir(), SETTINGS_NAME)


def parse_env(text: str) -> dict[str, str]:
    """아주 작은 .env 파서 — `KEY=값`, `#` 주석, 따옴표, `export ` 접두 허용."""
    out: dict[str, str] = {}
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            out[key] = value
    return out


def load_env(path: str | None = None, *, into: dict[str, str] | None = None,
             override: bool = False) -> dict[str, str]:
    """`.env` 를 읽어 환경변수로 넣는다(기본은 기존 값 우선). 넣은 값들을 돌려준다."""
    target = into if into is not None else os.environ
    path = path or env_path()
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            values = parse_env(fh.read())
    except OSError:
        return {}
    for key, value in values.items():
        if override or not target.get(key):
            target[key] = value
    return values


def save_env(values: dict[str, str], path: str | None = None) -> str:
    """`.env` 를 쓴다(0600 은 최선노력 — Windows 는 icacls 를 따로 쓴다)."""
    path = path or env_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lines = ["# opsarchive 비밀 값 — 커밋하지 마라(저장소에는 .gitignore 로 막혀 있다)",
             "# Render API 키는 대시보드에서만 발급된다(Account Settings > API Keys)."]
    for key, value in sorted(values.items()):
        if str(value or "").strip():
            lines.append("%s=%s" % (key, value))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


def read_settings(path: str | None = None) -> dict[str, Any]:
    """settings.json + 기본값 병합. 없으면 기본값만."""
    data = dict(DEFAULTS)
    try:
        with open(path or settings_path(), "r", encoding="utf-8-sig") as fh:
            got = json.load(fh)
        if isinstance(got, dict):
            data.update({k: v for k, v in got.items() if v not in (None, "")})
    except (OSError, json.JSONDecodeError):
        pass
    if not data.get("sa_path"):
        data["sa_path"] = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
    if not data.get("key_dir"):
        data["key_dir"] = config_dir()
    if not data.get("pin_path"):
        # 핀은 **저장소 밖**에 둔다. 공개키·공개 지문이라도 공개 저장소에는 올리지 않는다.
        # CI 는 GitHub Actions 변수(`vars.EVIDENCE_PIN_*`)를 읽는다 — `opsarchive pin-publish` 로 올린다.
        data["pin_path"] = os.path.join(config_dir(), "evidence-key-pin.json")
    # 이전 판은 핀을 저장소 안(security/)에 두었다. 그 경로가 settings.json 에 남아 있으면 밖으로 옮긴다.
    # 비교는 normcase(Windows 대소문자 무시)로 한다 — 소문자 경로로 다시 저장소 안을 가리키는 우회를 막는다.
    pin_abs = os.path.normcase(os.path.abspath(str(data["pin_path"])))
    repo_abs = os.path.normcase(os.path.abspath(repo_root())) + os.sep
    if pin_abs.startswith(repo_abs):
        data["pin_path"] = os.path.join(config_dir(), "evidence-key-pin.json")
    if not data.get("checkpoints_dir"):
        # 체크포인트는 관리자 자산이라 저장소 밖에 둔다(저장소 사본은 편의·감사용).
        data["checkpoints_dir"] = os.path.join(config_dir(), "checkpoints")
    return data


def write_settings(data: dict[str, Any], path: str | None = None) -> str:
    path = path or settings_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    merged = dict(DEFAULTS)
    merged.update({k: v for k, v in (data or {}).items() if v not in (None, "")})
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(merged, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    return path


def bootstrap() -> dict[str, Any]:
    """CLI/GUI 시작 시 한 번: `.env` 를 환경변수로 올리고 설정을 읽는다."""
    load_env()
    return read_settings()


def key_files() -> dict[str, list[str]]:
    """로컬에 있는 개인키 파일 목록(파일 이름만 — 키 내용은 절대 읽지 않는다)."""
    directory = read_settings().get("key_dir") or config_dir()
    admin, sign, other = [], [], []
    try:
        names = sorted(os.listdir(directory))
    except OSError:
        names = []
    for name in names:
        if name.startswith("admin-") and name.endswith(".key"):
            admin.append(os.path.join(directory, name))
        elif name.startswith("sign-") and name.endswith(".key"):
            sign.append(os.path.join(directory, name))
        elif name.endswith(".key"):
            other.append(os.path.join(directory, name))
    return {"admin": admin, "sign": sign, "other": other, "dir": directory}
