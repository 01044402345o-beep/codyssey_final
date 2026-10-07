# 백엔드 — 배포 먼저

엔드포인트 **3개가 상한**입니다. 기능을 더 붙이면 Firebase를 걷어낸 이유가 그대로 재발합니다.

| 메서드 | 경로 | 역할 |
|---|---|---|
| GET | `/health` | 배포 확인 + 시연 전 콜드스타트 깨우기 |
| POST | `/generate` | 카테고리 문장 생성 → 스키마·규칙 검증 → 위반 시 재생성 |
| POST | `/speak-check` | 녹음 → **Silero VAD**(말소리 없으면 끝) → **전용 STT**(Groq Whisper 등, 목표 문장 모름) → 환각 필터·단어 비교(코드) → 피드백(Gemini, 오디오 없음). 근거: `docs/research/speak-hallucination.md` |

`GEMINI_API_KEY` 가 없으면 **목업으로 응답**합니다. 그래서 키 없이도 배포·시연이 됩니다.

## 경로 규칙 (중요)

`agent_contract/` 는 **저장소 루트**에 있습니다. `main.py` 는 `backend/app/` 기준으로
`../../agent_contract` 를 봅니다. 옮기면 `/health` 의 `categories` 가 `[]` 가 되고
`/generate` 가 전부 404가 됩니다 — 배포 후 `categories` 에 `restaurant` 가 보이는지
반드시 확인하세요.

```
codyssey_final/
├── render.yaml              ← 저장소 루트 (rootDir 없음)
├── agent_contract/          ← 팀원이 PR 하는 곳
│   ├── schema.json
│   └── categories/*.json
└── backend/
    ├── app/main.py          ← REPO_ROOT/agent_contract 를 참조
    └── scripts/check_negatives.py
```

---

## 1. 로컬 실행

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

- 확인: http://127.0.0.1:8000/health — `categories` 에 `restaurant` 가 보여야 정상
- 자동 문서: http://127.0.0.1:8000/docs

## 2. 규칙 자체 점검

```bash
cd backend
python scripts/check_negatives.py
```

각 카테고리의 `negative_cases` 가 실제로 걸러지는지 확인합니다. 새 카테고리 파일을 올릴 때마다 실행하세요.

## 3. Render 배포 (내용 채우기 전에 먼저)

1. https://render.com 가입 → GitHub 연결
2. **New → Blueprint** → 이 저장소 선택 (`render.yaml` 자동 인식)
3. 배포 끝나면 `https://<앱이름>.onrender.com/health` 접속
4. **`categories: ["restaurant"]` 를 확인하고 멈추세요.** 비어 있으면 경로 문제입니다.

### 환경변수 (나중에)

| 키 | 값 | 비고 |
|---|---|---|
| `GEMINI_API_KEY` | Google AI Studio에서 발급 | 문장 생성·말하기 피드백. 없으면 생성은 목업, 피드백은 문장 틀 |
| `GROQ_API_KEY` | console.groq.com | 말하기 전사 1순위(Whisper). STT 키가 하나도 없으면 말하기는 목업 |
| `OPENAI_API_KEY` | platform.openai.com | 전사 보충(whisper 계열만, gpt-4o-transcribe 제외) |
| `ASSEMBLYAI_API_KEY` | assemblyai.com | **교차검증 전사(필수)**. `speech_models` 미전송 → 계정 기본 모델. `ASSEMBLY_AI_API_KEY` 도 인식 |
| `PYANNOTEAI_API_KEY` | pyannote.ai | **두 번째 말소리 검출(필수)**. `model` 미전송. `PYANNOTE_API_KEY` 도 인식 |
| `GROQ_STT_MODEL` / `OPENAI_STT_MODEL` | 비워 둠 | 고정이 아니라 우선 선호(목록에 있을 때만) |
| `STT_SELFTEST` | 비워 둠 | `1` 이면 시작 시 공급자별 실제 호출 점검 → `/health` `stt_selftest`. **검증 뒤 지운다**(콜드스타트마다 비용) |
| `GEMINI_MODEL` | 비워 둠 | **고정이 아니라 우선 선호.** 실행 중 받은 목록에 있을 때만 맨 앞에 둔다 |
| `AI_MIN_ATTEMPTS` | 기본 `30` | AI API 호출당 최소 시도 횟수. **늘릴 수만 있고 30 미만은 무시** |
| `AI_BACKOFF_BASE` / `AI_BACKOFF_MAX` | `0.5` / `4` (초) | 실패 후 대기: 0.5→1→2→4→4… |
| `AI_CALL_TIMEOUT` | `60` (초) | API 요청 1회의 제한 시간 (전체 제한 시간은 없음) |
| `AI_MODELS_TTL` | `600` (초) | 모델 목록 캐시 시간 |
| `ALLOW_ORIGINS` | 프론트 배포 주소 | 기본 `*` |

