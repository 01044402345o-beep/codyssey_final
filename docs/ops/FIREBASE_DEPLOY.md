# Firebase · Cloud Run 배포 (Render 와 역할 분담)

> 목표: **Hosting(정적·CDN) + Cloud Run(HTTP API) + Render(WebSocket 통역)** 로 역할을 자른다.
> 같은 엔드포인트를 양쪽에 두지 않는다 — 속도 제한·키 쿨다운이 프로세스 메모리라 두 벌이면 두 배로 약해진다
> (`docs/ops/API_KEY_AND_REQUEST_POLICY.md` §4).

## 지금 구성 (11/06) — Hosting(화면) + Render(API), Cloud Run 은 보류

| 무엇 | 어디서 | 비고 |
|---|---|---|
| 화면(`mockup/` 정적 파일) | **Firebase Hosting** `https://com-example-myapplicatio-3bb36.web.app` | `firebase deploy --only hosting` |
| HTTP API 전부(`/health` `/generate` `/research` `/place-check` `/place-photo` …) | **Render** `https://codyssey-final.onrender.com` | 화면이 `*.web.app`·`*.firebaseapp.com` 에서 열리면 `AI.apiBase` 가 Render 를 고른다(교차 출처) |
| 통역 WebSocket | **Render** `wss://codyssey-final.onrender.com/interp/stream` | `API.base` 에서 만든다 |
| Render 자체 화면 | `https://codyssey-final.onrender.com` | 그대로(같은 출처) |

- `firebase.json` 에는 **rewrite 가 없다** — 예전 rewrite 는 없는 Cloud Run 서비스(`codyssey-api`)로 보내 모든 API 가 실패했을 것이다.
- Hosting CSP(지금 Report-Only)의 `connect-src` 에 Render(https·wss), `img-src` 에 Render(`/place-photo`)·`*.googleusercontent.com`(Google 사진).
- Render 의 CORS 는 `ALLOW_ORIGINS` 가 비어 `*` 다(11/06 실측: `access-control-allow-origin: *`). 좁히려면
  `ALLOW_ORIGINS=https://codyssey-final.onrender.com,https://com-example-myapplicatio-3bb36.web.app,https://com-example-myapplicatio-3bb36.firebaseapp.com`.
- 로그인: Firebase Auth 승인 도메인에 `*.web.app`·`*.firebaseapp.com` 은 기본으로 들어 있다.

### Cloud Run 을 보류한 이유 — 마감(11/08 18:00)의 한계

아래 §2~§6 의 Cloud Run 구성은 **하지 않았다**(11/06 확인: `gcloud run services list` 0개). 마감 전에는 위험·비용이 이익보다 크다.

1. **요금제·비용**: Cloud Run·Cloud Build·Secret Manager 는 Blaze(종량제)가 필요하다. 이 앱은 인스턴스당 2Gi 메모리·2 CPU(onnxruntime·VAD 모델)라 `--min-instances 0` 이면 첫 요청이 느리고, 1 이면 상시 비용이 든다.
2. **비밀 13개 이전**: Gemini·Groq·OpenAI·AssemblyAI·Soniox·Azure·Firebase 서비스 계정 등 키를 Secret Manager 로 옮기고 전용 서비스 계정 권한을 줘야 한다 — 하나라도 빠지면 그 기능만 조용히 꺼진다.
3. **이미지 빌드 미검증**: `backend/Dockerfile` 은 한 번도 빌드해 본 적이 없다(첫 빌드 로그를 봐야 한다). 모델 파일·ffmpeg 포함 1GB 안팎.
4. **카운터 이중화**: 속도 제한·키 쿨다운·장소 생성 하루 한도(`place_quota`)·발음기호 기억이 **프로세스 메모리**라, Render 와 Cloud Run 이 같은 API 를 나눠 받으면 한도가 두 배로 약해지고 '하루 3번'이 지켜지지 않는다. 한쪽으로 모아야 한다.
5. **프록시 홉 재측정**: Hosting → Cloud Run 은 홉이 하나 더 생겨 `TRUSTED_PROXY_HOPS` 를 로그로 다시 정해야 한다(틀리면 모든 사용자가 한 IP).
6. **검증 시간**: 배포 뒤 통역 WS(`INTERP_WS_URL`)·로그인·음성 채점·음소 노드(Tailscale)·조사 잡 폴링을 모두 다시 확인해야 하는데, 마감 전 남은 시간으로는 Render 와 같은 수준의 확인이 안 된다.

**마감 뒤에 Cloud Run 으로 옮길 때**: §2~§6 순서대로 하고, `firebase.json` 에 API rewrite 를 되돌리고(`git log -- firebase.json` 의 11/06 이전 형태), `mockup/ai.js` 의 `HOSTED_API` 분기를 지워 같은 출처로 돌린다. 그 전에 위 4번(카운터를 한쪽으로)을 먼저 정한다.

