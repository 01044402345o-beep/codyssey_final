# 요구사항 정의서 (현행)

| 항목 | 내용 |
|---|---|
| 프로젝트명 | 여행영어 — 내가 갈 장소에서 쓸 문장을 AI 로 만들고, 말해 보고, 기억하는 학습 서비스 |
| 목적 | 여행자가 실제로 갈 장소에서 쓸 영어 문장을 여행 전부터 여행 중까지 익히고 말해 보게 한다 |
| 대상 사용자 | 해외여행을 앞둔 한국어 사용자, 영어 기초~초급, 주로 휴대폰 브라우저 |
| 기준 시점 | 2026-10-09, 커밋 `f78b23b` (카테고리 계약 3종 완비) |
| 이전 문서 | `prd.md`(v2, Firebase 기준 초기 기획 — 이력으로 보존). 범위·구조가 다르면 **이 문서**를 따른다 |

상태 표기: **완료**(배포·테스트됨) · **부분**(일부만 구현) · **예시**(화면은 있으나 예시 데이터) · **예정**

## 1. 기능 요구사항

| ID | 기능 | 설명 | 우선순위 | 상태 | 근거(코드·테스트) |
|---|---|---|---|---|---|
| FR-01 | 여행 입력 | 나라, 도시 1~5곳, 체류일, 학습 시작일 입력과 검사 | Must | 완료 | `mockup/app.js` `R.validate` |
| FR-02 | 학습 일정표 계산 | 문장 수·하루 학습량·복습일·총복습을 코드로 계산(AI 아님, 같은 입력이면 같은 결과) | Must | 완료 | `mockup/app.js` `R.counts`·`buildPlan` |
| FR-03 | 장소 보고서 | 도시별 관광지·맛집 목록, 후보 교체, 출처 표시 | Must | **예시** | `mockup/data.js` — 화면에 "미리 준비한 예시 데이터" 고지 |
| FR-04 | 방문 순서 | 날짜별 장소 배치와 규칙 검증 | Should | **예시** | 코드 배치(`R.placeByCode`) |
| FR-05 | **맛집 문장 AI 생성** | 카테고리 계약으로 프롬프트 → Gemini 생성 → 스키마·규칙 검증 → 위반 시 재생성 | Must | 완료 | `POST /generate`, `backend/app/validators.py`, `tests/test_gemini_retry.py` |
| FR-06 | 생성 결과 신뢰 표시 | 실제 AI 결과는 'AI 생성', 키 없는 샘플은 '샘플', 검증 실패는 학습에 넣지 않음 | Must | 완료 | `usable` 값, `mockup/ai.js` `normalizeAiResponse`, `ai.test.js` |
| FR-07 | 카드 학습·듣기 | 카드 뒤집기, 브라우저 TTS, 날짜별 완료 처리 | Must | 완료 | `mockup/app.js` SCR-08 |
| FR-08 | 문장 모음 | 공통 상황·장소별 문장 조회 | Should | 완료 | SCR-09 |
| FR-09 | **말해 보기(채점)** | 녹음 → 말소리 검출 → 전사 → 단어 일치 점수 → 피드백 | Must | 완료 | `POST /speak-check`, `tests/test_speak_pipeline.py`, `e2e/test_silence.py` |
| FR-10 | 무음·잡음 거부 | 말소리가 없으면 채점하지 않고 외부 AI 를 부르지 않음 | Must | 완료 | `tests/test_speech_vad.py`, 배포 실측 무음 10/10 |
| FR-11 | **어려워한 상황 기억** | 낮은 점수의 상황을 저장 → 다음 생성 요청에 포함 → 그 상황 문장이 생성됐는지 서버가 검증 | Must | 완료 | `weakDecision`, `weak_expressions`, `weak_not_covered` |
| FR-12 | 기억 관리 | 복습 목록 보기·삭제, 동의 철회 시 함께 삭제 | Must | 완료 | 홈 "AI · 개인정보" 카드, `e2e/test_consent.py` |
| FR-13 | 녹음 동의 | 첫 녹음 전 동의(보내는 것·받는 곳·처리·보관), 거부해도 나머지 기능 사용 | Must | 완료 | `askVoiceConsent`, 동의 v6 |
| FR-14 | 여행 종료 요약 | 완료율·학습 문장 수·새 여행 | Should | 완료 | SCR-06 |
| FR-15 | 교통·숙소 카테고리 생성 | 맛집 외 카테고리 문장 생성 | Should | **부분** | 계약 3종 모두 서버에 있음(`restaurant.json`·`transport.json`·`lodging.json`, 각 상황 10개). 화면 코드는 장소 종류로 카테고리를 정해 (도시, 카테고리)별로 요청함(`categoryOfKind`, `ai.test.js`). 남은 것: 예시 장소 데이터(`data.js`)에 교통·숙소 장소가 없어 실제로는 맛집만 요청됨 |
| FR-16 | 로그인·사용자별 저장 | 구글 로그인, 서버 저장 | Could | **예정** | 현재 데모 사용자 + 브라우저 저장 |

