# 자동화 워크플로우 마인드맵 — 노드·정책·한계

## 0. 한 줄 요약

관리자가 **GUI 개요 탭의 마인드맵에서 노드를 클릭해 값을 바꾸고 `[정책에 저장]`** 하면, 그 값이 곧
`run_step`/`push_env`/`automation_loop` 의 동작(무엇을 실행하고 무엇을 Render 환경변수로 밀어넣을지)을 결정한다.

| 어디서 쓰나 | 사실 |
|---|---|
| GUI | **개요 탭**에서만 쓴다. `workflow.py` 를 import 하는 곳은 `gui.py` 뿐이다. |
| CLI | **노드 개념 없음.** CLI(`python -m opsarchive …`)는 `keygen`/`publish`/`anchor` 같은 개별 명령만 노출한다(노드/정책 미지원). |

근거: `tools/opsarchive/opsarchive/workflow.py`, `tools/opsarchive/opsarchive/gui.py`(개요 탭 342–389행), `tools/opsarchive/tests/test_workflow.py`.

---

## 1. 노드 표

`workflow.NODES`(workflow.py 36–87행)를 **한 글자도 바꾸지 않고** 옮겼다. `실행 가능`은 `run_step` 이 실제로 처리하는 노드(`_RUNNABLE = {observe, pin_check, iam_check, anchor, verify_chain}`, 103행) 기준이다.

| id | 그룹 | 종류 | 기본값 | 연결 env | 재배포 필요 | 실행 가능 |
|---|---|---|---|---|---|---|
| `seal_failures` | 탈퇴 대응 | toggle | `True` | `EVIDENCE_SEAL_FAILURES` | 필요 | ✘ (env 밀어넣기 노드) |
| `daily_cap` | 탈퇴 대응 | number | `5` (1~100000) | `EVIDENCE_DAILY_CAP` | 필요 | ✘ |
| `per_uid_seconds` | 탈퇴 대응 | number | `60` (1~86400) | `EVIDENCE_PER_UID_SECONDS` | 필요 | ✘ |
| `ttl_days` | 탈퇴 대응 | number | `30` (1~3650) | `EVIDENCE_TTL_DAYS` | 필요 | ✘ |
| `issue_notify` | 탈퇴 대응 | toggle | `True` | — | 불필요 | ✘ (안내 노드) |
| `client_report` | 탈퇴 대응 | toggle | `False` | — | 불필요 | ✘ (안내 노드) |
| `observe` | 감시·증인 | choice | `"60"` (60/360/1440) | — | 불필요 | **✔** |
| `iam_check` | 감시·증인 | action | `True` | — | 불필요 | **✔** |
| `pin_check` | 감시·증인 | action | `True` | — | 불필요 | **✔** |
| `anchor_interval` | 검증·앵커 | choice | `"3600"` (3600/21600/86400/0) | — | 불필요 | ✘ (안내 노드) |
| `anchor` | 검증·앵커 | action | `True` | — | 불필요 | **✔** |
| `verify_chain` | 검증·앵커 | action | `True` | — | 불필요 | **✔** |
| `include_secrets` | 안전 | toggle | `False` | `EVIDENCE_INCLUDE_SECRETS` | 필요 | ✘ |

- `choice` 옵션 라벨: `observe` = 60분/6시간/24시간, `anchor_interval` = 1시간/6시간/24시간/수동(`0`).
- `number` 단위 표시(`_UNITS`, 108행): `daily_cap`=회, `per_uid_seconds`=초, `ttl_days`=일.
- `action` 노드는 값을 갖지 않는다(편집 불가, `[이 노드 실행]` 만 가능).

---

## 2. 환경변수 대조표 (노드가 미는 env ↔ 앱이 실제로 읽는지)

앱이 읽는 env 는 `backend/app/evidence.py` 에서 직접 확인했다(아래 `근거` 열). 노드가 미는데 **앱이 읽지 않으면 지금은 효과 없음(개념 노드)** 이다.

