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

3. 모델 상태를 기억한다 (프로세스 메모리).
   - 마지막으로 성공한 모델을 다음 요청에서 먼저 쓴다.
   - 404(제공 중단)·429(할당량)·5xx(과부하) 로 실패한 모델은 일정 시간 순서의 뒤로 미룬다.
   - 미루는 것이지 빼는 것이 아니다. 모든 모델이 미뤄져 있어도 30회는 그대로 시도한다.

4. API 키를 여러 개 둘 수 있다 — 주 키가 막히면 예비 키로 넘어가고, 주 키가 풀리면 되돌아온다(롤백).
   - GEMINI_API_KEY(주 키) + GEMINI_API_KEY_FALLBACK(예비 키, 쉼표로 여러 개). 예비 키가 없으면 지금과 같다.
   - 키 탓인 실패만 키를 미룬다: 401, 400·403 중 'API key' 문구(무효·만료·유출 차단), 429(할당량).
     키 거부는 모델 탓이 아니므로 모델 쿨다운에 넣지 않는다(잘못된 키 하나가 모든 모델을 6시간 미루지 않게).
   - 호출마다 '쿨다운이 아닌 키 중 가장 앞 번호'를 쓴다. 그래서 주 키의 쿨다운이 끝나면 다음 호출부터 자동으로 주 키로 돌아온다.
     모든 키가 쿨다운이면 가장 먼저 풀리는 키를 쓴다(30회 규칙은 그대로).
   - 키 값은 로그·/health 어디에도 남기지 않는다. '주 키'·'예비 키 1' 같은 번호만 쓴다.
   - 주의: 예비 키도 주 키와 **같은 등급(유료/무료)·같은 약관**이어야 한다. 무료 등급 키로 넘어가면 보낸 내용이
     제품 개선에 쓰일 수 있다(docs/product/privacy-policy-draft.md 3절).
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Generic, TypeVar

T = TypeVar("T")

log = logging.getLogger("app.gemini")

MIN_ATTEMPTS = 30

# 생성(generateContent)을 지원해도 이 서비스의 텍스트·오디오 입력 + JSON 출력에 맞지 않는 모델
# (임베딩·이미지·영상·음성 합성/받아쓰기 전용·실시간·로봇·컴퓨터 조작·도구 전용·Gemma)
_EXCLUDE = (
    "embedding", "aqa", "imagen", "veo", "tts", "image", "banana", "live", "native-audio",
    "transcribe", "robotics", "computer-use", "customtools", "gemma",
)

ERROR_MAX_CHARS = 300   # 응답·로그에 남기는 오류 문구 길이 (API 오류 본문이 길다)

_sleep: Callable[[float], None] = time.sleep          # 테스트에서 바꿔 끼운다
_client_factory: Callable[[], Any] | None = None      # 테스트에서 가짜 클라이언트를 넣는다(키 회전 없이)
_key_client_factory: Callable[[str], Any] | None = None   # 테스트: 키 → 가짜 클라이언트(키 회전 포함)

_models_lock = threading.Lock()
_models_cache: tuple[float, list[str]] | None = None

# 모델 상태: 마지막 성공 모델 + 실패로 뒤로 미룬 모델 {이름: (해제 시각, 사유)}
_state_lock = threading.Lock()
# 마지막 성공 모델은 모델 묶음(pool)별로 기억한다 — Gemini 와 STT 공급자가 서로 덮어쓰지 않게.
# STT 모델은 "groq:whisper-large-v3" 처럼 공급자를 붙인 이름으로 다뤄 쿨다운도 섞이지 않는다.
_last_good: dict[str, str] = {}
_cooldown: dict[str, tuple[float, str]] = {}
# 키 상태: 번호(0 = 주 키) → (해제 시각, 사유). 키 값이 아니라 번호로만 기억한다.
_key_cooldown: dict[int, tuple[float, str]] = {}
_key_active: int | None = None   # 마지막으로 쓴 키 번호(전환·롤백 로그용)


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


def failure(attempt: int, exc: BaseException, model: str | None = None) -> dict[str, Any]:
    """실패한 시도 1건. 응답의 failures[] 와 서버 로그에 같은 내용이 남는다."""
    msg = " ".join(str(exc).split())
    if len(msg) > ERROR_MAX_CHARS:
        msg = msg[:ERROR_MAX_CHARS] + "…"
    return {"attempt": attempt, "model": model, "error": type(exc).__name__, "detail": msg}