### 무료 플랜 주의

- **콜드스타트**: 15분 유휴 후 첫 요청이 30~60초. **시연 10분 전에 `/health` 를 호출**해 깨우세요.
- 파일시스템이 휘발성입니다. 상태를 저장하지 마세요(취약 표현은 요청에 실어 보내는 구조).

## 3-1. 모델 선택과 재시도 (`app/gemini.py`)

**모델 이름을 코드에 고정하지 않습니다.** Gemini 모델은 수시로 추가·폐기되고 별칭이 바뀌므로,
서버가 `models.list()` 로 지금 쓸 수 있는 목록을 받아(10분 캐시) 고릅니다.

- 대상: `gemini*` 이면서 `generateContent` 지원. 임베딩·이미지(`image`·`banana`)·TTS·받아쓰기(`transcribe`)·Live·
  로봇(`robotics`)·컴퓨터 조작(`computer-use`)·도구 전용(`customtools`)·Gemma 는 제외
- 순서: 안정 버전 → flash → flash-lite → pro, 같은 계열은 `-latest` 별칭·최신 버전 우선,
  버전 번호가 없는 낯선 계열(`gemini-omni-…`)은 버전 있는 모델 뒤
- 시도마다 목록을 순서대로 돌아가며 씁니다. 한 모델의 장애·할당량 초과를 다른 모델로 흡수합니다.

**AI API 호출 하나당 최소 30회 시도합니다.** (`/generate`, `/speak-check` 받아쓰기·피드백, 모델 목록 조회 각각)

| 규칙 | 내용 |
|---|---|
| 하한 | 실패를 확정하기 전에 **반드시 30회 이상** 요청한다. 오류 종류로 조기 중단하지 않는다 |
| 시도 1회 | API 요청 1회. SDK 자체 재시도는 꺼서(`attempts=1`) 셈이 어긋나지 않게 한다 |
| 실패로 세는 것 | 예외(네트워크·429·5xx·잘못된 모델 등), 빈 응답, JSON 아님, (`/generate`) 검증 block |
| 성공 | 그 자리에서 멈춘다. 응답의 `attempts` 에 실제 시도 횟수, `model` 에 성공한 모델 |
| 전체 제한 시간 | **두지 않는다.** 시간 제한이 시도 횟수를 깎으면 '최소'가 깨진다 |

> ⚠️ 모두 실패하면 대기만 약 1분 48초(0.5+1+2+4×26=107.5초)에 요청 시간이 더해집니다.
> 프론트 제한 시간(`/generate` 90초, `/speak-check` 90초 — 받아쓰기+피드백 2회 호출)이 먼저 끝나면 화면은 대체 결과를 보여 주지만,
> 서버는 30회를 끝까지 채웁니다. 시도 횟수는 `backend/tests/test_gemini_retry.py` 가 검증합니다.

### 모델 상태 기억 (뒤로 미루기)

같은 실패를 매 요청 반복하지 않도록 서버가 모델 상태를 기억합니다 (프로세스 메모리, 재시작 시 초기화).

| 실패 | 미루는 시간 | 환경변수 |
|---|---|---|
| 403·404 (제공 중단 등) | 6시간 | `AI_COOLDOWN_GONE` |
| 429 할당량·400 요청 거부 | 10분 | `AI_COOLDOWN_QUOTA` |
| 5xx 과부하·타임아웃 | 60초 | `AI_COOLDOWN_BUSY` |
| 빈 응답·JSON 아님·검증 block | 미루지 않음 (모델 탓이 아님) | |

- 시도 순서: **마지막 성공 모델 → 정상 모델 → 미룬 모델(빨리 풀리는 순)**
- 미루는 것이지 **빼는 것이 아닙니다.** 모든 모델이 미뤄져 있어도 최소 30회는 그대로 시도합니다.
- `/health` 의 `model_health`: `last_good`(마지막 성공 모델), `cooling`(미룬 모델·사유·남은 초)

> 배포 실측(10/7): flash 5개 `503` 과부하, `gemini-2.5-flash` `404`(신규 사용자 제공 중단),
> `gemini-omni-1.1-flash` `429`(무료 할당량 없음) → 8번째 `gemini-flash-lite-latest` 성공, 60초.
> 이 기억이 있으면 다음 요청은 성공한 모델부터 시도합니다.

