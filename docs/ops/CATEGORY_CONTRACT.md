# 카테고리 계약 정리 (agent_contract)

2026-11-07 팀 `main` 기준 · `agent_contract/` 4개 카테고리 · 상황 40개

생성기가 **무엇을 만들어야 하는지**를 고정하는 계약이다. 산문이 아니라 JSON 이고, 검증기가 이 파일을 읽어 판정한다.


## 1. 파일 지도

| 파일 | 역할 | 이 정리에서 중요한 점 |
|---|---|---|
| `schema.json` | 팩 응답의 구조 | 어기면 `block` — 재생성 |
| `categories/{id}.json` | 카테고리별 상황·규칙·예시 | `situation_id` 가 문장 배정의 키 |
| `README.md` | 사람이 읽는 설명 | 코드보다 먼저 낡는다 — 아래 §6 참고 |

## 2. 카테고리 4종 한눈에

| 카테고리 | 이름 | 장소 유형 | 상황 | 규칙 | 부정 예시 | 좋은 예시 |
|---|---|---|---|---|---|---|
| `attraction` | 관광지·명소 | 1종(attraction) | **10** | 5개 | 5 | 8 |
| `lodging` | 숙소·호텔 | 4종(hotel·hostel·guesthouse·airbnb) | **10** | 5개 | 5 | 3 |
| `restaurant` | 식당·카페 | 2종(restaurant·cafe) | **10** | 5개 | 5 | 3 |
| `transport` | 교통·공항 | 5종(airport·train_station·bus_station·subway_station·taxi_stand) | **10** | 5개 | 5 | 3 |

각 카테고리 = 1개 장소 유형 묶음 = **10상황**이다. 4×10 = **40상황**이 생성기의 전체 표면이다.


## 3. 상황 계약 (situation)

```json
{
  "situation_id": "...",
  "situation": "...",
  "required_keywords": ["..."]
}
```

| 카테고리 | situation_id | 상황 | 필수 키워드 |
|---|---|---|---|
| `attraction` | `buy_ticket` | 입장권 구매 | ticket, tickets |
| `attraction` | `ask_hours` | 운영 시간 문의 | open, close |
| `attraction` | `find_entrance` | 입구·출구 찾기 | entrance, exit |
| `attraction` | `guided_tour` | 가이드 투어·오디오 가이드 문의 | tour, guide |
| `attraction` | `photo_request` | 사진 부탁·촬영 가능 여부 | photo, picture |
| `attraction` | `ask_way` | 찾아가는 길 묻기 | — |
| `attraction` | `see_feature` | 대표 볼거리 묻기 | — |
| `attraction` | `bag_storage` | 짐 보관·반입 문의 | — |
| `attraction` | `ask_discount` | 학생·어린이 할인 문의 | discount |
| `attraction` | `souvenir_shop` | 기념품 가게 찾기 | — |
| `lodging` | `check_in` | 체크인·예약 확인 | check in, reservation |
| `lodging` | `leave_luggage` | 수하물 맡기기 | luggage, baggage, keep, store |
| `lodging` | `room_upgrade` | 객실 업그레이드 문의 | — |
| `lodging` | `ask_breakfast` | 조식 시간·위치 질문 | breakfast |
| `lodging` | `ask_wifi` | 와이파이 비밀번호 요청 | — |
| `lodging` | `early_late_check` | 얼리 체크인·레이트 체크아웃 | — |
| `lodging` | `request_amenity` | 수건·어메니티 추가 요청 | towel, water |
| `lodging` | `order_room_service` | 룸서비스 주문 | — |
| `lodging` | `room_complaint` | 객실 문제(청소·소음) 컴플레인 | — |
| `lodging` | `check_out` | 체크아웃·비용 정산 | check out, bill, pay |
| `restaurant` | `reserve_table` | 자리 예약·문의 | — |
| `restaurant` | `ask_wait` | 대기 시간·웨이팅 및 호출 방식 확인 | — |
| `restaurant` | `order_menu` | 대표 메뉴 주문 | — |
| `restaurant` | `ask_recommend` | 추천 메뉴 요청 | — |
| `restaurant` | `allergy_notice` | 알레르기·재료 고지 | allergy, allergic |
| `restaurant` | `request_side` | 추가 요청 (물·리필·소스) | refill, one more, another |
| `restaurant` | `ask_ingredient` | 재료·조리법 질문 | — |
| `restaurant` | `takeout` | 포장 요청 | — |
| `restaurant` | `pay_check` | 계산·영수증 요청 | check, bill, receipt |
| `restaurant` | `tip_split` | 더치페이·분할 결제 문의 | — |
| `transport` | `airport_checkin` | 공항 체크인·좌석 요청 | — |
| `transport` | `check_baggage` | 수하물 위탁·무게 확인 | baggage, luggage |
| `transport` | `security_check` | 보안 검색 절차·위치 문의 | — |
| `transport` | `find_gate` | 탑승구·탑승 시간 확인 | gate, boarding |
| `transport` | `flight_delay` | 항공편 지연·결항 문의 | delayed, cancelled |
| `transport` | `transfer_route` | 환승·연결편 문의 | transfer, connecting flight |
| `transport` | `buy_ticket` | 기차·버스표 구매 | — |
| `transport` | `ask_platform` | 승강장·정류장 위치 확인 | platform, stop |
| `transport` | `public_transport_route` | 지하철·버스 노선·하차 지점 문의 | — |
| `transport` | `taxi_ride` | 택시 목적지·요금·결제 문의 | — |

