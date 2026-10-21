# Firebase · Cloud Run 배포 (Render 와 역할 분담)

> 목표: **Hosting(정적·CDN) + Cloud Run(HTTP API) + Render(WebSocket 통역)** 로 역할을 자른다.
> 같은 엔드포인트를 양쪽에 두지 않는다 — 속도 제한·키 쿨다운이 프로세스 메모리라 두 벌이면 두 배로 약해진다
> (`docs/ops/API_KEY_AND_REQUEST_POLICY.md` §4).

## 0. 이 문서의 상태

- **실제 배포는 아직 하지 않았다.** 이 작업 환경에는 `gcloud`·`firebase` CLI 가 없고(`exit 127`), GCP 자격증명도 없다.
- `backend/Dockerfile`·`firebase.json`·이 문서는 **배포 가능한 형태로 준비한 것**이고, 이미지 빌드는 이 환경에서 검증하지 못했다
  (도커 데몬 없음). 첫 배포에서 빌드 로그를 반드시 확인한다.
- 로컬에서 코드가 뜨는 것은 확인했다(`uvicorn app.main:app`, `/health` 200).

## 1. 무엇이 어디로 가는가

| 경로 | 어디서 | 비고 |
|---|---|---|
| `/`, `/app.js`, `/styles.css`, 이미지 | Firebase Hosting (`mockup/`) | CDN. `no-cache` 는 `app.js`·`index.html` 만 |
| `/health` `/generate` `/itinerary` `/speak-check` `/interp/providers` `/auth/**` `/user/**` `/account/**` `/diagnostics/**` | Cloud Run `codyssey-api` (Hosting rewrite) | `firebase.json` 의 rewrites |
| `wss://.../interp/stream` | **Hosting 을 거치지 않는다** | Hosting 은 WS 업그레이드를 중계하지 못한다(404/400). Cloud Run 직접 URL 또는 Render |

프론트는 `API.base` 로 서버 주소를 정한다(`mockup/app.js`, `AI.apiBase`). 한 백엔드로 합칠 거면 `API.base` 를 Hosting 오리진으로,
통역만 직접 URL 로 두려면 `wsBase` 를 따로 두는 변경이 필요하다 — **이번 커밋에는 넣지 않았다**(서버 배포가 먼저다).

## 2. 준비 (한 번)

```bash
gcloud auth login
gcloud config set project <PROJECT_ID>
gcloud services enable run.googleapis.com cloudbuild.googleapis.com secretmanager.googleapis.com artifactregistry.googleapis.com
firebase login
```

## 3. 키를 Secret Manager 로 (환경변수보다 강함)

`render.yaml` 이 `sync: false` 로 받는 값과 **같은 이름**을 쓴다.

```bash
for S in GEMINI_API_KEY GEMINI_API_KEY_FALLBACK SONIOX_API_KEY OPENAI_API_KEY \
         GROQ_API_KEY ASSEMBLYAI_API_KEY AZURE_SPEECH_KEY AZURE_SPEECH_REGION \
         FIREBASE_API_KEY FIREBASE_AUTH_DOMAIN FIREBASE_PROJECT_ID FIREBASE_APP_ID \
         FIREBASE_SERVICE_ACCOUNT_JSON; do
  read -rsp "$S: " V; printf '%s' "$V" | gcloud secrets create "$S" --data-file=- 2>/dev/null \
    || printf '%s' "$V" | gcloud secrets versions add "$S" --data-file=-
done
```

서비스 계정에 접근 권한을 준다(전용 SA 권장):

```bash
gcloud iam service-accounts create codyssey-run
for S in GEMINI_API_KEY GEMINI_API_KEY_FALLBACK SONIOX_API_KEY OPENAI_API_KEY \
         GROQ_API_KEY ASSEMBLYAI_API_KEY AZURE_SPEECH_KEY AZURE_SPEECH_REGION \
         FIREBASE_API_KEY FIREBASE_AUTH_DOMAIN FIREBASE_PROJECT_ID FIREBASE_APP_ID \
         FIREBASE_SERVICE_ACCOUNT_JSON; do
  gcloud secrets add-iam-policy-binding "$S" \
    --member="serviceAccount:codyssey-run@<PROJECT_ID>.iam.gserviceaccount.com" \
    --role="roles/secretmanager.secretAccessor" --quiet
done
```

## 4. Cloud Run 배포

이미지는 저장소 루트 기준이다(`backend/`·`mockup/`·`agent_contract/` 를 함께 COPY).

