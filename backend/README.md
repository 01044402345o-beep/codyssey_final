# 백엔드 — 배포 먼저

엔드포인트 **3개가 상한**입니다. 기능을 더 붙이면 Firebase를 걷어낸 이유가 그대로 재발합니다.

| 메서드 | 경로 | 역할 |
|---|---|---|
| GET | `/health` | 배포 확인 + 시연 전 콜드스타트 깨우기 |
| POST | `/generate` | 카테고리 문장 생성 → 스키마·규칙 검증 → 위반 시 재생성 |
| POST | `/speak-check` | 발음 오디오 → 피드백 (멀티모달) |

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
| `GEMINI_API_KEY` | Google AI Studio에서 발급 | 없으면 목업 응답 |
| `GEMINI_MODEL` | 기본 `gemini-flash-latest` | 별칭이 바뀌면 AI Studio에서 현재 이름 확인 |
| `ALLOW_ORIGINS` | 프론트 배포 주소 | 기본 `*` |

### 무료 플랜 주의

- **콜드스타트**: 15분 유휴 후 첫 요청이 30~60초. **시연 10분 전에 `/health` 를 호출**해 깨우세요.
- 파일시스템이 휘발성입니다. 상태를 저장하지 마세요(취약 표현은 요청에 실어 보내는 구조).

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
| `weak_not_covered` | block | 요청한 취약 표현을 겨냥한 문장이 없음 (Long-term Memory를 코드로 보장) |
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
    weak_expressions: ["w_allergy_peanut"],   // localStorage 에서 읽어 전달
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