**주의**: `required_keywords` 는 네 카테고리 모두에 있지만 **상황마다** 있거나 없다. 40상황 중 19개만 갖고 있다(attraction 6 · lodging 5 · restaurant 3 · transport 5). 키워드는 두 곳에 쓰인다. 복습 상황을 프롬프트에 넣을 때 함께 넣고(`backend/app/main.py:472-478`), `check_weak_coverage()` 가 판정에 쓴다. 복습 목록에 오른 상황의 문장에 키워드가 하나도 없으면 `weak_content_mismatch`(block)로 막는다. 키워드가 없는 21상황은 문장이 있기만 하면 통과한다(§5).


## 4. 규칙(rules)과 부정 예시


### `attraction`

- **min_sentences_per_situation**: 1
- **max_sentences_per_situation**: 3
- **max_words_per_sentence**: 15
- **min_sentences_per_category**: 8
- **tone**: polite
- 부정 패턴: forbidden_topic, place_mismatch, too_long, duplicate, not_polite

### `lodging`

- **min_sentences_per_situation**: 1
- **max_sentences_per_situation**: 3
- **max_words_per_sentence**: 15
- **min_sentences_per_category**: 8
- **tone**: polite
- 부정 패턴: forbidden_topic, place_mismatch, too_long, duplicate, not_polite

### `restaurant`

- **min_sentences_per_situation**: 1
- **max_sentences_per_situation**: 3
- **max_words_per_sentence**: 15
- **min_sentences_per_category**: 8
- **tone**: polite
- 부정 패턴: forbidden_topic, place_mismatch, too_long, duplicate, not_polite

### `transport`

- **min_sentences_per_situation**: 1
- **max_sentences_per_situation**: 3
- **max_words_per_sentence**: 15
- **min_sentences_per_category**: 8
- **tone**: polite
- 부정 패턴: forbidden_topic, place_mismatch, too_long, duplicate, not_polite

## 5. 검증기가 계약을 읽는 방식

| 함수 | 하는 일 |
|---|---|
| `validators._words()` | 단어 수 세기(길이 규칙의 기반) |
| `validators.check_pattern_declarations()` | `negative_case_patterns` 의 `type`·`match` 가 구현된 값인지 검사(severity 오타는 검사하지 않는다) |
| `validators.validate_sentence()` | 문장 1건: 길이·자리표시자·장소 불일치·금지 패턴·중복 |
| `validators.validate_schema()` | 팩이 `schema.json` 을 따르는지 |
| `validators.check_weak_coverage()` | 복습 목록의 상황이 팩에 실제로 들어갔는지(빠지면 block) |
| `validators.validate_pack()` | 위 검사를 팩 단위로 묶고 `has_blocking` 으로 판정 |
| `validators.has_blocking()` | block 이 하나라도 있으면 재생성 신호 |