```bash
gcloud builds submit --tag asia-northeast3-docker.pkg.dev/<PROJECT_ID>/app/codyssey-api:$(git rev-parse --short HEAD) \
  --file backend/Dockerfile .

gcloud run deploy codyssey-api \
  --image asia-northeast3-docker.pkg.dev/<PROJECT_ID>/app/codyssey-api:<SHA> \
  --region asia-northeast3 --allow-unauthenticated \
  --service-account codyssey-run@<PROJECT_ID>.iam.gserviceaccount.com \
  --memory 2Gi --cpu 2 --concurrency 4 --timeout 900 \
  --min-instances 0 --max-instances 3 \
  --set-secrets GEMINI_API_KEY=GEMINI_API_KEY:latest,GEMINI_API_KEY_FALLBACK=GEMINI_API_KEY_FALLBACK:latest,SONIOX_API_KEY=SONIOX_API_KEY:latest,OPENAI_API_KEY=OPENAI_API_KEY:latest,GROQ_API_KEY=GROQ_API_KEY:latest,ASSEMBLYAI_API_KEY=ASSEMBLYAI_API_KEY:latest,AZURE_SPEECH_KEY=AZURE_SPEECH_KEY:latest,AZURE_SPEECH_REGION=AZURE_SPEECH_REGION:latest,FIREBASE_API_KEY=FIREBASE_API_KEY:latest,FIREBASE_AUTH_DOMAIN=FIREBASE_AUTH_DOMAIN:latest,FIREBASE_PROJECT_ID=FIREBASE_PROJECT_ID:latest,FIREBASE_APP_ID=FIREBASE_APP_ID:latest,FIREBASE_SERVICE_ACCOUNT_JSON=FIREBASE_SERVICE_ACCOUNT_JSON:latest \
  --set-env-vars INTERP_PROVIDERS=soniox,ALLOW_ORIGINS=https://<PROJECT_ID>.web.app,TRUSTED_PROXY_HOPS=1,PYTHON_VERSION=3.11.9
```

- **`--concurrency 4`**: 이 앱은 요청마다 최대 30회 AI 시도를 하고 VAD 모델을 메모리에 올린다. 80(기본)이면 한 인스턴스가 죽는다.
- **`--timeout 900`**: `/generate` 가 30회 시도로 길어진다. Hosting rewrite 도 같은 한도를 넘으면 504 다.
- **`--memory 2Gi`**: onnxruntime + azure SDK + faster-whisper. 512Mi 에서는 OOM 이 난다.
- **`TRUSTED_PROXY_HOPS=1`** 은 **출발점일 뿐**이다. 배포 직후 `/health` 대신 **로그**의
  `프록시 확인: 연결 상대=..., X-Forwarded-For=...` 한 줄을 보고 다시 정한다(Hosting→Cloud Run 이면 홉이 하나 더 늘 수 있다).

## 5. Hosting

```bash
firebase deploy --only hosting
```

- `firebase.json` 의 `public` 은 `mockup/` 이다. 저장소의 `mockup/index.html` 이 그대로 정적 파일로 나간다.
- rewrite 는 **API 경로만** Cloud Run 으로 보낸다. 나머지는 정적 파일.
- `pinTag` 는 쓰지 않았다(태그 1,000개 한도, 롤백 결합). 필요하면 `run` 블록에 `"pinTag": true`.

## 6. 배포 후 확인 (순서대로)

```bash
curl -s https://<PROJECT_ID>.web.app/health | jq '{status, deploy, security_review, gemini_keys}'
curl -s -o /dev/null -w '%{http_code}\n' https://<PROJECT_ID>.web.app/generate -X POST   # 422(검증 실패)면 라우팅 성공
curl -s https://<PROJECT_ID>.web.app/interp/providers | jq '[.providers[]|{id,available}]'
```

- `security_review.warnings` 가 비어 있지 않으면 **의도한 상태인지 확인**한다(`ALLOW_ORIGINS`·`TRUSTED_PROXY_HOPS`).
- `/health` 의 `deploy.commit` 은 **Render 값**(`RENDER_GIT_COMMIT`)만 채운다. Cloud Run 에서는 null 이다 —
  배포 식별이 필요하면 `K_REVISION` 을 함께 쓰도록 고쳐야 한다(이번엔 넣지 않음).

## 7. 알려진 위험 (배포 전에 반드시 볼 것)

| 위험 | 내용 | 대응 |
|---|---|---|
| 이미지 크기·cold start | torch 계열은 안 쓰지만 onnxruntime + azure SDK + ffmpeg 로 1GB 안팎. 첫 요청에 모델 초기화가 붙는다 | `--min-instances 1`(비용) 또는 `/health` 워밍업 |
| 모델 파일 위치 | `pyannote segmentation-3.0 (local onnx)` 를 **런타임에 내려받는지** 저장소에 있는지 확인하지 못했다. 이미지에 없으면 교차검증이 조용히 꺼진다 | 배포 후 `/health` 의 `cross_validation_ready`·`speech_detectors` 확인 |
| `/generate` 무인증 | Hosting 도메인이 공개되면 누구나 호출 | `ALLOW_ORIGINS` 좁히기 + 예산 알림(`API_KEY_AND_REQUEST_POLICY.md` §2) |
| 카운터 분리 | Render 와 Cloud Run 이 각자 속도 제한·키 쿨다운을 센다 | 경로를 겹치지 않게(§1). 합칠 거면 Render 쪽 `/generate` 를 끈다 |
| WS 는 Hosting 불가 | 위 §1 | 통역은 직접 URL |
| 서비스 계정 JSON | 장기 자격증명이 Secret Manager 에 있어도 권한이 넓다 | 전용 SA + 최소 권한, 90일 회전 |

## 8. 되돌리기

- Cloud Run: `gcloud run services update-traffic codyssey-api --to-revisions=<이전 리비전>=100`
- Hosting: `firebase hosting:rollback`
- Render 는 그대로 살아 있으므로, Hosting 을 내려도 서비스는 유지된다(이중화의 실익).