## 0. 이 문서의 상태 (10/21 작성 — Cloud Run 준비 단계의 기록)

- **실제 배포는 아직 하지 않았다.** 이 작업 환경에는 `gcloud`·`firebase` CLI 가 없고(`exit 127`), GCP 자격증명도 없다.
- `backend/Dockerfile`·`firebase.json`·이 문서는 **배포 가능한 형태로 준비한 것**이고, 이미지 빌드는 이 환경에서 검증하지 못했다
  (도커 데몬 없음). 첫 배포에서 빌드 로그를 반드시 확인한다.
- 로컬에서 코드가 뜨는 것은 확인했다(`uvicorn app.main:app`, `/health` 200).
- **프로젝트는 `com-example-myapplicatio-3bb36`** — 운영 앱의 로그인·Firestore 프로젝트다(10/21 운영 `/auth/config` 의 projectId 로 확인).
  저장소의 `.firebaserc` 도 이 프로젝트를 가리킨다. 개발 PC 의 `firebase use` 가 다른 프로젝트(예: `gunsan-university-daily-check`)로 되어 있으면
  배포 전에 `firebase use com-example-myapplicatio-3bb36` 으로 바꾼다 — 다른 프로젝트에 올리면 로그인·Firestore 가 이어지지 않는다.
- **Blaze(종량제) 요금제가 필요하다**(Cloud Run·Cloud Build·Secret Manager). 프로젝트 소유자가 콘솔에서 결제 계정을 연결한다.
- `firebase.json` 은 기존 Firestore 규칙 배포 설정(`firestore.rules`)을 그대로 두고 `hosting` 을 더했다. `firebase deploy` 를 인자 없이 하면 **규칙도 같이 배포**되므로 아래처럼 `--only` 를 쓴다.

## 1. 무엇이 어디로 가는가

| 경로 | 어디서 | 비고 |
|---|---|---|
| `/`, `/app.js`, `/styles.css`, 이미지 | Firebase Hosting (`mockup/`) | CDN. `no-cache` 는 `app.js`·`index.html` 만 |
| `/health` `/generate` `/itinerary` `/speak-check` `/interp/providers` `/auth/**` `/user/**` `/account/**` `/diagnostics/**` | Cloud Run `codyssey-api` (Hosting rewrite) | `firebase.json` 의 rewrites |
| `wss://.../interp/stream` | **Hosting 을 거치지 않는다** | Hosting 은 WS 업그레이드를 중계하지 못한다(404/400). Cloud Run 직접 URL 또는 Render |

프론트는 `API.base` 로 서버 주소를 정한다(`mockup/app.js`, `AI.apiBase`). Hosting 도메인에서 열면 같은 오리진(`''`)이라
HTTP API 는 rewrite 로 Cloud Run 에 간다. **통역 WebSocket 은 Cloud Run 의 `INTERP_WS_URL` 환경변수**로 정한다 —
`/interp/providers` 가 그 값을 `ws_url` 로 내려 주고, 화면은 있으면 그 주소로 WebSocket 을 연다(없으면 화면과 같은 서버).
예: `INTERP_WS_URL=wss://codyssey-api-<hash>-du.a.run.app/interp/stream`(Cloud Run 직접 URL) 또는 Render 주소.

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
  --set-env-vars "^|^INTERP_PROVIDERS=soniox|ALLOW_ORIGINS=https://<PROJECT_ID>.web.app,https://<PROJECT_ID>.firebaseapp.com|TRUSTED_PROXY_HOPS=1|GIT_COMMIT=$(git rev-parse --short HEAD)"
```

- **`--concurrency 4`**: 이 앱은 요청마다 최대 30회 AI 시도를 하고 VAD 모델을 메모리에 올린다. 80(기본)이면 한 인스턴스가 죽는다.
- **`--timeout 900`**: `/generate` 가 30회 시도로 길어진다. Hosting rewrite 도 같은 한도를 넘으면 504 다.
- **`--memory 2Gi`**: onnxruntime + azure SDK + faster-whisper. 512Mi 에서는 OOM 이 난다.
- **`--set-env-vars "^|^..."`**: 값에 쉼표가 있으면(`ALLOW_ORIGINS` 두 도메인) gcloud 기본 구분자 `,` 와 겹친다. `^|^` 로 구분자를 `|` 로 바꾼다.
- **`INTERP_WS_URL`** 은 첫 배포로 Cloud Run URL 을 안 다음에 넣는다:
  `gcloud run services update codyssey-api --region asia-northeast3 --update-env-vars INTERP_WS_URL=wss://<서비스 URL 호스트>/interp/stream`
