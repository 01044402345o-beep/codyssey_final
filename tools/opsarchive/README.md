# opsarchive — 탈퇴 실패 증거 봉인 관리자 도구

## 1. 한 줄 소개

탈퇴(계정 삭제)가 실패한 순간의 상태를 **금고에 넣고, 열쇠는 관리자만** 갖는 도구다.
금고에 해당하는 봉인 증거를 서버 저장소에 격리하고, 여는 개인키는 이 컴퓨터 밖으로 나가지 않는다.
설계와 위협 모델은 [`docs/ops/EVIDENCE_SEAL.md`](../../docs/ops/EVIDENCE_SEAL.md)에 있다.

---

## 2. 누가 무엇을 할 수 있나

이 시스템은 두 부분으로 나뉜다. 이 구분이 가장 중요하다.

| 부분 | 무엇인가 | 어디서 되나 |
|---|---|---|
| (가) 앱 자체 | 사용자가 탈퇴를 요청하고 실패하면 증거가 봉인되는 서비스 | 서버에서 돈다. 사용자는 휴대폰·태블릿 브라우저로 요청만 한다 |
| (나) 관리자 도구(`opsarchive`) | 키 생성·공개키 발행·핀·앵커·검증·복호화 | **컴퓨터**에서만. 휴대폰에서는 못 한다 |

관리자 도구가 필요한 것: **컴퓨터 + 인터넷 + Python 3.10 이상**.
Windows / macOS / Linux 아무거나 된다. `run_gui.cmd`도 "install Python 3.10+ first"라고 안내한다.

| 휴대폰·태블릿에서 할 수 있다 | 휴대폰·태블릿에서 못 한다 |
|---|---|
| 앱에서 탈퇴(계정 삭제) 요청 | `keygen` / `signkey` — 관리자 키 만들기 |
| Render·Firebase·GitHub 대시보드를 브라우저로 열람 | `publish` / `env-set` — 서버 환경변수 발행 |
| GitHub 이슈를 눈으로 읽기 | `pin` / `pin-check` / `anchor` / `verify-chain` — 핀·앵커·검증 |
| 가능하면 간단한 값 복사 | `list` / `decrypt` — 아카이브 열기(개인키 필요) |
| — | `gui` 창 열기(데스크톱 창이라 휴대폰에 없다) |

휴대폰 대시보드로 환경변수를 손으로 넣을 수는 있다. 하지만 오타·유출 위험이 크다.
가능하면 컴퓨터의 `env-set` 또는 GUI를 쓰라.

### 이 도구가 지키는 경계

- **앱과 완전히 독립**이다. `backend/`의 어떤 모듈도 import 하지 않는다.
- **개인키는 이 프로세스의 로컬 파일에만** 있다. 파일은 scrypt+AES-256-GCM으로 잠근다.
- **패스프레이즈는 TTY 입력으로만** 받는다. 명령줄 인자·환경변수로 받지 않는다.
- 네트워크로 나가는 것은 **공개키**와 **봉인된 아카이브**뿐이다.
- 어떤 출력에도 키·패스프레이즈를 넣지 않는다(지문만 보여준다).

---

## 3. 5분 안에 열어보기

경로 구분자와 `&&` 차이를 주의하라. **PowerShell 5.1은 `&&`가 동작하지 않는다.**
그래서 아래 표는 명령을 **한 줄씩** 적었다.

| 단계 | Windows PowerShell (5.1) | macOS (zsh) | Linux (bash) |
|---|---|---|---|
| ① 폴더 이동 | `cd tools\opsarchive` | `cd tools/opsarchive` | `cd tools/opsarchive` |
| ② 가상환경 만들기 | `python -m venv .venv` (`py -m venv .venv`도 가능) | `python3 -m venv .venv` | `python3 -m venv .venv` |
| ③ 의존성 설치 | `.venv\Scripts\python -m pip install -r requirements.txt` | `.venv/bin/python -m pip install -r requirements.txt` | `.venv/bin/python -m pip install -r requirements.txt` |
| ④ 자체 점검 | `.venv\Scripts\python -m opsarchive selftest` | `.venv/bin/python -m opsarchive selftest` | `.venv/bin/python -m opsarchive selftest` |
| ⑤ GUI 열기 | `.venv\Scripts\python -m opsarchive gui` | `.venv/bin/python -m opsarchive gui` | `.venv/bin/python -m opsarchive gui` |

