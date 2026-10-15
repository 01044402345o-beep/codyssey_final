# 저장소 상태

절차는 [`AGENT_WORKFLOW.md`](AGENT_WORKFLOW.md)를 따른다. 이 문서는 한 시점의 사실이다. 세션을 열 때마다 다시 읽고 고친다.

| 항목 | 값 |
|---|---|
| 기록 시각 | 2026-10-14 |
| 최근 세션 | `C:\Users\seong\.grok\sessions\C%3A%5CUsers%5Cseong%5CDesktop%5CProJect%5Ccodyssey_final\01a138a0-a233-7ca1-843c-3de2a5de06b6` |
| 세션 파일 | `chat_history.jsonl`, `events.jsonl`, `updates.jsonl`, `summary.json`, `prompt_context.json`, `resources_state.json`, `system_prompt.txt`, `tool_definitions.json`, `terminal/` |
| 작업 브랜치 | `docs/results-pr55` |
| 이 커밋 | `8b5a92d`와 팀 `main` `169954b`의 머지. 충돌은 `docs/AGENT_WORKFLOW.md`, `docs/REPO_STATE.md`, `docs/user-test/results.md` |
| `origin` | `https://github.com/seongbin45/codyssey_final` |
| `team` | `https://github.com/01044402345o-beep/codyssey_final.git` |
| 팀 `main` | `169954b` — 2026-10-14 16:46:56 +0900, seongbin45, `docs: 결과 표의 PR 칸을 머지 결과로 정정, 에이전트 작업 절차·저장소 상태 문서 추가`. 부모는 `e18cb77` |
| 배포 | `https://codyssey-final.onrender.com`. 이 충돌 해결에서는 `/health`를 다시 열지 않았고 테스트도 다시 돌리지 않았다 |

이 읽기의 git 사실:

- `git ls-remote --heads` 로 본 팀 브랜치: `main` `169954b34be23af79a10f92687787ad4aa0dc111`, `New-add-backend` `a4b850ac16483695080b38f93b0e942e4818d4ac`, `feat/memory-and-speak` `47f5c698852f3f24277d0ede20a7f01c6b5ae5b3`, `docs/sync-and-results-pr` `661005a25f767d4d8115fe0d6e838848077873a6`.
- `git rev-list --left-right --count origin/main...team/main` 은 45와 2이다. 팀에만 있는 두 커밋은 `e18cb77`과 `169954b`이다. `e18cb77`은 머지 전 `HEAD` `8b5a92d`의 조상이 아니다.
- 로컬 `main`(`4a21b87`)은 `origin/main`보다 58커밋 뒤이고, 앞은 0이다. `origin/main`은 `a7d0021`이다.
- `docs/agent-workflow` 는 `3756ecc`이다. 그 커밋과 부모 `a1fa890`은 `8b5a92d`의 조상이 아니고, `169954b`의 부모는 `e18cb77`이라 이 머지에도 들어오지 않는다. 과제 원문 대조(`docs/ASSIGNMENT.md`)는 그 브랜치에 있다.
- `gh repo set-default --view` 는 `01044402345o-beep/codyssey_final` 이다. `remote.team.gh-resolved` 는 `base` 이다.
- 추적되지 않은 루트 `.gitignore`는 커밋하지 않는다. `core.autocrlf` 는 true이고, 커밋 blob은 LF로 둔다.
- `169954b`가 이 문서에 적은 `deploy.commit = e18cb7775` 와 프론트 테스트 33 pass 는 그 커밋의 기록이다. 이 충돌 해결에서 다시 확인하지 않았다.

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

`169954b`가 팀 `main`에 더한 패치 파일 세 개(`add-agent-workflow-repo-state.patch`, `fix-landscape-fluid.patch`, `results-pr-columns.patch`)는 충돌이 아니라 그 커밋의 추가분이라 이 머지에 남긴다.

## 동결

2026-10-14에 사용자가 정한 것이다. 전문 기록은 `docs/agent-workflow` `3756ecc`에 있다.

- 디자인 가이드 적용은 `a1fa890`에서 멈춘다. 그 커밋은 이 머지의 어느 부모에도 없다.
- `team` 원격에는 직접 푸시하지 않는다. 팀 `main` 반영은 PR 이다. `gh pr create --fill --base main` 의 대상은 `01044402345o-beep/codyssey_final` 이다.
- `mockup/`은 2차 테스트가 끝나는 2026-10-22까지 동결이다.
- 그때까지 저장소에서 할 일은 과제 요건 확인과, 2차 테스트에서 나온 버그 수정이다.

