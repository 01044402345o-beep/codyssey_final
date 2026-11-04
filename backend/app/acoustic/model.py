"""음성 → 음소 사후확률(CTC). onnxruntime 만 쓴다(torch 없음).

모델: onnx-community/wav2vec2-lv-60-espeak-cv-ft-ONNX, 리비전 c69750f5, onnx/model_quantized.onnx (int8, Apache-2.0)
입력: input_values float32 [1, N] (16kHz 단일 채널) → 출력: logits [1, T, 392] (espeak IPA, 프레임 약 20ms)

모델 파일(317MB)은 저장소에 넣지 않는다 — tools/fetch_phoneme_model.py 가 받고 SHA256 을 확인한다.
불러올 때도 같은 해시를 다시 확인한다(받다 끊긴 파일·바뀐 파일로 추론하지 않는다).
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .align import log_softmax

DATA = Path(__file__).resolve().parent / "data"
MODEL_PATH = Path(os.getenv("PHONEME_ONNX", str(DATA / "model_quantized.onnx")))
VOCAB_PATH = DATA / "vocab.json"
MODEL_SHA256 = "3d1479b5c70836645a4310902479f7f7e8bbc8c16c58745d918804f4f6f9d120"
MODEL_BYTES = 317_712_852
SAMPLE_RATE = 16000

_lock = threading.Lock()
_model: "Model | None" = None


class ModelError(RuntimeError):
    pass


def normalize(x: np.ndarray) -> np.ndarray:
    """preprocessor_config.json do_normalize=true — 발화마다 평균 0·분산 1 (Wav2Vec2FeatureExtractor 와 같다)."""
    x = np.asarray(x, dtype=np.float32)
    return (x - x.mean()) / np.sqrt(x.var() + 1e-7)


@dataclass
class Model:
    session: object
    vocab: list[str]
    index: dict[str, int]
    blank: int = 0

    def log_probs(self, samples: np.ndarray, *, do_normalize: bool = True) -> np.ndarray:
        x = normalize(samples) if do_normalize else np.asarray(samples, dtype=np.float32)
        x = x.reshape(1, -1)
        feed = {}
        for inp in self.session.get_inputs():
            feed[inp.name] = np.ones((1, x.shape[1]), dtype=np.int64) if inp.name == "attention_mask" else x
        return log_softmax(self.session.run(None, feed)[0][0])


def available() -> bool:
    return MODEL_PATH.is_file() and MODEL_PATH.stat().st_size == MODEL_BYTES


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load() -> Model:
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                if not available():
                    raise ModelError(f"model missing: {MODEL_PATH} (tools/fetch_phoneme_model.py)")
                if os.getenv("PHONEME_ONNX") is None and _sha256(MODEL_PATH) != MODEL_SHA256:
                    raise ModelError("model hash mismatch")
                import onnxruntime as ort

                so = ort.SessionOptions()
                so.intra_op_num_threads = max(1, min(4, os.cpu_count() or 1))
                so.inter_op_num_threads = 1
                so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
                sess = ort.InferenceSession(str(MODEL_PATH), so, providers=["CPUExecutionProvider"])
                raw = json.loads(VOCAB_PATH.read_text(encoding="utf-8"))
                vocab = [""] * (max(raw.values()) + 1)
                for sym, i in raw.items():
                    vocab[i] = sym
                _model = Model(session=sess, vocab=vocab, index=dict(raw))
    return _model