| 노드 id | 미는 env | 값 형식 | 앱이 읽는가 | 앱 근거(evidence.py) | 앱 기본값 |
|---|---|---|---|---|---|
| `seal_failures` | `EVIDENCE_SEAL_FAILURES` | `"1"`/`"0"` (toggle) | **아니오 — 지금은 효과 없음(개념 노드)** | evidence.py 에 문자열 없음(봉인 on/off 는 `EVIDENCE_PUBKEY` 유무로 결정) | — |
| `daily_cap` | `EVIDENCE_DAILY_CAP` | 정수 (`str(값)`) | 예 | 523행 `_int_env("EVIDENCE_DAILY_CAP", 5)` | **5** (서버 감지 예산. 화면 보고는 `EVIDENCE_CLIENT_DAILY_CAP` 별도) |
| `per_uid_seconds` | `EVIDENCE_PER_UID_SECONDS` | 정수 | 예 | 525행 `_int_env("EVIDENCE_PER_UID_SECONDS", 3600)` | **3600** (노드 기본 60과 다름) |
| `ttl_days` | `EVIDENCE_TTL_DAYS` | 정수 | 예 | 399·464·562행 `_int_env("EVIDENCE_TTL_DAYS", 90)` | **90** (노드 기본 30과 다름) |
| `include_secrets` | `EVIDENCE_INCLUDE_SECRETS` | `"1"`/`"0"` | 예 (문자열 `"1"` 일 때만) | 167행 `os.getenv("EVIDENCE_INCLUDE_SECRETS") == "1"` | 꺼짐 |
| `issue_notify` | (없음, `env=None`) | — | — | 노드가 아무 env 도 밀지 않음 | — |
| `client_report` | (없음, `env=None`) | — | — | 노드가 아무 env 도 밀지 않음 | — |

**앱이 읽지만 어떤 노드도 밀지 않는 env**(GUI 로는 못 바꾼다 — 대시보드/`.env`/CLI `publish` 로만):
`EVIDENCE_PUBKEY`, `EVIDENCE_KEY_GENERATION`, `EVIDENCE_GH_TOKEN`, `EVIDENCE_GH_REPO`,
`EVIDENCE_MAX_BYTES`, `EVIDENCE_MAX_SOURCE_BYTES`, `EVIDENCE_MAX_LOGS_BYTES`.

주의: `daily_cap`/`per_uid_seconds`/`ttl_days` 는 **노드 기본값과 앱 기본값이 다르다**. GUI 에서 값을 저장하지 않고 곧바로 `[Render에 반영]` 하면 노드 기본값(50/60/30)이 밀려 들어간다 — 앱의 기본값(5/3600/90)과 다르므로 의도한 값인지 확인하라.

---

## 3. GUI 사용법 (클릭 몇 번)

개요 탭(gui.py 342–389행)에서:

1. 마인드맵 캔버스에서 **노드를 클릭** → 아래 "선택한 노드" 편집기에 label·설명·현재 값이 뜬다.
2. 값 수정(toggle=체크, choice=콤보, number=입력+min~max). action 노드는 값이 없다.
3. **`[정책에 저장]`** → `workflow.save(policy)` 로 `~/.opsarchive/workflow.json` 에 쓴다(다음 실행부터 반영).
4. env 노드면 **`[Render에 반영]`** → `workflow.push_env(...)` 로 Render 환경변수를 바꾼다. env 없는 노드는 "연결돼 있지 않습니다" 안내만 뜬다.
5. **재배포** — 서버 정책(환경변수)은 값만 바꿔도 앱이 옛 값을 들고 돈다. 재배포는 GUI 가 하지 않는다(Render 대시보드/CLI).
6. **`[plan 미리보기]`** → 이번에 무엇이 실행될지(ok/사유)를 텍스트로 보여준다. 반영 확인용.
7. **`[이 노드 실행]`** → `run_step`. `anchor` 는 서명 키 파일 선택 + 패스프레이즈 입력을 먼저 받는다.
8. **`[자동 실행 시작]` / `[중지]`** → 워커 스레드에서 `automation_loop` 를 돈다. `[중지]` 는 `stop_event` 를 세팅해 **현재 주기가 끝나면** 멈춘다.

그 밖의 버튼: `[정책 파일 위치]`(경로 로그 출력), `[새로 고침]`/`[설정 다시 읽기]`/`[정책 다시 읽기]`.

---

## 4. plan 의 의미

`plan()`(281–292행)이 `_PLAN_ORDER`(96–100행) 순서로 돌려주는 항목마다 `ok`/`reason` 을 정한다(`_plan_status`, 266–278행):

