# 저장소 상태

절차는 [`AGENT_WORKFLOW.md`](AGENT_WORKFLOW.md)를 따른다. 이 문서는 한 시점의 사실이다. 세션을 열 때마다 다시 읽고 고친다.

| 항목 | 값 |
|---|---|
| 기록 시각 | 2026-10-14 |
| 최근 세션 | `C:\Users\seong\.grok\sessions\C%3A%5CUsers%5Cseong%5CDesktop%5CProJect%5Ccodyssey_final\01a138a0-a233-7ca1-843c-3de2a5de06b6` |
| 세션 파일 | `chat_history.jsonl`, `events.jsonl`, `updates.jsonl`, `summary.json`, `prompt_context.json`, `resources_state.json`, `system_prompt.txt`, `tool_definitions.json`, `terminal/` |
| 작업 브랜치 | 이 문서를 다시 대조하는 시점에는 `docs/agent-workflow`가 없다. 통과 뒤 커밋할 때 `fix/dup-swipe`(`2e77ff1`)에서 그 브랜치를 만든다 |
| 조사 시점 `HEAD` | `2e77ff1` — `fix/dup-swipe`. `origin/fix/dup-swipe`와 같다 (앞 0, 뒤 0) |
| `origin` | `https://github.com/seongbin45/codyssey_final` |
| `team` | `https://github.com/01044402345o-beep/codyssey_final.git` |
| 배포 | `https://codyssey-final.onrender.com` (팀 `main` 머지 시 Render 무료 플랜) |

이 세션 동안 `fix/dup-swipe` 끝이 두 번 바뀌었다. 처음 읽은 끝은 `5cee643`이었고, 다음 대조 때는 `bd4bf06`이며 `origin/fix/dup-swipe`(`49aea20`)보다 3커밋 앞이었다. 그 다음 대조 때는 끝이 `2e77ff1`이고 원격과 같아져 있었다. 이 문서의 git 사실은 세 번째 읽기다.

`2e77ff1`은 병합이다. 첫 부모는 `bd4bf06`, 둘째 부모는 `809c38d` fix(mockup): 카드·토스트의 듣기 미지원 안내에도 카톡 메뉴 안내 + 되는 것(말하기·카드) 안내 이다. 그 커밋은 이 문서 작업이 아니다.

세션 시작 때 로컬 `main`(`4a21b87`)은 `origin/main`보다 44커밋 뒤에 있었다. 평가·배포 기준은 팀 저장소 `main`이다.

추적되지 않은 루트 `.gitignore`는 Next.js 템플릿이다. 이 제품은 바닐라 JS와 FastAPI라 그 파일은 커밋하지 않는다.

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

## `.`에서 열려 있는 일

기준 문서: `docs/requirements.md` (2026-10-09, 커밋 `f78b23b` 시점 표기). 아래는 그 문서가 완료로 두지 않은 항목이다.

| ID | 상태 | 코드에서 확인한 내용 |
|---|---|---|
| FR-03 장소 보고서 | 예시 | `mockup/data.js` `PLACE_POOLS`. 뉴욕·보스턴은 관광지·맛집만 있음 |
| FR-04 방문 순서 | 예시 | 코드 배치 |
| FR-15 교통·숙소 생성 | 부분 | 계약 3종은 `agent_contract/categories/`에 있다. `mockup/ai.js` `categoryOfKind`는 식당·카페→restaurant, 공항·역·택시→transport, 호텔·호스텔·게스트하우스·에어비앤비→lodging. `genReport`(`mockup/app.js`)는 장소를 `attraction`과 `restaurant`로만 만든다. `attraction`은 계약 밖이라 생성 요청은 식당만 나간다 |
| FR-16 로그인·서버 저장 | 예정 | 데모 사용자와 브라우저 저장 |
| NFR-08 화면 | 부분 | 반응형·다크·넓은 화면 배치는 구현 기록이 `docs/RESPONSIVE_STRATEGY.md`에 있다. 남은 것: 실기기(iOS Safari·iPad), 다크 모드 팀 디자인 검수, 브라우저 뒤로가기와 날짜 선택 |
| 장소 보강 파이프라인 | 제안 | `docs/ENRICHMENT_PIPELINE.md`는 미구현 |

`README.md`의 알려진 한계는 "화면 코드가 카테고리를 restaurant로 고정"이라고 적혀 있었다. 코드는 장소 종류로 카테고리를 정한다. 이번 기록에서 그 문장을 FR-15 행과 같게 고친다.

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

