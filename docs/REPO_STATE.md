# 저장소 상태

절차는 [`AGENT_WORKFLOW.md`](AGENT_WORKFLOW.md)를 따른다. 이 문서는 한 시점의 사실이다. 세션을 열 때마다 다시 읽고 고친다.

| 항목 | 값 |
|---|---|
| 기록 시각 | 2026-10-14 오후 (PR #55 반영 후) |
| 최근 세션 | `C:\Users\seong\.grok\sessions\C%3A%5CUsers%5Cseong%5CDesktop%5CProJect%5Ccodyssey_final\01a138a0-a233-7ca1-843c-3de2a5de06b6` |
| 세션 파일 | `chat_history.jsonl`, `events.jsonl`, `updates.jsonl`, `summary.json`, `prompt_context.json`, `resources_state.json`, `system_prompt.txt`, `tool_definitions.json`, `terminal/` |
| 사실 확인 시점 HEAD | 팀 `main` `e18cb77` (10-14 13:51, PR #55) · 포크 `main` `a7d0021` |
| 팀 `main` 대비 포크 `main` | 45 앞, 1 뒤. **파일 차이는 `README.md`·`docs/AGENT_WORKFLOW.md`·`docs/REPO_STATE.md` 셋뿐**(194줄). 나머지 43커밋은 브랜치 병합 이력이라 팀에 올라가도 무해하다 |
| 작업 브랜치 | `docs/agent-workflow` (포크). 팀 반영은 PR 로 한다 — 직접 푸시하지 않는다(§5.1) |
| `origin` | `https://github.com/seongbin45/codyssey_final` |
| `team` | `https://github.com/01044402345o-beep/codyssey_final.git` |
| 배포 | `https://codyssey-final.onrender.com` (팀 `main` 머지 시 Render 무료 플랜). 확인 시점 `deploy.commit = e18cb7775`, `branch = main` |

세션 시작 때 로컬 `main`(`4a21b87`)은 `origin/main` 보다 44커밋 뒤에 있었다. 평가·배포 기준은 팀 저장소 `main`이다.

추적되지 않은 루트 `.gitignore`는 Next.js 템플릿이다. 이 제품은 바닐라 JS와 FastAPI라 그 파일은 커밋하지 않는다.

## PR #55 (`e18cb77`, 10-14 13:51) 로 바뀐 것

| 항목 | 이전 | 지금 (코드에서 확인) |
|---|---|---|
| 상황별 연습 | 없음 | **구현.** `mockup/app.js` `S.drill` — 문장 모음의 묶음마다 "카드로 연습". `drill:${by}:${v}` 를 날짜 대신 쓰므로 날짜 일정과 분리된다. 끝낼 때 `S.card` 를 `savedCard` 로 되돌린다 |
| 터치 스와이프 검사 | 없음 | **추가.** `e2e/test_shell.py` 가 CDP `Input.dispatchTouchEvent` 로 `0→1`, `1→2`, `2→1`, 끝 카드에서 멈춤, 놓으면 제자리, JS 오류 0 을 단언한다. `has_touch=True` 만 켜 두면 못 잡던 회귀다 |
| 카톡 안내 | "일부 기능이 안 됨" | 듣기(TTS)만 안 되는 것으로 좁히고, 카톡 자체 메뉴 `⋮ → 다른 브라우저로 열기` 안내 + 여기서도 되는 것(말하기·카드) 표시 |
| 프론트 테스트 | 31 | **33 pass / 0 fail** (`node --test mockup/ai.test.js mockup/tokens.test.js`) |
| `results.md` | §1 빈 표 | §1 P1~P5 명단, §5 피드백 6행(1a·1b·1c·2·3·4), §6 원문, §6.1 실기기 채점 2건. **§2·§3·§4 는 아직 빈칸** |

## 구조

```
.                         현재 제품
├── README.md             제품 설명 (현행)
├── prd.md                초기 기획 (Firebase, 이력)
├── 기술스택.md            초기 기술 구조 (이력)
├── 시나리오.md            시나리오 초안 (이력)
├── 시나리오완료.MD        기능·규칙 상세 (이력)
├── render.yaml           Render 배포
├── agent_contract/       카테고리 계약. restaurant, transport, lodging
├── backend/              FastAPI. /health, /generate, /speak-check
├── mockup/               화면. index.html, app.js, ai.js, data.js, styles.css
├── e2e/                  Playwright 시나리오. 터치 제스처·말하기·동의 검사 포함
├── docs/                 현행 요구사항, 반응형, 배포, 연구, 측정, 사용자 테스트,
│                         AGENT_WORKFLOW.md, REPO_STATE.md
└── other/                아이디어·자료. 런타임에 서빙하지 않음
    └── Project261000/
        ├── codyssey_final/   루트보다 오래된 사본 (lodging.json 없음)
        ├── design/           디자인 가이드.dc.html (2026-10-08), 반응형 전략.dc.html, 반응형 전략 v2.dc.html
        ├── output/           발표 HTML·슬라이드
        ├── resorce/          기획 PDF, 진단, 체크리스트 (폴더명 철자 그대로)
        └── transcribe_app/   다른 프로그램. 이 제품의 범위 밖
```

제품은 여행지와 일정을 넣으면 갈 장소에서 쓸 영어 문장을 만들고, 말해 보고, 어려웠던 상황을 브라우저에 기억하는 학습 서비스다. 화면과 API는 같은 주소에서 서빙한다. AI가 하는 일은 문장 생성(`/generate`), 말하기 채점(`/speak-check`), 어려웠던 상황의 다음 생성 반영이다. 장소 목록은 예시 데이터다.

## `.`에서 열려 있는 일

기준 문서: `docs/requirements.md` (2026-10-09, 커밋 `f78b23b` 시점 표기). 아래는 그 문서가 완료로 두지 않은 항목이다.

| ID | 상태 | 코드에서 확인한 내용 |
|---|---|---|
| FR-03 장소 보고서 | 예시 | `mockup/data.js` `PLACE_POOLS`. 뉴욕·보스턴은 관광지·맛집만 있음 |
| FR-04 방문 순서 | 예시 | 코드 배치 |
| FR-15 교통·숙소 생성 | 부분 | 계약 3종은 `agent_contract/categories/`에 있다. `mockup/ai.js` `categoryOfKind`는 식당·카페→restaurant, 공항·역·택시→transport, 호텔·호스텔·게스트하우스·에어비앤비→lodging. `genReport`(`mockup/app.js`)는 장소를 `attraction`과 `restaurant`로만 만든다. `attraction`은 계약 밖이라 생성 요청은 식당만 나간다 |
| FR-16 로그인·서버 저장 | 예정 | 데모 사용자와 브라우저 저장 |
| NFR-08 화면 | 부분 | 반응형·다크·넓은 화면 배치는 구현 기록이 `docs/RESPONSIVE_STRATEGY.md`에 있다. 남은 것: 실기기(iOS Safari·iPad), 다크 모드 팀 디자인 검수, 브라우저 뒤로가기와 날짜 선택 |
| **사용자 테스트 측정값** | **미기록** | `docs/user-test/results.md` §2 과업 성공률(T1·T2·T3·T5·T6·T7), §3 말해 보기 측정(오거부율 포함), §4 설문 12문항이 **빈칸**이다. §1 참가자 5명과 §5 피드백 6행은 채워져 있다. T6(한 단어 빼고 말하기)은 아직 실행되지 않았다 |
| 장소 보강 파이프라인 | 제안 | `docs/ENRICHMENT_PIPELINE.md`는 미구현 |

`README.md`의 알려진 한계 문장은 이제 `categoryOfKind`·`genReport`와 같다(이번 커밋에서 함께 고쳤다).

## `./other`에서 가져올 수 있는 것

| 자료 | 쓰는 조건 |
|---|---|
| `design/디자인 가이드.dc.html` | 2026-10-08 가이드 v1. 색·글자·부품. 출처로 `mockup/styles.css`를 들고, 목업과 다른 값을 표에 적는다 |
| `design/반응형 전략 v2.dc.html`, `반응형 전략.dc.html` | 초안. `docs/RESPONSIVE_STRATEGY.md`가 바닐라 CSS 기준으로 다시 적었고, React·Vite·Tailwind 전제는 따르지 않는다 |
| `output/` | 발표 구성. 제품 동작을 바꾸려면 `docs/requirements.md`와 코드를 먼저 본다 |
| `resorce/` | 과제 원문, 상세기획서, 2026-10-04 진단(스코프 과대, 기술 요소 미달). 진단이 제안한 말하기·기억은 현재 제품에 들어가 있다 |
| `codyssey_final/` | 오래된 사본. 루트에 없는 기능을 여기서 현재인 것처럼 가져오지 않는다 |
| `transcribe_app/` | 범위 밖 |

## 다음 구현 후보

1. **FR-15.** 예시 장소에 교통·숙소를 넣어 `categoryOfKind`가 그 계약을 실제로 호출하게 한다. 뉴욕·보스턴 장소 목록이 있거나, `data.js`와 같은 결의 예시 장소를 만들어도 된다는 확인이 필요하다.
2. **생성 실패가 화면에 안 보이는 문제.** `mockup/ai.js` `GEN_TIMEOUT_MS = 90 * 1000` 하나를 `/health` 와 모든 도시가 **공유**하고(`withTimeout` 1개), 실패한 도시는 `kind:'fallback'` 으로 로컬 템플릿 문장이 된다. 화면에는 실패 표시가 없고 전체가 실패한 경우에만 `u-gen` 에 문구가 뜬다(`mockup/app.js` `runAi`·`failStage`). 최소 조치는 **실패한 도시를 화면에 표시**하는 것. 사용자 테스트 중 재발하면 그 회차 측정값이 무효가 된다.
3. **말하기 결과를 점수부터 표시.** `/speak-check` 응답을 통째로 받은 뒤에야 결과가 뜬다(`mockup/app.js` `uploadSpeech` → `updateSpeakUi`). 실측 20초 중 17초가 피드백 문장 생성이라, 점수는 나와 있는데 화면에는 아무것도 없는 구간이 생긴다. 전사·점수를 먼저 그리고 피드백은 도착 시 덧붙인다.
4. **디자인 가이드와 목업의 차이 정리.** `디자인 가이드.dc.html`이 2026-10-08 이후에도 기준인지, 다크 모드 팀 검수 메모가 있는지가 필요하다.

백엔드 재시도·제한 시간은 **의도가 코드 주석에 박혀 있다.** `backend/app/gemini.py` 는 `MIN_ATTEMPTS = 30` 이고 "전체 제한 시간(deadline)을 두지 않는다. 시간 제한이 시도 횟수를 깎으면 '최소'가 깨진다"고 적혀 있다. `stt_providers.py` 는 `REQUEST_TIMEOUT = 60`, `POLL_MAX_SECONDS = 120` 이다. 팀 결정 없이 줄이지 않는다.

## 사용자에게 요청할 파일

트리에 이미 있어서 다시 받지 않는 것: `other/Project261000/design/`의 DC 세 파일, `docs/RESPONSIVE_STRATEGY.md`, `docs/requirements.md`.

다음에 구현하려면 필요한 것:

1. 2026-10-08보다 새로운 디자인 가이드가 있으면 그 파일. 없으면 현재 DC를 기준으로 쓴다.
2. 다크 모드 팀 검수 메모나 화면 캡처. NFR-08이 이 검수를 미완으로 둔다.
3. 실기기에서 깨진 화면이 있으면 그 캡처(기기, 브라우저, 화면 이름).
4. FR-15를 먼저 할지, 디자인 가이드와 목업의 차이를 먼저 할지.
5. `results.md` §6.1 채점 기록 스크린샷을 넣을 `docs/user-test/img/` 가 아직 없다. 파일을 넣을지, 폴더만 만들지.
6. §6.1 의 실기기 채점 2건을 발표 자료에 쓸 동의(현재 "동의 요청 중").

## 이전 작업 — 절차·상태 문서 작성 (2026-10-14 오전)

목적: 위 절차를 문서화하고, 이 시점의 구조와 열린 일을 한 문서에 고정한다. 제품 동작은 바꾸지 않는다.

| 단계 | 목적 | 파일 | 완료 조건 |
|---|---|---|---|
| 1 | 절차를 적는다 | `docs/AGENT_WORKFLOW.md` | 아이디어 출처, 세션마다 상태 갱신, 구현 전 단계 계획, 단계별 다른 에이전트 검증, 없는 자료 요청, 작업 끝 커밋·`origin` 푸시, 세션 경로 공개가 모두 있다 |
| 2 | 이 시점의 사실을 적는다 | `docs/REPO_STATE.md` | 브랜치, 원격, 구조, FR-15의 실제 연결, `./other`의 역할이 코드·git과 같다 |
| 3 | 읽는 사람이 절차를 찾게 하고, 한계 문장을 코드와 맞춘다 | `README.md` | 문서 표에 두 문서가 있고, 한계 문장이 `categoryOfKind`와 `genReport`와 같다 |
| 4 | 1–3을 다른 에이전트가 대조한다 | 위 세 파일 | 불일치를 고친 뒤 같은 기준으로 다시 본다 |
| 5 | 이 세 파일만 커밋하고 `origin`의 `docs/agent-workflow`에 푸시한다 | git | 분기 기준은 그 시점의 `fix/dup-swipe` 끝. `.gitignore`와 `fix/dup-swipe` 자체는 푸시하지 않는다 |

검증 기록:

- 절차 문서 대조: 통과. 아이디어 출처, 세션마다 상태 갱신, 구현 전 단계 계획, 다른 에이전트의 단계별 대조, 없는 자료 요청, `origin` 푸시와 `team` 제한, 세션 경로 공개, 오래된 사본의 우선순위, 사실 순서를 문서에서 확인했다.
- 상태 문서 첫 대조 (`bd4bf06` 시점): 불일치. 상태 표만 `docs/agent-workflow`가 이미 있는 것처럼 적혀 있었다.
- 상태 문서 재대조: 불일치. `fix/dup-swipe`가 `2e77ff1`로 움직여 `origin/fix/dup-swipe`와 같아졌다.
- 상태 문서 세 번째 대조: 불일치 한 곳. "`2e77ff1`의 바로 아래는 `809c38d`"는 틀렸다. `2e77ff1`은 병합이고 첫 부모는 `bd4bf06`, 둘째 부모는 `809c38d`이다.
- 상태 문서 네 번째 대조: 통과.

## 이번 작업 — 팀 저장소 반영 (2026-10-14 오후)

목적: 이 세 파일(`docs/AGENT_WORKFLOW.md`, `docs/REPO_STATE.md`, `README.md`)을 팀 저장소 `main` 에 올리고, 그 사이 움직인 사실을 반영한다. 제품 동작은 바꾸지 않는다.

| 단계 | 목적 | 파일 | 완료 조건 |
|---|---|---|---|
| 1 | 팀 `main` 최신(`e18cb77`)을 사실로 다시 읽는다 | `docs/REPO_STATE.md` | `deploy.commit`, 프론트 테스트 수, `S.drill`, E2E 터치 단언, `results.md` 채워진 절/빈 절이 git·코드와 같다 |
| 2 | `results.md` §5 의 PR 칸을 머지 결과로 고친다 | `docs/user-test/results.md` | 1a·1b = `#54`(`747c673`), 1c·2 = `#55`(`e18cb77`). "PR 예정" 표기가 남지 않는다 |
| 3 | 팀 `main` 직접 푸시 금지 규칙을 절차에 넣는다 | `docs/AGENT_WORKFLOW.md` §5.1 | `c76335a` 사고를 근거로 적고, PR 전 두 검사 명령이 있다 |
| 4 | 세 파일을 PR 로 올린다 | git | 팀 `main` 에 직접 푸시하지 않는다 |

검증:

- `node --test mockup/ai.test.js mockup/tokens.test.js` → **33 pass / 0 fail** (문서만 바꿨으므로 `e18cb77` 과 같은 수여야 한다).
- `python e2e/test_shell.py <주소> <폴더>` → CI 에서 확인한다.
