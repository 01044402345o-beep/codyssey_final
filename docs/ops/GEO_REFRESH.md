# 전세계 국가·도시명 주간 수집 (geo-refresh)

앱의 여행 입력(국가·도시)은 한국어 자유 입력뿐이다. 표준 국가·도시 데이터를 **매주** 모아 **Firestore** 에 둔다.
저장소에는 데이터를 커밋하지 않는다.

- 워크플로우: `.github/workflows/geo-refresh.yml` (월요일 03:23 KST + 수동 실행)
- 스크립트: `.github/scripts/geo_refresh.py` (표준 라이브러리만) · 테스트 `tools/opsarchive/tests/test_geo_refresh.py`

## 1. 소스 선정 (다중 에이전트 리서치·회귀 조사, 2026-10-24)

무료로 쓸 수 있고 **공개 저장·재배포가 허용**되는 소스만 골랐다. 받은 안내문의 주장을 직접 호출로 다시 확인했다.

| 소스 | 판정 | 확인한 사실 |
|---|---|---|
| **GeoNames 덤프** | **본 소스** | 키·한도 없음, 매일 갱신(파일 수정일 2026-10-23), **CC BY 4.0**. `allCountries.zip` 422MB · `alternateNamesV2.zip` 205MB |
| dr5hn countries-states-cities | 교차 검증만 | ODbL(파생 DB 도 같은 라이선스여야 함 — 그래서 저장 데이터에 섞지 않는다), 국가 250·도시 약 15만, 한국어는 국가명만 |
| CountriesNow | 교차 검증만 | 키 없음, 227개국·도시 76,863, 좌표·인구·한국어 없음, 출처·라이선스 불명 |
| Rest Countries | 제외 | **v3.1 종료**(HTTP 200 에 실패 본문 — 상태 코드만 보면 놓친다), v5 는 키 필수·월 1,000건, 재배포 조건 미확인 |
| GeoDB Cities | 제외 | 약관상 24시간 넘게 캐시·재배포 금지, 무료 일 1,000건·페이지 10건 |
| Google Places | 제외 | 2025-03 **$200 크레딧 폐지**(SKU별 무료 한도), 콘텐츠 **저장 금지**(place_id 만 예외) |
| npm country-state-city | 제외 | 2023년 데이터, GPL-3.0 |

안내문 정정: GeoNames 웹서비스 무료 한도는 일 20,000 이 아니라 **10,000**(20,000 은 demo 계정), HTTPS(`secure.geonames.org`)도 된다.

## 2. 무엇을 모으나

- 국가: `countryInfo.txt` — ISO2/3, 영문명, **한국어명**, 수도, 인구, 대륙, 1급 행정구역(`admin1CodesASCII.txt`).
- 도시: `allCountries.zip` 의 **feature class P(사람이 사는 곳)** 전부 — 도시부터 마을까지(최대 범위).
  역사적(PPLH·PPLCH)·버려진(PPLQ)·파괴된(PPLW) 곳과 도시 안의 구역(PPLX)은 '도시명'이 아니라 뺀다.
- 한국어 이름: `alternateNamesV2.zip` 의 `isolanguage=ko`. 대표 이름(preferred) 우선, 역사적·구어 이름 제외.
- 한 행: `[geonameid, 이름, ASCII 이름, 한국어 이름, 1급 행정구역 코드, 인구, 위도, 경도, feature code]`.

## 3. Firestore 구조

문서 1MiB 상한·중첩 배열 불가 → 국가별로 **인구 내림차순** 정렬해 gzip JSON 샤드로 나눈다(샤드 ≤ 800KB).

| 경로 | 내용 |
|---|---|
| `geo_meta/current` | `version`, `generated_at`, `attribution`, `license`, `sources`(파일별 크기·sha256·Last-Modified), `counts`, `country_counts`, `country_hashes`, `shards`(문서→해시) |
| `geo_countries/{ISO2}` | `name`, `ko`, `iso3`, `capital`, `population`, `continent`, `admin1`, `city_count`, `shards`, `hash` |
| `geo_cities/{ISO2}_{nnn}` | `country`, `shard`, `count`, `data`(gzip JSON 바이트), `hash` — `data` 는 색인 제외(`firestore.indexes.json`) |