이번 세션은 절차와 상태만 기록한다. 아래는 아직 구현하지 않는다.

1. FR-15. 예시 장소에 교통·숙소를 넣어 `categoryOfKind`가 그 계약을 실제로 호출하게 한다. 뉴욕·보스턴 장소 목록이 있거나, `data.js`와 같은 결의 예시 장소를 만들어도 된다는 확인이 필요하다.
2. 디자인 가이드와 목업의 차이 정리. `디자인 가이드.dc.html`이 2026-10-08 이후에도 기준인지, 다크 모드 팀 검수 메모가 있는지가 필요하다.

## 사용자에게 요청할 파일

트리에 이미 있어서 다시 받지 않는 것: `other/Project261000/design/`의 DC 세 파일, `docs/RESPONSIVE_STRATEGY.md`, `docs/requirements.md`.

다음에 구현하려면 필요한 것:

1. 2026-10-08보다 새로운 디자인 가이드가 있으면 그 파일. 없으면 현재 DC를 기준으로 쓴다.
2. 다크 모드 팀 검수 메모나 화면 캡처. NFR-08이 이 검수를 미완으로 둔다.
3. 실기기에서 깨진 화면이 있으면 그 캡처(기기, 브라우저, 화면 이름).
4. FR-15를 먼저 할지, 디자인 가이드와 목업의 차이를 먼저 할지.

## 이번 작업

목적: 위 절차를 문서화하고, 이 시점의 구조와 열린 일을 한 문서에 고정한다. 제품 동작은 바꾸지 않는다.

| 단계 | 목적 | 파일 | 완료 조건 |
|---|---|---|---|
| 1 | 절차를 적는다 | `docs/AGENT_WORKFLOW.md` | 아이디어 출처, 세션마다 상태 갱신, 구현 전 단계 계획, 단계별 다른 에이전트 검증, 없는 자료 요청, 작업 끝 커밋·`origin` 푸시, 세션 경로 공개가 모두 있다 |
| 2 | 이 시점의 사실을 적는다 | `docs/REPO_STATE.md` | 브랜치, 원격, 구조, FR-15의 실제 연결, `./other`의 역할이 코드·git과 같다 |
| 3 | 읽는 사람이 절차를 찾게 하고, 한계 문장을 코드와 맞춘다 | `README.md` | 문서 표에 두 문서가 있고, 한계 문장이 `categoryOfKind`와 `genReport`와 같다 |
| 4 | 1–3을 다른 에이전트가 대조한다 | 위 세 파일 | 불일치를 고친 뒤 같은 기준으로 다시 본다 |
| 5 | 이 세 파일만 커밋하고 `origin`의 `docs/agent-workflow`에 푸시한다 | git | 분기 기준은 그 시점의 `fix/dup-swipe` 끝. `.gitignore`와 `fix/dup-swipe` 자체는 푸시하지 않는다 |

검증:

- 절차 문서 대조: 통과. 아이디어 출처, 세션마다 상태 갱신, 구현 전 단계 계획, 다른 에이전트의 단계별 대조, 없는 자료 요청, `origin` 푸시와 `team` 제한, 세션 경로 공개, 오래된 사본의 우선순위, 사실 순서를 문서에서 확인했다.
- 상태 문서 첫 대조 (`bd4bf06` 시점): 불일치. 브랜치·HEAD·ahead 3커밋·원격·`genReport`·`categoryOfKind`·계약 파일·디자인 파일·세션 디렉터리·README 문장은 그때 맞았다. 상태 표만 `docs/agent-workflow`가 이미 있는 것처럼 적혀 있었다.
- 상태 문서 재대조: 불일치. 그 사이에 `fix/dup-swipe`가 `2e77ff1`로 움직였고 `origin/fix/dup-swipe`와 같아졌다. `bd4bf06`과 ahead 3 문장을 세 번째 읽기로 고쳤다.
- 상태 문서 세 번째 대조: 불일치 한 곳. `HEAD` `2e77ff1`, 원격과 앞 0 뒤 0, `main` 44 뒤, FR-15, README는 맞았다. "`2e77ff1`의 바로 아래는 `809c38d`"는 틀렸다. `2e77ff1`은 병합이고 첫 부모는 `bd4bf06`, 둘째 부모는 `809c38d`이다. 그 문장을 고쳤다.
- 상태 문서 네 번째 대조: 통과. 첫 부모는 `bd4bf06`, 둘째 부모는 `809c38d`, `HEAD`는 `2e77ff1`이다. "바로 아래"는 이 오류 기록에만 남아 있다.
