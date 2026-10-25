# 도시 조사 에이전트 (운영)

사용자가 고른 나라·도시를 여행 조건(날짜·체류·도착/이동/출국일·여러 나라)에 맞게 실제 소스에서 조사한다.
코드: `backend/app/research/` (LangGraph). 단계별 PR: PR0 도시 정체성 → PR1 백엔드(키 없는 소스) → PR2 보고서 화면 → **PR3 LLM 추출** → PR4 Geoapify·Google·Tavily → PR5 `/generate` 연결.

## 켜기 / 끄기

| 환경변수 | 기본 | 뜻 |
|---|---|---|
| `RESEARCH_ENABLED` | `0` | **킬 스위치.** 0 이면 `POST /research` 가 외부 호출 없이 `unavailable` |
| `RESEARCH_SOURCES` | 전부 | 소스별 끄기(쉼표): `wikivoyage,wikidata,openmeteo,frankfurter` |
| `RESEARCH_MAX_JOBS` | `1` | 동시에 도는 조사 잡(전역). IP 당은 항상 1 |
| `RESEARCH_MAX_CITIES` | `5` | 요청당 도시 수 |
| `RESEARCH_SOFT_DEADLINE_S` | `100` | 넘으면 선택 단계(후속 PR 의 빈칸 검색 등)를 건너뛴다 |
| `RESEARCH_CACHE_DAYS` / `RESEARCH_VOLATILE_HOURS` | `30` / `24` | 캐시 수명(안정 / 환율·권고·예보) |
| `WIKIMEDIA_CONTACT` | 저장소 URL | 위키미디어 User-Agent 연락처 |
| `LANGSMITH_TRACING` | `false` | 코드가 강제로 끈다(langchain-core 의존성) |
| `RESEARCH_USE_GRAPH` | `1` | 0 이면 LangGraph 없이 같은 노드를 스레드 4개로(같은 결과). 그래프가 실패해도 자동으로 이 경로 |
| `RESEARCH_PLACE_CHAIN` | `wikidata_places,overpass,google` | 위키보이지 장소가 모자랄 때 차례로 묻는 대체 소스. `none` 이면 끔(위키보이지만). 어댑터가 없는 이름은 무시(이 PR 은 골격만 — 소스는 다음 PR) |
| `RESEARCH_PLACE_MIN_EXTRA` | `2` | 종류별 목표 = 일정이 정한 장소 수 + 이만큼(화면 '후보' 몫) |
| `RESEARCH_LLM` | `1` | 0 이면 LLM 추출(여행 조건 순위·한국어 요약)을 끈다. Gemini 키가 없으면 저절로 꺼진다 — 보고서는 listing 순서·영어 원문 |
| `RESEARCH_LLM_CONCURRENCY` | `2` | 조사 잡 안에서 동시에 부르는 Gemini 수(도시 5곳이어도 2개씩) |
| `CITY_BRIEF_ENABLED` | `1` | 백업 경로 `GET /city-brief` 끄기 |
| `CITY_BRIEF_PROMPT` | `0` | 1 이면 `/generate` 프롬프트에 도시 브리프(출처 붙은 문단)를 배경으로 넣는다(첫 회 외부 조회가 붙어 기본 꺼짐) |

값은 호출마다 읽으므로 재시작 없이 바뀐다. opsarchive 의 `policy-set`/자동 반영으로 Render 에 넣어도 된다(임의 키 지원).
`/health` 상세(`HEALTH_DETAIL_TOKEN`)의 `research` 블록: 켜짐·LangGraph 설치·LLM 추출 켜짐·소스·잡 수·최대 RSS(MB).

## 흐름

```
POST /research {countries:[{name, iso2?}], cities:[{name, gid?, ci, start, end, attr, rest}], cache_only?}
  → 꺼짐: {status: unavailable, reason: research_disabled}
  → 전부 캐시: {status: done, report, cached: true}          (외부 호출 0)
  → cache_only 인데 빠짐: {status: miss}
  → 그 밖: 202 {status: running, job_id}   → GET /research/{job_id}: {status, progress, report?}
```

그래프: `planner → (country × 나라, city × 도시) → writer`, 도시 안은 `guide(Wikidata → 위키보이지) ∥ climate(Open-Meteo) → extract(LLM) → finalize`.
- 장소는 위키보이지 listing 템플릿에서만 나온다(코드 파싱). 도시 중심 50km 밖·이상한 이름은 버린다.
- 소스 실패는 status(`unavailable`·`rate_limited`·`empty`·`disabled`)로 남고 보고서는 계속 만들어진다(`quality: full|reduced|failed`).
- 같은 요청은 같은 잡(single-flight). 화면이 기다리기를 멈춰도 잡은 끝까지 돌아 캐시를 데운다. 서버 재시작 시 잡은 사라진다(404 → 다시 요청, 끝난 도시는 캐시).