**Windows는 `run_gui.cmd`를 더블클릭**해도 된다.
이 파일이 가상환경 생성·의존성 설치·GUI 실행을 한 번에 해 준다.
가상환경을 활성화하지 않고 폴더 안 파이썬을 직접 부르는 방식이라 실패가 적다.

보조: 굳이 활성화하려면 Windows `.venv\Scripts\activate`, macOS/Linux `source .venv/bin/activate`.
활성화 뒤에는 `python -m opsarchive selftest`처럼 짧게 쓸 수 있다.

---

## 4. 처음 하는 사람 9단계

경고: 아래 ④·⑥·⑧단계는 **서버·저장소 상태를 바꾼다**.
특히 ④ `publish`는 운영 앱에 공개키를 발행하고 재배포한다. 시험용 키를 운영에 발행하지 마라.

GUI를 쓰면 "명령" 대신 해당 탭의 버튼을 누르면 된다(같은 일을 한다).

| # | 무엇을 하는가(쉬운 말) | 명령 또는 GUI 버튼 | 성공하면 이렇게 보인다 |
|---|---|---|---|
| ① | 이 PC에서 도구가 정상인지 확인 | `python -m opsarchive selftest` · 키 탭 `[selftest 실행]` | `roundtrip`·`tamper`·`wrong_key`·`key_file`이 모두 `true` |
| ② | 증거를 잠글 **봉투 키** 만들기 | `python -m opsarchive keygen` · 키 탭 `[keygen 실행]` | `key_id`·`public_key`·`fingerprint` 출력, 0600 권한 |
| ③ | 도장 찍을 **서명 키** 만들기 | `python -m opsarchive signkey` · 키 탭 `[signkey 실행]` | `key_id`·`fingerprint` 출력 |
| ④ | 공개키를 서버에 **발행** | `python -m opsarchive publish --service codyssey_final --key <개인키> --base-url https://codyssey-final.onrender.com` · Render 탭 `[publish 실행]` | 단계 ①~⑤ 로그, `env_set: true`, `match: true` |
| ⑤ | 이 PC 키와 서버 지문 **대조** | `python -m opsarchive doctor --service codyssey_final --key <개인키> --base-url https://codyssey-final.onrender.com` · Render 탭 `[doctor 실행]` | `env_match: true`, `health_match: true` |
| ⑥ | 핀 파일 만들기(오프라인) | `python -m opsarchive pin --key <개인키> --health-url https://codyssey-final.onrender.com --sign-key <서명키>` · Render 탭 `[핀 만들기]` | `security/evidence-key-pin.json` 생성, `generation` 증가 |
| ⑦ | 핀과 서버 지문 **검사** | `python -m opsarchive pin-check --pin security/evidence-key-pin.json` · Render 탭 `[핀 검사 실행]` | `ok: true`, `reasons: []` |
| ⑧ | 삭제 차단 점검 | `python -m opsarchive iam-check --project <프로젝트> --sa <서비스계정>` · Render 탭 `[IAM 검사 실행]` | `verdict`가 `ok`(만들 수는 있고 지울 수는 없음) |
| ⑨ | 체크포인트 앵커 + 체인 검증 | `python -m opsarchive anchor --project <프로젝트> --sa <서비스계정> --sign-key <서명키>` · 검증 탭 `[anchor 실행]` `[verify 실행]` | anchor `seq` 증가, verify `ok: true` |

부가(필요할 때): 아카이브 보기 = 보관소 탭 `[목록 새로 고침]` → 줄 클릭 → `[복호화 실행]`.
또는 `list` / `decrypt`(개인키 필요, 평문엔 개인정보가 있음).

