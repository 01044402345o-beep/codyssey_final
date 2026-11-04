"""실제 소리 → 음소 감지(음향). app/phonemes.py(받아쓴 글자 기준)와 짝이다.

  g2p     목표 문장 → 음소(IPA). 사전은 app/lexicon/cmudict.dict.gz
  model   wav2vec2-lv-60-espeak-cv-ft int8 ONNX(Apache-2.0) → 프레임별 음소 확률
  align   CTC 강제정렬(목표 음소가 소리의 어디에 있었는지)
  score   음소별 GOP · 대체음(heard_as) · 한국어 조음 안내
  server  상시 가동 PC 에서 뜨는 음소 노드(/phoneme-check). 본체(Render 무료)는 모델을 올리지 않는다
  remote  본체가 노드를 부르는 클라이언트

본체는 remote 만 import 한다 — onnxruntime·모델을 읽지 않는다.
"""
