"""Gemini 호출 공통부.

두 가지를 보장한다.

1. 모델을 코드에 고정하지 않는다.
   호출할 때마다 `models.list()` 로 지금 쓸 수 있는 모델 목록을 받아(짧게 캐시) 고른다.
   모델이 폐기되거나 별칭이 바뀌어도 코드를 고치지 않아도 된다.

2. AI API 호출 하나당 **최소 MIN_ATTEMPTS(30)회** 시도한다.
   - 30회 전에는 어떤 오류로도 포기하지 않는다 (오류 종류로 조기 중단하지 않음).
   - 환경변수 AI_MIN_ATTEMPTS 로 늘릴 수만 있고 30 미만으로 줄일 수 없다.
   - 전체 제한 시간(deadline)을 두지 않는다. 시간 제한이 시도 횟수를 깎으면 '최소'가 깨진다.
   - SDK 자체 재시도는 끈다(attempts=1). 그래야 시도 횟수 = 실제 API 요청 수다.
   - 성공하면 그 자리에서 멈춘다. '최소'는 실패를 확정하기 전까지의 하한이다.
   - 시도마다 모델 목록을 순서대로 돌아가며 쓴다. 한 모델의 장애·할당량 초과를 다른 모델로 흡수한다.
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Generic, TypeVar

T = TypeVar("T")

MIN_ATTEMPTS = 30

# 생성(generateContent)을 지원해도 이 서비스의 텍스트·오디오 입력 + JSON 출력에 맞지 않는 모델
_EXCLUDE = ("embedding", "aqa", "imagen", "veo", "tts", "image", "live", "native-audio", "gemma")

_sleep: Callable[[float], None] = time.sleep          # 테스트에서 바꿔 끼운다
_client_factory: Callable[[], Any] | None = None      # 테스트에서 가짜 클라이언트를 넣는다

_models_lock = threading.Lock()
_models_cache: tuple[float, list[str]] | None = None


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, "") or default)
    except ValueError:
        return default


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, "") or default)
    except ValueError:
        return default


def min_attempts() -> int:
    """하한 30. 환경변수가 더 작거나 잘못된 값이면 무시한다."""
    return max(MIN_ATTEMPTS, _env_int("AI_MIN_ATTEMPTS", MIN_ATTEMPTS))


def backoff(attempt: int) -> float:
    """attempt 번째 실패 뒤 대기 시간(초). 0.5, 1, 2, 4, 4, ... (상한 AI_BACKOFF_MAX)"""
    base = max(0.0, _env_float("AI_BACKOFF_BASE", 0.5))
    cap = max(0.0, _env_float("AI_BACKOFF_MAX", 4.0))
    return min(cap, base * (2 ** min(attempt - 1, 16)))


class AttemptsExhausted(RuntimeError):
    """최소 시도 횟수를 모두 채운 뒤에도 성공하지 못함."""

    def __init__(self, what: str, attempts: int, errors: list[str]) -> None:
        self.what = what
        self.attempts = attempts
        self.last_error = errors[-1] if errors else ""
        super().__init__(f"{what}: {attempts}회 시도 후 실패 — {self.last_error}")


def retry(what: str, fn: Callable[[int], T]) -> tuple[T, int]:
    """fn(attempt) 를 성공할 때까지 부른다. 실패 확정은 min_attempts() 회를 채운 뒤에만 한다.

    반환: (결과, 실제 시도 횟수)
    """
    floor = min_attempts()
    errors: list[str] = []
    attempt = 0
    while True:
        attempt += 1
        try:
            return fn(attempt), attempt
        except Exception as exc:  # noqa: BLE001 — 어떤 오류든 하한 전에는 포기하지 않는다
            errors.append(f"#{attempt} {type(exc).__name__}: {exc}")
            del errors[:-3]
        if attempt >= floor:
            raise AttemptsExhausted(what, attempt, errors)
        _sleep(backoff(attempt))


def make_client() -> Any:
    if _client_factory is not None:
        return _client_factory()
    from google import genai
    from google.genai import types

    timeout_ms = int(max(1.0, _env_float("AI_CALL_TIMEOUT", 60.0)) * 1000)
    return genai.Client(
        api_key=os.environ["GEMINI_API_KEY"],
        http_options=types.HttpOptions(
            timeout=timeout_ms,
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )


def _version_key(name: str) -> tuple[float, ...]:
    """'gemini-2.5-flash' → (-2.0, -5.0). 새 버전이 앞에 오도록 음수."""
    rest = name.split("gemini-", 1)[-1]
    nums: list[float] = []
    for part in rest.split("-")[0].split("."):
        if not part.isdigit():
            break
        nums.append(-float(part))
    return tuple(nums)


def rank(name: str) -> tuple[Any, ...]:
    """안정 버전 → flash → flash-lite → pro 순, 같은 계열은 -latest 별칭과 최신 버전 우선."""
    n = name.lower()
    unstable = any(t in n for t in ("preview", "exp"))
    if "flash-lite" in n:
        family = 1
    elif "flash" in n:
        family = 0
    elif "pro" in n:
        family = 2
    else:
        family = 3
    latest = 0 if n.endswith("-latest") else 1
    return (unstable, family, latest, _version_key(n), n)


def pick_models(raw: list[Any]) -> list[str]:
    """models.list() 결과에서 이 서비스가 쓸 수 있는 모델만 골라 우선순위대로 정렬한다."""
    names: list[str] = []
    for m in raw:
        name = (getattr(m, "name", "") or "").removeprefix("models/")
        actions = getattr(m, "supported_actions", None)
        if not name.startswith("gemini"):
            continue
        if actions is not None and "generateContent" not in actions:
            continue
        if any(x in name.lower() for x in _EXCLUDE):
            continue
        if name not in names:
            names.append(name)
    names.sort(key=rank)

    # GEMINI_MODEL 은 '고정'이 아니라 '우선 선호'다. 목록에 있을 때만 맨 앞으로 올린다.
    preferred = (os.getenv("GEMINI_MODEL") or "").strip().removeprefix("models/")
    if preferred in names:
        names.remove(preferred)
        names.insert(0, preferred)
    return names


def available_models(client: Any | None = None, *, refresh: bool = False) -> list[str]:
    """지금 쓸 수 있는 모델 목록. AI_MODELS_TTL(기본 600초) 동안 캐시한다.

    목록 조회도 AI API 호출이므로 최소 시도 규칙을 똑같이 따른다.
    빈 목록은 실패로 보고 다시 조회한다(고정 모델로 대체하지 않는다).
    """
    global _models_cache
    ttl = max(0.0, _env_float("AI_MODELS_TTL", 600.0))
    with _models_lock:
        if not refresh and _models_cache and time.time() - _models_cache[0] < ttl:
            return list(_models_cache[1])

    c = client or make_client()

    def once(_attempt: int) -> list[str]:
        names = pick_models(list(c.models.list()))
        if not names:
            raise RuntimeError("사용 가능한 Gemini 생성 모델이 목록에 없습니다")
        return names

    names, _ = retry("models.list", once)
    with _models_lock:
        _models_cache = (time.time(), names)
    return list(names)


def cached_models() -> list[str] | None:
    """/health 용. API 를 부르지 않고 마지막으로 받은 목록만 보여준다."""
    with _models_lock:
        return list(_models_cache[1]) if _models_cache else None


def reset_cache() -> None:
    global _models_cache
    with _models_lock:
        _models_cache = None


@dataclass
class Result(Generic[T]):
    value: T
    attempts: int
    model: str


def run(what: str, fn: Callable[[Any, str, int], T]) -> Result[T]:
    """fn(client, model, attempt) 를 최소 시도 규칙으로 실행한다. 시도마다 모델을 돌아가며 쓴다."""
    client = make_client()
    models = available_models(client)
    used: dict[str, str] = {}

    def once(attempt: int) -> T:
        model = models[(attempt - 1) % len(models)]
        used["model"] = model
        return fn(client, model, attempt)

    value, attempts = retry(what, once)
    return Result(value=value, attempts=attempts, model=used["model"])


def generate_text(client: Any, model: str, contents: Any, **config: Any) -> str:
    """generate_content 1회 = API 요청 1회. 재시도는 run()/retry() 가 맡는다."""
    from google.genai import types

    resp = client.models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(response_mime_type="application/json", **config),
    )
    text = resp.text or ""
    if not text.strip():
        raise ValueError("빈 응답")
    return text