class AttemptsExhausted(RuntimeError):
    """최소 시도 횟수를 모두 채운 뒤에도 성공하지 못함."""

    def __init__(self, what: str, attempts: int, failures: list[dict[str, Any]]) -> None:
        self.what = what
        self.attempts = attempts
        self.failures = failures
        last = failures[-1] if failures else None
        self.last_error = f"{last['error']}: {last['detail']}" if last else ""
        super().__init__(f"{what}: {attempts}회 시도 후 실패 — {self.last_error}")


def retry(
    what: str,
    fn: Callable[[int], T],
    model_of: Callable[[int], str | None] = lambda _a: None,
) -> tuple[T, int, list[dict[str, Any]]]:
    """fn(attempt) 를 성공할 때까지 부른다. 실패 확정은 min_attempts() 회를 채운 뒤에만 한다.

    반환: (결과, 실제 시도 횟수, 성공 전 실패 목록)
    실패한 시도는 모두 WARNING 으로 로그에 남긴다 — 성공해도 앞선 실패 원인을 볼 수 있게.
    """
    floor = min_attempts()
    failures: list[dict[str, Any]] = []
    attempt = 0
    while True:
        attempt += 1
        try:
            return fn(attempt), attempt, failures
        except Exception as exc:  # noqa: BLE001 — 어떤 오류든 하한 전에는 포기하지 않는다
            f = failure(attempt, exc, model_of(attempt))
            failures.append(f)
            log.warning("%s 시도 %d/%d 실패 model=%s %s: %s",
                        what, attempt, floor, f["model"], f["error"], f["detail"])
        if attempt >= floor:
            log.error("%s %d회 시도 후 최종 실패", what, attempt)
            raise AttemptsExhausted(what, attempt, failures)
        _sleep(backoff(attempt))


# ---------------------------------------------------------------- API 키: 주 키 → 예비 키, 롤백

def api_keys() -> list[str]:
    """[주 키, 예비 키…]. 빈 값·중복은 뺀다."""
    keys: list[str] = []
    for raw in [os.getenv("GEMINI_API_KEY") or ""] + (os.getenv("GEMINI_API_KEY_FALLBACK") or "").split(","):
        k = raw.strip()
        if k and k not in keys:
            keys.append(k)
    return keys


def key_label(i: int) -> str:
    return "주 키" if i == 0 else f"예비 키 {i}"


_KEY_WORDS = ("api key", "api_key", "apikey")


def is_key_rejection(exc: BaseException) -> bool:
    """키 자체가 거부됨(무효·만료·유출 차단·권한 없음). 모델을 바꿔도 같은 키로는 낫지 않는다."""
    code = getattr(exc, "code", None)
    return code == 401 or (code in (400, 403) and any(w in str(exc).lower() for w in _KEY_WORDS))


def key_cooldown_for(exc: BaseException) -> tuple[float, str] | None:
    """키 탓인 실패면 그 키를 얼마나 미룰지. 그 밖의 실패(과부하·형식·빈 응답)는 None — 키를 바꾸지 않는다."""
    code = getattr(exc, "code", None)
    if is_key_rejection(exc):
        return _env_float("AI_KEY_COOLDOWN_BAD", 3600.0), f"{code} 키 거부"
    if code == 429:
        flat = str(exc).lower().replace(" ", "").replace("_", "")
        if "perday" in flat or "daily" in flat:
            return _env_float("AI_KEY_COOLDOWN_DAILY", 3600.0), "429 일일 할당량"
        return _env_float("AI_KEY_COOLDOWN_QUOTA", 120.0), "429 할당량"
    return None


def pick_key(n: int) -> int:
    """이번 호출에 쓸 키 번호: 쿨다운이 아닌 키 중 가장 앞 번호(주 키가 풀리면 자동으로 롤백)."""
    global _key_active
    now = time.time()
    with _state_lock:
        cooling = {i: until for i, (until, _r) in _key_cooldown.items() if until > now and i < n}
        free = [i for i in range(n) if i not in cooling]
        i = free[0] if free else min(cooling, key=lambda k: (cooling[k], k))
        prev, _key_active = _key_active, i
    if prev is not None and prev != i:
        if i < prev:
            log.warning("Gemini 키 롤백: %s → %s (앞 키의 쿨다운이 끝남)", key_label(prev), key_label(i))
        else:
            log.warning("Gemini 키 전환: %s → %s", key_label(prev), key_label(i))
    return i


def note_key_failure(i: int, exc: BaseException) -> None:
    cd = key_cooldown_for(exc)
    if cd is None:
        return
    seconds, reason = cd
    with _state_lock:
        _key_cooldown[i] = (time.time() + max(0.0, seconds), reason)
    log.warning("Gemini %s 를 %d초 미룸: %s", key_label(i), int(seconds), reason)


