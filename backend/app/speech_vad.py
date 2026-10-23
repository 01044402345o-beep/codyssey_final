"""말소리 구간 검출 — Silero 신경망 VAD (데시벨·음량 기준이 아니다).

seongbin45/transcribe_app 의 core/engines/local_whisper.py 와 같은 함수·같은 옵션을 쓴다:
    get_speech_timestamps(audio, VadOptions(min_silence_duration_ms=500, speech_pad_ms=200))
발화 구간이 하나도 없으면 전사(외부 API)를 부르지 않는다.

음량 기준 판정은 큰 잡음·신호음도 '소리 있음'으로 통과시킨다. Silero 는 말소리인지를
판정하므로 큰 백색잡음·440Hz 신호음은 발화 0구간으로 나온다(tests/test_speech_vad.py).

디코드는 faster-whisper 의 decode_audio(PyAV) 로 16kHz mono float32 로 맞춘다.
브라우저 녹음(webm/opus, Safari mp4/aac, ogg)과 wav 를 메모리에서 바로 읽는다.
Whisper 모델은 로드하지 않는다 — Silero ONNX(패키지 내장, 약 2MB)만 쓴다.
"""
from __future__ import annotations

import io
import threading
import wave
from dataclasses import dataclass
from typing import Any

import numpy as np

SAMPLE_RATE = 16000
MIN_SILENCE_MS = 500   # transcribe_app 과 같음
SPEECH_PAD_MS = 200    # transcribe_app 과 같음

_lock = threading.Lock()


class AudioDecodeError(ValueError):
    """녹음 파일을 오디오로 읽을 수 없음(손상·형식 오류)."""


class AudioTooLongError(ValueError):
    """디코드 중 길이 상한 초과(헤더의 길이 또는 실제로 풀린 샘플 수)."""


MAX_DECODE_SECONDS = 30   # main.MAX_AUDIO_SECONDS 와 같게


@dataclass
class SpeechResult:
    duration_sec: float
    segments: list[dict[str, int]]   # 샘플 단위 {"start", "end"}

    @property
    def speech_sec(self) -> float:
        return sum(s["end"] - s["start"] for s in self.segments) / SAMPLE_RATE

    @property
    def has_speech(self) -> bool:
        return bool(self.segments)

    def summary(self, engine: str = "silero (faster-whisper)") -> dict[str, Any]:
        return {
            "engine": engine,
            "duration_sec": round(self.duration_sec, 2),
            "speech_sec": round(self.speech_sec, 2),
            "segments": [[round(s["start"] / SAMPLE_RATE, 2), round(s["end"] / SAMPLE_RATE, 2)]
                         for s in self.segments],
        }


def decode(data: bytes, max_seconds: float = MAX_DECODE_SECONDS) -> np.ndarray:
    """16 kHz mono float32 로 푼다. max_seconds 를 넘으면 **푸는 도중에** AudioTooLongError 로 멈춘다.

    예전에는 faster_whisper.audio.decode_audio 로 파일 전체를 푼 뒤 길이를 봤다. 저비트레이트 opus 는 8MB 안에
    3시간이 넘게 들어가고(6 kbps 실측 6.24 MB), 푸는 동안 최대 1.7 GB 를 써서 로그인 없는 요청 하나로 서버가 죽을 수
    있었다(10/23 교차 검증 #1). 이제 프레임마다 샘플을 세고 상한을 넘는 순간 그만둔다(실측 최대 ~44 MB).
    브라우저 MediaRecorder 의 webm 은 헤더에 길이가 없어(duration=None) 헤더 검사만으로는 막지 못한다 — 샘플 수로 센다.
    결과는 decode_audio 와 같다(픽스처 3개 샘플 수·값 동일 실측).
    """
    import av

    limit = int(max_seconds * SAMPLE_RATE)
    chunks: list[np.ndarray] = []
    n = 0

    def take(frames: Any) -> None:
        nonlocal n
        for rf in frames:
            arr = rf.to_ndarray().reshape(-1)
            n += arr.size
            if n > limit:
                raise AudioTooLongError(f"longer than {max_seconds}s")
            chunks.append(arr)

    try:
        with av.open(io.BytesIO(data), mode="r", metadata_errors="ignore") as container:
            if not container.streams.audio:
                raise AudioDecodeError("no audio stream")
            stream = container.streams.audio[0]
            # 헤더에 길이가 있으면 풀기 전에 거절한다(여유 5초).
            if container.duration is not None and container.duration / av.time_base > max_seconds + 5:
                raise AudioTooLongError("header duration")
            resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
            for packet in container.demux(stream):
                try:
                    frames = packet.decode()
                except av.error.InvalidDataError:
                    continue            # faster_whisper 의 _ignore_invalid_frames 와 같은 관용
                for f in frames:
                    take(resampler.resample(f))
            take(resampler.resample(None))   # 남은 샘플 flush
    except (AudioTooLongError, AudioDecodeError):
        raise
    except EOFError:
        # 컨테이너 머리만 있고 오디오 프레임이 없는 녹음(브라우저 실측: 소리 입력이 없는 스트림 → 110바이트 webm).
        # 깨진 파일이 아니라 '소리가 없는 녹음'이므로 빈 오디오로 보고 VAD 가 말소리 없음으로 판정하게 한다.
        return np.zeros(0, dtype=np.float32)
    except Exception as exc:  # noqa: BLE001 — av.error.InvalidDataError 등: 오디오로 읽을 수 없는 파일
        raise AudioDecodeError(f"{type(exc).__name__}: {exc}") from exc
    if not chunks:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(chunks).astype(np.float32) / 32768.0