`negative_case_patterns` 안의 `_note` 는 패턴이 아니라 사람이 읽는 설명이다.

severity 는 두 단계다. `block` 은 응답을 버리고 재생성, `warn` 은 쓰되 품질 측정값으로 남긴다. 계약의 `negative_case_patterns` 에 `severity` 를 적어 두면 그 값이 우선한다.


## 6. 계약의 빈틈

2026-11-08 에 생성기·화면·테스트·데이터 네 방향으로 나눠 점검했다. 아래 항목은 모두 코드로 따라가거나 실제 검증기를 돌려 확인했다. "지금은 안 일어남"은 지금 화면이 만드는 장소 종류(restaurant·cafe·attraction)로는 생기지 않는다는 뜻이다.

### 6-1. 복습 상황 판정

1. **`required_keywords` 가 40상황 중 19개에만 있다.** 나머지 21상황(예: `restaurant.order_menu`, `transport.taxi_ride`)은 복습 목록에 올라도 문장 내용이 그 상황과 맞는지 판정할 근거가 없다. 상황 id 만 붙이고 내용은 다른 문장도 통과한다.
2. **키워드 철자가 좁아서 자연스러운 문장이 block 된다.** 키워드는 소문자 부분일치(`validators.py:233-236`)라 다른 철자를 잡지 못한다.
   - "Where is the check-in desk?" 는 `check_in` 에서 `weak_content_mismatch`(block)가 난다. 키워드가 `check in`(띄어쓰기)이다.
   - "Has my flight been canceled?" 는 `flight_delay` 에서 block 된다. 키워드가 영국식 `cancelled` 다.
   - 반대로 "Is this the tourist information desk?" 는 `tour` 가 `tourist` 안에 있어 `guided_tour` 로 인정된다.
3. **두 카테고리에 같은 id 가 있으면 복습 상황이 바뀐다(지금은 안 일어남).** `buy_ticket` 은 attraction(입장권 구매, 키워드 ticket)과 transport(기차·버스표 구매, 키워드 없음)에 모두 있다.
   - 화면은 모든 카테고리의 복습 id 를 한 목록으로 합친 뒤(`mockup/app.js:1933`, `1960`) 요청 카테고리에 같은 이름이 있는지만 본다(`mockup/ai.js:149-150`).
   - 서버도 이름만 본다(`backend/app/main.py:472-478`, `validators.check_weak_coverage()`).
   - 그래서 transport 의 `buy_ticket` 이 attraction 요청에 실리면 입장권 문장이 나오고, 서버는 복습이 반영됐다고 판정한다.
   - 저장과 표시는 `(category_id, id)` 쌍으로 처리하므로 충돌이 없다(`mockup/ai.js:184`).
4. **요청 카테고리에 없는 복습 id 는 경고 하나만 남고 빠진다.** `weak_unknown_situation` 은 warn 이라(`validators.py:207-217`) 재생성이 일어나지 않는다. `/health` 에 `situations` 가 없으면 화면은 거르지 않고 그대로 보낸다(`mockup/ai.js:150`).
5. **키 없는 시연(목업)에서 일부 복습 상황은 결과가 버려진다.** 목업은 `good_examples` 를 그대로 돌려주고 같은 검증을 거친다(`main.py:925-936`). 예시 문장이 없는 상황을 복습 목록에 넣으면 `weak_not_covered`(block)가 나서 결과가 `rejected` 가 된다.
   - 해당 상황: lodging `ask_breakfast`·`request_amenity`·`check_out`, restaurant `request_side`·`pay_check`, transport `find_gate`·`transfer_route`·`ask_platform`
   - attraction 은 해당 없다.

### 6-2. 금지어가 정상 문장을 잡는다

