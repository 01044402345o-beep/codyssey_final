"""음소 노드 — 상시 가동 PC 에서 단독으로 뜨는 작은 서버. 모델(+358MB)을 올리고 /phoneme-check 하나만 받는다.

    python -m app.acoustic.server          # 127.0.0.1:8443, PHONEME_TOKEN 필수

밖으로는 Tailscale Funnel 하나로만 연다(https://<기기>.<tailnet>.ts.net → 127.0.0.1:8443).
그 주소는 인터넷에 공개되므로:
  - PHONEME_TOKEN 이 없거나 짧으면 아예 시작하지 않는다(인증 없는 공개 음성 엔드포인트를 만들지 않는다)
  - 토큰은 상수 시간 비교, 오디오는 16bit mono WAV · 최대 MAX_AUDIO_SECONDS 초, 목표 문장은 300자
  - 받은 음성은 메모리에서만 쓰고 디스크에 저장하지 않는다. 로그에도 음성·문장을 남기지 않는다
"""
from __future__ import annotations

import hmac
import io
import logging
import os
import sys
import threading
import time
import wave
from contextlib import asynccontextmanager

import numpy as np
from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile

from . import model, score

log = logging.getLogger("app.acoustic.server")

MIN_TOKEN_LEN = 24
MAX_AUDIO_SECONDS = 20
MAX_UPLOAD_BYTES = MAX_AUDIO_SECONDS * 16000 * 2 + 4096      # 16k·16bit mono WAV + 헤더
_state = {"ready": False, "error": "", "loaded_at": None}
_lock = threading.Lock()


def token() -> str:
    return os.getenv("PHONEME_TOKEN", "").strip()


def _warm() -> None:
    with _lock:
        if _state["ready"]:
            return
        try:
            t = time.time()
            model.load()
            _state.update(ready=True, error="", loaded_at=round(time.time() - t, 1))
            log.info("음소 모델 준비 (%.1fs)", time.time() - t)
        except Exception as exc:  # noqa: BLE001
            _state["error"] = type(exc).__name__
            log.exception("음소 모델 로드 실패")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    threading.Thread(target=_warm, daemon=True).start()   # 첫 요청을 기다리지 않고 미리 올린다
    yield


app = FastAPI(title="madi-phoneme-node", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)


def _rss_mb() -> int | None:
    try:
        import psutil
        return int(psutil.Process().memory_info().rss / 1e6)
    except Exception:  # noqa: BLE001
        return None


def read_wav(data: bytes) -> np.ndarray:
    with wave.open(io.BytesIO(data), "rb") as w:
        ch, sr, sw, n = w.getnchannels(), w.getframerate(), w.getsampwidth(), w.getnframes()
        if sw != 2 or ch != 1 or sr != 16000:
            raise ValueError("16kHz 16-bit mono WAV only")
        if n > MAX_AUDIO_SECONDS * 16000:
            raise ValueError("too long")
        raw = w.readframes(n)
    return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0


@app.get("/healthz")
def healthz() -> dict:
    # 공개 주소에서도 보이므로 경로·토큰·호스트 정보는 넣지 않는다
    return {"status": "ok", "ready": bool(_state["ready"]), "model_present": model.available(),
            "error": _state["error"] or None, "load_seconds": _state["loaded_at"], "rss_mb": _rss_mb()}


@app.post("/phoneme-check")
async def phoneme_check(
    request: Request,
    audio: UploadFile = File(...),
    text: str = Form(..., max_length=300),
    x_phoneme_token: str | None = Header(default=None),
) -> dict:
    if not hmac.compare_digest((x_phoneme_token or "").encode(), token().encode()):
        raise HTTPException(status_code=401, detail="bad token")
    if int(request.headers.get("content-length") or 0) > MAX_UPLOAD_BYTES + 2048:
        raise HTTPException(status_code=413, detail="too large")
    data = await audio.read(MAX_UPLOAD_BYTES + 1)
    if not data or len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413 if data else 400, detail="bad audio size")
    try:
        samples = read_wav(data)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"wav: {exc}") from exc
    if samples.size < 1600:      # 0.1초 미만
        raise HTTPException(status_code=400, detail="too short")
    if not _state["ready"]:
        _warm()
        if not _state["ready"]:
            return {"status": "unavailable", "reason": "model_not_ready"}
    try:
        m = model.load()
        t = time.time()
        logp = m.log_probs(samples)
        rep = score.evaluate(text, logp, m.vocab, m.index, duration_ms=int(round(1000.0 * samples.size / 16000)))
        rep["infer_ms"] = int((time.time() - t) * 1000)
        log.info("phoneme-check ok %.1fs audio, %dms", samples.size / 16000, rep["infer_ms"])
        return rep
    except Exception as exc:  # noqa: BLE001
        log.warning("phoneme-check 실패: %s", type(exc).__name__)
        return {"status": "error", "reason": type(exc).__name__}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if len(token()) < MIN_TOKEN_LEN:
        log.error("PHONEME_TOKEN 이 없거나 %d자 미만 — 공개 주소에 인증 없이 열 수 없어 시작하지 않는다", MIN_TOKEN_LEN)
        return 2
    import uvicorn

    # 기본은 127.0.0.1(PC 노드 — 밖으로는 Funnel 하나). 컨테이너(HF Spaces·Cloud Run)만 PHONEME_HOST=0.0.0.0
    host = os.getenv("PHONEME_HOST", "127.0.0.1").strip()
    if host not in ("127.0.0.1", "0.0.0.0"):
        log.error("PHONEME_HOST 는 127.0.0.1 또는 0.0.0.0 만")
        return 2
    uvicorn.run(app, host=host, port=int(os.getenv("PHONEME_PORT", "8443")), log_level="warning",
                access_log=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