## `.`에서 열려 있는 일

기준 문서: `docs/requirements.md` (2026-10-09, 커밋 `f78b23b` 시점 표기). 아래는 그 문서가 완료로 두지 않은 항목이다. FR-15 행은 이 작업 트리의 `mockup/ai.js` `categoryOfKind`와 `mockup/app.js` `genReport`를 이전 읽기에서 확인했고, `169954b`는 `mockup/app.js`를 바꾸지 않는다.

| ID | 상태 | 코드에서 확인한 내용 |
|---|---|---|
| FR-03 장소 보고서 | 예시 | `mockup/data.js` `PLACE_POOLS`. 뉴욕·보스턴은 관광지·맛집만 있음 |
| FR-04 방문 순서 | 예시 | 코드 배치 |
| FR-15 교통·숙소 생성 | 부분 | 계약 3종은 `agent_contract/categories/`에 있다. `categoryOfKind`는 식당·카페→restaurant, 공항·역·택시→transport, 호텔·호스텔·게스트하우스·에어비앤비→lodging. `genReport`는 장소를 `attraction`과 `restaurant`로만 만든다. `attraction`은 계약 밖이라 생성 요청은 식당만 나간다 |
| FR-16 로그인·서버 저장 | 예정 | 데모 사용자와 브라우저 저장 |
| NFR-08 화면 | 부분 | 반응형·다크·넓은 화면 배치는 구현 기록이 `docs/RESPONSIVE_STRATEGY.md`에 있다. 남은 것: 실기기(iOS Safari·iPad), 다크 모드 팀 디자인 검수, 브라우저 뒤로가기와 날짜 선택 |
| 사용자 테스트 측정값 | 미기록 | `docs/user-test/results.md` 2·3·4절이 빈칸이다. 1절 참가자 5명과 5절 피드백 6행은 채워져 있다. T6(한 단어 빼고 말하기)은 아직 실행 기록이 없다 |
| 장소 보강 파이프라인 | 제안 | `docs/ENRICHMENT_PIPELINE.md`는 미구현 |

이 작업 트리 `README.md` 161행은 `categoryOfKind`와 생성 요청이 식당만 나간다는 문장이다.

`backend/app/gemini.py` 는 `MIN_ATTEMPTS = 30` 이고, 주석은 전체 제한 시간(deadline)을 두지 않는다고 적는다. 시간 제한이 시도 횟수를 깎으면 '최소'가 깨진다는 문장이다. `backend/app/stt_providers.py` 는 `REQUEST_TIMEOUT = 60`, `POLL_MAX_SECONDS = 120` 이다. 이 충돌 해결은 그 값을 바꾸지 않는다.

## PR #55 로 이미 들어가 있는 것

