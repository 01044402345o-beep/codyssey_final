# 도시 조사 에이전트 (운영)

사용자가 고른 나라·도시를 여행 조건(날짜·체류·도착/이동/출국일·여러 나라)에 맞게 실제 소스에서 조사한다.
코드: `backend/app/research/` (LangGraph). 단계별 PR: PR0 도시 정체성 → **PR1 백엔드(키 없는 소스)** → PR2 보고서 화면 → PR3 LLM 추출 → PR4 Geoapify·Google·Tavily → PR5 `/generate` 연결.

## 켜기 / 끄기

| 환경변수 | 기본 | 뜻 |
|---|---|---|
| `RESEARCH_ENABLED` | `0` | **킬 스위치.** 0 이면 `POST /research` 가 외부 호출 없이 `unavailable` |
| `RESEARCH_SOURCES` | 전부 | 소스별 끄기(쉼표): `wikivoyage,wikidata,openmeteo,fcdo,frankfurter` |
| `RESEARCH_MAX_JOBS` | `1` | 동시에 도는 조사 잡(전역). IP 당은 항상 1 |
| `RESEARCH_MAX_CITIES` | `5` | 요청당 도시 수 |
| `RESEARCH_SOFT_DEADLINE_S` | `100` | 넘으면 선택 단계(후속 PR 의 빈칸 검색 등)를 건너뛴다 |
| `RESEARCH_CACHE_DAYS` / `RESEARCH_VOLATILE_HOURS` | `30` / `24` | 캐시 수명(안정 / 환율·권고·예보) |
| `WIKIMEDIA_CONTACT` | 저장소 URL | 위키미디어 User-Agent 연락처 |
| `LANGSMITH_TRACING` | `false` | 코드가 강제로 끈다(langchain-core 의존성) |

값은 호출마다 읽으므로 재시작 없이 바뀐다. opsarchive 의 `policy-set`/자동 반영으로 Render 에 넣어도 된다(임의 키 지원).
`/health` 상세(`HEALTH_DETAIL_TOKEN`)의 `research` 블록: 켜짐·LangGraph 설치·소스·잡 수·최대 RSS(MB).

## 흐름

```
POST /research {countries:[{name, iso2?}], cities:[{name, gid?, ci, start, end, attr, rest}], cache_only?}
  → 꺼짐: {status: unavailable, reason: research_disabled}
  → 전부 캐시: {status: done, report, cached: true}          (외부 호출 0)
  → cache_only 인데 빠짐: {status: miss}
  → 그 밖: 202 {status: running, job_id}   → GET /research/{job_id}: {status, progress, report?}
```

그래프: `planner → (country × 나라, city × 도시) → writer`, 도시 안은 `guide(Wikidata → 위키보이지) ∥ climate(Open-Meteo) → finalize`.
- 장소는 위키보이지 listing 템플릿에서만 나온다(코드 파싱). 도시 중심 50km 밖·이상한 이름은 버린다.
- 소스 실패는 status(`unavailable`·`rate_limited`·`empty`·`disabled`)로 남고 보고서는 계속 만들어진다(`quality: full|reduced|failed`).
- 같은 요청은 같은 잡(single-flight). 화면이 기다리기를 멈춰도 잡은 끝까지 돌아 캐시를 데운다. 서버 재시작 시 잡은 사라진다(404 → 다시 요청, 끝난 도시는 캐시).

## 캐시 (Firestore, 서비스 계정 전용 — 클라이언트 규칙은 그대로 전부 거부)

| 경로 | 내용 | 수명 | 라이선스 |
|---|---|---|---|
| `research_cities/{ISO2}_{gid}/sections/guide` | 위키보이지 listing·섹션 평문, revid | 30일(미해결 도시 `{ISO2}_n<해시>` 7일) | CC BY-SA 4.0 — 출처·링크 표시 |
| `research_cities/{key}/sections/climate_MMDD_N` | 여행 날짜 평년값(최근 5년) / 16일 안 예보 | 30일 / 1일 | CC BY 4.0 |
| `research_countries/{ISO2}/sections/facts` | 통화·긴급번호·플러그·전압·운전 방향·언어 | 30일 | CC0 |
| `research_countries/{ISO2}/sections/advisory` | GOV.UK 여행 권고(안전·법·건강, 입국 요건 제외) | 1일 | OGL v3 |
| `research_countries/{ISO2}/sections/fx` | 1단위 = ?원 | 1일 | Frankfurter |

섹션 문서에 `expire_at`(timestamp)이 있다 — Firestore TTL 정책을 `sections` 컬렉션 그룹의 `expire_at` 에 걸면 오래된 문서가 자동으로 지워진다(선택).

## 외부 정책 메모 (2026-10 확인)
- 위키미디어: User-Agent 에 앱·연락처 필수, 익명 10회/분, 동시 3개 이하(코드가 지킨다), 429 는 Retry-After.
- Open-Meteo 무료 API 는 비상업 용도. 상업화하면 유료 플랜 또는 자체 호스팅.
- GOV.UK 권고는 영국 국적자 기준 — 화면에 '영국 정부 권고 기준'으로 표시한다.
- 개인정보: 외부 API·LLM 에 나라·도시·날짜만 보낸다(uid·이메일 없음).
