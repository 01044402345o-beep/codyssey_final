# 저장소 상태

절차는 [`AGENT_WORKFLOW.md`](AGENT_WORKFLOW.md)를 따른다. 이 문서는 한 시점의 사실이다. 세션을 열 때마다 다시 읽고 고친다.

| 항목 | 값 |
|---|---|
| 기록 시각 | 2026-10-14 |
| 최근 세션 | `C:\Users\seong\.grok\sessions\C%3A%5CUsers%5Cseong%5CDesktop%5CProJect%5Ccodyssey_final\01a138a0-a233-7ca1-843c-3de2a5de06b6` |
| 세션 파일 | `chat_history.jsonl`, `events.jsonl`, `updates.jsonl`, `summary.json`, `prompt_context.json`, `resources_state.json`, `system_prompt.txt`, `tool_definitions.json`, `terminal/` |
| 작업 브랜치 | `docs/results-pr55`. 이 읽기에서 `origin/main`(`a7d0021`)에서 갈라졌다. 푸시 대상은 `origin`의 `docs/results-pr55`이다 |
| 조사 시점 `HEAD` | `a7d0021` — Merge pull request #6 from seongbin45/docs/agent-workflow (2026-10-14 14:09:41 +0900) |
| `origin` | `https://github.com/seongbin45/codyssey_final` |
| `team` | `https://github.com/01044402345o-beep/codyssey_final.git` |
| 팀 `main` | `e18cb77` — 2026-10-14 13:51:39 +0900, 최성빈, `fix(mockup): 사용자 테스트 반영 — 카톡 듣기 안내, 상황별 연습, 터치 스와이프 E2E (#55)`. 부모는 `747c673` (#54) |
| 배포 | `https://codyssey-final.onrender.com` (팀 `main` 머지 시 Render 무료 플랜). 이 읽기에서는 `/health`를 다시 열지 않았고 테스트도 다시 돌리지 않았다 |

이 읽기의 git 사실:

- `git ls-remote --heads` 로 본 팀 브랜치는 세 개다. `main` `e18cb77753786748eec3a04494307d6c82267765`, `New-add-backend` `a4b850ac16483695080b38f93b0e942e4818d4ac`, `feat/memory-and-speak` `47f5c698852f3f24277d0ede20a7f01c6b5ae5b3`.
- `git rev-list --left-right --count origin/main...team/main` 은 45와 1이다. 팀에만 있는 그 1커밋은 `e18cb77`이다. `e18cb77`은 이 브랜치의 조상이 아니고, 부모 `747c673`은 조상이다. `git merge-base team/main HEAD` 는 `747c673`이다.
- `git diff team/main HEAD` 는 파일 3개, 194줄이다. `README.md` 5줄, `docs/AGENT_WORKFLOW.md` 78줄, `docs/REPO_STATE.md` 112줄. `docs/user-test/results.md` blob은 양쪽 다 `abe095b3d5b1adf790a27b3f6a95d2f6d2b6e4fc`이다. `mockup/app.js` blob은 양쪽 다 `06a47ec638f9b6168b9bc7456bdd0185d7ace6b7`이다.
- 그 `results.md`는 1c행·2행에 `` `fix/dup-swipe` (PR 예정) ``, 6절 대응에 `` `fix/dup-swipe` `` 를 적고 있다. 1a·1b는 `#54` (`747c673`)이다.
- `e18cb77`의 `mockup/app.js` 1263행은 `function endDrill() { if (S.drill) { S.card = S.drill.savedCard; S.drill = null; } }` 이고, 1587행은 `savedCard: S.card` 이다. `e2e/test_shell.py` 는 `Input.dispatchTouchEvent` 를 쓴다.
- 로컬 `main`(`4a21b87`)은 `origin/main`보다 58커밋 뒤이고, 앞은 0이다.
- `docs/agent-workflow` 는 `3756ecc`이다. 그 커밋과 부모 `a1fa890`은 이 브랜치의 조상이 아니다. 과제 원문 대조(`docs/ASSIGNMENT.md`)와 그 시점의 동결 기록은 그 브랜치에 있다.
- 추적되지 않은 루트 `.gitignore`는 커밋하지 않는다. `core.autocrlf` 는 true이고, 커밋 blob은 LF로 둔다.

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
├── e2e/                  Playwright 시나리오
├── docs/                 현행 요구사항, 반응형, 배포, 연구, 측정, 사용자 테스트
└── other/                아이디어·자료. 런타임에 서빙하지 않음
    └── Project261000/
        ├── codyssey_final/   루트보다 오래된 사본 (lodging.json 없음)
        ├── design/           디자인 가이드.dc.html (2026-10-08), 반응형 전략.dc.html, 반응형 전략 v2.dc.html
        ├── output/           발표 HTML·슬라이드
        ├── resorce/          기획 PDF, 진단, 체크리스트 (폴더명 철자 그대로)
        └── transcribe_app/   다른 프로그램. 이 제품의 범위 밖
```

제품은 여행지와 일정을 넣으면 갈 장소에서 쓸 영어 문장을 만들고, 말해 보고, 어려웠던 상황을 브라우저에 기억하는 학습 서비스다. 화면과 API는 같은 주소에서 서빙한다. AI가 하는 일은 문장 생성(`/generate`), 말하기 채점(`/speak-check`), 어려웠던 상황의 다음 생성 반영이다. 장소 목록은 예시 데이터다.

## 동결

2026-10-14에 사용자가 정한 것이다. 전문 기록은 `docs/agent-workflow` `3756ecc`에 있다.

- 디자인 가이드 적용은 `a1fa890`에서 멈춘다. 그 커밋은 `docs/agent-workflow`에 있고 이 브랜치의 조상이 아니다.
- `team`에는 푸시하지 않는다. 팀 저장소로는 나중에 PR을 연다.
- `mockup/`은 2차 테스트가 끝나는 2026-10-22까지 동결이다.
- 그때까지 저장소에서 할 일은 과제 요건 확인과, 2차 테스트에서 나온 버그 수정이다. 이번 커밋은 문서의 PR 칸만 고친다.

## `.`에서 열려 있는 일

기준 문서: `docs/requirements.md` (2026-10-09, 커밋 `f78b23b` 시점 표기). 아래는 그 문서가 완료로 두지 않은 항목이다. FR-15 행은 이 브랜치(`a7d0021`)의 `mockup/ai.js` `categoryOfKind`와 `mockup/app.js` `genReport`를 이 읽기에서 다시 보았다.

| ID | 상태 | 코드에서 확인한 내용 |
|---|---|---|
| FR-03 장소 보고서 | 예시 | `mockup/data.js` `PLACE_POOLS`. 뉴욕·보스턴은 관광지·맛집만 있음 |
| FR-04 방문 순서 | 예시 | 코드 배치 |
| FR-15 교통·숙소 생성 | 부분 | 계약 3종은 `agent_contract/categories/`에 있다. `categoryOfKind`는 식당·카페→restaurant, 공항·역·택시→transport, 호텔·호스텔·게스트하우스·에어비앤비→lodging. `genReport`는 장소를 `attraction`과 `restaurant`로만 만든다. `attraction`은 계약 밖이라 생성 요청은 식당만 나간다 |
| FR-16 로그인·서버 저장 | 예정 | 데모 사용자와 브라우저 저장 |
| NFR-08 화면 | 부분 | 반응형·다크·넓은 화면 배치는 구현 기록이 `docs/RESPONSIVE_STRATEGY.md`에 있다. 남은 것: 실기기(iOS Safari·iPad), 다크 모드 팀 디자인 검수, 브라우저 뒤로가기와 날짜 선택 |
| 장소 보강 파이프라인 | 제안 | `docs/ENRICHMENT_PIPELINE.md`는 미구현 |

이 브랜치 `README.md` 161행은 이미 `categoryOfKind`와 생성 요청이 식당만 나간다는 문장이다.

## 사용자에게 요청할 파일

아직 저장소에 없는 것:

1. 팀 6인에 대한 운영진 예외 승인. 원문 문장 "팀 인원: 3~5인 (5명 권장)"은 `docs/agent-workflow` `3756ecc`의 `docs/ASSIGNMENT.md`에 있다. 이 브랜치에는 그 파일이 없다. README 2절은 이름 6명이다.
2. 2차 테스트의 과업 성공률·설문. `docs/user-test/results.md` 2·3·4절 칸은 비어 있다. 이번 커밋에서 채우지 않는다.

## 이번 작업

목적: `docs/user-test/results.md`가 이미 팀 `main` `e18cb77`(PR #55)에 있는 반영을 `` `fix/dup-swipe` (PR 예정) ``으로 적고 있다. 1c행, 2행, 6절 대응을 `#55` (`e18cb77`)로 고친다. `mockup/`은 수정하지 않는다. 2·3·4절 빈칸은 채우지 않는다. `team`과 `origin/main`에는 푸시하지 않는다.

| 단계 | 목적 | 파일 | 완료 조건 | 읽을 것 |
|---|---|---|---|---|
| 1 | 1c, 2행, 6절 대응을 #55로 가리킨다 | `docs/user-test/results.md`, 이 문서 | 그 세 곳이 `#55` (`e18cb77`)이다. `results.md`에 `fix/dup-swipe`와 `PR 예정`이 없다. 1a·1b는 `#54` (`747c673`)이다. `e18cb77`이 `team/main`이고 `endDrill`, `savedCard`, `Input.dispatchTouchEvent`를 포함한다. 이번 diff에 `mockup/`이 없다. 다른 에이전트가 같은 조건으로 통과라고 적는다. 그 다음 이 두 파일만 커밋하고 `origin`의 `docs/results-pr55`에 푸시한다 | `results.md`, `git show e18cb77`, `git diff team/main HEAD`, `git status` |

검증:

- 단계 1: 다른 에이전트 `01a1395f-c6c2-7a72-8db4-e4b196ce40dd` 가 통과라고 적었다. 1c·2행·6절 대응은 `#55` (`e18cb77`)이고, `results.md`에 `fix/dup-swipe`와 `예정`은 없다. 1a·1b는 `#54` (`747c673`)이다. 2·3·4절 빈칸은 그대로다. `e18cb77`은 `team/main`이고 `endDrill`, `savedCard`, `Input.dispatchTouchEvent`가 있다. 작업 트리 diff는 이 두 문서와 추적되지 않은 `.gitignore`뿐이다.

## 이전 기록

`a7d0021`에 들어 있던 이 문서의 검증 기록이다. 그때의 조사 `HEAD`는 `2e77ff1`이었고, 지금 `HEAD`는 `a7d0021`이다.

- 절차 문서 대조: 통과. 아이디어 출처, 세션마다 상태 갱신, 구현 전 단계 계획, 다른 에이전트의 단계별 대조, 없는 자료 요청, `origin` 푸시와 `team` 제한, 세션 경로 공개, 오래된 사본의 우선순위, 사실 순서를 문서에서 확인했다.
- 상태 문서 첫 대조 (`bd4bf06` 시점): 불일치. 브랜치·HEAD·ahead 3커밋·원격·`genReport`·`categoryOfKind`·계약 파일·디자인 파일·세션 디렉터리·README 문장은 그때 맞았다. 상태 표만 `docs/agent-workflow`가 이미 있는 것처럼 적혀 있었다.
- 상태 문서 재대조: 불일치. 그 사이에 `fix/dup-swipe`가 `2e77ff1`로 움직였고 `origin/fix/dup-swipe`와 같아졌다. `bd4bf06`과 ahead 3 문장을 세 번째 읽기로 고쳤다.
- 상태 문서 세 번째 대조: 불일치 한 곳. `HEAD` `2e77ff1`, 원격과 앞 0 뒤 0, `main` 44 뒤, FR-15, README는 맞았다. "`2e77ff1`의 바로 아래는 `809c38d`"는 틀렸다. `2e77ff1`은 병합이고 첫 부모는 `bd4bf06`, 둘째 부모는 `809c38d`이다.
- 상태 문서 네 번째 대조: 통과. 첫 부모는 `bd4bf06`, 둘째 부모는 `809c38d`, `HEAD`는 `2e77ff1`이다.

과제 원문 대조의 검증 기록은 `docs/agent-workflow` `3756ecc`의 이 문서에 있다. 그 커밋은 이 브랜치에 없다.