### 말하기 — 말소리 검출과 전사 (`app/speech_vad.py`, `app/stt_providers.py`)

seongbin45/transcribe_app 의 방식을 따랐다(정독·커밋 교차검증 결과는 `docs/research/speak-hallucination.md`).

1. **말소리 검출은 Silero 신경망 VAD** — 데시벨(음량) 기준이 아니다. faster-whisper 의
   `get_speech_timestamps(audio, VadOptions(min_silence_duration_ms=500, speech_pad_ms=200))`(transcribe_app 과 같은 옵션).
   큰 백색잡음·440Hz 신호음도 말소리 0초로 판정한다(`tests/test_speech_vad.py`). 말소리가 없으면 **외부 API 0회**.
   디코드는 PyAV 로 16kHz mono(브라우저 webm/opus·Safari mp4/aac·ogg·wav). 프레임 없는 녹음은 말소리 없음, 깨진 파일은 400.
2. **전사는 전용 STT** — Groq Whisper → OpenAI Whisper → AssemblyAI. 말소리 구간만 이어붙여 보내고, **목표 문장은 보내지 않는다**.
   공급자마다 최소 30회·모델 회전·쿨다운, 다 실패해야 다음 공급자. 모델은 `/models` 에서 whisper 계열만 동적으로 고른다.
3. **환각 필터(코드)** — `no_speech_prob > 0.85`(transcribe_app), `no_speech_prob > 0.6 ∧ avg_logprob < -1.0`(openai/whisper 기본),
   알려진 환각 문구. transcribe_app 은 로컬 엔진에만 적용했지만 여기서는 모든 공급자에 적용한다. 필드가 없으면 그 규칙만 건너뛴다.
4. **교차검증 필수**(다음 절) — 다른 모델 계열 전사(AssemblyAI)와 두 번째 말소리 검출기(pyannoteAI).
5. 점수(두 전사 모두에서 들린 단어 일치율)는 코드, 피드백 문장만 Gemini(오디오 없음, 점수 변경 불가).

#### 교차검증 (필수)
- 배포 자가 점검: Groq·OpenAI(둘 다 Whisper)는 1초 무음에 같은 "you"를 지어냈고 AssemblyAI 는 "" 를 냈다.
  그래서 1차 전사(Groq→OpenAI)와 **다른 계열**인 AssemblyAI 를 교차검증자로 쓴다. OpenAI 는 검증자로 인정하지 않는다.
- pyannoteAI 로 말소리를 한 번 더 확인한다(Silero 와 다른 신경망). 둘 다 말소리를 찾아야 채점한다.
- 세 호출은 동시에(각각 최소 30회). 교차검증 키(`ASSEMBLYAI_API_KEY`·`PYANNOTEAI_API_KEY`)가 없거나 실패하면 **채점하지 않는다**.
- 점수 `100 × 2·M_both / (T + H_max)` — 각 전사 단독 점수보다 크지 않다. 응답 `cross_validation`, `heard_checker`, `diff.per_stt`, `diff.agreement`.
- 근거·한계: `docs/research/references.md`.

응답에 `vad`(말소리 구간), `stt`(공급자·모델·시도), `dropped_segments`(필터가 버린 세그먼트)가 들어간다.
Render 무료 플랜 메모리: faster-whisper+onnxruntime 로드 후 최대 약 88MB(로컬 실측, Whisper 모델은 로드 안 함).

### 실패 원인 보기

실패한 시도는 **성공한 요청이라도** 모두 남깁니다.

- 응답의 `failures[]`: `{ "attempt": 3, "model": "gemini-3.7-flash", "error": "ClientError", "detail": "429 RESOURCE_EXHAUSTED …" }`
  (`detail` 은 300자까지)
- Render 로그: `WARNING app.gemini: generate 시도 3/30 실패 model=gemini-3.7-flash ClientError: 429 …`

| `error` | 흔한 원인 |
|---|---|
| `ClientError` + `429` | 해당 모델 무료 할당량 초과 → 다음 모델로 넘어감 |
| `ClientError` + `404`/`400` | 목록에는 있으나 이 키·요청 형식으로 못 쓰는 모델 |
| `ServerError` + `503` | Google 측 일시 장애 |
| `ValueError` | 빈 응답 또는 JSON 아님 |
| `BlockedResult` | 응답은 왔지만 검증 block (`detail` 에 block 코드) |

