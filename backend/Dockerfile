# Cloud Run / Firebase 용 이미지 (Render 는 render.yaml 의 python 런타임을 그대로 쓴다).
# 앱은 저장소 루트를 기준으로 backend/ 와 mockup/ 을 함께 읽는다(CONTRACT_DIR·WEB_DIR 이 상대 경로).
#   docker build -f backend/Dockerfile -t codyssey-api .
FROM python:3.11-slim

# ffmpeg: PyAV 디코드, libgomp1: onnxruntime, libasound2/libssl3: azure-cognitiveservices-speech
RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg libgomp1 libasound2 libssl3 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend backend
COPY mockup mockup
COPY agent_contract agent_contract

# 루트 사용자로 돌리지 않는다. Cloud Run 은 $PORT 를 준다.
RUN useradd -m -u 10001 appuser && chown -R appuser:appuser /app
USER appuser
ENV PORT=8080
EXPOSE 8080
WORKDIR /app/backend
# --no-proxy-headers: uvicorn 이 X-Forwarded-For 로 클라이언트 주소를 바꾸지 않게 한다.
# 예전 --forwarded-allow-ips="*" 는 헤더의 맨 왼쪽(사용자가 넣는 값)을 IP 로 써서 속도 제한을 위조로 우회할 수 있었다(10/23 #3).
# 사용자 IP 는 main.client_ip 가 TRUSTED_PROXY_HOPS(Cloud Run 직접 접속 = 1)로 헤더 끝에서 센다.
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080} --no-proxy-headers
