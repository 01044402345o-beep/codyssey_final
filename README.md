# 여행영어 — 내가 갈 장소에서 쓸 문장을 AI 로 만들고, 말해 보고, 기억하는 학습 서비스

여행지와 일정을 넣으면 실제로 갈 맛집에서 쓸 영어 문장을 AI 가 만들고, 출발 전부터 여행 중까지 매일 카드로 학습합니다.
문장을 소리 내어 말하면 AI 가 받아쓰고 코드가 채점하며, 어려워한 상황은 기억했다가 다음 문장 생성 때 더 연습시킵니다.

- **배포**: https://codyssey-final.onrender.com (화면과 API 가 같은 주소, Render 무료 플랜 — 15분 쉬면 첫 요청이 30~60초 걸림)
- **코디세이 AI Native Final Project** (자율 주제, 팀)

> 화면의 장소 목록·방문 순서는 아직 **예시 데이터**입니다(화면에 고지). AI 가 실제로 하는 일은 아래 "핵심 AI 활용" 에 있는 것뿐입니다.

---

## 1. 해결하려는 문제

- 여행 영어 교재는 일반 상황만 다룬다. "내가 갈 식당에서 그 메뉴를 주문하는 문장"은 따로 찾아야 한다.
- 여행 준비와 영어 공부가 따로 놀아 출발 전까지 꾸준히 학습할 계획을 세우기 어렵다.
- 문장을 외워도 실제로 말할 수 있는지 확인할 방법이 없다.

**핵심 가치**: 내가 실제로 갈 장소에서 실제로 쓸 문장만, 여행 전부터 여행 중까지 익히고 말해 본다.

## 2. 팀원 및 역할

| 이름 | 역할 | 담당 업무 |
|---|---|---|
| 최성빈 | 통합 / Backend | 생성 함수·검증 코드·말하기 채점 파이프라인, 배포(Render)·CI, 통합 |
| 이영애 | AI 콘텐츠 | 식당·카페 카테고리 계약(`agent_contract/categories/restaurant.json`) |
| 이창진 | AI 콘텐츠 | 교통·공항 카테고리 계약(`transport.json`) |
| 함명자 | AI 콘텐츠 | 숙소·체크인 카테고리 계약(`agent_contract/categories/lodging.json`) |
| 이주란 | 검증 | 전 카테고리 실패 케이스(`negative_cases`)·측정 |
| 한재정 | 리뷰 | 전체 리뷰 |

카테고리 계약 작성 규칙: `agent_contract/README.md`

## 3. 주요 기능

| 기능 | 상태 | 비고 |
|---|---|---|
| 여행 입력 → 학습 일정표(문장 수·복습일 자동 계산) | 동작 | 계산 규칙은 코드(`mockup/app.js` `R`) |
| 맛집별 영어 문장 **AI 생성** + 검증·재생성 | 동작 | `POST /generate`, 화면에 'AI 생성'/'샘플' 표시 |
| 카드 학습·듣기(TTS)·문장 모음 | 동작 | 브라우저 음성 합성 |
| **말해 보기** — 녹음 → 받아쓰기 → 채점·피드백 | 동작 | `POST /speak-check`, 녹음 전 동의 |
| 어려워한 상황 **기억** → 다음 생성에 반영 | 동작 | 브라우저 저장(`localStorage`) |
| 보고서(관광지·맛집)·방문 순서 AI | **예시 데이터** | 장소 목록은 미리 준비한 데이터, 화면에 고지 |
| 로그인 | 흉내 | 데모 사용자 |

## 4. 기술 스택과 선정 이유

