# `/speak-check` score 반환률 측정 실행법

기준 커밋: `seongbin45/codyssey_final` `New-add-backend` (스크립트는 `bf61752`에서 보완, 저장 판정은 `9ea2eab`의 `weakDecision`)
대상 스크립트: `backend/scripts/measure_score_rate.py`

> 아래 "≥ 80%", "< 50%" 같은 숫자는 **임시 판단 기준**이다. 근거 데이터가 없고, 표본은 3개 파일이다. 유효한 점수가 **오는지**를 볼 뿐 그 점수가 **정확한지**는 보여주지 않는다.

> **왜 재는가**: `weakDecision`이 `auto`(자동 저장)로 판정하려면 **점수(70 미만)** 가 있어야 한다.
> Gemini가 점수를 자주 생략하면 `auto` 경로가 거의 안 쓰이고 `ask`(사용자 선택)가 기본이 된다.
> 이 측정은 **어느 경로가 실제로 제품을 지배하는지**를 정하는 근거다. `/health` 확인만으로는 알 수 없다.

---

## 0. 선행 조건

| 조건 | 확인 |
|---|---|
| 서버가 **목업이 아님** | `/health` → `has_api_key: true` (없으면 스크립트가 `exit 2`로 중단) |
| 배포 URL 확정 | 저장소·브랜치·커밋·URL 네 가지를 먼저 고정 |
| `target` 길이 | 서버 제약 **200자 이하** (`max_length=200`) — 넘으면 422 |
| 오디오 크기 | **8MB 이하** (초과 시 413) |
| 오디오 형식 | MIME이 `audio/*` 여야 함 (아니면 415). 확장자로 MIME을 추정하므로 **`.webm`/`.wav`/`.m4a`/`.ogg`** 로 저장 |
| 호출 제한 | 서버 기본 **20회/60초** → `--sleep 4` 이상이 안전 |

---

## 1. 오디오 3개 준비

**같은 `target` 문장**을 세 조건으로 각각 녹음한다. 브라우저 카드 뒷면 "🎤 말해보기"로 녹음한 파일을 그대로 써도 된다.

| 파일 | 조건 | 녹음 방법 |
|---|---|---|
| `good.webm` | 또박또박 | 목표 문장을 정확히, 또렷하게 |
| `bad.webm` | 일부러 틀리게 | 단어를 빼거나 다르게 (예: `allergy` 생략) |
| `silent.webm` | 무음 | 마이크 켜고 **말하지 않고** 2~3초 |

```
target = "I have a peanut allergy."   ← 세 조건 모두 같은 문장
```

---

## 2. 실행

**조건별로 따로** 실행한다 (한 번에 하나씩). `--label`이 출력 파일명과 요약 제목이 된다.

```bash
# Render 의 실제 HTTPS URL 로 바꿔서 한 번만 지정한다 (<…> 를 그대로 붙이면 셸이 리다이렉션으로 해석한다)
BASE_URL='여기에_Render의_실제_URL'

# good
python3 backend/scripts/measure_score_rate.py \
  --base "$BASE_URL" \
  --audio good.webm \
  --target "I have a peanut allergy." \
  --label good --n 10 --out measure_good_run01.jsonl

# bad
python3 backend/scripts/measure_score_rate.py \
  --base "$BASE_URL" \
  --audio bad.webm \
  --target "I have a peanut allergy." \
  --label bad --n 10 --out measure_bad_run01.jsonl

# silent
python3 backend/scripts/measure_score_rate.py \
  --base "$BASE_URL" \
  --audio silent.webm \
  --target "I have a peanut allergy." \
  --label silent --n 10 --out measure_silent_run01.jsonl
```

### 플래그 (검증된 실제 값)

| 플래그 | 기본 | 설명 |
|---|---|---|
| `--base` | 필수 | 서버 주소. 끝의 `/`는 있어도 됨 (`rstrip("/")` 처리) |
| `--audio` | 필수 | 오디오 파일 경로 |
| `--target` | 필수 | 목표 문장 (200자 이하) |
| `--label` | `run` | 조건 이름. `measure_<label>.jsonl` 파일명이 됨 |
| `--n` | `10` | 반복 횟수 |
| `--sleep` | `4.0` | 호출 간 대기(초). 서버 20회/60초 제한 |
| `--timeout` | `90.0` | 첫 호출은 콜드스타트로 느릴 수 있음 |
| `--out` | `measure_<label>.jsonl` | 호출별 원본 JSON 기록 (append) |

---

## 3. 출력 읽기

```
=== good: 10회 (원본: measure_good.jsonl) ===
1 HTTP 성공 / 전체 요청                         10 /  10  (100%)
2 usable:true / 실제 응답                       10 /  10  (100%)
3 유효 score / usable:true                     9 /  10  (90%)
4 점수 누락(null)+heard 있음 / usable:true        1 /  10  (10%)
  (참고) 값은 있으나 무효한 점수 / usable:true         0 /  10  (0%)
  (참고) score_discarded / 실제 응답               0 /  10  (0%)
  (참고) heard 비어 있음 / 실제 응답                 0 /  10  (0%)
```

