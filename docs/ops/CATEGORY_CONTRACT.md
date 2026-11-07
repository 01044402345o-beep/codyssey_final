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

**주의**: `required_keywords` 는 네 카테고리 모두에 있지만 **상황마다** 있거나 없다. 40상황 중 19개만 갖고 있다(attraction 6 · lodging 5 · restaurant 3 · transport 5). 검증기는 이 키워드를 `check_weak_coverage()` 에서만 쓴다. 복습 목록에 오른 상황의 문장에 키워드가 하나도 없으면 `weak_content_mismatch`(block)로 막는다. 키워드가 없는 21상황은 문장이 있기만 하면 통과한다(§5).


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
| `validators.check_pattern_declarations()` | `negative_case_patterns` 에 적힌 severity 선언 자체를 검사 |
| `validators.validate_sentence()` | 문장 1건: 길이·자리표시자·장소 불일치·금지 패턴·중복 |
| `validators.validate_schema()` | 팩이 `schema.json` 을 따르는지 |
| `validators.check_weak_coverage()` | 복습 목록의 상황이 팩에 실제로 들어갔는지(빠지면 block) |
| `validators.validate_pack()` | 위 검사를 팩 단위로 묶고 `has_blocking` 으로 판정 |
| `validators.has_blocking()` | block 이 하나라도 있으면 재생성 신호 |

`negative_case_patterns` 안의 `_note` 는 패턴이 아니라 사람이 읽는 설명이다.

severity 는 두 단계다. `block` 은 응답을 버리고 재생성, `warn` 은 쓰되 품질 측정값으로 남긴다. 계약의 `negative_case_patterns` 에 `severity` 를 적어 두면 그 값이 우선한다.


## 6. 지금 계약에서 발견한 불일치 4건

1. **`required_keywords` 가 40상황 중 19개에만 있다** — 나머지 21상황(예: `restaurant.order_menu`, `transport.taxi_ride`)은 복습 목록에 올라도 문장 내용이 그 상황과 맞는지 판정할 근거가 없다. 상황 id 만 붙이고 내용은 다른 문장도 통과한다.
2. **`situation_id` 형식이 두 곳에 정의돼 있다** — `schema.json` 은 `^[a-z][a-z0-9_]*$`, 화면은 `mockup/ai.js` 의 `ID_RE` 로 같은 것을 따로 검사한다. 한쪽만 고치면 서버가 만든 id 를 화면이 버린다. (`sentences` 항목은 `situation_id`·`situation`·`en`·`ko` 를 `required` 로 두므로 id 가 빠지면 스키마에서 막힌다.)
3. **`owner` 필드가 카테고리 JSON 안에 있다** — 사람 이름이 계약 파일에 박혀 있으면 담당이 바뀔 때 코드가 아니라 데이터를 고쳐야 한다.
4. **README 가 코드보다 먼저 낡는다** — 계약을 고칠 때 README 를 같이 고치는 규칙이 자동 검사에 없다.

## 7. 계약을 고칠 때 지켜야 하는 순서

1. `categories/{id}.json` 의 `situations` 를 고친다 (`situation_id` 는 **바꾸지 않는다** — 기존 문장 배정이 끊긴다).
2. `schema.json` 이 그 필드를 허용하는지 본다.
3. `python -m pytest backend/tests -q` — 계약 불일치는 여기서 잡힌다.
4. `/health` 의 `categories`·`situations` 가 그대로인지 확인한다(공개 필드다).