| 노드 부류 | 판정 규칙 | ok | reason 예 |
|---|---|---|---|
| 실행 노드(`_RUNNABLE`) | `requires` 의 설정값이 하나라도 없으면 불가 | `False` | `필수 설정 없음: project_id, sa_path` |
| 실행 노드, 설정 충족 | 모두 있으면 실행 가능 | `True` | `""` |
| 안내 노드(`_INFO`) | `anchor_interval`/`issue_notify`/`client_report` | `False` | `실행 노드 아님(정책 안내)` |
| 나머지 정책 노드 | 꺼짐이면 제외 | `False` | `꺼짐` |
| 나머지 정책 노드, 켜짐 | — | `True` | `""` |

- 실행 순서: 정책 반영(env) → `observe` → `pin_check` → `iam_check` → `anchor` → `verify_chain` → (안내 노드).
- `requires` 는 `settings.json` 값이 `None`/`""`/`False` 가 아닐 때만 충족으로 본다(`_present`, 143–144행).
- 예: 기본값에서 `include_secrets` 는 꺼짐이라 `ok=False, reason="꺼짐"`.

---

## 5. 자동 실행이 하는 일 / 하지 않는 일

`automation_loop()`(423–482행):

**하는 일**
- 매 주기 `plan()` → `ok=True` 노드만 `run_step` 으로 실행(조회·검증·앵커).
- 위반은 `violations` 목록과 로그로 남긴다(`_violation`, 404–420행: `observe` verdict, `iam_check` verdict, `verify_chain`/`pin_check` 의 `ok=False`).
- 예외(`CommandError`·기타)는 **삼키고** 로그·violations 로만 남긴다 — 자동화가 앱을 방해하지 않는다.
- 주기 길이(`_delay_seconds`, 382–392행): `anchor_interval` 이 `0`/빈값이 아니면 그 초, 아니면 `observe`(분)×60, 그것도 안 되면 3600초.

**하지 않는 일**
- **되돌릴 수 없는 작업 없음** — 봉인/삭제/아카이브 파기는 하지 않는다(조회·검증·앵커만).
- **관리자 PC 가 켜져 있는 동안만** 돈다 — 서버측 스케줄러가 아니다.
- 앱/대시보드 상태를 바꾸지 않는다(정책 파일·Render env 는 GUI 버튼이 담당).

---

## 6. 정책 파일

- 위치: `config.config_dir()/workflow.json` = **`~/.opsarchive/workflow.json`**(`workflow_path`, 181–182행). 없으면 `DEFAULTS` 를 돌려준다.
- 스키마: 노드 id 13개를 키로 갖는다. toggle→bool, number→int(범위 클램프), choice→옵션 키 문자열, action→값 없음(기본 `true` 로 채워짐).
- 저장은 `save()` 가 `_normalize()` 를 거쳐 `sort_keys=True, indent=2` 로 쓴다.

손으로 편집할 때의 안전 규칙(`_normalize`/`_coerce`, 149–178행):

| 상황 | 결과 |
|---|---|
| 모르는 키 | **버려진다** |
| 누락 키 | **기본값으로 채워진다** |
| 타입 오류 | **기본값으로 되돌아간다**(예: `"abc"` → number 기본값) |
| number 가 범위 밖 | **min/max 로 클램프**(예: `ttl_days=-5` → 1) |
| toggle 의 `false` | 보존된다(꺼짐 유지) |

**서명 키 경로·패스프레이즈는 이 파일에 저장되지 않는다.** `run_step` 은 비밀을 `secrets` 인자로 따로 받고, GUI 는 실행 직전 대화상자로 입력받는다(workflow.py 311–316행, gui.py 519–534행).

예시(`~/.opsarchive/workflow.json`):

```json
{
  "daily_cap": 50,
  "include_secrets": false,
  "observe": "60",
  "seal_failures": true,
  "ttl_days": 30
}
```
(실제 파일은 13개 키가 모두 채워져 나온다 — 위는 일부만 편집한 입력 예.)

---

## 7. 검증 방법

개별 테스트(PowerShell, `tools\opsarchive` 에서):

```powershell
cd tools\opsarchive
$env:PYTHONPATH="."
.venv\Scripts\python.exe -m unittest tests.test_workflow -v
```

전체 테스트(discover):

