# `/itinerary` 요청 계약과 검색 위치 편향

`POST /itinerary` 는 도시 하나의 장소를 Google Places Text Search 로 모은다(`backend/app/agents/itinerary.py`).
공개 배포에서는 `ITINERARY_ENABLED` 가 꺼져 있어 `itinerary_disabled` 를 돌려준다. 이 문서는 켜졌을 때의 계약이다.

배경: [장소 0건 조사](../research/place-zero-investigation.md)(#205) → 진단 기록(#207) → 위치 편향(#208).

## 1. 요청

```json
{
  "city": "뉴욕",
  "days": 3,
  "start_date": "2026-11-10",
  "itinerary_kinds": ["restaurant", "cafe", "attraction"],
  "iso2": "US",
  "gid": 5128581
}
```

| 필드 | 타입 | 필수 | 설명 | 제약 |
|---|---|:---:|---|---|
| `city` | string | 필수 | 도시 이름(입력 그대로) | 1–80자 |
| `days` | int | 선택 | 체류 일수 | |
| `start_date` | string | 선택 | 시작일 | `YYYY-MM-DD` |
| `itinerary_kinds` | string[] | 선택 | `restaurant`·`cafe`·`attraction` | 최대 4개 |
| `iso2` | string | 선택 | 나라 코드(ISO 3166-1 alpha-2) | `^[A-Z]{2}$` |
| `gid` | int | 선택 | 도시 선택 목록(`/geo/cities`)에서 고른 도시의 GeoNames id | 1 이상 |

- **좌표(`lat`/`lon`)는 받지 않는다.** 서버가 `iso2`·`gid` 로 도시 목록(GeoNames, Firestore `geo_cities`)에서 찾는다.
  화면이 보낸 좌표를 믿지 않아도 되고, 도시 조사(`/research`)와 같은 좌표 출처를 쓴다. `/geo/cities` 응답에도 좌표는 없다.
- `iso2`·`gid` 가 없는 요청(구버전 화면, 손으로 친 도시)은 이전과 똑같이 처리한다. 필수로 바꾸지 않는다.

화면(`mockup/ai.js` `itineraryRequestBody(city, iso2)`)은 값이 있을 때만 두 필드를 붙인다.
`iso2` 는 여행의 나라 이름을 `countryByName()` 으로 찾은 값, `gid` 는 도시를 목록에서 골랐을 때 `trip.cities[i].gid` 다.

## 2. 위치 편향 결정 (`_location`)

1. `iso2` 가 없거나 형식이 틀리면 → 편향 없음(`no_country`)
2. 나라를 먼저 읽는다(`store.country`). 장애면 `geo_unavailable`, 모르는 코드면 `unknown_country`
   - 이유: `city_by_id`·`match_city` 는 도시 목록 장애를 삼키고 `None` 을 돌려준다. 나라를 먼저 읽지 않으면 장애가 '도시 못 찾음'으로 기록된다.
3. `gid` 로 찾는다(`city_by_id`) → 실패하면 이름 일치(`match_city`, 한국어·영문·ASCII)
4. 못 찾으면 → 편향 없음(`city_not_found`)
5. 찾으면 `{lat, lon, radius_m}` 를 `_search_one(..., bias)` 에 넘긴다 → 요청 본문 `locationBias.circle`

반경은 `/research` Google 대체 소스와 같은 공식(`research/sources/google_places.radius_m`)이다.

| 도시 인구 | 반경 |
|---|---|
| 100만 이상 | 10 km |
| 20만 이상 | 6 km |
| 그 외 | 4 km |

**하지 않는 것**

- 못 찾은 도시를 국가 중심·고정 좌표로 대신하지 않는다. 모르는 도시를 엉뚱한 지점으로 끌어당기면 0건보다 나쁜 결과가 나온다.
- 코드 안에 도시 좌표 표를 두지 않는다. 도시 목록(GeoNames)이 이미 모든 나라의 좌표·인구를 갖고 있다.
- 고정 반경(예: 50 km)을 쓰지 않는다. 대도시에서는 이웃 도시까지 우선 범위에 들어간다.
- 편향이 걸려도 검증 규칙(폐업·ID·이름·좌표·지도 URL)은 그대로다.

## 3. 응답의 진단 필드

```json
{
  "location": {"bias": "gid", "reason": "", "radius_m": "10000"},
  "queries": [
    {"query": "뉴욕 restaurant", "included_type": "restaurant", "status": "unavailable",
     "reason": "none_verified", "raw": 3, "excluded": {"closed": 1, "bad_maps_uri": 2}}
  ]
}
```

| 필드 | 값 |
|---|---|
| `location.bias` | `gid` · `name` · `none` |
| `location.reason` | `no_country` · `unknown_country` · `geo_unavailable` · `city_not_found` (편향이 걸리면 빈 문자열) |
| `queries[].raw` | 공급자가 돌려준 원시 결과 수 |
| `queries[].excluded` | 검증에서 빠진 사유별 개수: `closed` · `no_id` · `no_name` · `no_coords` · `bad_maps_uri` · `not_object` |

서버 로그(`app.itinerary`)의 `no_verified_places` 줄은 `provider_fail`(공급자 장애) · `raw_zero`(응답 0건) ·
`all_excluded`(응답은 있었지만 전부 제외) · `excluded` · `bias` · `bias_reason` 을 남긴다.
0건이 났을 때 이 값으로 어느 단계에서 비었는지 먼저 가른다.

## 4. 테스트

- `backend/tests/test_itinerary.py`: 위치 편향 8건(gid·이름 경로, 반경, 구버전 호환, 못 찾음, 장애·모르는 나라 구분, 실제 `GeoStore` 장애, 요청 모델), 진단 4건
- `mockup/ai.test.js`: 요청 본문에 `iso2`·`gid` 는 있을 때만, 좌표는 보내지 않음
- `e2e/test_itinerary_screen.py`: 보고서 화면 흐름(로컬 서버, API 키 없이)
