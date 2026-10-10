"""전사(STT) 공급자 — 범용 LLM 이 아니라 전용 음성인식 모델만 쓴다.

seongbin45/transcribe_app 의 원칙을 따른다: 전사는 Whisper/AssemblyAI 같은 전용 STT 가 하고,
어떤 전사 요청에도 목표(정답) 문장을 넣지 않는다. 공급자 레지스트리는 transcribe_app 의
core/llm_providers.py 패턴(환경변수 이름 규칙)을 따른다.

transcribe_app 커밋 교차검증에서 찾은 빈틈을 여기서 메운다:
  - STT 모델명 하드코딩(whisper-large-v3-turbo 등) → /models 목록에서 그때그때 고른다
  - Groq·AssemblyAI 재시도 없음 → 공급자마다 최소 30회(app/gemini.retry)
  - AssemblyAI 요청 timeout 없음 → 모든 요청에 timeout
  - 환각 필터가 로컬 엔진에만 있음 → 모든 공급자 결과에 공통 적용(app/speech_compare.filter_segments)

역할 (교차검증 필수화, 2026-10-07):
  - 1차 전사(Whisper 계열): groq → openai. 앞 공급자가 최소 시도를 다 실패해야 다음으로 넘어간다.
  - 교차검증 전사(다른 모델 계열): assemblyai. Groq·OpenAI 는 같은 Whisper 계열이라 무음에서 같은 "you"를
    지어냈다(배포 자가 점검) → 서로의 검증자가 될 수 없다. AssemblyAI(Universal)는 같은 무음에 "" 를 냈다.
  - 2차 말소리 검출: 로컬 pyannote segmentation-3.0 (app/speech_vad.py). pyannoteAI 클라우드는 크레딧 없음(402)으로
    모든 요청이 실패해 로컬 모델로 바꿨다(2026-10-08).
교차검증 공급자가 없거나 실패하면 채점하지 않는다(사용자 결정).
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import requests

from . import gemini as ai

LANGUAGE = "en"            # 학습 문장은 영어 — transcribe_app 규칙: 언어가 하나로 정해지면 힌트로 보낸다
REQUEST_TIMEOUT = 60       # 초
POLL_INTERVAL = 1.0        # AssemblyAI 폴링 간격(짧은 녹음이라 짧게)
POLL_MAX_SECONDS = 120


@dataclass(frozen=True)
class ProviderSpec:
    id: str
    env_keys: tuple[str, ...]
    kind: str                     # "openai_compat" | "assemblyai"
    base_url: str
    model_env: str | None = None  # 선호 모델(고정 아님): 목록에 있을 때만 맨 앞


PROVIDERS: dict[str, ProviderSpec] = {
    "groq": ProviderSpec("groq", ("GROQ_API_KEY",), "openai_compat",
                         "https://api.groq.com/openai/v1", "GROQ_STT_MODEL"),
    "openai": ProviderSpec("openai", ("OPENAI_API_KEY",), "openai_compat",
                           "https://api.openai.com/v1", "OPENAI_STT_MODEL"),
    "assemblyai": ProviderSpec("assemblyai", ("ASSEMBLYAI_API_KEY", "ASSEMBLY_AI_API_KEY"), "assemblyai",
                               "https://api.assemblyai.com/v2"),
}
ORDER = ("groq", "openai", "assemblyai")   # /health 표시·자가 점검 순서(전사 공급자)
PRIMARY = ("groq", "openai")               # 1차 전사 — Whisper 계열
CHECKER = "assemblyai"                     # 교차검증 전사 — 다른 모델 계열
# 2차 말소리 검출은 외부 API 가 아니라 서버 안의 pyannote segmentation-3.0(app/speech_vad.detect_pyannote).

_session_factory: Callable[[], Any] | None = None   # 테스트에서 가짜 세션을 넣는다
_models_lock = threading.Lock()
_models_cache: dict[str, tuple[float, list[str]]] = {}


class SttHTTPError(RuntimeError):
    """HTTP 오류. code 를 가져 app/gemini.cooldown_for 가 404·429·5xx 를 구분한다."""

    def __init__(self, provider: str, code: int, body: str) -> None:
        super().__init__(f"{provider} HTTP {code}: {' '.join((body or '').split())[:300]}")
        self.code = code


class SttChainExhausted(RuntimeError):
    def __init__(self, failures: dict[str, ai.AttemptsExhausted]) -> None:
        self.by_provider = failures
        last = list(failures.values())[-1] if failures else None
        self.attempts = sum(f.attempts for f in failures.values())
        self.last_error = last.last_error if last else "설정된 STT 공급자가 없습니다"
        self.failures = [dict(f, provider=pid) for pid, e in failures.items() for f in e.failures]
        super().__init__(self.last_error)


@dataclass
class SttResult:
    provider: str
    model: str
    text: str
    segments: list[dict[str, Any]]           # 공급자가 준 세그먼트(없으면 빈 목록)
    raw_keys: list[str]                       # 응답 최상위 키(자가 점검용)
    attempts: int = 0
    failures: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)   # 실패해서 넘어간 앞 공급자들

    def meta(self) -> dict[str, Any]:
        return {"provider": self.provider, "model": self.model, "attempts": self.attempts,
                "skipped_providers": self.skipped}


def api_key(pid: str) -> str | None:
    for k in PROVIDERS[pid].env_keys:
        v = (os.getenv(k) or "").strip()
        if v:
            return v
    return None


def configured() -> list[str]:
    return [pid for pid in ORDER if api_key(pid)]


def configured_primary() -> list[str]:
    return [pid for pid in PRIMARY if api_key(pid)]


def session() -> Any:
    return _session_factory() if _session_factory is not None else requests.Session()


def _check(pid: str, resp: Any) -> Any:
    if resp.status_code >= 400:
        raise SttHTTPError(pid, resp.status_code, resp.text)
    return resp.json()


# ---------------------------------------------------------------- 모델 목록 (하드코딩 금지)

def rank_stt(model_id: str) -> tuple[int, str]:
    """짧은 학습 발화는 정확도 우선: large-v3 → large-v3-turbo → 그 밖의 whisper."""
    n = model_id.lower()
    if "large-v3" in n and "turbo" not in n and "distil" not in n:
        tier = 0
    elif "large-v3" in n and "turbo" in n:
        tier = 1
    else:
        tier = 2
    return (tier, n)


def pick_stt_models(pid: str, ids: list[str]) -> list[str]:
    """whisper 로 시작하는 전사 모델만 쓴다(distil-whisper 포함).
    gpt-4o-transcribe 같은 LLM 기반 전사는 제외한다(프롬프트 텍스트가 무음 구간에 새어 나온다는 보고, no_speech_prob 없음).
    이름에 whisper 가 들어 있어도 'gpt-realtime-whisper' 처럼 전사 엔드포인트가 아닌 모델은 제외한다
    (배포 실측: /audio/transcriptions 에 404 "Invalid URL")."""
    names = sorted({i for i in ids if i.lower().startswith(("whisper", "distil-whisper"))}, key=rank_stt)
    env = PROVIDERS[pid].model_env
    preferred = (os.getenv(env) or "").strip() if env else ""
    if preferred in names:
        names.remove(preferred)
        names.insert(0, preferred)
    return names


def available_models(pid: str, sess: Any) -> list[str]:
    spec = PROVIDERS[pid]
    if spec.kind == "assemblyai":
        return ["default"]   # 목록 API 가 없다 — speech_models 를 보내지 않아 계정 기본 모델을 쓴다
    ttl = max(0.0, float(os.getenv("AI_MODELS_TTL", "600") or 600))
    with _models_lock:
        hit = _models_cache.get(pid)
        if hit and time.time() - hit[0] < ttl:
            return list(hit[1])
    headers = {"Authorization": f"Bearer {api_key(pid)}"}

    def once(_a: int) -> list[str]:
        data = _check(pid, sess.get(f"{spec.base_url}/models", headers=headers, timeout=REQUEST_TIMEOUT))
        names = pick_stt_models(pid, [str(m.get("id", "")) for m in data.get("data") or []])
        if not names:
            raise RuntimeError(f"{pid}: whisper 전사 모델이 목록에 없습니다")
        return names

    names, _, _ = ai.retry(f"stt-models:{pid}", once)
    with _models_lock:
        _models_cache[pid] = (time.time(), names)
    return list(names)


def cached_models() -> dict[str, list[str]]:
    with _models_lock:
        return {pid: list(v[1]) for pid, v in _models_cache.items()}


def reset_cache() -> None:
    with _models_lock:
        _models_cache.clear()


# ---------------------------------------------------------------- 전사 1회 = API 요청 1회

def _openai_compat(pid: str, sess: Any, model: str, wav: bytes) -> dict[str, Any]:
    spec = PROVIDERS[pid]
    data = _check(pid, sess.post(
        f"{spec.base_url}/audio/transcriptions",
        headers={"Authorization": f"Bearer {api_key(pid)}"},
        files={"file": ("speech.wav", wav, "audio/wav")},
        # 목표 문장은 절대 보내지 않는다(prompt 도 쓰지 않는다).
        data={"model": model, "response_format": "verbose_json", "language": LANGUAGE, "temperature": "0"},
        timeout=REQUEST_TIMEOUT,
    ))
    if not isinstance(data, dict) or not isinstance(data.get("text"), str):
        raise ValueError(f"{pid}: 응답에 text 가 없습니다")
    segs = data.get("segments") if isinstance(data.get("segments"), list) else []
    return {"text": data["text"], "segments": [s for s in segs if isinstance(s, dict)],
            "raw_keys": sorted(data.keys()), "model": model}


def _assemblyai(pid: str, sess: Any, _model: str, wav: bytes) -> dict[str, Any]:
    spec = PROVIDERS[pid]
    h = {"authorization": api_key(pid) or ""}
    up = _check(pid, sess.post(f"{spec.base_url}/upload", headers=h, data=wav, timeout=REQUEST_TIMEOUT))
    job = _check(pid, sess.post(f"{spec.base_url}/transcript", headers=h, timeout=REQUEST_TIMEOUT,
                                json={"audio_url": up["upload_url"], "language_code": LANGUAGE}))
    deadline = time.time() + POLL_MAX_SECONDS
    while True:
        data = _check(pid, sess.get(f"{spec.base_url}/transcript/{job['id']}", headers=h,
                                    timeout=REQUEST_TIMEOUT))
        status = data.get("status")
        if status == "completed":
            return {"text": data.get("text") or "", "segments": [], "raw_keys": sorted(data.keys()),
                    "model": str(data.get("speech_model") or data.get("speech_model_used") or "default")}
        if status == "error":
            raise RuntimeError(f"assemblyai 전사 오류: {data.get('error')}")
        if time.time() > deadline:
            raise TimeoutError(f"assemblyai 폴링 {POLL_MAX_SECONDS}초 초과")
        ai._sleep(POLL_INTERVAL)


def call_once(pid: str, sess: Any, model: str, wav: bytes) -> dict[str, Any]:
    fn = _assemblyai if PROVIDERS[pid].kind == "assemblyai" else _openai_compat
    return fn(pid, sess, model, wav)


def transcribe_with(pid: str, wav: bytes, sess: Any | None = None) -> SttResult:
    """한 공급자로 전사 — 최소 시도 규칙·모델 회전·쿨다운(app/gemini.run_on)."""
    s = sess or session()
    models = available_models(pid, s)
    keys = [f"{pid}:{m}" for m in models]
    res = ai.run_on(f"stt:{pid}", s, keys,
                    lambda c, key, _a: call_once(pid, c, key.split(":", 1)[1], wav), pool=f"stt:{pid}")
    v = res.value
    return SttResult(provider=pid, model=v["model"], text=v["text"], segments=v["segments"],
                     raw_keys=v["raw_keys"], attempts=res.attempts, failures=res.failures)


def transcribe(wav: bytes) -> SttResult:
    """1차 전사(Whisper 계열) 체인: 앞 공급자가 최소 시도를 모두 실패해야 다음으로 넘어간다."""
    failed: dict[str, ai.AttemptsExhausted] = {}
    for pid in configured_primary():
        try:
            out = transcribe_with(pid, wav)
        except ai.AttemptsExhausted as exc:
            failed[pid] = exc
            continue
        out.skipped = list(failed)
        out.failures = [dict(f, provider=p) for p, e in failed.items() for f in e.failures] + \
                       [dict(f, provider=pid) for f in out.failures]
        out.attempts += sum(e.attempts for e in failed.values())
        return out
    raise SttChainExhausted(failed)