## 장소 대체 체인·복구 (`research/chain.py`)

도시마다 위키보이지 장소를 종류별(관광지 / 식당·카페)로 세어, 목표(`caps + RESEARCH_PLACE_MIN_EXTRA`)에 모자라면 `RESEARCH_PLACE_CHAIN` 순서로 대체 소스에 **모자란 종류만** 묻는다. 채우면 멈춘다.

| 실패 | 예 | 처리 |
|---|---|---|
| exhaust | 401·403·한도(capped) | 6시간 쿨다운 |
| rate_limited | 429 | 5분 쿨다운, 이번 요청은 다음 소스로 |
| transient | 5xx·시간 초과·어댑터 예외 | 1분 쿨다운, 다음 소스로 |
| nodata | 정상인데 결과 없음 | 다음 소스로(쿨다운 없음) |

- 연속 실패 5번이면 회로 열림(쿨다운 4배). 성공하면 바로 복구. 체인의 모든 소스가 쿨다운이면 가장 빨리 풀리는 하나는 시도한다. 상태는 프로세스 메모리(`/health` research `place_sources`).
- 같은 장소 합치기: wikidata id 같음 → 아니면 정규화 이름 + 150m 이내. 앞 소스를 남기고 뒤 소스는 빈 설명·홈페이지만 채우고 출처를 합친다.
- **마지막 정상 캐시**: 대체 결과는 `places_extra` 섹션(30일, 장애가 섞이면 1일). 새 결과가 기존의 절반 미만이고 원인이 장애면 덮어쓰지 않고 기존(만료돼도)을 `stale: true` 로 쓴다. 만료 문서는 `get(..., allow_stale=True)` 로만 읽히고, Firestore `expire_at` 은 `valid_until + 30일`이라 TTL 정책을 걸어도 그동안 남는다.
- **문서 없음도 기억**: 위키보이지에 문서가 정말 없으면(`empty`) `guide` 에 `{wikivoyage: null, reason}` 을 7일 저장한다(매번 다시 묻지 않고 `cache_only` 도 바로 답한다). 장애(`unavailable`·`rate_limited`)는 저장하지 않는다.
- 보고서 도시: `place_status` = `ok`(일정 수 채움)·`thin`(일부)·`none`(0곳), `none_reason` = `outage`(소스 장애)·`no_coords`(좌표 모름)·`no_sources`(정상인데 자료 없음), `stale`, `chain`(소스별 status·outcome·count).

## LLM 추출 (PR3, `research/extract.py`)

도시당 Gemini 1회(기존 `gemini.run` — 키 순환·모델 회전·최소 시도 규칙 그대로). 비용 예산은 `research` 한 묶음으로 센다:
조사 잡이 사용자의 `/generate` IP 예산을 먹지 않고, 조사 전체가 `AI_IP_ATTEMPTS_PER_HOUR`(기본 150/시) 안에 머문다. `paid_slot` 이 차 있으면 건너뛴다(`busy`).

- 모델에게 주는 것: 여행 조건(도시·나라·날짜·박 수·달·도착/출국/이동 여부·원하는 장소 수·날씨 평년값), 후보 listing(최대 40, URL·HTML 제거), 실용 정보 원문 + 주제별 허용 상황 id. 사용자 정보는 없다.
- 모델이 하는 일: 순위·한국어 한 줄 요약·추천 이유, 실용 정보 한국어 요약 + **영어 원문 인용**, 상황 id 고르기. 장소·URL·출처는 만들지 않는다.
- 코드 검증: 모르는 id·중복 → 버림 / 인용은 원문 부분 문자열(공백·따옴표 정규화) / 요약의 숫자는 원문(장소 설명·인용)에 있어야 함 / `<>{}[]`·URL·@·한글 없는 요약·다른 후보 이름을 섞은 요약 → 버림 / 상황 id 는 주제별 허용 목록(`agent_contract/categories`) 안에서만. 검증을 통과한 장소가 하나도 없으면 그 시도는 실패로 보고 다음 모델로 다시 한다.
- 출처 URL 은 코드가 원래 listing 기록에서 붙인다(모델 출력 URL 은 쓰지 않는다).
- 실패·꺼짐·마감(`RESEARCH_SOFT_DEADLINE_S`)이면 보고서는 listing 순서·영어 원문 그대로(`cities[].extract.status`: ok·failed·busy·disabled·deadline·empty). 실패는 캐시하지 않는다. 마감에 걸린 추출은 뒤에서 끝까지 돌아 캐시만 데운다(Gemini 장애 때 최소 시도 규칙으로 몇 분 걸려도 화면은 150초 안에 listing 보고서를 받는다).
- 화면: 장소 카드에 한국어 요약 — 이유, 그 아래 영어 원문(작게). 실용 정보는 한국어 요약 + 인용(blockquote).

