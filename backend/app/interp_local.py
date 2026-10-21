"""자체 통역 엔진('local') — 외부 회사 키 없이 우리 서버에서 받아쓰기와 번역을 한다.

- 받아쓰기: Whisper(faster-whisper, CTranslate2). 이미 말소리 검출 때문에 설치돼 있는 패키지다.
- 번역: Argos Translate 의 ko→en·en→ko 모델(CTranslate2 모델 + sentencepiece). argostranslate 패키지는 쓰지 않는다 —
  문장 분리용 의존성(stanza·torch)이 무거워 무료 인스턴스 빌드를 깨뜨릴 수 있어, 모델 파일을 직접 읽는다.
  모델: https://argos-net.com/v1/translate-{ko_en,en_ko}-1_1.argosmodel (argospm-index, 10/21 확인. MIT/CC0 라이브러리)
- 처리 단위: 실시간 스트리밍이 아니라 '한 번 말이 끝나면'(INTERP_LOCAL_SILENCE_MS 동안 조용하면) 그 말을 받아쓰고 번역한다.
- 서버 밖으로 음성을 보내지 않는다. 모델 파일만 처음에 내려받는다(INTERP_LOCAL_DIR, 기본 ~/.cache/madi-interp).
- CPU 를 많이 쓴다. Render 무료 인스턴스에서는 사실상 쓸 수 없다 — 유료 인스턴스로 올린 뒤 INTERP_PROVIDERS 맨 앞에 local 을 넣는다.
  켜져 있으면 서버가 뜰 때 모델을 미리 내려받고 불러 둔다(warm_in_background). 준비 전에 들어온 통역은 다음 엔진으로 넘어간다.

환경 변수: INTERP_LOCAL_WHISPER(기본 small), INTERP_LOCAL_COMPUTE(기본 int8), INTERP_LOCAL_DIR,
          INTERP_LOCAL_SILENCE_MS(기본 700), INTERP_LOCAL_MAX_SPEECH_S(기본 12), INTERP_LOCAL_RMS(기본 0.015)
"""
from __future__ import annotations

import logging
import os
import threading
import time
import zipfile
from pathlib import Path
from typing import Any

log = logging.getLogger("interp.local")

ARGOS_URLS = {
    ("ko", "en"): "https://argos-net.com/v1/translate-ko_en-1_1.argosmodel",
    ("en", "ko"): "https://argos-net.com/v1/translate-en_ko-1_1.argosmodel",
}

_lock = threading.Lock()          # 불러오기 한 번만
_infer = threading.Lock()         # CPU 를 나눠 쓰지 않게 추론은 한 번에 하나
_state: dict[str, Any] = {"status": "idle", "error": "", "seconds": None}
_models: dict[str, Any] = {}

# 테스트에서 바꿔 끼운다: (pcm16 bytes, langs) → (text, lang) / (text, src, dst) → text
transcribe_fn = None
translate_fn = None


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name) or default)
    except ValueError:
        return default


def silence_ms() -> float:
    return _env_float("INTERP_LOCAL_SILENCE_MS", 700)


def max_speech_s() -> float:
    return _env_float("INTERP_LOCAL_MAX_SPEECH_S", 12)


def rms_threshold() -> float:
    return _env_float("INTERP_LOCAL_RMS", 0.015)


def model_dir() -> Path:
    return Path(os.getenv("INTERP_LOCAL_DIR") or Path.home() / ".cache" / "madi-interp")


def deps_ok() -> bool:
    """패키지가 설치돼 있는지(모델 준비와는 별개)."""
    try:
        import ctranslate2  # noqa: F401
        import faster_whisper  # noqa: F401
        import sentencepiece  # noqa: F401
        return True
    except Exception:      # noqa: BLE001
        return False


def status() -> dict[str, Any]:
    with _lock:
        return dict(_state)


def ready() -> bool:
    return transcribe_fn is not None or _state["status"] == "ready"


def warm_in_background() -> None:
    """서버가 뜰 때 한 번. 이미 불러오는 중이거나 끝났으면 아무것도 안 한다."""
    with _lock:
        if _state["status"] != "idle":
            return
        _state["status"] = "loading"
    threading.Thread(target=_load_safely, name="interp-local-load", daemon=True).start()