def detect(audio: np.ndarray) -> SpeechResult:
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    if len(audio) == 0:
        return SpeechResult(duration_sec=0.0, segments=[])
    # Silero 상태(h, c)는 호출마다 새로 만들어져 세션 공유는 안전하다. 무료 인스턴스(CPU 1개)에서
    # 동시 요청이 서로 CPU 를 빼앗지 않도록 직렬화만 한다(15초 녹음 기준 수십 ms).
    with _lock:
        segments = get_speech_timestamps(
            audio, VadOptions(min_silence_duration_ms=MIN_SILENCE_MS, speech_pad_ms=SPEECH_PAD_MS)
        )
    return SpeechResult(duration_sec=len(audio) / SAMPLE_RATE, segments=list(segments))


def speech_only_wav(audio: np.ndarray, result: SpeechResult) -> bytes:
    """발화 구간만 이어붙인 16kHz mono 16-bit WAV. 전사 공급자에 이것만 보낸다."""
    parts = [audio[s["start"]:s["end"]] for s in result.segments]
    joined = np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)
    pcm = (np.clip(joined, -1.0, 1.0) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def warmup() -> None:
    """콜드스타트 뒤 첫 요청이 모델 로드를 기다리지 않도록 두 검출기를 미리 불러 둔다."""
    detect(np.zeros(SAMPLE_RATE // 2, dtype=np.float32))
    detect_pyannote(np.zeros(SAMPLE_RATE // 2, dtype=np.float32))


# ---------------------------------------------------------------- 두 번째 말소리 검출기: pyannote segmentation-3.0 (로컬 ONNX)
# Silero 와 다른 신경망으로 말소리를 한 번 더 확인한다. 두 검출기가 모두 말소리를 찾아야 채점한다.
# pyannoteAI 클라우드 API 는 계정 크레딧 없음(HTTP 402)이라 로컬 모델로 바꿨다 — 네트워크·크레딧이 필요 없다.
# 모델 출처·라이선스(MIT)·SHA256: app/models/README.md
# 추론 방식은 pyannote 와 같다: 10초 창, 남는 부분은 0 으로 채우고, 프레임별 powerset argmax ≠ 0 을 말소리로 본다.
# 실측(로컬): 무음·큰 백색잡음 → 0초, 합성 440Hz 신호음 0.02초, TTS 음성 전체 검출.
#   단, 브라우저로 녹음한 신호음은 1.29/1.50초를 말소리로 본다 — Silero 는 0초라 AND 판정에서 걸러진다.

import hashlib  # noqa: E402
from pathlib import Path  # noqa: E402

PYANNOTE_MODEL = Path(__file__).resolve().parent / "models" / "pyannote-segmentation-3.0.onnx"
PYANNOTE_SHA256 = "057ee564753071c0b09b5b611648b50ac188d50846bff5f01e9f7bbf1591ea25"
PYANNOTE_WINDOW = SAMPLE_RATE * 10

_pyannote_session: Any = None
_pyannote_lock = threading.Lock()


def _pyannote() -> Any:
    global _pyannote_session
    with _pyannote_lock:
        if _pyannote_session is None:
            data = PYANNOTE_MODEL.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            if digest != PYANNOTE_SHA256:
                raise RuntimeError(f"pyannote 모델 SHA256 불일치: {digest}")
            import onnxruntime as ort

            opts = ort.SessionOptions()
            opts.inter_op_num_threads = 1
            opts.intra_op_num_threads = 1
            opts.log_severity_level = 4
            _pyannote_session = ort.InferenceSession(data, sess_options=opts, providers=["CPUExecutionProvider"])
        return _pyannote_session


def detect_pyannote(audio: np.ndarray) -> SpeechResult:
    """pyannote segmentation-3.0 으로 말소리 구간을 찾는다. 구간은 샘플 단위 {"start","end"}."""
    if len(audio) == 0:
        return SpeechResult(duration_sec=0.0, segments=[])
    sess = _pyannote()
    segments: list[dict[str, int]] = []
    for off in range(0, len(audio), PYANNOTE_WINDOW):
        chunk = audio[off:off + PYANNOTE_WINDOW].astype(np.float32)
        x = np.zeros(PYANNOTE_WINDOW, dtype=np.float32)
        x[:len(chunk)] = chunk
        with _pyannote_lock:
            logits = sess.run(None, {"input_values": x.reshape(1, 1, -1)})[0][0]
        step = PYANNOTE_WINDOW / logits.shape[0]          # 프레임당 샘플 수(약 17ms)
        speech = logits.argmax(-1) != 0
        valid = int(np.ceil(len(chunk) / step))
        start = None
        for i, is_speech in enumerate(list(speech[:valid]) + [False]):
            if is_speech and start is None:
                start = i
            elif not is_speech and start is not None:
                s, e = off + int(start * step), off + min(len(chunk), int(i * step))
                if segments and s - segments[-1]["end"] <= int(step):
                    segments[-1]["end"] = e                  # 창 경계에서 이어지는 구간은 합친다
                else:
                    segments.append({"start": s, "end": e})
                start = None
    return SpeechResult(duration_sec=len(audio) / SAMPLE_RATE, segments=segments)
