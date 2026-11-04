# 음소 노드를 클라우드에 띄우는 컨테이너 — Hugging Face Spaces(Docker)·Cloud Run 등.
# PC 노드와 같은 코드·모델·토큰이다. 주소를 PHONEME_REMOTE_URLS 맨 뒤에 넣으면 PC 가 모두 꺼졌을 때 이어받는다.
#
#   저장소 루트에서:  docker build -f backend/phoneme-node/Dockerfile -t madi-phoneme-node .
#   실행:            docker run -e PHONEME_TOKEN=<24자 이상> -p 7860:7860 madi-phoneme-node
#
# 이미지 안에 모델(317MB, SHA256 확인)을 빌드 때 받아 둔다 — 콜드 스타트 때 내려받지 않게.
# 주의: 공개 Space 는 소스가 보인다. 토큰은 Space 의 Secrets(PHONEME_TOKEN)로만 넣고 이미지에 넣지 않는다.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    PHONEME_HOST=0.0.0.0 PHONEME_PORT=7860 PYTHONPATH=/app/backend
WORKDIR /app

COPY backend/phoneme-node/requirements-phoneme.txt backend/phoneme-node/requirements-phoneme.txt
RUN pip install -r backend/phoneme-node/requirements-phoneme.txt

# 노드에 필요한 것만: 음향 패키지·발음 사전·토큰화(phonemes·speech_compare)·모델 받기 도구
COPY backend/app/__init__.py backend/app/__init__.py
COPY backend/app/acoustic backend/app/acoustic
COPY backend/app/lexicon backend/app/lexicon
COPY backend/app/phonemes.py backend/app/speech_compare.py backend/app/
COPY tools/fetch_phoneme_model.py tools/fetch_phoneme_model.py
RUN python tools/fetch_phoneme_model.py

RUN useradd -m -u 1000 node && chown -R node:node /app
USER node
EXPOSE 7860
CMD ["python", "-m", "app.acoustic.server"]