지금 쓸 수 있는 모델은 GitHub Actions **"Gemini 모델 목록"** 워크플로(수동 실행 + 매주 월요일)나
`python scripts/list_gemini_models.py` 로 확인합니다. Actions 에는 저장소 Secret `GEMINI_API_KEY` 가 필요합니다.

## 4. 응답 형태

```json
{
  "pack": { "category_id": "restaurant", "city": "New York", "sentences": [ ... ] },
  "issues": [
    { "severity": "warn", "code": "missing_situation", "detail": "7/10 situations below min 1: [...]" }
  ],
  "attempts": 1,
  "mock": false,
  "degraded": true
}
```

| 필드 | 뜻 |
|---|---|
| `usable` | **프론트가 이 결과를 학습 화면에 넣어도 되는지** (아래 표) |
| `issues[].severity` | `block` = 재생성 대상 / `warn` = 검토 대상 |
| `degraded` | 재시도 후에도 `block` 이 남아 목업으로 대체됨 |
| `mock` | API 키 없이 목업으로 응답 |

### `usable` — 실패를 정상 학습으로 포장하지 않기

| 값 | 뜻 | 프론트 처리 |
|---|---|---|
| `ok` | 검증 통과한 실제 AI 결과 | 정상 표시 |
| `sample` | 검수된 샘플(목업) | **"샘플" 표시**하고 제공 |
| `rejected` | 검증 실패 | **학습 화면에 넣지 않는다.** 재시도 안내 |

`usable` 이 `ok`/`sample` 이 아니면 그 문장으로 학습시키지 마세요. 목업을 쓰는 것 자체는
문제가 아니고, **목업과 실제 AI 성공을 구분하지 않는 것**이 문제입니다.

## 4-1. 취약 표현(Long-term Memory) — 태그가 아니라 상황으로 검증

**별도 매핑 파일이 없습니다. 취약 id = 연습해야 할 `situation_id` 입니다.**

```json
"weak_expressions": ["allergy_notice"]   →   알레르기 상황의 문장이 생성돼야 함
```

검증 규칙 (세 조건):

| # | 조건 | 코드 | severity |
|---|---|---|---|
| 1 | 요청한 id 가 그 카테고리의 유효한 `situation_id` 인가 | `weak_unknown_situation` | warn |
| 2 | `targets_weak` 태그가 그 문장의 `situation_id` 와 일치하는가 | `weak_tag_mismatch` | warn |
| 3 | 요청한 상황의 문장이 결과에 포함됐는가 (+ 키워드) | `weak_not_covered` / `weak_content_mismatch` | block |

`required_keywords` 는 카테고리 파일의 상황에 선택적으로 답니다. 없으면 상황 존재만 봅니다.

**`targets_weak` 태그만 보고 통과시키지 않습니다.** 태그는 "반영했다"는 자기 주장일 뿐이고,
실제 판단은 상황(+키워드)으로 합니다. 그래서 목업도 태그를 위조하지 않습니다.

### 이 검사가 보장하지 않는 것

**구조적 일관성 검사이지 의미 검증이 아닙니다.** 문장 내용이 "샌드위치 주세요"인데
`situation_id` 를 `allergy_notice` 로 잘못 붙이고 키워드까지 넣으면 통과합니다.
그래서 **"내용까지 자동으로 보장한다"고 주장하면 안 됩니다.** 관련 문장은 사람이 검수합니다.
`required_keywords` 는 명백한 불일치(알레르기 단어가 아예 없음)만 잡는 보조 장치입니다.

### 제품 용어도 맞추세요

weak id 가 상황 단위가 되었으므로, **"취약 표현 기억"보다 "어려워한 상황 기억"**이 정확합니다.

Long-term Memory의 실제 완료 기준:

> **발화/어려움 표시 → 저장 → 새 세션 복구 → 관련 카드 우선 배정 → 성공 후 상태 갱신**

지금 구현된 것은 네 번째(관련 카드 우선 배정 = 관련 상황 문장 생성)까지입니다.
**저장·복구·상태 갱신은 프론트 작업으로 남아 있습니다.**

### `usable` 이 `sample` 일 때

목업/샘플 결과로는 **취약 상태를 저장·갱신하지 마세요.** 개인화가 실제로 일어난 것처럼
표시하면 안 됩니다. "샘플 데이터입니다" 배지를 띄우고, 약점 기록은 `ok` 일 때만 씁니다.

## 4-2. 비용·남용 방어

