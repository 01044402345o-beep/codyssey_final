# AI 보강(enrichment) 파이프라인 설계 — 제안 (미구현)

> **상태: 설계 제안이다. 이 문서의 어떤 단계도 실행·측정한 적이 없다.** 게이트가 실제로 얼마나 잡는지는 모른다.
> 기준: `seongbin45/codyssey_final` `New-add-backend` @ `7e22bf5` 이후. 코드가 바뀌면 "현재 코드" 열을 다시 확인할 것.
> 우선순위: 지금 병목은 이 파이프라인이 아니라 **배포 증거(SHA, `/health` 원문, 실제 생성·말하기)와 팀 JSON 수집**이다. 이 문서는 그 뒤에 쓴다.

## 0. 먼저 읽을 것 — 이 설계의 한계

- **"보강이 맞는지" 판정할 오라클이 없으면 안 된다.** 이 프로젝트의 검증기(`backend/app/validators.py`)는 형식·`required_keywords`·단어 수·개수·중복만 본다. **문장이 자연스러운지, 상황에 쓸모 있는지는 보지 못한다.** 게이트를 통과한 결과도 **사람이 검수**해야 하고, 그 비용이 일정에 들어가야 한다.
- 아래 표에서 **"현재 코드"에 이미 있는 것**과 **"새로 필요"한 것**을 구분한다. 일정은 "새로 필요"만 센다.

## 1. 입력(슬롯)

| 슬롯 | 이 프로젝트의 값 |
|---|---|
| INPUT DATA | 카테고리 계약 JSON(`agent_contract/categories/<id>.json`) — `situations[]`, `rules`, `system_prompt` |
| ADDITIONAL INFO | ① 장소별 사실(간판 메뉴 등) ② 학습자의 취약 상황 id(`weak_expressions`) |

다른 워크플로에 쓰려면 3단계(요청 조립)와 4단계(판정 규칙)만 바꾼다.

## 2. 단계와 구현 상태

| # | 단계 | 현재 코드 | 새로 필요 |
|---|---|---|---|
| 1 | **입력 동결**: `validate_category.py`로 입력을 먼저 검사. 무효면 보강을 시작하지 않는다 | ✅ `backend/scripts/validate_category.py` | — |
| 2 | **오라클 정의**: "각 `situation_id`에 문장 ≥1, `required_keywords` 포함, ≤`max_words_per_sentence`" 등을 규칙으로 못 박는다. 비어 있으면 중단 | ✅ 규칙은 `rules`·`required_keywords`에 있고 `validate_pack`이 검사 | 보강 전용 합격 기준(예: 상황별 최소 문장 수 상향) 문서화 |
| 3 | **요청 조립**: 문자열 연결이 아니라 슬롯 채우기. 고정 `system_prompt` + 동적 입력(`situations`, `places`, `weak_expressions`) | ✅ `build_prompt`가 `{플레이스홀더}`를 `rules`로 치환 | `prompt_version` 개념(현재 없음) |
| 4 | **생성 + 검증 게이트**: 생성 직후 `validate_pack`(스키마·키워드·길이·개수·중복·`targets_weak` 정합)으로 판정 | ✅ `/generate` → `ai.run("generate", …)` → `validate_pack`, 실패 시 팩 **전체** 재생성 | — |
| 4a | **슬롯 단위 수리**: 걸린 상황만 부족한 키워드를 명시해 다시 요청, 3회 상한, 초과 시 그 슬롯을 비워 둠 | ❌ **없음** (지금은 팩 전체를 다시 만든다) | 상황별 부분 요청 경로, 슬롯 상태 관리 |
| 5 | **병합**: 기존 팩에 추가만 하고 삭제하지 않는다. 출처를 남긴다 | ❌ 없음 | 아래 3절 "출처 기록" |
| 6 | **실패 분류·대응** | 일부 ✅ (아래 표) | 배치 재개(멱등 키) |
| 7 | **관측** | ✅ 시도별 `failures[]`(응답·로그) | 배치 단위 집계(카테고리별 시도 수, 모델별 오류) |
| 8 | **재현**: 입력·`prompt_version`·결과 스냅샷 저장 | ❌ 없음 | 스냅샷 저장 규칙 |

### 6단계 실패 대응

| 실패 | 현재 코드 | 새로 필요 |
|---|---|---|
| 스키마 불일치 | ✅ `schema_invalid`(block) → 재생성 | 슬롯 단위 재요청(4a) |
| `required_keywords` 누락 | ✅ 검증에서 block | 누락 키워드를 명시한 수리 요청(4a) |
| 429·할당량 / 503·모델 장애 | ✅ `gemini.py`: 시도마다 모델 순환, 백오프 0.5→상한 4.0초, 부적합 모델 제외(`_EXCLUDE`) | — |
| 최소 시도 횟수 소진 | ✅ `AttemptsExhausted`(실패 목록 보유) → `usable:"rejected"` | "마지막 정상 팩 + `stale` 표시"로 대체하는 정책(없음). 조용히 성공 처리하지 않는다 |
| 부분 배치 실패 후 재실행 | ❌ 없음 | `(category_id, place, situation_id, prompt_version)` 멱등 키 |

