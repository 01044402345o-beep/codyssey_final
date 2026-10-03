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
| `issues[].severity` | `block` = 재생성 대상 / `warn` = 검토 대상 |
| `degraded` | 재시도 후에도 `block` 이 남아 목업으로 대체됨. 화면에 표시하고 검증 담당에게 로그 전달 |
| `mock` | API 키 없이 목업으로 응답 |

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