def _load_safely() -> None:
    t0 = time.monotonic()
    try:
        _load()
        with _lock:
            _state.update(status="ready", error="", seconds=round(time.monotonic() - t0, 1))
        log.info("local interp ready in %.1fs", time.monotonic() - t0)
    except Exception as exc:      # noqa: BLE001 — 실패해도 서버는 계속 돈다(다음 엔진으로 넘어간다)
        with _lock:
            _state.update(status="error", error=f"{type(exc).__name__}: {str(exc)[:200]}")
        log.warning("local interp load failed: %s", _state["error"])


def _safe_extract(zf: zipfile.ZipFile, dest: Path) -> None:
    root = dest.resolve()
    for m in zf.infolist():
        target = (dest / m.filename).resolve()
        if root not in target.parents and target != root:
            raise ValueError(f"압축 파일 경로가 이상합니다: {m.filename}")
    zf.extractall(dest)


def _argos_dir(pair: tuple[str, str]) -> Path:
    """모델을 내려받아 풀고, 'model/' 과 sentencepiece.model 이 있는 폴더를 돌려준다."""
    import httpx

    base = model_dir() / "argos" / f"{pair[0]}_{pair[1]}"
    found = [p.parent for p in base.rglob("sentencepiece.model")] if base.exists() else []
    if not found:
        base.mkdir(parents=True, exist_ok=True)
        part = base / "download.part"
        with httpx.stream("GET", ARGOS_URLS[pair], timeout=120, follow_redirects=True) as r:
            r.raise_for_status()
            with open(part, "wb") as f:
                for chunk in r.iter_bytes():
                    f.write(chunk)
        with zipfile.ZipFile(part) as zf:
            _safe_extract(zf, base)
        part.unlink(missing_ok=True)
        found = [p.parent for p in base.rglob("sentencepiece.model")]
    for d in found:
        if (d / "model").is_dir():
            return d
    raise FileNotFoundError(f"Argos 모델 폴더를 찾지 못했습니다: {base}")


def _load() -> None:
    import ctranslate2
    import sentencepiece
    from faster_whisper import WhisperModel

    for pair in ARGOS_URLS:
        d = _argos_dir(pair)
        _models[pair] = (ctranslate2.Translator(str(d / "model"), device="cpu", compute_type="int8"),
                         sentencepiece.SentencePieceProcessor(model_file=str(d / "sentencepiece.model")))
    _models["whisper"] = WhisperModel(
        (os.getenv("INTERP_LOCAL_WHISPER") or "small").strip(), device="cpu",
        compute_type=(os.getenv("INTERP_LOCAL_COMPUTE") or "int8").strip(),
        download_root=str(model_dir() / "whisper"))


def transcribe(pcm16: bytes, langs: tuple[str, str]) -> tuple[str, str]:
    """한 번의 말 → (받아쓴 글, 언어). 언어는 langs 둘 중 하나로 고른다(다른 언어로 잘못 듣지 않게)."""
    if transcribe_fn is not None:
        return transcribe_fn(pcm16, langs)
    import numpy as np

    audio = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768.0
    model = _models["whisper"]
    with _infer:
        segs, info = model.transcribe(audio, language=None, beam_size=1, vad_filter=True,
                                      condition_on_previous_text=False)
        text = "".join(s.text for s in segs).strip()
        lang = info.language
        if lang not in langs:
            probs = dict(info.all_language_probs or [])
            lang = max(langs, key=lambda x: probs.get(x, 0.0))
            segs, _ = model.transcribe(audio, language=lang, beam_size=1, vad_filter=True,
                                       condition_on_previous_text=False)
            text = "".join(s.text for s in segs).strip()
    return text, lang


def translate(text: str, src: str, dst: str) -> str:
    if translate_fn is not None:
        return translate_fn(text, src, dst)
    translator, sp = _models[(src, dst)]
    tokens = sp.encode(text, out_type=str)
    with _infer:
        out = translator.translate_batch([tokens], beam_size=2, max_decoding_length=256)
    return sp.decode(out[0].hypotheses[0]).strip()