**분모가 전부 다르다** — 이게 이 표의 핵심이다.

| 지표 | 분모 | 뜻 |
|---|---|---|
| 1 | 전체 요청 | 네트워크·서버가 살아 있는가 |
| 2 | 실제 응답(HTTP 200 ∧ 목업 아님) | 모델이 `usable:true`를 주는가 |
| 3 | `usable:true` | **점수가 유효하게 오는가** (bool 제외·유한·0~100·폐기 아님) |
| 4 | `usable:true` | **점수가 누락(null/없음)** 이고 `heard`는 있는가 → **`ask` 후보**. 점수 값이 있으나 무효(범위 밖·bool·문자열)인 응답은 여기 넣지 않고 "(참고) 값은 있으나 무효한 점수"로 센다. 프론트는 AI 문장 여부·유효한 상황 ID 등 다른 조건도 확인하므로 **이 비율을 `ask` 발생률로 읽지 않는다** |
| 참고 | 실제 응답 | 점수를 줬다가 버린 경우 / 들린 내용이 빈 경우 |

---

## 4. 판정 — 이 결과로 무엇을 하는가

| 관찰 | 해석 | 조치 |
|---|---|---|
| **good**: 3번 ≥ 80% | 점수가 자주 온다 (**점수가 타당한지, 자동 저장이 적절한지는 별개**) | `auto`(70 미만 자동 저장) 규칙을 임시로 유지. good이 낮은 점수를 받으면 오저장 가능성이 있고, 높은 점수면 정상이지만 자동 저장은 일어나지 않는다. `bad`와 비교해서 본다 |
| **good**: 3번 < 50%, 4번 높음 | 모델이 점수를 자주 생략 (JSONL의 `response`로 누락인지 무효값인지 확인) | `auto` 경로가 거의 안 쓰임 → **제품은 `ask`(사용자 선택)가 기본**. 발표에서도 이 사실을 그대로 말한다 |
| **bad**: 3번 유효 score가 **높게**(70 이상) 나옴 | 틀린 발화를 통과시킴 | 자동 저장 규칙 신뢰 불가 — `ask` 비중을 높이는 쪽으로 |
| **silent**: 4번이 아니라 **3번이 높음** | **무음에 점수를 줌 — 결함** | `heard` 빈값 가드가 저장은 막지만(`none`), 점수 자체가 무의미 → `measure` 기록과 함께 보고 |
| **silent**: 참고 `heard 비어 있음` = 100% | 정상 | 무음이 무음으로 인식됨 |
| 1번 < 100% | **원인을 먼저 구분한다** (JSONL의 `status`·`error`) | 413·415·422: 파일·MIME·입력 수정 / 429: 우리 서버 제한(`RATE_LIMIT`)인지 Gemini 할당량인지 구분 / 타임아웃: 서버 상태·콜드스타트 확인 후 `--timeout` / 5xx: 서버 로그 확인. **실패 기록은 지우지 말고, 조건을 바꾼 재측정은 별도 실행으로 남긴다** |
| `exit 2` + "mock 모드" | 키 없음 | 키 등록 후 재실행 (측정 무효) |

---

## 4-1. 하지 말 것

- **"70 미만이 나올 때까지" 재실행하지 않는다.** good에서 점수가 70 위아래로 흔들리는 것은 자연스럽다. `auto`가 한 번도 안 나왔다면 그대로 보고하고, 기억은 `ask`(사용자 선택) 경로로 시연한다.
- 확장자만 바꿔서 형식을 맞추지 않는다. 확장자는 MIME 추정에만 쓰이고 **오디오 변환이 아니다.** 실제로 해당 형식으로 녹음된 파일을 쓴다.
- `--out` 은 append 이다. **실행마다 `--out measure_good_run01.jsonl` 처럼 다르게 지정**해 이전 측정과 섞이지 않게 한다.
- `--base` 는 Render의 **실제 URL** 로 바꿔서 실행한다. 아래 예시의 `<앱>` 은 실행 가능한 주소가 아니다.

## 5. 한계 — 발표에 쓸 때 반드시 붙일 것

- **같은 파일을 n번 보낸다.** 이건 **응답의 일관성** 측정이지 **서로 다른 발화 n개**를 평가한 것이 아니다.
  → "발화 30개를 평가했다"고 말하면 안 된다. 별도로 다양한 발화 세트가 필요하다.
- `--label` 3개 × `--n 10` = **30회 호출**이지만 표본은 **3개 파일**이다.
- 실제 사용자 목소리 다양성(억양·속도·잡음)은 이 측정에 들어 있지 않다.

---

## 6. 참고: 원본 JSONL

호출마다 한 줄씩 남는다. **원인 분석은 이 파일로 한다.**

```json
{"i": 1, "label": "bad", "status": 200, "error": null,
 "response": {"usable": true, "score": null, "heard": "I have allergy peanuts", "fix_one": "...", "tip": "..."},
 "class": {"http_ok": true, "mock": false, "real": true, "usable": true, "valid_score": false, "no_score_with_heard": true, ...}}
```

