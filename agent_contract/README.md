# AI 문장 생성 계약 (Agent Contract)

상황별 문장 생성을 **담당자별로 나눠서** 작업하기 위한 공통 형식입니다.
각 담당자는 **자기 카테고리 설정 파일 1개**를 만들어 PR 하면 됩니다.

---

## 1. 담당자별 카테고리

| 담당 | 카테고리 | category_id |
|---|---|---|
| 이영애 | 식당·카페 | `restaurant` |
| 이창진 | 교통·공항 | `transport` |
| 함명자 | 숙소·체크인 | `lodging` |
| 이주란 | 검증 — 전 카테고리 실패 케이스 | — |
| 최성빈 | 생성 함수·검증 코드·통합 | — |
| 한재정 | 전체 리뷰 | — |

> **돌발·응급은 AI 생성 카테고리에서 제외합니다.** 안전 문장은 매번 AI가 새로 만들면 안 되고,
> 팀원 한 명에게 의존하면 비면 위험합니다. **검수된 고정 문장**을 코드에 둡니다 (현재 5개: `mockup/data.js` 의 `emergency`)
> (한재정 선생님 부담은 전체 리뷰만). 기획서에는 "돌발·응급 표현 제공"으로 남습니다.
>
> 늦어져도 괜찮으니 편하게 알려주세요. 비난이 아니라 일정 장치입니다.


---

## 2. 각자 만들 것 — 파일 1개

`categories/<category_id>.json` 을 만들고 PR 하세요.
**`categories/restaurant.json` 이 완성된 예시입니다. 복사해서 값만 바꾸면 됩니다.**

PR 본문에 아래 4개를 체크해 주세요.

- [ ] `situations` — 상황 목록 10개 내외 (`situation_id` 는 영문 스네이크)
- [ ] `system_prompt` — 이 카테고리 전용 프롬프트
- [ ] `good_examples` — 좋은 출력 예시 3개
- [ ] `negative_cases` — 반드시 걸러야 할 예시 5개 (금칙·장소 불일치·중복·길이·말투)

**PR 올리기 전에 점검 한 줄** (내 파일이 서버가 읽을 수 있는 형식인지 확인합니다):

```bash
pip install -r backend/requirements.txt          # 처음 한 번
python backend/scripts/validate_category.py agent_contract/categories/<내_id>.json
```

`오류 0개` 가 나오면 PR 해도 됩니다. 오류는 무엇을 고칠지 한국어로 알려줍니다.
문장이 자연스러운지·상황이 실제로 쓸모 있는지는 이 점검이 보지 못합니다. 그건 사람이 검수합니다.

> 코드를 몰라도 됩니다. JSON은 `{ "키": "값" }` 형태의 목록이고, 예시 파일을 그대로 따라 쓰면 됩니다.
> 작성하다 막히면 디스코드에 물어보세요.

---

## 3. 프롬프트에 값 넣기 (플레이스홀더)

`system_prompt` 안에 `{키이름}` 을 쓰면, `rules` 의 **같은 키 값**으로 자동 치환됩니다.

| 프롬프트에 쓴다 | 치환되는 값 (rules 키) |
|---|---|
| `{min_sentences_per_situation}` | 1 |
| `{max_sentences_per_situation}` | 3 |
| `{max_words_per_sentence}` | 15 |

키 이름을 그대로 쓰세요. `{min}` 같은 축약형은 치환되지 않고 글자 그대로 남습니다.

---

## 4. 출력 형식

`schema.json` 이 **AI가 돌려줘야 하는 형식**입니다. 벗어나면 코드가 자동으로 재시도합니다.
`situation_id` 는 각자 설정 파일의 `situations[].situation_id` 중 하나여야 합니다.

