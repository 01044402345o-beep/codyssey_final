# 요구사항 정의서 (현행)

| 항목 | 내용 |
|---|---|
| 프로젝트명 | 여행영어 — 내가 갈 장소에서 쓸 문장을 AI 로 만들고, 말해 보고, 기억하는 학습 서비스 |
| 목적 | 여행자가 실제로 갈 장소에서 쓸 영어 문장을 여행 전부터 여행 중까지 익히고 말해 보게 한다 |
| 대상 사용자 | 해외여행을 앞둔 한국어 사용자, 영어 기초~초급, 주로 휴대폰 브라우저 |
| 기준 시점 | 2026-10-09, 커밋 `f78b23b` (카테고리 계약 3종 완비) |
| 이전 문서 | `docs/planning/prd.md`(v2, Firebase 기준 초기 기획 — 이력으로 보존). 범위·구조가 다르면 **이 문서**를 따른다 |

상태 표기: **완료**(배포·테스트됨) · **부분**(일부만 구현) · **예시**(화면은 있으나 예시 데이터) · **예정**

## 1. 기능 요구사항

| ID | 기능 | 설명 | 우선순위 | 상태 | 근거(코드·테스트) |
|---|---|---|---|---|---|
| FR-01 | 여행 입력 | 나라, 도시 1~5곳, 체류일, 학습 시작일 입력과 검사 | Must | 완료 | `mockup/app.js` `R.validate` |
| FR-02 | 학습 일정표 계산 | 문장 수·하루 학습량·복습일·총복습을 코드로 계산(AI 아님, 같은 입력이면 같은 결과) | Must | 완료 | `mockup/app.js` `R.counts`·`buildPlan` |
| FR-03 | 장소 보고서 | 도시별 관광지·맛집 목록, 후보 교체, 출처 표시 | Must | **부분** | 실제 보고서 요청만 `POST /itinerary`를 호출한다. 플래그가 꺼졌거나 모든 도시가 실패하면 예시 목록과 "미리 준비한 예시 데이터" 고지를 유지한다. 확인된 장소가 없으면 예시 장소로 채우지 않는다. 공개 `ITINERARY_ENABLED`는 꺼져 있고, 이 변경을 머지하기 전에는 공개 사이트가 예시 데이터다. 이번 슬라이스에서 Places 왕복은 다시 하지 않았다 |
| FR-04 | 방문 순서 | 날짜별 장소 배치와 규칙 검증 | Should | **부분** | 서버가 하루 블록을 주면 도시 시작일에 맞춰 보여주고, 없으면 코드 배치(`R.placeByCode`)를 쓴다. 공개 사이트는 플래그가 꺼져 있어 코드 배치다 |
| FR-05 | **맛집 문장 AI 생성** | 카테고리 계약으로 프롬프트 → Gemini 생성 → 스키마·규칙 검증 → 위반 시 재생성 | Must | 완료 | `POST /generate`, `backend/app/validators.py`, `tests/test_gemini_retry.py` |
| FR-06 | 생성 결과 신뢰 표시 | 실제 AI 결과는 'AI 생성', 키 없는 샘플은 '샘플', 검증 실패는 학습에 넣지 않음 | Must | 완료 | `usable` 값, `mockup/ai.js` `normalizeAiResponse`, `ai.test.js` |
| FR-07 | 카드 학습·듣기 | 카드 뒤집기, 브라우저 TTS, 날짜별 완료 처리 | Must | 완료 | `mockup/app.js` SCR-08 |
| FR-08 | 문장 모음 | 공통 상황·장소별 문장 조회 | Should | 완료 | SCR-09 |
| FR-09 | **말해 보기(채점)** | 녹음 → 말소리 검출 → 전사 → 단어 일치 점수 → 피드백 | Must | 완료 | `POST /speak-check`, `tests/test_speak_pipeline.py`, `e2e/test_silence.py` |
| FR-10 | 무음·잡음 거부 | 말소리가 없으면 채점하지 않고 외부 AI 를 부르지 않음 | Must | 완료 | `tests/test_speech_vad.py`, 배포 실측 무음 10/10 |
| FR-11 | **어려워한 상황 기억** | 낮은 점수의 상황을 저장 → 다음 생성 요청에 포함 → 그 상황 문장이 생성됐는지 서버가 검증 | Must | 완료 | `weakDecision`, `weak_expressions`, `weak_not_covered` |
| FR-12 | 기억 관리 | 복습 목록 보기·삭제, 동의 철회 시 함께 삭제 | Must | 완료 | 홈 "AI · 개인정보" 카드, `e2e/test_consent.py` |
| FR-13 | 녹음 동의 | 첫 녹음 전 동의(보내는 것·받는 곳·처리·보관), 거부해도 나머지 기능 사용 | Must | 완료 | `askVoiceConsent`, 동의 v7 |
| FR-14 | 여행 종료 요약 | 완료율·학습 문장 수·새 여행 | Should | 완료 | SCR-06 |
| FR-15 | 교통·숙소 카테고리 생성 | 맛집 외 카테고리 문장 생성 | Should | **부분** | 계약 3종 모두 서버에 있음(`restaurant.json`·`transport.json`·`lodging.json`, 각 상황 10개). 화면 코드는 장소 종류로 카테고리를 정해 (도시, 카테고리)별로 요청함(`categoryOfKind`, `ai.test.js`). 남은 것: 예시 장소 데이터(`data.js`)에 교통·숙소 장소가 없어 실제로는 맛집만 요청됨 |
| FR-16 | 로그인·사용자별 저장 | 구글 로그인, 서버 저장 | Could | **부분** | 구글·이메일 로그인은 붙었다. `GET/PUT /user/state` 가 검증된 토큰 uid 의 진도·복습 목록·말하기 동의와 **여행 입력(나라·도시·날짜·학습 시작일)**을 읽고 쓴다(`backend/tests/test_user_state.py`, `e2e/test_account_storage.py`, `e2e/test_home_settings.py`). 장소·문장 본문은 저장하지 않고 화면이 그 입력으로 규칙을 다시 돌려 만든다 — 새로고침·재로그인 뒤에도 홈이 사용자의 실제 여행으로 복원된다. 서버 문서에 여행 입력이 없고 이 브라우저에만 있으면 그 입력을 지우지 않고 서버로 올린다. 홈에서 학습 카드를 열기 전이면 그 카드는 없는 것으로 저장한다. 날짜가 없는 카드 객체 때문에 여행 입력까지 거절하지 않는다. 홈 D-Day 카드에서 그 입력을 고친다. 날짜만 바뀌면 학습 일정표만 다시 계산하고, 도시나 나라가 바뀌면 보고서부터 다시 만든다. 홈 맨 아래 계정 카드(안내와 로그아웃이 카드 패딩 하나 안)에서 로그아웃하며, 여행이 끝난 홈에도 같은 카드가 있다. uid 가 없으면 기존 브라우저 키. 저장소 호출이 실패하면 503 이고 브라우저 기록은 유지된다. 공개 사이트의 토큰 없는 `/user/state`는 401 `missing_token`이다. 로그인한 실기기 왕복은 아직 다시 확인하지 않아 상태는 부분이다 |
| FR-17 | **회원 탈퇴** | 계정과 연결된 모든 저장 데이터 삭제·폐기 | Must | **부분** | 홈 계정 카드 **패딩 밖** 아래에 연하고 작은 `탈퇴하기`. 확인 후 **(1) 서버 `POST /account/erase`**(관리자: 토큰 취소 `validSince` + Firestore 문서 삭제 + Auth 계정 삭제, **최근 로그인 불필요**) → **(2) 응답 본문이 `erased:true` 일 때만 성공으로 보고** 브라우저 계정 칸 + 로그인 전 공용 칸 기록(`cd_session`·`cd_weak`·`cd_consent`·`cd_trip`)을 폐기. 서비스 계정 키가 없으면(503 `admin_unavailable`) 또는 옛 서버(404/405)면 규칙 삭제 `DELETE /user/state`(본문 `deleted:true` 확인) + 클라이언트 `deleteUser` 로 되돌아간다. **서버 단계가 실패하거나 토큰을 받지 못하면 계정도 기록도 지우지 않고 멈춘다.** 관리자 경로는 서비스 계정 키(`FIREBASE_SERVICE_ACCOUNT_JSON`)가 있어야 하며, 없으면 화면 동작은 그대로 폴백으로 동작한다(`backend/tests/test_firebase_admin.py`·`test_account_erase.py`, `e2e/test_account_withdrawal.py`). **탈퇴 흔적(tombstone)**: 관리자 경로는 탈퇴할 때 Firestore `deleted/{uid}`(uid·시각만)를 **가장 먼저** 남기고, `GET`·`PUT /user/state` 는 그 uid 를 **403 `account_deleted`** 로 거부한다 — 다른 기기의 미만료 ID 토큰(≤1h)이 문서를 다시 만들지 못한다. 탈퇴가 도중 실패하면 흔적을 되돌려(계정이 살아 있는데 저장이 막히지 않게) 다시 시도할 수 있다. 화면은 403 을 받으면 **계정이 정말 사라졌는지 강제 갱신으로 확인한 뒤** 로컬을 비우고 로그아웃한다(흔적만 남은 경우 기록을 지키려고). 흔적은 서비스 계정으로만 읽고 써서 `firestore.rules` 변경이 필요 없고, 조회는 **양성만** 캐시(1h)하며 실패하면 통과시킨다(fail-open). **서비스 계정 키가 없는 배포에서는 흔적이 쓰이지 않아 이 차단이 동작하지 않는다**. 로그인한 실계정 탈퇴 왕복은 아직 확인하지 않아 상태는 부분이다 |