`response` 가 원본, `class` 가 분류 결과다. **점수가 왜 안 왔는지**는 `response` 를 봐야 안다.

---

## 7. 검증 이력

| 항목 | 결과 |
|---|---|
| 분류 규칙 단위 테스트 (`test_measure_score_rate.py`) | 4 tests OK (이 저장소 작업 세션에서 실행 확인) |
| 가짜 로컬 서버에 응답 5종(정상 점수 · 점수 없음 · `usable:false` · 깨진 JSON · 429)을 보내 집계·원본 JSONL 기록 확인 | 분모별 집계가 의도대로 나옴 (실행 확인) |
| 연결 불가 서버 대상 실행 | 중단 없이 분모 0으로 종료 (실행 확인) |
| good·bad·silent 스텁 서버 3조건 실행 | **다른 작업 세션의 실행 보고** (good → 3번 100%, bad → 4번 100%, silent → heard 비어 있음 100%). 재현 자료(명령·로그) 미첨부 |
| 실제 Gemini 호출 | **미검증** — 키와 URL 필요 |

> 위는 합성 응답으로 확인한 것이다. **실제 Gemini 응답의 점수 반환률은 아직 모른다.**

---

## 무음 실측 (2026-10-07) — 채점 구조 변경 근거

자세한 조사와 결정: `docs/research/speak-hallucination.md`

목표 문장 "I have a peanut allergy.", 배포 서버, `measure_score_rate.py`.
음성은 macOS `say -v Samantha` → `afconvert -f WAVE -d LEI16@16000` 로 만들었다(사람 녹음 아님).

### 수정 전 (`01d29ae`, 녹음 + 목표 문장을 한 번에 Gemini 에)

| 입력 | n | usable:true | 유효 점수 | heard |
|---|---:|---:|---:|---|
| 1초 완전 무음 WAV | 10 | **10** | **10 (95~100점)** | **10회 모두 목표 문장 그대로** |
| 맞게 읽음 (TTS) | 3 | 3 | 3 (95~100점) | 정확 |
| 다른 문장 (TTS) | 3 | 3 | 3 (10~20점) | 정확 ("where is the subway station") |

### 수정 후 (`e961b55`: Silero VAD + Groq Whisper, 점수는 코드)

| 입력 | n | usable:true | 점수 | heard | 비고 |
|---|---:|---:|---|---|---|
| 1초 완전 무음 WAV | 10 | **0** | 없음 | "" | VAD 말소리 0초, 전사 API 호출 0회 |
| 맞게 읽음 (TTS) | 3 | 3 | 100·100·100 | "I have a peanut allergy." | Groq `whisper-large-v3`, 1회 시도 |
| 다른 문장 (TTS) | 3 | 3 | 0·0·0 | "Where is the subway station?" | 들린 문장을 그대로 받아씀 |

원자료: 측정 스크립트 jsonl(로컬 보관). 교차검증 필수화(다음 PR) 뒤 같은 표를 다시 잰다.

### 교차검증 필수화 + 로컬 pyannote (`6e46f10`, 2026-10-08)

Silero·로컬 pyannote 두 검출기 AND → Groq whisper-large-v3 + AssemblyAI universal-3-5-pro 동시 전사 → 두 전사 모두에서 들린 단어만 점수.

| 입력 | n | usable:true | 점수 | 1차 전사 / 교차검증 전사 | 비고 |
|---|---:|---:|---|---|---|
| 1초 완전 무음 WAV | 10 | **0** | 없음 | – | 두 검출기 0초, 외부 API 0회, 요청당 약 0.2초 |
| 맞게 읽음 (TTS) | 3 | 3 | 100·100·100 | 같은 문장 / 같은 문장 (일치도 1.0) | 전사·교차검증 각 1회 시도 |
| 다른 문장 (TTS) | 3 | 3 | 0·0·0 | "Where is the subway station?" 둘 다 (일치도 1.0) | 요청당 약 5초 |

- 응답 시간: 정상 상태에서 요청당 약 5초(동시 전사 + Gemini 피드백).
- **재배포 직후 첫 요청**은 Gemini 피드백이 8번째 시도에야 성공해 매우 오래 걸렸다(서버 재시작으로 '마지막 성공 모델' 기억이 사라짐, `/health` cooling: gemini-2.5-flash 404, gemini-omni-1.1-flash 429). 두 번째부터 1회.
  → 시연·사용자 테스트 전에는 `/health` 로 깨운 뒤 말하기를 한 번 해 두면 이후 요청이 빠르다.
- 자가 점검(`/health` `stt_selftest.results.local_detectors`): 서버에서도 무음 Silero 0·pyannote 0, TTS 둘 다 1.32초 — 로컬과 같음.
- pyannoteAI 클라우드는 402(크레딧 없음)로 쓰지 않는다 — PR #14.

> 수정 후 점수는 **단어 일치율**(`score_kind: "word_match"`)이다. 수정 전 점수(AI 가 매긴 발음 점수)와 뜻이 다르므로 숫자를 직접 비교하지 않는다. 비교할 것은 무음에 점수가 나오는지와 heard 를 지어내는지다.