```json
{
  "category_id": "restaurant",
  "city": "New York",
  "sentences": [
    {
      "place": "Katz's Delicatessen",
      "place_type": "restaurant",
      "situation_id": "order_menu",
      "situation": "대표 메뉴 주문",
      "en": "I'd like a pastrami sandwich, please.",
      "ko": "파스트라미 샌드위치 하나 주세요.",
      "level": "basic",
      "tags": ["주문"],
      "targets_weak": ["allergy_notice"]
    }
  ]
}
```

**`targets_weak`** — 이 문장이 겨냥한 취약 표현을 적습니다. **값은 `situation_id` 와 같아야 합니다.**

> ⚠️ **태그는 "반영했다"는 자기 주장일 뿐입니다.** 서버는 태그만 보고 통과시키지 않습니다.
> 요청에 취약 상황이 오면 **그 상황의 문장이 실제로 생성됐는지**, 그리고
> **`required_keywords` 가 그 문장에 들어갔는지**를 확인합니다.
> - 그 상황의 문장이 없으면 → `weak_not_covered` (차단)
> - 상황은 맞는데 관련 단어가 없으면 → `weak_content_mismatch` (차단)
>
> 별도 취약 표현 목록 파일은 없습니다. **취약 id = 연습할 상황 id** 입니다.
> (예: 알레르기를 못하면 weak id 는 `allergy_notice`)

상황별로 반드시 들어가야 할 단어가 있으면 그 상황에 `required_keywords` 를 답니다.

```json
{ "situation_id": "allergy_notice", "situation": "알레르기·재료 고지",
  "required_keywords": ["allergy", "allergic"] }
```

이 필드는 **선택**입니다. 없으면 "그 상황의 문장이 있는지"만 검사합니다.
단어까지 확인하려면 본인 카테고리 파일의 해당 상황에 추가하세요.


---

## 5. 검증 담당(이주란)이 쓰는 법

각 카테고리의 `negative_cases` 와 `negative_case_patterns` 를 모아서 **같은 코드로** 자동 검사합니다.
규칙은 `backend/app/validators.py` 에 이미 구현돼 있습니다.

| 검사 | 코드 | severity | 측정값 |
|---|---|---|---|
| 금칙이 실제로 걸러지는가 | `forbidden_topic` | block | 카테고리별 적중률 |
| 취약 상황 반영 | `weak_not_covered` / `weak_content_mismatch` | block | 요청 대비 미반영 수 |
| 상황 누락 수 | `missing_situation` | warn | `situations` 대비 누락 |
| 카테고리 최소 문장 수 | `below_min_sentences` | warn | `rules.min_sentences_per_category` 대비 |
| 영문 중복 | `duplicate_en` | warn | 팩 안 중복 수 |
| 문장 길이 | `too_long` | warn | `max_words_per_sentence` 초과 수 |


**block 은 재생성이 돌고, warn 은 측정값으로 남습니다.**
3주차 비교 실험(단일 프롬프트 vs 카테고리 분할)은 **warn 항목의 개수**로 비교하세요.
단일 프롬프트는 상황 누락과 중복에서 warn 이 더 많이 나오는지 보는 것이 핵심입니다.

실행:
```bash
cd backend && python scripts/check_negatives.py        # negative_cases 자체 점검
cd backend && uvicorn app.main:app --reload            # /docs 에서 직접 호출
```

**측정은 제안자가 아니라 검증 담당이 합니다.**

---

## 6. 일정

| 시점 | 할 일 |
|---|---|
| 10/5 (월) | 최성빈: `restaurant.json` 샘플 + 생성 함수 형식 확정, 채널 공지 |
| 10/8 (목) | 각자 `categories/<id>.json` PR |
| 10/11 (일) | 검증 코드 연결, 비교 실험 1회 |

샘플이 늦으면 다섯 명이 전부 대기합니다. 이 구조에서 가장 먼저 깨지는 지점입니다.

---

## 7. 파일

| 파일 | 설명 |
|---|---|
| `schema.json` | AI 출력 형식 (수정 금지, 필요하면 이슈) |
| `categories/restaurant.json` | **완성된 예시 + 내가 만들 템플릿** |
