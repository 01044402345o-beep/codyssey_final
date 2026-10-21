# API 키 관리·요청 정책 검토 + Firebase(Cloud Run) 배포 준비

## 1. 검토 (`docs/ops/API_KEY_AND_REQUEST_POLICY.md`)

키 자체는 깨끗하다 — 전부 환경변수, 저장소에 키 파일 없음, 로그에 키 값 없음(번호만). 문제는 **키를 쓰는 문**이다.

| 심각도 | 발견 | 근거 |
|---|---|---|
| P1 | `/generate` 가 **로그인 없이** 호출 가능 | `main.py:470` (통역은 게이트 있음) |
| P1 | `FIREBASE_SERVICE_ACCOUNT_JSON` — 장기 자격증명을 환경변수로 | `render.yaml` |
| P1 | `FIREBASE_API_KEY` 제한 여부 미확인(공개 키지만 제한 없으면 남용 가능) | `firebase_auth.py:35` |
| P2 | 속도 제한·키 쿨다운이 **프로세스 메모리** | `main.py:130`, `gemini._key_cooldown` |
| P2 | `TRUSTED_PROXY_HOPS=0` 기본 — 프록시 뒤에서 전체가 한 버킷 | `main.py:97` |
| P3 | `/health` 가 키 회전 상태를 노출(값 아님) | `gemini.key_health()` |

핵심 결론: **지금 구조로 백엔드를 두 벌 띄우면 정책이 두 배로 약해진다**(제한 20→40/분, 쿨다운 백엔드별).
그래서 역할을 자르는 설계를 전제로 했다.

## 2. Firebase 확인 사실 두 가지

- **Hosting rewrite 로 WebSocket 은 안 된다**(404/400). `/interp/stream` 은 Hosting 을 거치지 않고 Cloud Run 직접 URL 또는 Render 로 붙여야 한다.
- Cloud Run WebSocket 은 요청 타임아웃(최대 60분)을 따르고, 연결이 열린 동안 인스턴스 과금이다.

## 3. 배포 준비물

- `backend/Dockerfile` — python:3.11-slim + ffmpeg/libgomp1/libasound2/libssl3, 비루트, `$PORT`.
- `firebase.json` — `public: mockup`, API 경로만 Cloud Run rewrite(11개), `app.js`·`index.html` 만 no-cache.
- `docs/ops/FIREBASE_DEPLOY.md` — Secret Manager 이전, gcloud 명령, 배포 후 확인, 위험·되돌리기.

**배포는 하지 않았다.** 이 환경에 `gcloud`·`firebase` CLI 가 없고(`exit 127`) GCP 자격증명도 없다.
이미지 빌드도 검증하지 못했다(도커 없음) — 첫 배포에서 빌드 로그를 봐야 한다.

## 4. 코드 변경 (동작 불변)

`/health` 에 `security_review` 블록 추가 — 경고만 담고 라우팅·제한은 건드리지 않는다.
키 값은 테스트로 노출 없음을 고정했다(`test_security_review` 4/4).

## 5. 검증

- 백엔드 전체 통과, `test_security_review` 4/4, `/health` 부팅 스모크 200.
- `firebase.json` JSON 파싱 확인.