---

## 5. GUI 사용법

GUI는 표준 라이브러리(tkinter)만 써서 **설치 단계가 없다**. 창 이름은 `opsarchive — 탈퇴 실패 증거 봉인`이다.

| 탭 | 하는 일 |
|---|---|
| 개요 | 자동화 워크플로우 마인드맵. 노드를 클릭해 정책 값을 바꾼다 |
| 설정 | `settings.json` 값과 `.env`(비밀)를 편집·저장한다 |
| 키 | selftest → 봉투 키 → 서명 키 → 무작위 값 → 회전(선택) 순서 안내 |
| Render | 공개키 발행, 지문 대조, 상태 확인, observe, 핀 만들기·검사, IAM 검사, 재배포 |
| 보관소 | 봉인 아카이브 목록을 보고 개인키로 연다 |
| 검증 | 서명 키·핀 상태 확인, anchor, verify-chain, 챌린지 대조 |

**개요 탭 마인드맵(정책 바꾸기)**: 노드 클릭 → 값을 수정(켜기/콤보/숫자) → `[정책에 저장]` → 환경변수 노드면 `[Render에 반영]` → `[재배포 실행]`.
`[plan 미리보기]`로 이번에 무엇이 실행될지 미리 볼 수 있다.

**로그는 별도 창**이다. 제목은 `opsarchive — 로그`이고 아래 상태 줄의 `[로그 창 열기]`로 연다.
이 창을 닫아도 작업은 계속되고, 다시 열면 기록이 되살아난다.

**아래 상태 줄**: 지금 무엇을 하는지와 **다음 할 일**을 문구로 보여준다.
예: "다음 할 일: .env 에 RENDER_API_KEY 를 넣으세요(설정 탭) → ③ 공개키 발행".
GUI는 성공을 파란 `✔`, 실패를 빨간 `✘`, 경고를 노란색으로 표시한다.
색만으로 판단하지 말고 **함께 나오는 문구**를 읽어라.

---

## 6. 명령 표

경고: **되돌릴 수 없음** 표시가 있는 명령은 운영·원장을 바꾼다.
실행 전에 무엇을 하는지 확인하고, 시험용 값을 운영에 쓰지 마라.

`python -m opsarchive` 뒤에 아래 명령을 붙인다. `--help` 출력과 일치한다.

| 명령 | 하는 일 | 위험도 |
|---|---|---|
| `selftest` | 봉인·해제·변조 감지·키 잠금 왕복 확인 | 안전 |
| `keygen [--dir]` | 봉투 키쌍 생성(개인키는 잠가 저장) | 안전(로컬 파일) |
| `signkey [--dir]` | 서명 키(Ed25519) 생성 | 안전(로컬 파일) |
| `rand [--length --encoding --command --show-command]` | OS를 감지해 무작위 값 생성 | 안전 |
| `list --project --sa [--limit --json]` | 봉인 아카이브 목록 | 안전 |
| `env-read --service --key` | 환경변수 설정 여부(값은 길이만) | 안전 |
| `doctor --service --key [--base-url --pin]` | 로컬 키와 배포된 공개키 지문 대조 | 안전 |
| `pin-check [--pin --health-url]` | 핀 파일과 배포된 /health 대조 | 안전 |
| `observe --project --sa --service [--path --minutes --tolerance]` | 접근 로그와 체인 시도 비교 | 안전 |
| `tui` | rich 기반 화면(없으면 안내만) | 안전 |
| `gui` | 관리자 창 열기 | 안전 |
| `iam-check --project --sa` | 앱이 증거를 지울 수 있는지 시험(카나리아) | 주의(서버에 시험 문서 생성) |
| `decrypt --project --sa --id --key [--out]` | 아카이브를 내려받아 개인키로 연다 | 주의(평문 개인정보가 디스크에 남음) |
| `env-set --service --key [--from-file --stdin]` | Render 환경변수 하나를 올린다 | 주의(서버 환경변수 변경) |
| `deploy --service [--timeout]` | Render 서비스를 재배포한다 | 주의(서비스 재시작) |
| `publish --service --key [--base-url --env-key --no-redeploy]` | 공개키를 발행하고 재배포 | 되돌릴 수 없음(운영 반영) |
| `rotate --service --key [--base-url --no-redeploy]` | 새 키 생성·발행(옛 개인키는 보관) | 되돌릴 수 없음 |
| `pin --key --health-url [--out --generation --commit --note --sign-key]` | 개인키 지문으로 핀 파일 생성 | 되돌릴 수 없음(세대는 올리기만) |
| `anchor --project --sa --sign-key [--out]` | 체인을 확인하고 체크포인트를 서명해 앵커 | 되돌릴 수 없음(원장에 남음) |
| `verify-chain --project --sa [--pin --out --challenge]` | 서명·연속성·사라진 아카이브·챌린지 검증 | 안전 |