`negative_case_patterns` 의 `terms` 는 소문자 부분일치다. 아래는 실제 검증기(`validate_sentence`)로 돌린 결과다.

| 문장 | 판정 | 걸린 금지어 |
|---|---|---|
| Can children under six enter without a ticket? | **block** | `without a ticket` |
| Am I allowed to touch the exhibits? | **block** | `touch the exhibits` |
| Can I get drunken noodles, please? | **block** | `get drunk` |
| Where is the fast lane to skip security lines? | **block** | `skip security` |
| Is the museum open right now? | warn | `right now` |
| Could you give me the bill, please? | warn | `give me the` |

- block 은 결과를 버리고 다시 생성한다. 그래서 어린이 무료 입장이나 전시물을 만져도 되는지 같은 정당한 질문이 결과에서 빠질 수 있다.
- `right now` 는 lodging·restaurant 의 `_note` 가 스스로 넣지 말라고 한 'now 같은 일반어'에 해당한다.
- 반대로 lodging 의 음주 금지는 "Let's grab a beer." 를 잡지 못한다. 프롬프트는 음주 권유 전체를 금지하지만 `terms` 는 일부 문구만 막는다.

### 6-3. 적혀 있지만 검사하지 않는 규칙

| 규칙 | 실제로 쓰는 곳 | 빈틈 |
|---|---|---|
| `max_sentences_per_situation` | 프롬프트 치환만 | 검사하는 코드가 없다. 한 상황에 문장이 몇 개 나와도 통과한다. |
| `max_words_per_sentence` | 프롬프트 치환만 | 길이 검사는 `negative_case_patterns.too_long.max` 를 쓴다(`validators.py:140-146`, warn). 지금은 둘 다 15지만 같은지 확인하는 곳이 없다. |
| `tone` | 아무 데도 없음 | 프롬프트에 polite 가 직접 적혀 있고, 이 값을 바꿔도 아무것도 달라지지 않는다. |
| `min_sentences_per_situation` | `validate_pack` | 위반이 warn 이다. 값이 없거나 0이면 1로 바뀐다(`validators.py:323`). |
| `min_sentences_per_category` | `validate_pack` | 위반이 warn 이고, 값이 없으면 검사가 꺼진다(`validators.py:337`). 프롬프트에도 없다. |

- **생성된 문장의 `place_type` 은 검사하지 않는다.** 요청의 장소 종류는 422로 거절하지만(`main.py:448-462`), 출력 쪽은 schema 가 아무 문자열이나 받고 검증기도 읽지 않는다. restaurant 팩에 `place_type: "hotel"` 이 섞여도 통과한다.
- **`place_mismatch` 라는 이름과 실제 검사가 다르다.** 이 패턴의 severity 는 상황 id 검사(`situation_not_in_config`)에 쓰인다(`validators.py:104`). 장소는 검사하지 않는다.
- **`good_examples` 는 실제 생성 때 모델에 보이지 않는다.** 목업 응답에만 쓰인다(`main.py:506-513`).

### 6-4. 계약을 두 곳 이상에 적어 둔 곳

계약을 고칠 때 아래도 함께 고쳐야 한다. 지금은 모두 JSON 과 일치한다.

- **`situation_id` 형식:** `schema.json` 과 `mockup/ai.js:16` 의 `ID_RE`
- **장소 종류→카테고리 표:** `mockup/ai.js:294-300` 의 `KIND_CATEGORY`. 화면은 `/health` 의 `categories` 를 쓰지 않으므로 카테고리를 추가하면 이 표를 고치기 전에는 화면에 나오지 않는다.
- **`place_types` 목록:** 네 `system_prompt` 가 `place_type in [...]` 을 직접 적었다. 프롬프트에는 JSON 값이 들어가지 않는다.
- **조사 주제→카테고리:** `backend/app/research/situations.py:14-18` 의 `TOPIC_CATEGORIES`
- **장소 종류(kind)가 빈 요청:** `mockup/ai.js:155` 는 `place_type: p.kind || cat` 을 보낸다. kind 가 비면 transport·lodging 요청은 카테고리 이름이 장소 종류 목록에 없어 422가 난다. 지금 화면은 kind 가 있는 장소만 보내서 안 일어난다. 422가 나면 화면은 그 도시만 기본 문장으로 바꾸고 원인을 보여 주지 않는다.