```powershell
cd tools\opsarchive
$env:PYTHONPATH="."
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

정책 파일·plan 을 GUI 없이 확인(숨긴 Tk 루트 포함):

```python
import os, tempfile, tkinter as tk
from opsarchive import workflow, gui

# 1) 정책 저장/복원 + plan (순수 로직 — 네트워크 불필요)
path = os.path.join(tempfile.mkdtemp(), "workflow.json")
workflow.save({"daily_cap": 7, "bogus": 1}, path)     # 모르는 키는 버려진다
print(workflow.load(path)["daily_cap"])               # 7
for step in workflow.plan(workflow.load(path)):
    print(step["id"], step["ok"], step["reason"])

# 2) GUI 를 창 없이 만들어 노드 그래프만 확인(디스플레이 필요)
root = tk.Tk(); root.withdraw()
app = gui.App(root)
print(list(app.node_boxes.keys()))                    # 캔버스에 그려진 노드 id
root.destroy()
```

---

## 8. 정직한 한계 / 미구현

- **자동 실행의 스케줄러 부재** — 주기 실행은 관리자 PC(프로세스)가 켜져 있는 동안만 돈다. 서버측 cron/스케줄러가 아니다(workflow.py 15행, 423행).
- ~~env 반영 후 재배포 필요~~ → **해결(2026-10-22)**: `[Render에 반영]`·`[변경 모아 반영(재배포·확인)]` 이 `workflow.apply_env` 로 **바뀐 값만** 올리고 한 번 재배포한 뒤, Render 에서 값을 다시 읽어 정책과 같은지·재배포가 끝났는지·`/health` 의 키 세대가 맞는지 확인한다. 바뀐 것이 없으면 재배포하지 않는다. [아니요] 를 고르면 값만 올린다.
- ~~앱이 읽지 않는 env 노드~~ → **해결**: 앱이 실제로 읽는다 — `seal_failures`→`EVIDENCE_SEAL_FAILURES`(evidence.seal_and_report), `issue_notify`→`EVIDENCE_NOTIFY`(evidence.notify), `client_report`→`EVIDENCE_CLIENT_REPORTS`(/diagnostics/withdraw). 백엔드 테스트가 각 변수의 효과를 확인한다(`test_evidence`·`test_account_erase`).
- ~~서버 측 정책을 GUI 가 못 바꾼다~~ → **해결**: 노드 추가·연결 — `gh_repo`(text, `EVIDENCE_GH_REPO`, owner/repo 형식 검사), `gh_token`(secret, `EVIDENCE_GH_TOKEN`, 반영 때 가려진 칸으로 받고 **저장·로그 안 함**), `pubkey`(key, `EVIDENCE_PUBKEY` — 키 파일에서 역산하는 공개키 발행으로 연결), `max_source_bytes`·`max_logs_bytes`(number). `key_generation`·`max_bytes` 는 이미 있다. 앱이 읽는 `EVIDENCE_*` 변수 중 노드가 없는 것은 없다.
- **`observe` 는 플랫폼 로그 보존 기간만큼만** 본다(그보다 오래된 구간은 안 보인다).
- **[정책 다시 읽기] 버튼의 코드 불일치** — gui.py 392행이 호출하는 `workflow.policy_path()` 는 `workflow.py` 에 **없다**(존재하는 이름은 `workflow_path`). 이 버튼은 클릭 시 `AttributeError` 가 날 수 있다(코드에서 직접 확인; 다른 버튼은 `workflow.load()` 사용).
- **공개키는 값으로 넣지 않는다** — `pubkey` 노드는 키 파일·패스프레이즈가 필요한 발행 흐름이라 [변경 모아 반영] 에 포함되지 않는다(따로 실행).
- **번호 노드 최소값 1** — `per_uid_seconds`/`daily_cap`/`ttl_days` 는 1 미만으로 내려가지 않는다(끄기 개념이 없다).
- **문서-코드 어긋남 경고**: 이 문서는 특정 커밋의 코드를 읽고 작성했다. 값·규칙이 바뀌면 **항상 `workflow.NODES`·`plan()`·`_RUNNABLE` 을 코드에서 다시 확인하라.** 추측으로 채우지 않았고, 확인 못 한 값은 위 표에 표시했다.

---

## 9. 관련 문서

- 설계·위협 모델·런북: [`docs/ops/EVIDENCE_SEAL.md`](EVIDENCE_SEAL.md) (§9 발신자 인증, §10 (b)매니페스트 서명+(d)해시체인·앱 밖 앵커, §11 남은 위험/미검증)
- 배포: [`docs/deploy/DEPLOY_RUNBOOK.md`](../deploy/DEPLOY_RUNBOOK.md)
- 도구 개요·설치: [`tools/opsarchive/README.md`](../../tools/opsarchive/README.md)
## 노드 표 보강 (2026-10-17 추가분)

아래는 위 표에 이어 붙는 노드들이다. **정본은 코드**(	ools/opsarchive/opsarchive/workflow.py 의 NODES)이며,
새 노드가 추가되면 이 표를 갱신해야 한다(문서-코드 드리프트 주의).

| id | 그룹 | 종류 | 기본값 | 연결 env | 재배포 필요 | 실행 가능 |
|---|---|---|---|---|---|---|
| max_bytes | 안전 | number | 1000000 | EVIDENCE_MAX_BYTES | 예 | 아니오(정책 반영) |
| key_generation | 검증·앵커 | number | 1 | EVIDENCE_KEY_GENERATION | 예 | 아니오(정책 반영) — **핀의 세대와 같아야 한다** |
| gh_repo | 탈퇴 대응 | toggle | 꺼짐 | 없음(안내) | 아니오 | 아니오 — opsarchive env-set 또는 .env 로 EVIDENCE_GH_REPO 를 올린다 |
| ~~max_source_logs~~ (10/22 제거 → max_source_bytes·max_logs_bytes) | 안전 | toggle | 켜짐 | 없음(안내) | 아니오 | 아니오 — 소스·로그 캡은 앱 기본값(EVIDENCE_MAX_SOURCE_BYTES·EVIDENCE_MAX_LOGS_BYTES) 유지 |
| iam_check_enabled | 감시·증인 | toggle | 켜짐 | 없음 | 아니오 | 아니오 — 끄면 자동 실행이 iam_check 를 건너뛴다(수동 [이 노드 실행] 은 그대로 가능) |

### plan 의 ction 구분(2026-10-17)

plan() 은 각 항목에 ction 을 함께 준다: 
un(실제 실행) · env(환경변수 반영 대상) · info(안내 노드).
ok=True 인 항목이 전부 실행되는 것은 아니라는 점을 GUI 계획 미리보기에서 확인하세요.

### 자동 실행의 경보 구분(2026-10-17)

utomation_loop 은 결과를 두 갈래로 나눈다.
- iolations — 명확한 실패(예: ok=False, erdict != "ok")
- 
otices — **확인 못 함**(예: 핀 미활성으로 ok=None, 관측 결과가 빈 dict)

자동 실행 중 'IAM 점검이 정책에서 꺼져 있어…'·'앵커 주기가 수동이라…' 같은 로그가 나오면 정책에 따른 정상 동작이다.

## 노드 표 갱신 (2026-10-22 — 개념 노드 제거)

| id | 종류 | 연결 env | 기본값 | 비고 |
|---|---|---|---|---|
| issue_notify | toggle | EVIDENCE_NOTIFY | 켜짐 | 끄면 토큰·저장소가 있어도 이슈를 올리지 않는다 |
| gh_repo | text | EVIDENCE_GH_REPO | (빈 값) | owner/repo 형식만. 비어 있으면 반영하지 않는다(빈 값으로 덮지 않음) |
| gh_token | secret | EVIDENCE_GH_TOKEN | — | 반영할 때 입력. 정책 파일·로그·결과에 값이 남지 않는다 |
| client_report | toggle | EVIDENCE_CLIENT_REPORTS | 켜짐 | 화면 불일치 보고를 봉인할지(앱의 기존 동작 = 켜짐) |
| pubkey | key | EVIDENCE_PUBKEY | — | 공개키 발행(Render 탭 ①)과 같은 흐름 |
| max_source_bytes | number | EVIDENCE_MAX_SOURCE_BYTES | 524288 | 앱 기본값과 같다 |
| max_logs_bytes | number | EVIDENCE_MAX_LOGS_BYTES | 65536 | 앱 기본값과 같다 |

`max_source_logs`(안내 토글)는 없어졌다 — 저장된 workflow.json 에 남아 있어도 읽을 때 버린다.