`publish`·`doctor`·`rotate`는 같은 옵션 집합을 받는다: `--service --key --env-key --base-url --pin --no-redeploy`.
이 중 일부는 특정 명령에서만 쓰인다(예: `--pin`은 `doctor`, `--no-redeploy`는 `publish`·`rotate`).

---

## 7. 파일과 설정 위치

| 무엇 | 어디 | 비고 |
|---|---|---|
| `.env`(비밀) | `tools/opsarchive/.env` 우선, 없으면 `~/.opsarchive/.env` | API 키·서비스 계정 경로. 커밋 금지 |
| `settings.json` | `~/.opsarchive/settings.json` | 서비스 이름·주소·프로젝트 ID 등 |
| `workflow.json`(정책) | `~/.opsarchive/workflow.json` | GUI 개요 탭 정책. 없으면 기본값 |
| 개인키 폴더 | 기본 `~/.opsarchive` | `admin-<id>.key`(봉투), `sign-<id>.key`(서명) |
| 체크포인트 | 기본 `~/.opsarchive/checkpoints` | 관리자 자산. 저장소 밖 |
| 핀 파일 | `security/evidence-key-pin.json`(저장소 안) | 관리자가 커밋해 이력을 남긴다 |
| 서비스 계정 JSON | `.env`의 `GOOGLE_APPLICATION_CREDENTIALS` 경로 | 내용이 아니라 **경로만** 기록 |

경로 표기 차이: Windows는 `C:\Users\<이름>\.opsarchive`, macOS/Linux는 `/Users/<이름>/.opsarchive` 또는 `/home/<이름>/.opsarchive`(`~`가 그 폴더).

**상대경로는 저장소 루트 기준으로 풀린다.** 그래서 `--pin security/evidence-key-pin.json`처럼 쓴다.
주의: `verify-chain`·`anchor`의 `--out` 기본값은 저장소 루트의 `checkpoints`다.
하지만 실제 체크포인트는 `~/.opsarchive/checkpoints`에 있다. 그래서 `--out`을 명시해야 한다.
GUI는 설정값을 쓰므로 이 문제가 없다.

---

## 8. 이런 오류가 나오면

CLI 오류는 `실패: <코드>` 형태로 화면에 찍힌다. 코드를 보고 아래에서 같은 글자를 찾아라.
`[MASKED]`는 자격증명을 지운 표시다. 토큰(`rnd_`·`ghp_`·`github_pat_`·`AIza`)이나 환경변수 값이
이 글자로 바뀐다(기본 동작). `EVIDENCE_INCLUDE_SECRETS=1`로 끌 수 있지만 권장하지 않는다.