## 2. 비기능 요구사항

| ID | 항목 | 요구사항 | 상태 | 근거 |
|---|---|---|---|---|
| NFR-01 | 응답 시간 | 말하기 채점은 정상 상태 10초 이내 | 완료(실측 약 5초) | `docs/measurement/score_측정_실행법.md` |
| NFR-02 | 콜드스타트 | 재시작 뒤 첫 요청은 느릴 수 있음 — 시연 전 깨우기 | 한계 문서화 | `docs/deploy/DEPLOY_RUNBOOK.md` |
| NFR-03 | 신뢰성 | AI API 호출당 **최소 30회** 시도, 모델 회전·실패 모델 쿨다운, 모델명 하드코딩 금지 | 완료 | `backend/app/gemini.py`, `tests/test_gemini_retry.py`(뮤테이션 검증). 10/23: 시작한 요청의 30회는 그대로 두고, 남용 방어로 시작 전 예산(일일·IP)과 동시 실행 상한을 둔다. 입력 탓 실패의 조기 중단(`AI_MAX_DETERMINISTIC`)은 기본 꺼짐 — 켜려면 이 요건을 고쳐야 한다 |
| NFR-04 | 정확성(환각 방지) | 전사에 목표 문장을 주지 않음, 두 신경망 VAD AND, 이종 모델 전사 교차검증, 점수는 코드 | 완료 | `docs/research/speak-hallucination.md` |
| NFR-05 | 개인정보 | 서버는 녹음을 저장하지 않음, 말소리 없으면 외부 전송 없음. 로그인 계정의 진도·복습·동의·여행 입력은 `/user/state`, uid 가 없으면 브라우저 | 완료 | `/speak-check`, `e2e/test_silence.py`, `tests/test_user_state.py` |
| NFR-06 | 남용·비용 방어 | IP당 20회/60초, 입력 길이(도시 80자·장소 20개·목표 200자), 오디오 8MB·`audio/*` | 완료 | `backend/app/main.py` |
| NFR-07 | 보안 | API 키는 Render 환경변수에만, 코드·저장소에 없음 | 완료 | `render.yaml` `sync: false` |
| NFR-08 | 화면 | 휴대폰·태블릿·PC 폭 대응(반응형), 화면 문구 한국어·학습 문장 영어 | **부분** | 제품 셸(탭바→레일→사이드, 문서 스크롤)로 320~1920px 12개 화면 가로 넘침 0 (`mockup/audit/responsive_audit.js`), e2e `test_shell.py` 29개. P2 반영(12px 하한·입력 16px·터치 44px·keep-all, e2e 45개). P3 반영(라이트·다크·시스템, 글자 대비 AA 계산·측정 통과, e2e 57개). P4 반영(≥900px 일정표·학습·문장 모음 2열, e2e 86개). **미완**: 실기기(iOS Safari·iPad 등) 미검증, 다크 팀 디자인 검수, 브라우저 뒤로가기와 날짜 선택 연동. 설계: `docs/design/RESPONSIVE_STRATEGY.md` |
| NFR-09 | 품질 | PR 마다 CI(백엔드 227·프론트 41 단위 테스트, 브라우저 E2E 12종 323 검사 확인) | 완료 | `.github/workflows/ci.yml` |
| NFR-10 | 관측 | `/health` 에 배포 커밋, 키 상태, 모델 상태, 교차검증 준비 여부 | 완료 | `GET /health` |

