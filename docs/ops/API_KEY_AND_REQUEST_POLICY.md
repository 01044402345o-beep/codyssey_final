# API 키 관리·요청 정책 검토 (10/21)

> 근거: 팀 `main` `4ff695a` 코드 + 운영 `/health` 응답 + [Genkit Firebase 배포 문서](https://genkit.dev/docs/js/deployment/firebase/)의 권고.
> **이 문서는 검토이지 인증이 아니다.** 법률·보안 감사가 아니고, 실제 침투 시험도 하지 않았다.

## 0. 요약

키는 **코드·저장소에 없다**(전부 환경변수). 잘한 부분이다. 문제는 **키를 쓰는 문 앞**이다 —
비싼 생성 엔드포인트가 로그인도 App Check 도 없이 열려 있고, CORS 기본값이 `*` 이며,
속도 제한과 키 쿨다운이 **프로세스 메모리**라 인스턴스가 늘면 같이 약해진다.
Firebase 로 백엔드를 하나 더 띄우면 그 약점이 **2배**가 된다(§4).

## 1. 지금 상태 (사실)

| 항목 | 값 | 근거 |
|---|---|---|
| 키 보관 | 환경변수만. 저장소에 `.env`·키 파일 없음 | `backend/app/gemini.py:153`, `render.yaml`(`sync: false`) |
| 키 로그 노출 | 없음. `주 키`·`예비 키 n` 번호만 | `gemini.py` 키 상태 주석·`/health` |
| 키 회전 | 주 키 → 예비 키, 풀리면 복귀 | PR #138 |
| CORS | **`*` (기본값)** | `main.py:125-127` |
| `/generate` 인증 | **없음** (로그인·토큰 확인 없이 호출 가능) | `main.py:470` |
| `/interp/stream` 인증 | 있음(로그인) + 10분 6회·3분 상한 | `main.py:862`, `interp.py:49` |
| 속도 제한 | 20회/60초, **프로세스 메모리** | `main.py:92-93, 130-131`(코드 주석이 스스로 "임시 방어") |
| 프록시 신뢰 | `TRUSTED_PROXY_HOPS` 기본 **0** | `main.py:97` |
| 서비스 계정 | `FIREBASE_SERVICE_ACCOUNT_JSON` **전체 JSON 을 환경변수로** | `render.yaml` |

## 2. 위험 (심각도 순)

### P1 — `/generate` 가 열려 있다 (비용)
Genkit 문서가 첫 경고로 드는 것이 이것이다: *"without one, anyone can invoke your potentially-expensive generative AI flows"*.
권고는 모든 생성 엔드포인트에 `authPolicy` 를 두는 것(`hasClaim('email_verified')`).
우리는 통역에는 게이트를 걸었는데 **문장 생성에는 안 걸었다.** 요청당 Gemini 호출이 최소 30회 시도까지 갈 수 있어
(`min_attempts`) 한 번의 악용이 곧 quota 소진이다.

- 지금 완화책: IP당 20/60초. 하지만 IP는 값싸게 바뀌고, 브라우저에서 임의 사이트가 CORS `*` 로 직접 부를 수 있다.
- 권고: ① `GENERATE_REQUIRE_LOGIN=1` 같은 **opt-in 게이트**를 만들어 2차 테스트 뒤 켠다.
  ② 켜기 전까지는 `ALLOW_ORIGINS` 를 실제 도메인으로 좁힌다(§3-1). ③ 예산 알림을 건다(GCP 결제 알림).

### P1 — 서비스 계정 JSON 을 환경변수로 둔다
`FIREBASE_SERVICE_ACCOUNT_JSON` 은 **장기 자격증명**이고, 탈퇴 경로라 권한이 넓다(사용자 삭제).
Render 대시보드 권한이 있는 사람·로그·백업 어디로든 복제될 수 있다. GCP 로 옮기면 **키 없는 인증**(Workload Identity)이 가능하다.
Render 에 남길 경우: 전용 서비스 계정 + `firebaseauth.users.delete` 정도로 최소 권한, 90일 회전.

### P1 — `FIREBASE_API_KEY` 는 공개 키다
이 값은 비밀이 아니지만 **제한이 없으면** 남이 우리 프로젝트로 가입·로그인을 시도할 수 있다(Identity Toolkit).
Firebase 콘솔 → API 키 → **HTTP 리퍼러 제한 + Identity Toolkit API 로 제한**. `render.yaml` 의 `FIREBASE_API_KEY` 는 그대로 두되
"비밀"로 착각하지 않게 문서에 명시한다.

### P2 — 속도 제한·키 쿨다운이 프로세스 메모리
- `_hits` 는 인스턴스마다 따로다. Cloud Run 이 3개로 늘면 실효 제한은 60/분이 된다.
- `gemini._key_cooldown` 도 프로세스 메모리다. **백엔드가 둘이 되면** 한쪽이 주 키를 429 로 미뤄도 다른 쪽은 계속 주 키를 쓴다.
  → "주 키가 막히면 예비 키로, 풀리면 복귀"라는 약속이 **백엔드별로 따로** 성립한다. 이건 Firebase 이전의 직접 비용이다(§4).
- 권고: 두 백엔드 중 **한쪽만 키를 갖게** 하거나(§4 설계), 쿨다운을 Firestore 로 옮긴다.

### P2 — `TRUSTED_PROXY_HOPS=0` + 관리형 플랫폼
프록시 뒤에서 0 이면 `request.client.host` 는 프록시 IP 하나로 보인다 → **모든 사용자가 한 버킷**을 공유해
"20회/60초"가 사실상 **전체 20회/60초**가 된다(더 엄격해지는 쪽이라 보안 사고는 아니지만 서비스가 죽는다).
Firebase Hosting 을 앞에 두면 홉 수가 **또 바뀐다**(Hosting + Cloud Run). 배포 후 `/health` 로그의
`프록시 확인: ... TRUSTED_PROXY_HOPS=` 한 줄로 다시 정해야 한다(`DEPLOY_RUNBOOK.md` F14 절차 그대로).

### P3 — `/health` 가 운영 상태를 말한다
`gemini_keys.active: "예비 키 1"`, `cooling.reason` — 키 값은 아니지만 **언제 주 키가 막혔는지**를 알려 준다.
공격자에게 유용한 정보는 아니고 디버깅 가치가 더 크다고 판단해 남긴다. 다만 `has_api_key` 와 함께
"설정이 살아 있음"을 확인하는 정찰 신호가 된다는 점은 알고 있어야 한다.

### P3 — App Check 에 해당하는 것이 없다
Genkit 문서는 `enforceAppCheck: true`, `consumeAppCheckToken: true` 를 권한다. 우리 웹 앱은 순수 정적 파일이라
App Check(reCAPTCHA Enterprise)를 붙이면 **우리 앱에서 온 요청**임을 증명할 수 있다. 지금은 아무 브라우저나 호출 가능.

## 3. 바로 할 수 있는 것 (코드 변경 없이)

1. **`ALLOW_ORIGINS` 를 실제 도메인으로** — Render·Firebase 도메인 두 개만. 현재 미설정이면 `*`.
2. **GCP 결제 예산 알림**(월 $X, 50/90/100%). 키가 새도 청구서로 먼저 안다.
3. **Gemini 키 등급 확인** — 예비 키가 무료 등급이면 처리방침 3절과 어긋난다(PR #138 주의사항 그대로).
4. **서비스 계정 최소 권한 + 회전 주기** 문서화.
5. **`TRUSTED_PROXY_HOPS` 재측정** — 백엔드를 옮길 때마다.

## 4. Firebase 로 백엔드를 하나 더 띄울 때의 정책 영향 (중요)

"Render 와 상호보완"은 맞는 방향이지만, **지금 구조 그대로 두 벌을 띄우면 정책이 약해진다**:

| 항목 | 백엔드 1개 | 2개(현 구조) |
|---|---|---|
| 속도 제한 20/60s | IP당 20 | **IP당 40** (인스턴스별 카운터) |
| 키 쿨다운 | 전역 1개 | **백엔드별 1개** → 서로 다른 키를 쓴다 |
| 통역 시작 제한 6/10분 | IP·계정당 6 | **12** (`interp.py` 도 메모리) |
| 비용 추적 | `/health` 한 곳 | 두 곳의 로그를 합쳐야 함 |

그래서 이전 설계는 **역할을 자르는 것**이어야 한다(아래 표). 같은 엔드포인트를 양쪽에 두지 않는다.

| 역할 | 어디 | 이유 |
|---|---|---|
| 정적 앱(HTML/CSS/JS) | **Firebase Hosting** | CDN·커스텀 도메인·무료 |
| HTTP API(`/generate`·`/speech`·계정) | **Cloud Run**(Hosting rewrite) | 0으로 스케일, 초 단위 과금, Secret Manager |
| WebSocket `/interp/stream` | **Render** (또는 Cloud Run 직접 URL) | Hosting rewrite 는 WS 업그레이드를 중계하지 못한다(§5) |

이렇게 자르면 카운터가 겹치는 문제가 사라진다(경로가 다르므로).

## 5. 확인된 제약 두 가지 (근거)

1. **Firebase Hosting rewrite 로는 WebSocket 이 안 된다.**
   Hosting 은 CDN 이고 요청을 스트리밍하지 않는다. 실제 사례: rewrite 로 붙이면 `101 Switching Protocols` 대신 **404**,
   NiceGUI 사례에서는 **400**. Cloud Run 에 직접 붙이면 정상.
   → `/interp/stream` 은 **Hosting 을 거치지 않는다.** 앱은 통역만 Cloud Run/Render 의 직접 URL(`wss://...run.app`)로 붙어야 한다.
   ([StackOverflow 답변](https://stackoverflow.com/questions/70064955/is-it-possible-to-rewrite-websocket-requests-when-using-firebase-hosting), [NiceGUI #3563](https://github.com/zauberzeug/nicegui/discussions/3563))
2. **Cloud Run 의 WebSocket 은 요청 타임아웃을 따른다**(최대 60분, 기본 5분). 연결이 열려 있는 동안은 **인스턴스 과금**이다.
   우리 통역은 세션 상한 3분이라 문제 없지만, "계속 듣기"를 늘리면 요금 구조가 달라진다.
   ([Cloud Run WebSocket 문서](https://docs.cloud.google.com/run/docs/triggering/websockets))

## 6. 팀이 정할 것

1. `/generate` 에 로그인을 요구할지 — 2차 테스트(비로그인 참가자)와 충돌한다. **게스트 허용 + 강한 제한**이 현실적.
2. 백엔드를 둘로 나눌지, Cloud Run 하나로 합칠지 — 합치면 위 카운터 문제가 사라지고, 나누면 Render 의 상시성을 쓴다.
3. App Check 도입 여부 — 웹 앱이 정적이라 붙이기 쉽다. 도입하면 `enforceAppCheck` 상당의 게이트를 `/generate` 에 걸 수 있다.
4. 서비스 계정을 Workload Identity 로 옮길지(권장).

## 7. 이번 검토에서 코드로 반영한 것

`/health` 에 `security_review` 블록을 추가했다. **경고만** 담고 동작은 바꾸지 않는다 —
운영에서 무엇이 열려 있는지 매 배포마다 눈에 보이게 하려는 것이다. 키 이름·값은 여기에도 넣지 않는다.