## 3. 출처 기록 — 스키마를 깨지 않는 방법

**이 부분이 이전 초안의 결함이었다.** 이전 초안은 각 문장에 `source`·`prompt_version`·`model`·`attempts`를 붙이라고 했지만,
`agent_contract/schema.json`은 최상위(L7)와 문장(L21) 모두 `additionalProperties: false`다. **그대로 붙이면 모든 팩이 `schema_invalid`로 막힌다.**

두 가지 중 하나를 고른다.

**방안 A (권장, 스키마 변경 없음): 사이드카 파일.** 팩은 지금 형식 그대로 두고, 출처는 별도 파일에 둔다.

```text
agent_contract/provenance/<category_id>.jsonl      # 한 줄 = 문장 1개
{"category_id":"restaurant","situation_id":"allergy_notice","en_sha1":"…","source":"ai|human",
 "prompt_version":"v3","model":"…","attempts":2,"generated_at":"2026-10-07T00:00:00Z","reviewed_by":null}
```

- 키는 `(category_id, situation_id, en_sha1)`. 문장 본문은 팩에, 출처는 사이드카에 있어 **서버·검증기·`validate_category.py`가 모두 그대로 동작**한다.
- `reviewed_by`가 비어 있으면 "사람이 검수하지 않았다"를 뜻한다. 공개 전 게이트로 쓸 수 있다.

**방안 B (스키마 버전업): 문장에 `provenance` 객체를 추가.** 이 경우 반드시 세트로 한다.
1. `schema.json`에 선택 필드를 명시적으로 추가(`additionalProperties: false`는 유지) — 기존 팩은 필드 없이도 통과해야 한다.
2. 기존 팩 전량을 새 스키마로 재검증하고 `validate_category.py`·테스트를 갱신한다.
3. 팀원 PR 양식이 바뀌므로 `agent_contract/README.md`를 고치고 **미제출 팀원에게 다시 공지**한다.

> 마감이 임박한 지금은 방안 A만 현실적이다. 방안 B는 팀 제출이 끝난 뒤에 검토한다.

## 4. 시간 정책 — 대화형과 배치는 달라야 한다

- `backend/app/gemini.py`는 **전체 제한 시간을 두지 않고 호출당 최소 30회** 시도한다. 계속 실패하면 대기 시간만 약 **107.5초**(0.5+1+2+4+4×25)이고 시도마다 최대 60초(`AI_CALL_TIMEOUT`)가 더해진다.
- 클라이언트(`mockup/ai.js`)의 `GEN_TIMEOUT_MS`는 **90초**다. 서버가 계속 실패하면 **화면은 90초에 포기하고 로컬 문장으로 폴백하는데, 서버는 재시도를 계속한다**(클라이언트가 끊어도 서버 호출은 멈추지 않아 할당량이 소모된다).
- 보강을 **배치**로 돌릴 때는 이 정책을 그대로 재사용하지 말고, **작업 단위 deadline**을 새로 두거나 대화형 경로와 분리한다. `/generate`에는 IP당 `RATE_LIMIT`(기본 20/60초)도 걸려 있어 배치가 스스로를 막는다.
- 이 불일치를 어떻게 풀지는 **제품 결정**(클라이언트 제한 상향 / 서버 총 시간 상한 / 현행 유지)이고 아직 정해지지 않았다.

## 5. 선행 조건

1. `/health`로 현재 배포의 `config_problems`·`status`를 확인한다. `CONFIG_STRICT` 기본값은 `0`(`main.py:59`)이라 설정이 빠져도 `/generate`가 거부되지 않는다 — **검증이 꺼진 채 결과가 화면까지 갈 수 있다.** 배포 환경에서 `CONFIG_STRICT=1` 전환이 안전한지는 `/health` 응답으로 먼저 확인한다(미확인).
2. `prompt_version`을 도입할 때는 협업 규칙(`docs/배포시나리오트래커.xlsx` 담당_확정 시트의 규칙)에 "프롬프트를 바꾸면 버전을 올린다"를 함께 넣는다.
3. 사람 검수 담당과 일정을 먼저 정한다(0절).

## 6. 검증 계획 (착수한다면)

- 고정 입력 1개 카테고리로 4단계 게이트가 걸러내는 비율, 시도 횟수, 소요 시간을 **측정한 뒤에** 확대한다.
- 게이트 통과 결과 중 무작위 표본을 사람이 검수해 "통과했지만 부적절"한 비율을 따로 센다.
- 증거 등급은 `구현됨 → 합성·로컬 테스트 확인 → 실환경 검증 완료`를 섞어 쓰지 않는다.