| 화면에 보이는 문구 | 무슨 뜻인가 | 지금 할 일 |
|---|---|---|
| 설치 명령에서 `&&` 오류 | PowerShell 5.1은 `&&`를 지원하지 않는다 | 명령을 한 줄씩. Windows는 `run_gui.cmd` 더블클릭 |
| `UnicodeDecodeError: 'cp949'`(설치 중) | requirements.txt를 cp949로 읽음 | 지금 파일은 ASCII 전용이라 안 난다. 나면 최신 저장소를 다시 받아라 |
| `ModuleNotFoundError: cryptography` | 의존성 미설치 | 의존성 설치 또는 `run_gui.cmd`(자동 설치) |
| `실패: no_credentials` | Firestore 토큰 교환 실패 | urllib3 설치 확인. 도구는 직접 JWT로 대체하도록 고쳤다 |
| `실패: cli_failed` | Render CLI를 못 띄움(Windows는 `.cmd`) | render CLI 설치 확인. 도구는 `cmd.exe /c`로 실행한다 |
| `실패: not_found`(publish/rotate) | 서비스 이름 불일치(밑줄 vs 하이픈) | 설정 탭 `[Render 서비스 선택]`. 이름은 `codyssey_final` |
| publish가 "응답 없음"처럼 보임 | 재배포가 몇 분 걸리고 로그가 늦게 나온다 | 기다린다. 로그 창 ④ 단계 확인. 강제 종료 금지 |
| `실패: key_mismatch` 반복 | 패스프레이즈가 그 서명 키의 것이 아니다 | 올바른 패스프레이즈. 입력 즉시 검증한다(최대 3회) |
| anchor는 됐는데 `실패: no_signing_key` | 핀에 서명 공개키가 없다 | `pin --sign-key`로 핀을 다시 만든다 |
| 핀 검사 `fingerprint_mismatch`(회전 후) | 키를 회전했는데 핀을 안 고쳤다 | `pin` → `pin-check`. 핀 세대는 올리기만 된다 |
| `FileNotFoundError`(verify-chain) | 상대경로가 저장소 루트 기준으로 풀렸다 | 저장소 루트 기준 경로를 쓴다 |
| `실패: http_error`(env-set) | 값이 실제로 비었다(`.env`는 셸 변수가 아니다) | `--from-file <파일>`을 쓴다. 빈 값은 `empty_value`로 거부된다 |
| `실패: empty_value` | 환경변수 값이 비었다 | `--from-file` 또는 `--stdin`. 값을 인자로 직접 붙이지 마라 |
| "아카이브 2개"가 이상하다 | IAM 카나리아가 목록에 섞였다 | 목록은 `iam-canary-*`를 제외한다(별도 컬렉션으로 옮겼다) |
| `실패: not_found`(observe/anchor) | 문서가 없는 컬렉션을 404로 반환 | 빈 목록으로 처리하도록 고쳤다. 계속 나면 보고하라 |
| `chain_broken`(anchor) | 체인이 깨져 있어 앵커를 거부했다 | 체인을 먼저 고친다. 깨진 체인을 봉인하지 마라 |
| GUI가 `실패: TypeError` | 노드 목록을 dict로 가정(고침) | 최신 코드로 받아라 |
| 마인드맵 노드 클릭이 안 됨 | 화살표·판정 순서 문제(고침) | 최신 코드로 받아라 |
| 로그 창을 닫으면 로그가 사라짐 | 로그가 창에만 있었다(고침) | 다시 열면 복원된다. 최신 코드로 받아라 |
| `EVIDENCE_SEAL_FAILURES`를 켰는데 변화 없음 | 앱이 안 읽던 죽은 변수였다 | 지금은 앱이 읽는다. 다만 여전히 개념 노드다(§9) |
| 앵커 주기 '수동'인데 자동 앵커 | `anchor_interval='0'`을 루프가 무시(고침) | 수동이면 앵커를 건너뛴다. 최신 코드로 받아라 |
| 노드 기본값이 앱과 다름 | `daily_cap`·`per_uid`·`ttl` 값 불일치 | 코드는 일치시켰다. 단 디스크의 `workflow.json`은 아직 옛 값일 수 있다 |
| `UnicodeDecodeError`(workflow.json) | cp949로 손편집했다 | UTF-8로 저장한다. 코드가 디코드 오류도 잡는다 |
| `UnicodeDecodeError: 'cp949' … byte 0xe2`(list) | firebase CLI 사전 점검이 UTF-8을 못 읽음 | **아직 미수정.** `--json`이면 목록은 나온다(빈 값). 결과 자체는 정상 |
| `verify-chain` 기본 실행이 `실패: not_found` | 기본 `--out`이 저장소 루트 `checkpoints`다 | `--out C:\Users\<이름>\.opsarchive\checkpoints`처럼 명시한다 |
| `--pin "../../security/..."` → `no_pin_file` | 상대경로가 저장소 루트 기준으로 풀렸다 | `--pin security/evidence-key-pin.json`로 쓴다 |