### 6-5. 테스트가 지키는 것과 지키지 않는 것

점검 당시에는 CI 의 전체 점검(`scripts/test_validate_category.py`)이 restaurant 한 파일만 받았다. 이번에 아래 두 테스트를 넣었다.

- `backend/tests/test_contract_invariants.py`
  - 카테고리가 정확히 네 개인지 본다.
  - 네 파일 모두 `check_config` 를 오류 없이 통과하는지 본다. 이 점검에는 `situation_id` 중복, good_examples 통과, 플레이스홀더가 들어 있다.
  - 파일 이름과 `category_id` 가 같은지 본다.
  - 상황 id 목록을 고정해, 이름을 바꾸거나 지우면 깨지게 한다.
- `mockup/ai.test.js`: 계약 JSON 의 `place_types` 가 모두 `categoryOfKind` 로 그 파일의 카테고리에 가는지 본다(`KIND_CATEGORY` 와 계약 대조).

아직 남은 공백도 있다.

- `KIND_CATEGORY` 에만 있고 계약에 없는 장소 종류는 잡지 못한다. `KIND_CATEGORY` 가 공개돼 있지 않아서다.
- §6-1·§6-2 의 판정 문제(키워드 철자, 금지어 오탐)를 고정하는 테스트는 없다. 무엇을 막을지 정한 뒤에 넣는다.

### 6-6. 데이터와 문서

- **`owner` 가 계약 JSON 안에 있다.** 세 파일은 사람 이름이고 attraction 은 "도시 조사 에이전트(PR-V2)" 다. 런타임에서 읽는 곳은 없다. 담당이 바뀌면 계약 데이터를 고쳐야 한다.
- **README 가 계약보다 먼저 낡는다.** 같이 고쳤는지 보는 검사가 없고, 지금도 어긋나 있다.
  - `agent_contract/README.md` 와 루트 `README.md` 의 담당 표에 attraction 이 없다.
  - 두 README 모두 lodging 을 "숙소·체크인"이라 적었지만 JSON 은 "숙소·호텔"이다.
  - `agent_contract/README.md` 는 good_examples 를 "3개"라 적었지만 attraction 은 8개다.
- **`docs/product/필수단어-감사표.md` 는 10/15 시점 값이다.** "30상황 중 13개에 키워드"라고 적었지만 지금은 40개 중 19개다. 재현 스크립트(`:121`)는 `s.get('id')` 를 써서 모든 상황이 None 으로 나온다. 실제 필드는 `situation_id` 다.

## 7. 계약을 고칠 때 지켜야 하는 순서

1. `categories/{id}.json` 의 `situations` 를 고친다 (`situation_id` 는 **바꾸지 않는다** — 기존 문장 배정이 끊긴다. 상황을 일부러 추가·삭제했다면 `backend/tests/test_contract_invariants.py` 의 id 표도 같이 고친다).
2. `schema.json` 이 그 필드를 허용하는지 본다.
3. §6-4 에 적힌 다른 곳도 함께 고친다.
4. CI 와 같은 검사를 돌린다. `tests/` 가 네 파일의 전체 점검까지 돌리고, 부정 예시는 따로 돈다.
   ```
   cd backend
   python -m unittest discover -s tests -t .
   python -m unittest scripts/test_validate_category.py
   python scripts/check_negatives.py
   cd ../mockup && node --test ai.test.js
   ```
   경고까지 보려면 `python scripts/validate_category.py ../agent_contract/categories/<id>.json` 를 돌린다. Windows 콘솔에서는 한글 출력에서 멈추므로 `PYTHONIOENCODING=utf-8` 을 붙인다.
5. `/health` 의 `categories`·`situations` 가 그대로인지 확인한다(공개 필드다).