| 구분 | 기술 | 선정 이유 |
|---|---|---|
| Backend | Python 3.11, **FastAPI** | API 3개(`/health`·`/generate`·`/speak-check`)로 범위를 묶고 빠르게 배포 |
| 문장 생성·피드백 | **Google Gemini** (`google-genai`) | 모델은 고정하지 않고 실행 중 `models.list()` 로 고름 |
| 받아쓰기(STT) | **Groq Whisper**(→ OpenAI Whisper) + **AssemblyAI**(교차검증) | 범용 LLM 이 아니라 전용 음성인식. 서로 다른 모델 계열 두 개로 교차검증 |
| 말소리 검출 | **Silero VAD** + **pyannote segmentation-3.0**(ONNX, 서버 내장) | 데시벨이 아닌 신경망. 큰 잡음·신호음은 말소리로 보지 않음 |
| 오디오 디코드 | PyAV(faster-whisper) | 브라우저 녹음(webm/opus, Safari mp4) 그대로 처리 |
| Frontend | HTML·CSS·JavaScript (빌드 없음) | 백엔드가 같은 주소에서 정적 서빙 → CORS 없음 |
| 배포 | **Render** (무료) | GitHub `main` 머지 시 자동 배포 |
| CI | **GitHub Actions** | PR 마다 단위 테스트 + 브라우저 E2E(Playwright) |

기획 초기안은 React + Firebase 였다(`기술스택.md`, `prd.md` — 이력으로 보존). 배포를 먼저 확보하고 범위를 줄이기 위해 Render + FastAPI 로 바꿨다(`backend/README.md`).

## 5. 시스템 아키텍처

```
브라우저 (mockup/: 학습 화면, 녹음, 복습 목록 localStorage)
   │  같은 주소
   ▼
FastAPI (backend/app/main.py) ─ Render
   ├─ GET  /health        배포 커밋·키 상태·모델 상태
   ├─ POST /generate      카테고리 계약 → Gemini 생성 → 스키마·규칙 검증 → block 이면 재생성
   └─ POST /speak-check   PyAV → Silero VAD ─┐
                          로컬 pyannote ─────┴ 둘 다 말소리? 아니면 끝(외부 호출 0)
                          ├─ Groq Whisper(→OpenAI)  ┐ 동시, 목표 문장 미전송
                          └─ AssemblyAI             ┘
                          → 환각 필터·단어 일치(코드) → Gemini 피드백(글만, 점수 변경 불가)
```

## 6. 핵심 AI 활용 (필수 기술 요소 중 3개)

### 6-1. AI Agent — 생성 → 검증 → 재생성 (`/generate`)
- 담당자별 **카테고리 계약**(상황 목록·프롬프트·좋은 예·금지 예)으로 프롬프트를 만든다.
- Gemini 결과를 `agent_contract/schema.json` 과 규칙(`backend/app/validators.py`)으로 검사한다.
  - 문제가 `block` 이면 이유를 붙여 다시 생성한다.
  - 검증을 통과하지 못하면 `usable: "rejected"` 로 표시하고, 화면은 그 결과를 학습에 쓰지 않는다.
- AI API 호출 하나당 **최소 30회** 시도한다.
  - 모델을 돌아가며 쓴다.
  - 실패한 모델은 일정 시간 뒤로 미룬다.
  - 마지막으로 성공한 모델을 먼저 쓴다.

### 6-2. 멀티모달 — 말하기 채점 (`/speak-check`)
- 음성 입력을 처리한다.
- **AI 에게 최소 권한만 준다.**
  - 전사 AI 는 목표 문장을 모른다.
  - 점수는 코드가 매긴다.
  - 피드백 AI 는 오디오 없이 비교 결과만 받는다.
- 이렇게 바꾼 이유: 처음 구조(녹음과 목표 문장을 함께 Gemini 에 보냄)는 **1초 무음에도 10/10 목표 문장을 들었다고 답하고 95~100점**을 줬다.
- 근거: `docs/research/speak-hallucination.md`, 참고문헌 34편 `docs/research/references.md`

### 6-3. Long-term Memory — 어려워한 상황 기억
- 말하기 결과가 낮으면 그 상황(`situation_id`)을 브라우저에 저장한다. 점수가 없을 때는 저장할지 사용자에게 묻는다.
- 다음 문장을 생성할 때 그 상황을 `weak_expressions` 로 보낸다.
- 서버는 그 상황의 문장이 실제로 생성됐는지 검증한다(`weak_not_covered` 이면 재생성).
- 한계: 브라우저(기기)별 저장이라 다른 기기에서는 이어지지 않는다.

## 7. AI 윤리