## 3. AI 활용 명세

| 기능 | AI 활용 방식 | AI 가 정하는 것 | 코드가 정하는 것 |
|---|---|---|---|
| 맛집 문장 생성 (FR-05) | **AI Agent**: 계약 기반 프롬프트 → 생성 → 검증 → 재생성 루프 (Gemini) | 문장 내용 | 스키마·상황 커버리지·금지 표현 검증, 재생성 여부, 학습 투입 여부 |
| 말소리 검출 (FR-10) | 신경망 VAD 2개: Silero + pyannote segmentation-3.0(서버 내장) | – (로컬 모델) | 두 검출기 AND |
| 전사 (FR-09) | **멀티모달(음성 입력)**: Groq Whisper(→OpenAI Whisper) + AssemblyAI 교차검증 | 들린 단어 | 환각 세그먼트 제거, 두 전사 모두 들은 단어만 인정 |
| 채점 (FR-09) | 없음 | – | 단어 일치율 `100 × 2·M_both / (T + H_max)` |
| 피드백 (FR-09) | LLM(Gemini) — 오디오 없이 상황·목표·전사·차이만 입력 | 한국어 피드백 문장 | 점수(AI 가 바꿀 수 없음), 실패 시 사실 기반 문장 틀 |
| 기억 (FR-11) | **Long-term Memory**: 어려워한 상황을 다음 생성 프롬프트에 반영 | 그 상황의 새 문장 | 저장 여부(점수 70 미만), 반영 여부 검증 |

## 4. 시스템 구성

```
브라우저(mockup/) ──같은 주소──▶ FastAPI(backend/app) on Render
                                   ├─ /user/state  → 로그인한 계정의 진도·복습·동의·여행 입력
                                   ├─ /generate    → Gemini
                                   ├─ /speak-check → Silero·pyannote(서버) → Groq/OpenAI Whisper + AssemblyAI → Gemini
                                   └─ /health
GitHub(main) ──머지──▶ Render 자동 배포 / GitHub Actions CI
```

## 5. 범위 밖 (현 단계)

음소·운율 수준 발음 평가(GOP 등), 실제 웹 검색 기반 장소 보고서, 지도·경로 최적화, 알림, 네이티브 앱.