- **`TRUSTED_PROXY_HOPS=1`** 은 **출발점일 뿐**이다. 배포 직후 `/health` 대신 **로그**의
  `프록시 확인: 연결 상대=..., X-Forwarded-For=...` 한 줄을 보고 다시 정한다(Hosting→Cloud Run 이면 홉이 하나 더 늘 수 있다).

## 5. Hosting

```bash
firebase use com-example-myapplicatio-3bb36
firebase deploy --only hosting      # 규칙까지 바꿀 때만 --only hosting,firestore
```

- `firebase.json` 의 `public` 은 `mockup/` 이다. 저장소의 `mockup/index.html` 이 그대로 정적 파일로 나간다.
- rewrite 는 **API 경로만** Cloud Run 으로 보낸다. 나머지는 정적 파일.
- `pinTag` 는 쓰지 않았다(태그 1,000개 한도, 롤백 결합). 필요하면 `run` 블록에 `"pinTag": true`.

## 6. 배포 후 확인 (순서대로)

```bash
curl -s -H "X-Admin-Token: $HEALTH_DETAIL_TOKEN" https://<PROJECT_ID>.web.app/health | jq '{status, deploy, security_review, gemini_keys}'   # 상세는 관리자 토큰으로만(공개 응답은 status·deploy.commit 등 최소 필드)
curl -s -o /dev/null -w '%{http_code}\n' https://<PROJECT_ID>.web.app/generate -X POST   # 422(검증 실패)면 라우팅 성공
curl -s https://<PROJECT_ID>.web.app/interp/providers | jq '[.providers[]|{id,available}]'
```

- `security_review.warnings` 가 비어 있지 않으면 **의도한 상태인지 확인**한다(`ALLOW_ORIGINS`·`TRUSTED_PROXY_HOPS`).
- `/health` 의 `deploy`: Render 면 `platform: render`·`commit`(RENDER_GIT_COMMIT), Cloud Run 이면 `platform: cloud-run`·`revision`(K_REVISION)·`commit`(배포 때 넣은 `GIT_COMMIT`).
- `curl -s https://<PROJECT_ID>.web.app/interp/providers | jq .ws_url` 이 `wss://...run.app/interp/stream` 이면 통역 WS 가 Hosting 을 우회한다.

## 7. 알려진 위험 (배포 전에 반드시 볼 것)

| 위험 | 내용 | 대응 |
|---|---|---|
| 이미지 크기·cold start | torch 계열은 안 쓰지만 onnxruntime + azure SDK + ffmpeg 로 1GB 안팎. 첫 요청에 모델 초기화가 붙는다 | `--min-instances 1`(비용) 또는 `/health` 워밍업 |
| 모델 파일 위치 | `backend/app/models/pyannote-segmentation-3.0.onnx` 는 **저장소에 있고**(10/21 확인) `COPY backend` 로 이미지에 들어간다(`.dockerignore` 는 `.onnx` 를 빼지 않는다). Silero VAD 는 faster-whisper 패키지 안에 있다 | 배포 후 `/health` 의 `cross_validation_ready`·`speech_detectors` 로 한 번 더 확인 |
| `/generate` 무인증 | Hosting 도메인이 공개되면 누구나 호출 | `ALLOW_ORIGINS` 좁히기 + 예산 알림(`API_KEY_AND_REQUEST_POLICY.md` §2) |
| 카운터 분리 | Render 와 Cloud Run 이 각자 속도 제한·키 쿨다운을 센다 | 경로를 겹치지 않게(§1). 합칠 거면 Render 쪽 `/generate` 를 끈다 |
| WS 는 Hosting 불가 | 위 §1 | `INTERP_WS_URL` 로 직접 URL(§4) |
| 서비스 계정 JSON | 장기 자격증명이 Secret Manager 에 있어도 권한이 넓다 | 전용 SA + 최소 권한, 90일 회전 |

## 8. 되돌리기

- Cloud Run: `gcloud run services update-traffic codyssey-api --to-revisions=<이전 리비전>=100`
- Hosting: `firebase hosting:rollback`
- Render 는 그대로 살아 있으므로, Hosting 을 내려도 서비스는 유지된다(이중화의 실익).

## 정책 환경변수 반영 (opsarchive)
opsarchive 관리자 도구의 `[Cloud Run에 반영]`(또는 `python -m opsarchive policy-apply --target cloudrun`)이 정책 노드의
`EVIDENCE_*` 값 중 **바뀐 것만** 이 서비스에 올리고 새 리비전을 기다린 뒤 반영을 확인한다. gcloud 로그인 계정의 토큰으로
Cloud Run Admin API 를 부르며, 다른 변수와 Secret Manager 참조는 건드리지 않는다. 비밀 값은 Secret Manager 에 둔다.