- AI 가 만든 문장에는 **'AI 생성'**, 샘플에는 **'샘플'** 배지가 붙는다. 예시 데이터는 예시라고 고지한다.
- 말하기는 선택 기능이다. **처음 녹음할 때 동의**를 받는다. 동의 창에는 다음을 적는다.
  - 보내는 것, 받는 곳, 처리, 보관
  - Gemini 무료 등급 데이터 사용, 민감정보 금지
- 거부해도 나머지 기능은 그대로 쓸 수 있다. 홈 "AI · 개인정보" 카드에서 철회하면 복습 목록도 지운다.
- 서버는 녹음을 저장하지 않는다. 말소리가 없으면 외부 AI 로 보내지 않는다.

## 8. 실행 방법

### 요구사항
- Python 3.11, Node.js 20(프론트 단위 테스트), Playwright(E2E, 선택)

### 백엔드 + 화면
```bash
git clone https://github.com/01044402345o-beep/codyssey_final.git
cd codyssey_final/backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload      # http://127.0.0.1:8000  (화면도 같은 주소)
```
키 없이도 실행된다. 이때 문장 생성은 샘플, 말하기는 말소리 검출까지만 동작한다.
실제 AI 를 쓰려면 환경변수를 넣는다(키 목록·설명은 `backend/README.md`).
- `GEMINI_API_KEY`
- `GROQ_API_KEY`
- `ASSEMBLYAI_API_KEY`
- 선택: `OPENAI_API_KEY`

### 테스트
```bash
cd backend
python -m unittest discover -s tests -t .          # 백엔드 73
python scripts/check_negatives.py                   # 카테고리 금지 예 검사
node --test ../mockup/ai.test.js                    # 프론트 20
# E2E (서버를 켠 뒤)
python ../e2e/test_silence.py http://localhost:8000 && python ../e2e/test_consent.py http://localhost:8000
```

## 9. 결과

### 말하기 채점 — 배포 서버 실측 (`docs/score_측정_실행법.md`)
| 입력 | 처음 구조 (Gemini 에 녹음 + 목표 문장) | 현재 (신경망 VAD 2개 + 전용 STT 교차검증) |
|---|---|---|
| 1초 무음 ×10 | 10/10 **95~100점** (목표 문장을 지어냄) | 10/10 **채점 안 함**, 외부 API 0회 |
| 맞게 읽음 ×3 | 95~100점 | 100·100·100 (두 전사 일치) |
| 다른 문장 ×3 | 10~20점 | 0·0·0 (들은 문장을 그대로 받아씀) |

응답 시간은 정상 상태에서 약 5초다. 재배포 직후 첫 요청은 모델 기억이 비어 있어 오래 걸린다.

### 사용자 테스트
- 실사용자 5명 이상 테스트 예정이다. 결과와 반영 사항은 이 절에 기록한다.

### 알려진 한계
- 점수는 '두 전사 모두에서 들린 단어 일치율'이다. 음소·억양 같은 발음 품질은 재지 않는다.
- Whisper 가 학습자 오류를 교정해 받아쓸 수 있다.
- 두 검출기 AND 는 작게 말하거나 서툰 발화를 놓칠 수 있다.
- 화면 생성은 식당 카테고리만 연결돼 있다(교통·숙소 계약도 서버에 있으나 화면 코드가 카테고리를 `restaurant` 로 고정).
- Render 무료 플랜은 콜드스타트가 있다. 서버를 재시작하면 모델 상태 기억이 사라진다.

## 10. 문서

| 문서 | 내용 |
|---|---|
| `backend/README.md` | API·환경변수·모델 선택·재시도·말하기 파이프라인 |
| `docs/research/speak-hallucination.md` | 말하기 채점 구조를 바꾼 이유(실측·조사·결정) |
| `docs/research/references.md` | 참고문헌 34편 |
| `docs/DEPLOY_RUNBOOK.md` | 배포·장애 대응 런북 |
| `docs/score_측정_실행법.md` | 실측 방법과 결과 |
| `agent_contract/README.md` | 카테고리 계약 작성 규칙 |
| `mockup/README.md`, `mockup/SMOKE.md` | 화면 구성·시연 전 점검 |
| `prd.md`, `시나리오완료.MD`, `기술스택.md` | 초기 기획(Firebase 기준, 이력) |