def note_key_success(i: int) -> None:
    with _state_lock:
        _key_cooldown.pop(i, None)


def key_health() -> dict[str, Any]:
    """/health 용 — 키 개수, 지금 쓰는 키, 미뤄 둔 키. 키 값은 내보내지 않는다."""
    now = time.time()
    n = len(api_keys())
    with _state_lock:
        return {
            "count": n,
            "active": key_label(_key_active) if _key_active is not None and _key_active < n else None,
            "cooling": {
                key_label(i): {"reason": r, "seconds_left": int(until - now)}
                for i, (until, r) in sorted(_key_cooldown.items())
                if until > now and i < n
            },
        }


class KeyRotatingClient:
    """키마다 클라이언트를 두고 호출마다 지금 쓸 키를 고른다.

    retry() 의 다음 시도가 다시 이 객체를 부르므로, 키가 막히면 다음 시도는 자연스럽게 예비 키로 간다.
    호출 1회 = 키 1개로 API 요청 1회(시도 횟수 = 실제 요청 수 규칙 유지).
    """

    def __init__(self, keys: list[str], make: Callable[[str], Any]) -> None:
        self._keys = list(keys)
        self._make = make
        self._clients: dict[int, Any] = {}
        self.models = _RotatingModels(self)

    def _call(self, fn: Callable[[Any], T]) -> T:
        i = pick_key(len(self._keys))
        c = self._clients.get(i)
        if c is None:
            c = self._clients[i] = self._make(self._keys[i])
        try:
            out = fn(c)
        except Exception as exc:
            note_key_failure(i, exc)
            raise
        note_key_success(i)
        return out


class _RotatingModels:
    def __init__(self, owner: KeyRotatingClient) -> None:
        self._owner = owner

    def list(self) -> list[Any]:
        # 목록은 지연 순회(pager)라 오류가 순회 중에 난다 — 같은 키로 끝까지 받아 둔다
        return self._owner._call(lambda c: list(c.models.list()))

    def generate_content(self, **kwargs: Any) -> Any:
        return self._owner._call(lambda c: c.models.generate_content(**kwargs))


def make_client() -> Any:
    if _client_factory is not None:
        return _client_factory()
    keys = api_keys()
    if len(keys) > 1:
        return KeyRotatingClient(keys, _key_client)
    return _key_client(keys[0] if keys else os.environ["GEMINI_API_KEY"])


