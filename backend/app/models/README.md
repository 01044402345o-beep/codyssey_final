# 내장 모델

| 파일 | 출처 | 라이선스 | SHA256 |
|---|---|---|---|
| `pyannote-segmentation-3.0.onnx` (5,986,908 B) | [onnx-community/pyannote-segmentation-3.0](https://huggingface.co/onnx-community/pyannote-segmentation-3.0) `onnx/model.onnx` — [pyannote/segmentation-3.0](https://huggingface.co/pyannote/segmentation-3.0) 의 ONNX 변환 | MIT | `057ee564753071c0b09b5b611648b50ac188d50846bff5f01e9f7bbf1591ea25` |

두 번째 말소리 검출기(Silero 와 다른 신경망)로 쓴다. 서버가 불러올 때 SHA256 을 확인한다(`app/speech_vad.py`).
입력 `input_values` (batch, 1, samples@16kHz), 출력 `logits` (batch, frames, 7) — powerset log-softmax, 0번 클래스 = 말소리 없음.
pyannote 추론과 같이 10초 창, 남는 부분은 0 으로 채우고, 프레임별 argmax ≠ 0 을 말소리로 본다.

배경: pyannoteAI 클라우드 API 는 계정 크레딧 없음(HTTP 402)으로 모든 요청이 실패해 로컬 모델로 바꿨다(2026-10-08).