| 항목 | 값 | 방법 |
|---|---|---|
| 호출 제한 | 20회/60초 (IP 기준) | `RATE_LIMIT` / `RATE_WINDOW` 환경변수 |
| 입력 길이 | `city` 80자, `places` 20개, `weak_expressions` 20개, `target` 200자 | Pydantic → 초과 시 422 |
| 오디오 | 8MB, `audio/*` 만 | 초과 시 413, 형식 오류 415, 빈 파일 400 |

> ⚠️ **Google Cloud 예산 알림은 지출을 자동으로 차단하는 상한이 아닙니다.** 알림만으로는
> 비용이 계속 나갑니다. "알림 + 상한이면 코드보다 확실하다"는 설명은 틀렸습니다.
>
> 실제로 준비할 것:
> - 예산 **알림** 설정 (경고용)
> - 사용 API 의 **할당량(quota) 한도** 확인·설정 — 이게 실질 상한
> - 이상 시 **API 키 비활성화 절차**를 미리 정해둠
> - 테스트 기간을 정해두고 그 뒤 키 회수
> - `ALLOW_ORIGINS` 를 배포 주소로 좁히기 (단, **브라우저 접근만 좁힐 뿐 API 직접 호출 비용은 못 막습니다**)



### 실제로 검사하는 것

| 코드 | severity | 내용 |
|---|---|---|
| `schema_invalid` | block | `schema.json` 구조 위반 (필드 누락·타입 오류) — `jsonschema` 로 실제 검사 |
| `weak_not_covered` | block | 요청한 취약 상황(situation_id)을 겨냥한 문장이 없음 (Long-term Memory를 코드로 보장) |
| `forbidden_topic` | block | 금칙 표현 |
| `category_mismatch` / `empty_pack` | block | 카테고리 불일치 / 빈 결과 |
| `situation_not_in_config` | block | 카테고리에 없는 상황 id |
| `missing_situation` | warn | 상황 커버리지 부족 — 3주차 측정값 |
| `below_min_sentences` | warn | 카테고리 최소 문장 수 미달 — 3주차 측정값 |
| `too_long` / `duplicate_en` / `not_polite` | warn | 길이·중복·말투 |
| `unknown_pattern_type` / `unknown_pattern_match` | warn (**설정 오류**) | `negative_case_patterns` 에 코드가 모르는 `type`/`match` 를 적었음. 무시되므로 이슈로 요청할 것. **3주차 측정값에 포함하지 마세요** |

> 구현된 `type` 은 `situation_in_config`, `word_count`, `duplicate_en` 뿐이고
> `match` 는 `substring` 뿐입니다. **이 목록에 없는 값을 적으면 아무 일도 일어나지 않습니다.**
> (대신 위 `unknown_pattern_type` 경고가 뜹니다.)
> 새 검사가 필요하면 `validators.py` 를 고쳐야 하므로 이슈로 요청하세요.

## 5. 프론트 연결

목업 `data.js` 의 하드코딩 생성 부분만 교체하면 됩니다.

```js
const API = "https://<앱이름>.onrender.com";

const res = await fetch(`${API}/generate`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    category_id: "restaurant",
    city: "New York",
    places: [{ name: "Katz's Delicatessen", place_type: "restaurant" }],
    weak_expressions: ["allergy_notice"],   // localStorage 에서 읽어 전달
  }),
});
const { pack, issues, degraded } = await res.json();
```

발음 입력은 `MediaRecorder` 로 녹음해 `FormData` 로 보냅니다. 서버가 `audio/webm;codecs=opus`
의 파라미터를 떼어내므로 브라우저 기본값 그대로 쓰면 됩니다.

```js
const fd = new FormData();
fd.append("target", "I'd like a pastrami sandwich, please.");
fd.append("file", blob, "take.webm");
const r = await (await fetch(`${API}/speak-check`, { method: "POST", body: fd })).json();
```

---

## 남은 작업

| 항목 | 시점 |
|---|---|
| 의존성 버전 고정 | ✅ 완료 (`requirements.txt`) |
| 시연용 프리셋 시드 + "데모 불러오기" 버튼 | 10/11 전 |
| 프론트 `data.js` → `/generate` 교체 | URL 확보 직후 |
| 실사용자 테스트 | 10/19~ |

## 화면 서빙
`mockup/` 을 같은 서비스의 `/` 에서 정적으로 서빙합니다(API 라우트 뒤에 마운트). 배포 URL 하나로 화면과 API가 같은 출처가 되어 CORS 설정이 필요 없습니다.