def _key_client(key: str) -> Any:
    if _key_client_factory is not None:
        return _key_client_factory(key)
    from google import genai
    from google.genai import types

    timeout_ms = int(max(1.0, _env_float("AI_CALL_TIMEOUT", 60.0)) * 1000)
    return genai.Client(
        api_key=key,
        http_options=types.HttpOptions(
            timeout=timeout_ms,
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )


def _version_key(name: str) -> tuple[int, tuple[float, ...]]:
    """'gemini-2.5-flash' → (0, (-2.0, -5.0)). 새 버전이 앞에 오도록 음수.

    버전 번호가 없는 이름('gemini-omni-1.1-flash' 등 낯선 계열)은 버전 있는 모델 뒤로 보낸다.
    """
    rest = name.split("gemini-", 1)[-1]
    nums: list[float] = []
    for part in rest.split("-")[0].split("."):
        if not part.isdigit():
            break
        nums.append(-float(part))
    return (0 if nums else 1, tuple(nums))


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

    names, _, _ = retry("models.list", once)
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
    global _key_active
    with _state_lock:
        _last_good.clear()
        _cooldown.clear()
        _key_cooldown.clear()
        _key_active = None


def cooldown_for(exc: BaseException) -> tuple[float, str] | None:
    """실패 종류별로 그 모델을 얼마나 뒤로 미룰지. 모델 탓이 아닌 실패(빈 응답·JSON·검증)는 None."""
    code = getattr(exc, "code", None)
    if not isinstance(code, int):
        if isinstance(exc, TimeoutError) or "timeout" in type(exc).__name__.lower():
            return _env_float("AI_COOLDOWN_BUSY", 60.0), "timeout"
        return None
    if code in (403, 404):
        return _env_float("AI_COOLDOWN_GONE", 6 * 3600.0), f"{code} 사용 불가"
    if code == 400:   # 요청 형식 문제일 수도 있어(예: 오디오 미지원) 길게 미루지 않는다
        return _env_float("AI_COOLDOWN_QUOTA", 600.0), "400 요청 거부"
    if code == 429:
        return _env_float("AI_COOLDOWN_QUOTA", 600.0), "429 할당량"
    if code >= 500:
        return _env_float("AI_COOLDOWN_BUSY", 60.0), f"{code} 과부하"
    return None


def note_failure(model: str, exc: BaseException) -> None:
    if is_key_rejection(exc):   # 키 탓 — 모델은 멀쩡하다(키 쿨다운은 KeyRotatingClient 가 맡는다)
        return
    cd = cooldown_for(exc)
    if cd is None:
        return
    seconds, reason = cd
    with _state_lock:
        _cooldown[model] = (time.time() + max(0.0, seconds), reason)


def note_success(model: str, pool: str = "gemini") -> None:
    with _state_lock:
        _last_good[pool] = model
        _cooldown.pop(model, None)


def attempt_order(models: list[str], pool: str = "gemini") -> list[str]:
    """이번 요청의 시도 순서. 마지막 성공 모델 → 정상 모델(원래 순서) → 미룬 모델(빨리 풀리는 순).

    목록의 모델은 하나도 빠지지 않는다. 순서만 바뀐다.
    """
    now = time.time()
    with _state_lock:
        cooling = {m: until for m, (until, _r) in _cooldown.items() if until > now and m in models}
        last = _last_good.get(pool)
    healthy = [m for m in models if m not in cooling]
    if last in healthy:
        healthy.remove(last)
        healthy.insert(0, last)
    return healthy + sorted(cooling, key=lambda m: (cooling[m], models.index(m)))


def model_health() -> dict[str, Any]:
    """/health 용 — 마지막 성공 모델과 지금 뒤로 미뤄 둔 모델."""
    now = time.time()
    with _state_lock:
        return {
            "last_good": _last_good.get("gemini"),
            "last_good_by_pool": dict(sorted(_last_good.items())),
            "cooling": {
                m: {"reason": r, "seconds_left": int(until - now)}
                for m, (until, r) in sorted(_cooldown.items())
                if until > now
            },
        }


@dataclass
class Result(Generic[T]):
    value: T
    attempts: int
    model: str
    failures: list[dict[str, Any]]


def run(what: str, fn: Callable[[Any, str, int], T]) -> Result[T]:
    """Gemini 호출: fn(client, model, attempt) 를 최소 시도 규칙으로 실행한다."""
    client = make_client()
    return run_on(what, client, available_models(client), fn)


def run_on(
    what: str,
    client: Any,
    models: list[str],
    fn: Callable[[Any, str, int], T],
    pool: str = "gemini",
) -> Result[T]:
    """어떤 공급자든 공통: 최소 시도 규칙 + 시도마다 모델 회전 + 실패 모델 쿨다운 + 마지막 성공 모델 우선.

    models 는 쿨다운·기억에 쓰는 이름이다(STT 는 "groq:whisper-large-v3" 처럼 공급자를 붙인다).
    """
    if not models:
        raise AttemptsExhausted(what, 0, [{"attempt": 0, "model": None, "error": "NoModels",
                                           "detail": "사용 가능한 모델이 없습니다"}])
    order = attempt_order(models, pool)

    def model_of(attempt: int) -> str:
        return order[(attempt - 1) % len(order)]

    def once(attempt: int) -> T:
        model = model_of(attempt)
        try:
            value = fn(client, model, attempt)
        except Exception as exc:
            note_failure(model, exc)
            raise
        note_success(model, pool)
        return value

    value, attempts, failures = retry(what, once, model_of)
    return Result(value=value, attempts=attempts, model=model_of(attempts), failures=failures)


def thinking_budget(model: str) -> int | None:
    """GEMINI_THINKING_BUDGET(정수)이 있으면 flash 계열 호출에 생각(thinking) 토큰 상한을 건다.

    짧은 JSON 문장 생성에는 추론 시간이 거의 필요 없어 0 이면 응답이 빨라질 수 있다(배포에서 전후 측정).
    pro 계열은 생각을 끌 수 없어(예산 0 = 요청 오류) 적용하지 않는다. 비어 있으면 모델 기본값.
    """
    raw = (os.getenv("GEMINI_THINKING_BUDGET") or "").strip()
    if not raw or "flash" not in model.lower():
        return None
    try:
        return max(0, int(raw))
    except ValueError:
        return None


def generate_text(client: Any, model: str, contents: Any, **config: Any) -> str:
    """generate_content 1회 = API 요청 1회. 재시도는 run()/retry() 가 맡는다."""
    from google.genai import types

    budget = thinking_budget(model)
    if budget is not None:
        config["thinking_config"] = types.ThinkingConfig(thinking_budget=budget)
    resp = client.models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(response_mime_type="application/json", **config),
    )
    text = resp.text or ""
    if not text.strip():
        raise ValueError("빈 응답")
    return text
