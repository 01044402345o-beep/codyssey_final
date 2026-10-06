"""STT 공급자 자가 점검 — STT_SELFTEST=1 일 때만, 서버 시작 뒤 백그라운드에서 1회.

키는 Render 에만 있으므로, 배포된 서버가 공급자를 실제로 호출해 응답 형태를 확인하고
결과를 /health 의 stt_selftest 로 보여준다. 키 값·오디오는 노출하지 않는다.

확인하는 것(공급자마다):
  - 모델 목록에서 고른 whisper 모델
  - 1초 완전 무음 WAV 와 TTS 음성 "I have a peanut allergy." 를 각각 전사
    (무음은 VAD 를 일부러 거치지 않고 보낸다 — 공급자가 무음에 어떻게 답하는지 보려는 것)
  - 응답 최상위 키, 세그먼트에 no_speech_prob·avg_logprob 가 있는지, 원문 텍스트, 필터 뒤 텍스트

콜드스타트마다 호출 비용이 나므로 검증이 끝나면 STT_SELFTEST 를 지운다.
"""
from __future__ import annotations

import io
import os
import threading
import time
import wave
from pathlib import Path
from typing import Any

from . import gemini as ai
from . import speech_compare as compare
from . import stt_providers as stt

FIXTURE = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "good.wav"
FIXTURE_TEXT = "I have a peanut allergy."

_state: dict[str, Any] = {"enabled": False, "status": "off", "results": {}}
_lock = threading.Lock()


def enabled() -> bool:
    return os.getenv("STT_SELFTEST", "") == "1"


def status() -> dict[str, Any]:
    with _lock:
        return {"enabled": enabled(), "status": _state["status"], "results": dict(_state["results"])}


def silence_wav(seconds: float = 1.0) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * int(16000 * seconds))
    return buf.getvalue()


def _probe(pid: str, label: str, wav: bytes) -> dict[str, Any]:
    t0 = time.time()
    try:
        r = stt.transcribe_with(pid, wav)
    except ai.AttemptsExhausted as exc:
        return {"ok": False, "attempts": exc.attempts, "error": exc.last_error,
                "seconds": round(time.time() - t0, 1)}
    kept, dropped = compare.filter_segments(r.text, r.segments)
    seg_fields = sorted({k for s in r.segments for k in s.keys()})
    return {
        "ok": True,
        "model": r.model,
        "attempts": r.attempts,
        "raw_keys": r.raw_keys,
        "segment_count": len(r.segments),
        "segment_fields": seg_fields,
        "has_no_speech_prob": any("no_speech_prob" in s for s in r.segments),
        "has_avg_logprob": any("avg_logprob" in s for s in r.segments),
        "text": r.text,
        "segments": [{k: s.get(k) for k in ("text", "no_speech_prob", "avg_logprob", "compression_ratio")}
                     for s in r.segments][:5],
        "text_after_filter": kept,
        "dropped": dropped,
        "seconds": round(time.time() - t0, 1),
    }


def run() -> None:
    with _lock:
        _state.update(status="running", results={})
    tts = FIXTURE.read_bytes() if FIXTURE.exists() else None
    for pid in stt.configured():   # 전사 공급자(groq·openai·assemblyai)
        out: dict[str, Any] = {}
        try:
            out["models"] = stt.available_models(pid, stt.session())
        except ai.AttemptsExhausted as exc:
            out["models_error"] = exc.last_error
        out["silence_1s"] = _probe(pid, "silence", silence_wav())
        out["tts"] = _probe(pid, "tts", tts) if tts else {"ok": False, "error": f"fixture 없음: {FIXTURE}"}
        out["tts_expected"] = FIXTURE_TEXT
        with _lock:
            _state["results"][pid] = out
    if stt.api_key(stt.DETECTOR):
        det: dict[str, Any] = {}
        for label, wav in (("silence_1s", silence_wav()), ("tts", tts)):
            if wav is None:
                continue
            t0 = time.time()
            try:
                r = stt.detect_speech(wav)
                det[label] = {"ok": True, **r.meta(), "seconds": round(time.time() - t0, 1)}
            except ai.AttemptsExhausted as exc:
                det[label] = {"ok": False, "attempts": exc.attempts, "error": exc.last_error}
        with _lock:
            _state["results"][stt.DETECTOR] = det
    with _lock:
        _state["status"] = "done"


def start() -> None:
    if enabled():
        threading.Thread(target=run, name="stt-selftest", daemon=True).start()