`e18cb77`(2026-10-14 13:51:39 +0900, 최성빈, PR #55)의 부모는 `747c673`(2026-10-12 09:01:18 +0900, PR #54)이다. `169954b`는 `mockup/`을 바꾸지 않으므로 아래는 팀 `main`의 코드와 같다.

| 항목 | 코드 |
|---|---|
| 상황별 연습 | `mockup/app.js` `endDrill` 이 `S.card = S.drill.savedCard` 로 되돌리고, 시작 때 `savedCard: S.card` 를 넣는다 |
| 터치 스와이프 검사 | `e2e/test_shell.py` 가 `Input.dispatchTouchEvent` 를 쓴다 |
| 결과 표 | `results.md` 1a·1b 는 `#54` (`747c673`), 1c·2와 6절 대응은 `#55` (`e18cb77`) |

## 사용자에게 요청할 파일

아직 저장소에 없는 것:

1. 팀 6인에 대한 운영진 예외 승인. 원문 문장 "팀 인원: 3~5인 (5명 권장)"은 `3756ecc`의 `docs/ASSIGNMENT.md`에 있다. 이 머지에는 그 파일이 없다. README 2절은 이름 6명이다.
2. 2차 테스트의 과업 성공률·설문. `results.md` 2·3·4절은 비어 있다. 이 머지에서 채우지 않는다.
3. §6.1 스크린샷과 발표 사용 동의. 파일명은 비어 있고, 동의 전 외부 공개는 금지라고 적혀 있다.

## 이번 작업

목적: 팀 `main` `169954b`를 `docs/results-pr55`(`8b5a92d`)에 합치면서 세 문서의 충돌을 푼다. `mockup/`은 수정하지 않는다. `team`에는 푸시하지 않는다.

| 단계 | 목적 | 파일 | 완료 조건 | 읽을 것 |
|---|---|---|---|---|
| 1 | 충돌 표시를 없애고 양쪽의 문장을 한 벌로 맞춘다 | 위 세 문서 | 아래 체크리스트. 다른 에이전트가 통과라고 적는다. 그 다음 머지 커밋으로 `origin`의 `docs/results-pr55`에 푸시한다 | 작업 트리, `git diff --diff-filter=U`, `8b5a92d`, `169954b` |

체크리스트:

- 세 파일에 `<<<<<<<` 가 없다.
- `results.md` 1c·2행과 6절 대응은 `#55` (`e18cb77`)이다. 그 칸에 `fix/dup-swipe`와 `PR 예정`이 없다. 1a·1b는 `#54` (`747c673`)이다. 5절 표 아래 주석은 예전 `PR 예정` 표기를 고쳤다고 적고, #54 시각 `2026-10-12 09:01:18 +0900`과 #55 시각 `2026-10-14 13:51:39 +0900`을 가리킨다. 2·3·4절 빈칸은 그대로다.
- `AGENT_WORKFLOW.md` §5.1 이 있다. 팀 `main` 직접 푸시 금지, PR 전 두 검사, `c76335a` 기록, `gh pr create --fill --base main` 의 대상이 `01044402345o-beep/codyssey_final` 이라는 문장이 있다.
- 이 문서의 팀 `main`은 `169954b`이고, `/health`와 테스트를 이 자리에서 다시 실행하지 않았다고 적는다. 동결 네 줄이 있다.
- `git diff --name-only --diff-filter=U` 가 비어 있다. `.gitignore`는 스테이지에 없다.
- 세 문서의 작업 트리 바이트에 CR 이 0이다.

검증:

- 단계 1 첫 대조: 다른 에이전트 `01a1396d-d62e-7d23-b364-a7347a1e6532` 가 불일치 한 곳이라고 적었다. 6절에서 `| 대응 |` 행과 `| 재테스트 |` 행이 `||` 로 한 줄에 붙어 있었다. 나머지 항목은 맞았다.
- 그 두 행을 나누고 같은 단계 재대조: 다른 에이전트 `01a13971-696f-7b21-81cf-24d4edeeb73c` 가 통과라고 적었다. 1c·2행·6절 대응은 `#55` (`e18cb77`)이고, 1a·1b는 `#54` (`747c673`)이다. 2·3·4절 빈칸은 그대로다.

## 이전 기록

`8b5a92d`에 있던 검증이다. 그때 조사한 `HEAD`는 `a7d0021`이었고, 팀 `main`은 `e18cb77`이었다. 지금 팀 `main`은 `169954b`이다.

- 다른 에이전트 `01a1395f-c6c2-7a72-8db4-e4b196ce40dd` 가 `results.md`의 `#55` 정정을 통과라고 적었다. 재대조 `01a13961-9419-75a3-b7b4-6bcf4d2792fb` 도 통과라고 적었다.
- 그 이전 `2e77ff1` 대조의 결론: `2e77ff1`은 병합이고 첫 부모는 `bd4bf06`, 둘째 부모는 `809c38d`이다.

`169954b`에 있던 검증 기록은 그 커밋이 프론트 테스트 33 pass 와 E2E 는 CI 에서 본다고 적는다. 이 충돌 해결은 그 테스트를 다시 돌리지 않았다.

과제 원문 대조의 검증 기록은 `docs/agent-workflow` `3756ecc`에 있다.

## 이번 작업 — 사실 에이전트 (2026-10-14)

세션: `C:\Users\seong\.grok\sessions\C%3A%5CUsers%5Cseong%5CDesktop%5CProJect%5Ccodyssey_final\01a138a0-a233-7ca1-843c-3de2a5de06b6`

기준 브랜치: 팀 `main` `63b1809`. 이 작업 브랜치는 `feat/fact-agents`. `team`에는 푸시하지 않는다. `mockup/`은 2026-10-22까지 수정하지 않는다.

### reference 종합 결론

`reference`에는 서로 다른 문서가 세 갈래다. 구현에 쓰는 결론은 이것이다.

- 제품은 여행 영어 문장 생성이다. A1-2의 일정표·PyQt·경로 URL·날씨 문장은 가져오지 않는다.
- 좌표·주소·식이·포장·조식·와이파이는 API가 확정하고, Gemini는 문장만 만든다. LLM 호출은 지금처럼 문장 1곳이다.
- 장소 사실은 카카오 키워드 검색 1회, 식당·카페(`restaurant`)만. 카카오 키를 구글에 보내지 않는다. 구글 Places·그라운딩·날씨·경로·Ticketmaster·Foursquare·Unsplash·사진은 이번 구현에 없다.
- 상황 사실은 키 없는 OSM 1회. 대상은 `allergy_notice`·`takeout`·`ask_breakfast`·`ask_wifi`뿐이고, 카카오가 좌표를 줬을 때만 조회한다. 태그가 없거나 조회가 실패하면 미확인이지 정상 빈 결과가 아니다.
- 키가 없으면 그 조회만 꺼지고 `/generate`의 문장 경로는 그대로다.
- `required_keywords.patch`는 적용하지 않는다. 취약 상황 키워드가 없으면 `validators.py`가 생성을 막는다.
- 화면은 동결이라 실패 표시는 응답 JSON의 `facts`로만 드러낸다. `mockup/`은 이 작업에서 읽기만 한다.

| 단계 | 목적 | 파일 | 완료 조건 | 읽을 것 |
|---|---|---|---|---|
| 1 | 위 결론을 이 문서에 고정한다 | `docs/REPO_STATE.md` 이 절 | 다른 에이전트가 통과라고 적기 전에는 코드를 쓰지 않는다 | `reference/` 세 문서, `backend/app/main.py`의 `/generate`, `docs/requirements.md` FR-03·FR-15 |
| 2 | 사실 조회를 `/generate`에 붙인다 | `backend/app/agents/facts.py`, `backend/app/main.py`, `backend/tests/test_fact_agents.py` | 키 없으면 `facts`가 unavailable이고 외부 호출이 없다. 카카오 성공은 verified 장소만. 실패·0건은 failed 또는 unavailable. OSM은 좌표가 있을 때만. 구글 URL이 없다. 기존 `/generate` 샘플 경로는 200이다. `mockup/` diff가 없다 | 단계 1 결론, `validators.py`는 수정하지 않음 |

검증:

- 단계 1: 다른 에이전트 `01a139d0-0f99-7823-bf7c-c9e49a1d9ada` 가 통과라고 적었다.
- 단계 2: 다른 에이전트 `01a139d5-ea10-7411-8ff7-51085c5c3d72` 가 통과라고 적었다. 백엔드 테스트는 120개 OK다. `node --test mockup/ai.test.js`는 통과했다. `mockup/tokens.test.js` 5개 실패는 이 브랜치의 기준 `63b1809` 화면이고, 이 작업은 `mockup/`을 고치지 않았다. e2e는 이 브랜치를 배포하지 않아 돌리지 않았다.

### 정정 (2026-10-14, 검증)

위 "검증:" 절의 "`mockup/tokens.test.js` 5개 실패는 이 브랜치의 기준 `63b1809` 화면이고"는 **커밋의 사실이 아니다.** 정정한다.

**tokens 5개 실패 = Windows 작업 복사본의 CRLF.** 화면이 되돌아간 커밋은 없다.

| 확인 | 값 |
|---|---|
| `mockup/styles.css` blob | `88fb260c7faa37333a7df1e6f7808e2534cc03db` — `e18cb77`·`63b1809`·`1e75d8b`·`85968d0` 모두 동일 |
| 실패 원인 | `tokens.test.js` 가 `/:root \{\n  color-scheme: light;[\s\S]*?\n\}\n/` 처럼 **LF 를 상정한 정규식**으로 토큰 블록을 걷어낸다. CRLF 면 매치가 실패해 블록이 통째로 "`:root` 밖"으로 남고 그 안의 색이 전부 리터럴로 세어진다 |
| 재현 | `styles.css` 를 CRLF 로 바꾸면 **2 pass / 5 fail** — 실패 항목은 `:root 밖 리터럴`·다크 두 블록·AA 대비·비텍스트 3:1·`THEME_COLOR` 로 정확히 그 5개. LF 로 되돌리면 **7 pass / 0 fail** |
| 인덱스 blob(CR 0)에 같은 정규식을 적용 | 라이트·다크 블록이 정상적으로 잡힌다 |

**머지·배포.** PR #61 은 2026-10-14 10:08 UTC 에 squash 머지됐다. 머지 커밋 `85968d0`, 부모는 `5677dcc` 하나. 변경은 `agents/facts.py` 254행, `agents/__init__.py` 1행, `main.py` +23/−2, `tests/test_fact_agents.py` 203행, `REPO_STATE.md` +28. 빈 커밋이 아니다. 라이브 `/health` 도 같은 커밋이다 — `deploy.commit=85968d095ec088d348970d7b8a36172c00f6516b`, `branch=main`. `63b1809` 다음 팀 main 은 `6d0ef68`(진행자 체크리스트), `5677dcc`(루트 패치 네 개 삭제), `85968d0`(사실 조회)이고 `85968d0` 이 끝이다. 이 폴더의 `team/main` 은 fetch 전 로컬 참조라 `63b1809` 로 보인다.

**고친 결함 두 개 (같은 패치).**

1. `allergy_notice` 를 OSM `diet:*` 로 채우지 않는다. `diet:vegetarian=yes` 는 채식 메뉴가 있다는 뜻이고 알레르기 안전과 다른 주장인데, 그 값이 `allergy_notice` 키에 `status=verified` 로 붙었고 프롬프트가 "verified 만 사실"이라고 적으므로 알레르기 문장이 확정처럼 생성될 수 있었다. `OSM_SITUATIONS` 에서 뺐다.
2. 요청한 장소와 응답한 장소를 이름으로 대조한다. 이전에는 요청 `places` 의 첫 이름 하나를 검색어로 쓰고 응답 문서 최대 5개를 전부 `verified` 로 넣어, 요청하지 않은 가게가 사실이 되고 OSM 원점도 그 첫 문서가 됐다. 지금은 요청 이름의 토큰이 응답 이름의 앞에서 연속으로 시작할 때만 `verified` 다. `Pizza`, `Not Joe's Pizza`, `Joe's Famous Pizza` 는 `Joe's Pizza` 가 아니다. 요청 이름이 없으면 대조 기준이 없으므로 `unavailable` 이다.

**남은 제약.** 카카오 로컬은 한국 지번·도로명 주소 체계 위의 색인이고 국가·로캘 파라미터가 없다([문서](https://developers.kakao.com/docs/latest/ko/local/common), [데브톡 60374](https://devtalk.kakao.com/t/api/60374) "당사에서는 해외지도는 서비스하지 않습니다"). 이 제품의 도시는 전부 해외다(`mockup/data.js` 는 뉴욕·보스턴). 그래서 카카오 조회는 한국 도시로 범위를 좁혔고(`KOREA_CITIES`), `FACT_SOURCES_READY = False` 로 꺼 두었다. **키를 넣지 않는다**는 결정을 코드로도 막는다 — 키가 있어도 외부 호출 0회다. 이름 대조만으로도 해외 도시에서는 0건이 되어 `unavailable` 로 내려가지만, 같은 이름을 쓰는 한국 가게가 하나 있으면 통과하므로 범위 검사가 그 구멍과 헛 호출을 막는다.

검토 에이전트 01a139f2-9cc9-7cb3-86e7-cfdb193c6c13 은 토큰이 중간에 끼는 일치를 실패로 봤고, 고친 뒤 앞부분 연속 일치는 통과라고 적었다.

## 이번 작업 — 듣기 자리표시자 (2026-10-15)

영어 화면은 `slotText` 가 `[name]`·`[destination]` 을 `[your name]`·`[your destination]` 으로 펼친다. 한국어 줄은 토큰 그대로다. `mockup/data.js` 에 `your` 는 없다. 호출부는 저장 문장을 넘긴다.

검토 에이전트 01a13df2-e184-7002-a12e-8f215493f3e2 은 듣기 음성은 speak가 저장 문장을 slotText로 펼친 뒤 대괄호만 벗긴 값이고, 화면 영어의 대괄호 안 your와 그 음성이 같다고 통과로 봤다.

## 이번 작업 — 브라우저 듣기 조사 (2026-10-15)

기록은 `docs/research/browser-tts.md` 이다. 다음 문장의 이 문서는 그 파일이다. `speak()` 와 `mockup/` 은 고치지 않았다.

검토 에이전트 01a13b96-b142-7882-a604-7214d55f87b7 은 이 문서가 우리 cancel 다음 speak 한 번을 Chromium 41362336 의 재현이라고 단정하지 않고, 검증에서 뺀 주장을 확인된 사실로 다시 적지 않았다고 통과로 봤다.

## 이번 작업 — 뒤로가기와 새로고침 진도 (2026-10-15)

하단 뒤로가기는 화면 기록을 쌓아 이전 화면으로 간다. 새로고침 뒤에는 완료한 날짜와 보던 화면·카드가 남는다. 여행·장소·문장·오늘 날짜는 저장하지 않는다.

검토 에이전트 01a13e52-f8f6-7293-9caa-a7a0e2d8cd33 은 화면 이동이 히스토리를 쌓고 뒤로가기는 열린 확인 상자와 서랍을 먼저 닫으며 세션에는 버전과 시각과 완료 날짜와 화면과 학습일과 카드 날짜와 위치와 뒷면과 뒤집은 카드가 저장되고 여행과 장소와 문장과 오늘 날짜는 빠지며 처음 상태와 새 여행은 그 진도와 저장을 지우고 새 검사는 듣기 검사 다음에 돌며 학습 카드 음성은 비운 뒤 대괄호를 뺀 문장 하나를 배열 전체로 보는 변경을 통과로 봤다.

## 이번 작업 — 뒤로가기 상한과 예시 여행 진도 (2026-10-15)

화면 기록이 6에 닿으면 현재 항목만 바꾼다. 스택에 없는 화면은 되살리지 않는다. 예시 여행과 데모 생성은 완료 기록을 비운다.

검토 에이전트 01a13e6e-714f-7583-9d35-c218498a667f 은 pushScreen이 navStack이 NAV_MAX 6 이상이면 shift한 뒤 현재 히스토리 항목을 replaceState하고 그 전에는 pushState하며, onPop은 navStack.indexOf(target)가 0보다 작으면 go하지 않고, preset과 demoGen은 PROG.done을 비우고 sessionClear를 부르며, 학습 카드 듣기는 먼저 window.__spoken을 빈 배열로 두고 그 다음 버튼의 click을 직접 부른 뒤 길이가 0보다 큰지와 그 배열이 화면 원문이 아니라 대괄호를 뺀 문장 하나를 담은 배열과 같은지를 보는 통과로 봤다.

## 이번 작업 — 문서 폴더 (2026-10-15)

루트 `README.md` 는 저장소 입구로 루트에 둔다. 나머지 루트 기획 문서와 `docs/` 문서를 주제 폴더로 옮겼다. `docs/` 와 그 하위 폴더마다 `README.md` 가 있다.

| 폴더 | 문서 |
|---|---|
| `docs/product/` | `requirements.md`, `ENRICHMENT_PIPELINE.md` |
| `docs/planning/` | `prd.md`, `기술스택.md`, `시나리오.md`, `시나리오완료.MD` |
| `docs/assignment/` | `ASSIGNMENT.md`, `rubric.md`, `review-log.md` |
| `docs/workflow/` | `AGENT_WORKFLOW.md`, `REPO_STATE.md` |
| `docs/deploy/` | `DEPLOY_RUNBOOK.md`, `go-nogo-flow.html`, `배포시나리오트래커.xlsx` |
| `docs/measurement/` | `LATENCY_분석과_측정.md`, `score_측정_실행법.md` |
| `docs/design/` | `RESPONSIVE_STRATEGY.md` |
| `docs/research/` | 그대로. `README.md` 를 더했다 |
| `docs/user-test/` | 그 자리. README 에 문서 목록 링크 한 줄 |

이 절보다 위의 경로는 그 시점의 경로다. `mockup/README.md`, `mockup/app.js`, `mockup/audit/responsive_audit.js` 는 2026-10-22 동결이라 `docs/RESPONSIVE_STRATEGY.md`, `../prd.md`, `../시나리오완료.MD`, `../기술스택.md` 를 그대로 둔다. 외부 문서 URL 은 그대로다. `docs/user-test/results.md` 2·3·4절은 비어 있다.

세션 디렉터리: `C:\Users\seong\.grok\sessions\C%3A%5CUsers%5Cseong%5CDesktop%5CProJect%5Ccodyssey_final\01a138a0-a233-7ca1-843c-3de2a5de06b6`

계획 검토 에이전트 01a13eab-83cf-79f3-8cb6-edbb472c512b 은 폴더 묶음과 고칠 링크 목록을 통과로 봤다.

검토 에이전트 01a13eb8-74aa-7332-9b4e-3442f09397cd 은 루트 README.md가 루트에 남고 prd.md와 기술스택.md와 시나리오.md와 시나리오완료.MD가 docs/planning에 있으며 그 MD 대소문자가 유지되고 requirements.md와 ENRICHMENT_PIPELINE.md가 docs/product에 있고 ASSIGNMENT.md와 rubric.md와 review-log.md가 docs/assignment에 있고 AGENT_WORKFLOW.md와 REPO_STATE.md가 docs/workflow에 있고 DEPLOY_RUNBOOK.md와 go-nogo-flow.html과 배포시나리오트래커.xlsx가 docs/deploy에 있고 LATENCY_분석과_측정.md와 score_측정_실행법.md가 docs/measurement에 있고 RESPONSIVE_STRATEGY.md가 docs/design에 있고 research 세 문서가 그 자리에 있으며 docs와 그 하위 폴더마다 README.md가 있고 user-test README에 문서 목록 링크 한 줄이 더해졌고 REPO_STATE.md는 docs/workflow로 옮겨졌고 이전 docs/REPO_STATE.md 대비 본문 차이는 끝의 문서 폴더 절 추가뿐이며 그 앞 01a13e6e 문장은 이전 파일과 같고 루트 README와 prd.md와 requirements.md와 AGENT_WORKFLOW.md와 ASSIGNMENT.md와 rubric.md와 review-log.md와 user-test README와 speak-hallucination.md와 ENRICHMENT_PIPELINE.md와 e2e/test_speech_text.py와 e2e/test_shell.py와 backend/app/main.py와 backend/README.md의 현재 위치 링크가 새 경로이며 docs와 루트 README.md와 backend README.md의 상대 마크다운 링크가 실제 파일을 가리키고 mockup의 예전 경로 인용이 남아 있는 변경을 통과로 봤다.

## 이번 작업 — 일정 오케스트레이터 (2026-10-15)

팀 main `e8ac770`에서 분기했다. `/generate` 응답에 `itinerary` 형제를 붙인다. 공개 라우트는 그대로 세 개다. `ITINERARY_ENABLED` 기본값은 꺼짐이다. 화면은 2026-10-22 전 2차 사용자 테스트에 넣지 않는다. `GOOGLE_MAPS_API_KEY`는 이 환경에 없어 실호출 JSON은 만들지 않았다. 키가 없는 실행은 수집 성공이 아니다.

검토 에이전트 01a13f22-9fe7-7332-980e-cbdbaa094815 은 backend/app/main.py, backend/app/agents/itinerary.py, backend/tests/test_itinerary.py, backend/scripts/itinerary_live_once.py 네 경로가 커밋에 들어가고 mockup은 그대로이며 새 공개 라우트는 없고 POST /generate에 itinerary 형제가 붙으며 /health의 google_places와 FACT_SOURCES_READY는 거짓으로 남고 ITINERARY_ENABLED는 호출 때 읽어 기본이 꺼지며 itinerary_live_once.py는 플래그나 키가 없으면 종료 코드 2로 끝나고 키를 출력하지 않으며 저장소 안에는 쓰지 않고 _generate가 스레드에서 collect_itinerary와 문장 생성을 겹치며 MIN_ATTEMPTS는 30으로 남고 ITINERARY_DAILY_CAP 기본값은 20이며 검증된 목록에 없는 모델 place_id는 버리고 모델을 다시 부르지 않으며 tests.test_itinerary를 실행해 18개가 통과한 것을 확인하고 변경을 통과로 봤다.