## 2. 비기능 요구사항

| ID | 항목 | 요구사항 | 상태 | 근거 |
|---|---|---|---|---|
| NFR-01 | 응답 시간 | 말하기 채점은 정상 상태 10초 이내 | 완료(실측 약 5초) | `docs/score_측정_실행법.md` |
| NFR-02 | 콜드스타트 | 재시작 뒤 첫 요청은 느릴 수 있음 — 시연 전 깨우기 | 한계 문서화 | `docs/DEPLOY_RUNBOOK.md` |
| NFR-03 | 신뢰성 | AI API 호출당 **최소 30회** 시도, 모델 회전·실패 모델 쿨다운, 모델명 하드코딩 금지 | 완료 | `backend/app/gemini.py`, `tests/test_gemini_retry.py`(뮤테이션 검증) |
| NFR-04 | 정확성(환각 방지) | 전사에 목표 문장을 주지 않음, 두 신경망 VAD AND, 이종 모델 전사 교차검증, 점수는 코드 | 완료 | `docs/research/speak-hallucination.md` |
| NFR-05 | 개인정보 | 서버는 녹음을 저장하지 않음, 말소리 없으면 외부 전송 없음, 학습 기록은 브라우저에만 | 완료 | `/speak-check`, `e2e/test_silence.py` |
| NFR-06 | 남용·비용 방어 | IP당 20회/60초, 입력 길이(도시 80자·장소 20개·목표 200자), 오디오 8MB·`audio/*` | 완료 | `backend/app/main.py` |
| NFR-07 | 보안 | API 키는 Render 환경변수에만, 코드·저장소에 없음 | 완료 | `render.yaml` `sync: false` |
| NFR-08 | 화면 | 휴대폰 폭 대응, 화면 문구 한국어·학습 문장 영어 | 완료 | 360·390px 에서 14개 화면 가로 넘침 0, 관리자 표는 패널 안 가로 스크롤 (2026-10-10 Playwright 확인) |
| NFR-09 | 품질 | PR 마다 CI(백엔드 85·프론트 22 단위 테스트, 브라우저 E2E 51개 확인) | 완료 | `.github/workflows/ci.yml` |
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
                                   ├─ /generate    → Gemini
                                   ├─ /speak-check → Silero·pyannote(서버) → Groq/OpenAI Whisper + AssemblyAI → Gemini
                                   └─ /health
GitHub(main) ──머지──▶ Render 자동 배포 / GitHub Actions CI
```

## 5. 범위 밖 (현 단계)

음소·운율 수준 발음 평가(GOP 등), 실제 웹 검색 기반 장소 보고서, 지도·경로 최적화, 알림, 서버 계정·다기기 동기화, 네이티브 앱.