## 캐시 (Firestore, 서비스 계정 전용 — 클라이언트 규칙은 그대로 전부 거부)

| 경로 | 내용 | 수명 | 라이선스 |
|---|---|---|---|
| `research_cities/{ISO2}_{gid}/sections/guide` | 위키보이지 listing·섹션 평문, revid | 30일(미해결 도시 `{ISO2}_n<해시>` 7일) | CC BY-SA 4.0 — 출처·링크 표시 |
| `research_cities/{key}/sections/climate_MMDD_N` | 여행 날짜 평년값(최근 5년) / 16일 안 예보 | 30일 / 1일 | CC BY 4.0 |
| `research_cities/{key}/sections/extract_mMM_{s\|m\|l}` | LLM 추출: 장소 id 순위·한국어 요약·이유, 실용 정보 한국어 요약·영어 인용·상황 id, 위키보이지 revid | 30일, revid 가 바뀌면 다시 | 우리 요약(원문 인용은 CC BY-SA) |
| `research_countries/{ISO2}/sections/facts` | 통화·긴급번호·플러그·전압·운전 방향·언어 | 30일 | CC0 |
| `research_countries/{ISO2}/sections/fx` | 1단위 = ?원 | 1일 | Frankfurter |

섹션 문서에 `expire_at`(timestamp)이 있다 — Firestore TTL 정책을 `sections` 컬렉션 그룹의 `expire_at` 에 걸면 오래된 문서가 자동으로 지워진다(선택).

## 외부 정책 메모 (2026-10 확인)
- 위키미디어: User-Agent 에 앱·연락처 필수, 익명 10회/분, 동시 3개 이하(코드가 지킨다), 429 는 Retry-After.
- Open-Meteo 무료 API 는 비상업 용도. 상업화하면 유료 플랜 또는 자체 호스팅.
- 안전 권고: 영국 FCDO 는 영국 국적자 기준(영국 대사관 연락처 등)이라 **쓰지 않는다**(10/25 결정). 화면은 외교부 해외안전여행(0404.go.kr) 링크로만 안내하고, 공공데이터 API 키가 생기면 소스로 붙인다.
- 개인정보: 외부 API·LLM 에 나라·도시·날짜만 보낸다(uid·이메일 없음).

## 백업(롤백) 경로 — 도시 브리프 (`backend/app/agents/city_research.py`, `GET /city-brief`)

다른 에이전트가 만든 모듈을 백업으로 들였다(2026-10-25). 조사 파이프라인이 꺼져 있거나(`RESEARCH_ENABLED=0`) 실패한 보고서에서
화면이 도시마다 `GET /city-brief?country=&city=` 를 불러 '이 도시 알아두기' 카드를 그린다.
- 소스: 위키백과 ko/en REST 요약 · 영어 위키여행 extract · 위키데이터(검색 → 인구·좌표·sitelink) — 병렬 4개, LLM 없음
- 검증: 좌표 50km 일치, 제목에 도시 이름, 괄호 붙은 동명이인 문서 배제(단 위키데이터 sitelink 제목은 믿음),
  동음이의 문서(`type: disambiguation`, 예: 한국어 '파리')는 버리고 sitelink 제목('파리 (프랑스)')으로 다시 조회
- HTTP 는 조사 파이프라인과 같은 `SafeHttp`(허용 호스트에 ko/en.wikipedia.org·www.wikidata.org 추가). 캐시 메모리 7일/512
- CI e2e 서버는 `CITY_BRIEF_ENABLED=0`(외부 네트워크에 기대지 않는다). 화면 테스트는 `/city-brief` 를 가짜로 준다

## 다른 에이전트 검토에서 들인 결정 (2026-10-25)
- 영국 FCDO 권고 제거 — 영국 국적자 기준이라 오정보. 외교부 해외안전여행 링크로만 안내, API 키가 생기면 소스로
- LangGraph 탈출구(`RESEARCH_USE_GRAPH=0` / 그래프 실패 시 자동 plain)
- (PR4) Firestore 사용량 카운터는 원자적 증가(fieldTransforms increment)로 — 동시 잡에서 한도가 새지 않게
- (PR5) 조사에 없는 장소는 422 가 아니라 걸러 낸다(조사된 장소만 AI, 나머지는 틀 문장)
- 배포 후 PR3 전에 실서비스 경로로 한 번 돌려 본다(Firestore 캐시 쓰기·잡 스레드)