---

## 9. 실행 결과 (실측)

아래 값은 관리자 PC(Windows, Python 3.10)에서 **읽기 전용 명령만** 실제로 돌려 캡처한 결과다.
상태를 바꾸는 명령(`keygen`/`publish`/`anchor`/`env-set`/`gui` 등)은 돌리지 않았다.

**지금 실제로 통과하는 것**

| 항목 | 실측값 |
|---|---|
| `selftest` | `roundtrip true · tamper true · wrong_key true · key_file true · key_file_wrong_phrase true` |
| `pin-check --pin security/evidence-key-pin.json` | `armed true · ok true · reasons [] · pin_fingerprint 8400b0f5…7820 · runtime_fingerprint 8400b0f5…7820` |
| 핀 파일 | `schema 1 · armed true · generation 1 · key_id 8400b0f5ca08f5b1 · signing_key_id fb3022faadaa1478` |
| `env-read --key EVIDENCE_PUBKEY` | `set true · value_length 50` |
| `env-read --key EVIDENCE_GH_REPO` | `set true · value_length 32` |
| `env-read --key EVIDENCE_KEY_GENERATION` | `set false · value_length 0` |
| `/health` `evidence` | `key_id 8400b0f5ca08f5b1 · fingerprint 8400b0f5…7820 · generation 1` |
| `/health` `admin_erase` | `true` |
| `/health` `deploy` | `commit 238ed8aebb790f9b752ff7baa12578a485493ad3 · branch main` |
| `verify-chain --out C:\Users\seong\.opsarchive\checkpoints` | `ok true · chain_ok true · problems [] · archives 0 · entries 0 · missing_now []` |
| `observe --minutes 60` | `verdict ok · observed 0 · attempts 0 · diff 0` |
| `rand --length 16 --show-command` | OS를 감지해 PowerShell/.NET CSPRNG 명령을 자동 채운다(출처 표시) |
| 체크포인트 | `1.json`·`2.json`·`3.json`, 최신 `seq 3 · count 0 · head_seq 0` |

**아직 안 된 것 (정직하게)**

| 항목 | 상태 |
|---|---|
| IAM 삭제 차단 | `iam-check` verdict가 **`app_can_delete`** (`delete_blocked false`, `update_blocked false`) — 목표 미달 |
| 실계정 탈퇴 실패 리허설 | 미실시. `list` 아카이브 0(`[]`) → 라이브에서 봉인이 아직 한 번도 안 일어났다 |
| Render 재배포 최신 여부 | **UNKNOWN**. `EVIDENCE_KEY_GENERATION`이 미설정이라 세대는 앱 기본 1로 보고된다 |
| 자동 스케줄러 | 없음. 앵커·자동 실행은 관리자 PC가 켜져 있을 때만 돈다 |
| GUI `[정책 다시 읽기]` 버튼 | 코드가 없는 이름(`workflow.policy_path`)을 불러 클릭 시 `AttributeError`가 날 수 있다 |
| `list`의 cp949 크래시 | firebase CLI 사전 점검에서 아직 발생한다(위 표 마지막 참고) |
| 디스크 `workflow.json` | `per_uid_seconds 60 · ttl_days 30`으로 **앱 기본값(3600·90)과 아직 다르다** |