- 읽는 법: `geo_countries/KR` 의 `shards` 개수만큼 `geo_cities/KR_000…` 을 읽어 `data` 를 gunzip → JSON 배열.
- 클라이언트 규칙은 바꾸지 않는다(`firestore.rules` 는 그 밖 경로 전부 거부). 워크플로우·백엔드는 서비스 계정이라 규칙을 거치지 않는다.

## 4. 회귀 검사 (실패하면 아무것도 쓰지 않는다)

| 검사 | 실패 기준 |
|---|---|
| 형식 | 국가 240 미만, 도시 100만 미만(덤프가 잘린 것), 샤드 800KB 초과 |
| 지난 스냅샷 대비 | 전체 도시 2% 넘게 감소, 사라진 국가, 국가별 5% 넘게 **그리고** 50곳 이상 감소, 한국어 이름 비율 2%p 넘게 감소 |
| 교차 소스(경고만) | dr5hn 와 국가 집합 차이, CountriesNow 보다 도시가 적은 국가, 수도가 목록에 없는 국가 |

결과는 실행 요약(Step Summary) 표와 아티팩트 `geo-report.json`(30일)에 남는다. 실패하면 이슈 `[geo-refresh] 국가·도시 수집 실패` 하나에 모아 알린다.

## 5. 저장 방식

- **해시가 바뀐 문서만** 쓴다. 지난 스냅샷에 있던 샤드가 사라졌으면 지운다. `geo_meta/current` 는 **마지막**에 쓴다.
- 도중에 실패해도 다시 돌리면 맞춰진다(멱등). 커밋은 요청 하나 8MB·450건 이하로 나눈다.

## 6. 처음 켜기 (사람이 한 번)

1. GCP 서비스 계정 `geo-refresh@<프로젝트>.iam.gserviceaccount.com` 을 만들고 `roles/datastore.user` 를 준다.
2. 기존 WIF 풀(docs/ops/KMS_AUTO_ANCHOR.md)에 이 저장소가 그 계정을 쓸 수 있게 바인딩한다(`roles/iam.workloadIdentityUser`).
3. 저장소 Actions 변수: `GCP_WIF_PROVIDER`(이미 있으면 그대로), `GEO_SA_EMAIL`, 선택 `FIREBASE_PROJECT_ID`.
4. 색인 제외 배포: `firebase deploy --only firestore:indexes` (geo_cities.data — 큰 바이트 필드를 색인하지 않게).
5. Actions → geo-refresh → Run workflow(**dry_run 체크**) → 요약 확인 → dry_run 해제로 1회 실행 → `GEO_REFRESH=on` 으로 주간 실행 켜기.

## 7. 비용

첫 적재는 샤드 문서 수백 건 쓰기와 수백 MB 저장, 이후 주간은 바뀐 샤드만 쓴다. Firestore 무료 한도(일 쓰기 2만, 저장 1GiB) 안이다.
GeoNames 덤프는 키·한도가 없다(약 630MB 를 러너가 매주 받는다).

## 8. 출처 표기 (CC BY 4.0)

데이터를 화면·내보내기에 쓸 때는 `geo_meta/current.attribution` 문구(GeoNames 링크·라이선스·변경 사실)를 함께 보인다.

## 9. 로컬 실측 (2026-10-24, dry-run — Firestore 쓰기 없음)

| 항목 | 값 |
|---|---|
| 회귀 검사 | ✅ 통과(첫 적재라 감소 비교는 생략) |
| 국가 | 252 (도시 0곳: BV·HM 무인도, AN·CS 폐지된 코드) |
| 사람이 사는 곳 | **4,999,144** |
| 한국어 이름이 붙은 곳 | 1.34% (약 6.7만 — 큰 도시 위주, 마을 대부분은 한국어 이름이 없다) |
| 샤드 | 339개, 최대 797KB · 중간값 165KB · 합계 **94MB** |
| 많은 나라 | CN 897,100(24샤드) · IN 547,285 · MX 264,605 · ID 254,034 · RU 189,152 |
| 수도 확인 | 231개국 일치. 13개국은 표기·영토 차이로 경고(AG, CW, EH, GD, GG, IO, KZ, MN, MO, PS, PW, VU, WF) |
| 교차 소스 경고 | dr5hn 대비 우리만: AN·CS(폐지 코드) / CountriesNow 보다 적은 곳: FK |
| 소요 | 492초(덤프 약 630MB 다운로드 포함, 가정용 회선) |