정책 노드를 저장하지 않고 곧바로 `[Render에 반영]`하면 노드 기본값이 서버로 밀려 들어간다.
밀어넣기 전에 `[plan 미리보기]`로 의도한 값인지 확인하라.

---

## 10. 절대 하지 말 것

| 하지 말 것 | 왜 |
|---|---|
| 개인키를 백업 없이 지우기 | 잃으면 그 키로 만든 아카이브는 **영영 못 연다**. 복구 수단이 없다 |
| `.env`·서비스 계정 JSON·토큰을 저장소에 커밋 | 시크릿 유출. 저장소에는 `.gitignore`로 막혀 있다 |
| `EVIDENCE_INCLUDE_SECRETS=1` 켜기 | 증거에 살아 있는 자격증명이 들어가 유출 위험이 커진다(기본 꺼짐) |
| 시험용 키를 운영에 발행 | 실제 증거를 아무나 못 여는 상태가 된다 |
| 검증 없이 깨진 체인을 앵커 | `anchor`는 `chain_broken`이면 거부한다. 무시하고 넘기지 마라 |
| `rotate` 뒤 옛 개인키 삭제 | 옛 아카이브의 `key_id`가 그 키를 가리킨다 |
| 패스프레이즈를 명령줄 인자·환경변수로 넘기기 | 프로세스 목록·히스토리에 남는다. 도구는 TTY 입력만 받는다 |
| 핀 파일을 눈대중으로 손편집 | 핀은 관리자가 개인키에서 역산해 만드는 신뢰 뿌리다 |
| `.lock` 파일을 임의로 삭제 | 동시 실행을 막는 잠금 장치다. 지우면 체크포인트가 깨질 수 있다 |
| `.env`를 PowerShell에서 `$env:X`로 읽어 넘기기 | `.env`는 도구가 읽는 파일이다. 셸 변수는 비어 있다. `--from-file`을 써라 |

---

## 11. 더 알고 싶으면

| 문서 | 무엇이 있나 |
|---|---|
| [`docs/ops/EVIDENCE_SEAL.md`](../../docs/ops/EVIDENCE_SEAL.md) | 설계·위협 모델·컨테이너 포맷·런북·남은 위험 |
| [`docs/ops/WORKFLOW_MINDMAP.md`](../../docs/ops/WORKFLOW_MINDMAP.md) | 노드·정책·plan·자동 실행 한계 |
| [`docs/deploy/DEPLOY_RUNBOOK.md`](../../docs/deploy/DEPLOY_RUNBOOK.md) | 배포 절차 |
| [`backend/README.md`](../../backend/README.md) | 앱 쪽 환경변수와 증거 봉인 동작 |

용어 비유(처음 보는 단어): 공개키=우체통, 개인키=관리자만 가진 열쇠, 지문=키를 짧게 요약한 글자,
핀="이 지문이 진짜"라고 못 박은 쪽지, 해시체인=기차 칸처럼 이어 둔 목록,
체크포인트(앵커)=지금 상태를 찍은 서명 사진, TTL=유통기한.

(확인 필요) macOS/Linux에서 GUI가 실제로 열리는지, Windows 11 PowerShell 7의 `&&` 동작,
`publish`·`anchor`의 실제 소요 시간은 이 PC에서 검증하지 않았다.

## 부록: 핀은 어디에 있나 (2026-10-17 변경)

| 무엇 | 위치 | 비고 |
|---|---|---|
| 기대 지문·세대 | **GitHub Actions 변수** EVIDENCE_PIN_* | 저장소 파일이 아니다(admin 만 변경 가능) |
| 로컬 핀 파일 | ~/.opsarchive/evidence-key-pin.json | 기본 경로. 옛 security/ 경로는 자동 이전된다 |
| 올리는 명령 | pin-publish --repo <owner/name> | --dry-run 으로 먼저 확인 |
| 대조 명령 | pin-remote-check --repo <owner/name> | 불일치면 exit 1 |

CI(erify-key-pin)는 변수를 읽어 /health 와 대조하며, **변수 미설정이면 실패**한다(fail-closed).
