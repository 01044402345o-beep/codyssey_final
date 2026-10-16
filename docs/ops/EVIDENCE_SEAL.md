# 탈퇴 실패 증거 봉인(EVIDENCE SEAL) — 설계와 런북

탈퇴가 **완료되지 않았거나 단계가 하나라도 생략/실패**하면, 그 시점의 상태를 **아무도 풀 수 없는 형태로 봉인**해
비공개 저장소에 격리하고, GitHub 이슈로는 **메타데이터만** 통보한다. 관리자만 개인키로 열람할 수 있다.

이 문서는 **구상 + 런북**이다. **지금 구현된 것은 관리자 CLI(`tools/opsarchive/`)뿐이고, 앱 훅(`backend/app/evidence.py`)·원장·사후 검증·`/diagnostics/withdraw`·`/health` 의 지문 노출은 아직 없다** — §3·§4·§7 은 다음 단계의 설계다. 없는 것을 "있다"고 읽게 두지 않는다.

---

## 0. 요구의 재해석 (왜 비밀번호를 없앴는가)

> "관리자와 사용자 모두 알 수 없는 암호로 락"

비밀번호를 **만들면** 그것을 관리자에게 전달할 채널이 생기고, 그 순간 메모리·패킷 노출을 막을 수 없다.
그래서 비밀번호를 만들지 않는다. **데이터키(랜덤 32바이트)를 관리자 공개키로 봉인**하면

- 앱·네트워크에는 **봉인된 키**만 흐른다(공개키만 가진 쪽은 복호화 불가),
- 누구도 평문 데이터키를 "알지" 못한다(존재 시간 = 마이크로초, 즉시 덮어씀),
- 관리자 개인키는 관리자 로컬 밖으로 나가지 않는다.

이 구조를 **봉투 암호화(envelope encryption)** 라 한다. "암호를 안전하게 전달" 문제를 "암호를 전달하지 않음"으로 바꾼다.

## 1. 위협 모델

| 보장 | 근거 | 한계 |
|---|---|---|
| 유휴·전송 중 기밀성 | AES-256-GCM 본문 + X25519 봉인 키. 공개키만 가진 쪽은 열 수 없다 | — |
| 앱 런타임에 복호화 능력 없음 | 개인키는 관리자 로컬 파일에만 | 앱 침해자는 **위조·누락**은 가능(암호화 ≠ 인증) |
| 비밀번호가 네트워크·메모리에 없음 | 비밀번호 대신 봉인된 데이터키. 개인키 패스프레이즈는 **TTY 입력만** | Python 은 `bytes` 를 확실히 0화할 수 없다(스왑·GC 복사). "절대 노출 없음"은 보장 불가 |
| 아카이브 변조 감지 | 헤더 전체를 AAD 로 묶어 GCM 인증 | 헤더를 통째로 갈아끼운 다른 아카이브와의 혼동은 막지 못한다(key_id 로 완화) |

**보장하지 않는 것(정직하게)**
- **발신자 인증·부인방지**: §9 에 정리했다. **앱이 쥔 키**로 서명하면 같은 침해로 노출되므로 위조는 '탐지'까지다. 저장소+CI 를 장악한 공격자는 핀도 바꿀 수 있으므로 신뢰 뿌리는 저장소 밖(관리자 오프라인 키·서명 체크포인트)에 둔다. **누락**은 서명으로 막을 수 없고 앱 밖 증인으로만 가시화된다 — 둘 다 다음 단계다.
- **관리자 PC 침해**: 그 순간 전부 노출된다. 개인키는 오프라인 매체에 백업한다.
- **수집 내용의 PII**: "전부 포함"을 택했으므로 아카이브에는 사용자 데이터가 들어간다. 그래서 (a) 저장소는 비공개, (b) TTL 로 자동 소멸, (c) 자격증명(토큰·서비스 계정 JSON·환경변수 값)은 **기본 스크럽**한다 — 이건 디버깅 취향이 아니라 "한 번 복호화하면 살아 있는 자격증명이 되살아난다"는 별개 문제다. `ARCHIVE_INCLUDE_SECRETS=1` 로 끌 수 있지만 권장하지 않는다.

## 2. 컨테이너 포맷 (`MFA1`)

단일 파일. 자기서술적(self-describing)이라 포맷이 바뀌어도 옛 아카이브를 열 수 있다.

```
offset  size  내용
0       4     magic  b"MFA1"
4       1     alg    1 = X25519 + HKDF-SHA256 + AES-256-GCM (봉투)
5       1     ver    1
6       8     key_id = sha256(공개키 바이트)[:8]   ← 어느 관리자 키로 열어야 하는지
14      2     wrapped_len (BE)
16      N     wrapped_key = [ephemeral_pub(32)] [AES-GCM(kek, data_key) 32+16]
16+N    12    iv
28+N    R     ciphertext = AES-GCM(data_key, iv, aad=헤더)  ← 마지막 16바이트가 tag
```
- `kek = HKDF-SHA256(shared, salt=b"mfa1", info=b"mfa1-kek")`
- 데이터키를 감싸는 nonce 는 저장하지 않고 `HKDF-SHA256(shared, salt=b"mfa1-nonce", info=b"mfa1-wrap")` 12바이트로 유도한다 — 임시 키쌍이 매번 새로 만들어져 KEK 가 메시지마다 다르므로 nonce 재사용이 생기지 않는다(헤더에 12바이트를 더 넣지 않기 위한 선택). **이 유도식은 독립 구현에 필요하므로 형식의 일부다.**
- 봉인 해제는 **평문 상한(기본 32MB)** 을 두고 푼다 — gzip 은 100KB 를 100MB 로 부풀릴 수 있다(실측 ×1027).
- 본문은 `gzip` 후 암호화(압축을 먼저 — 암호화 후 압축은 효과가 없다).
- **AAD = magic|alg|ver|key_id|wrapped_len|wrapped|iv** → 헤더 변조 시 인증 실패.
- 구현 의존성은 `cryptography` 하나(앱·CLI 공통). Argon2 대신 `scrypt` 를 쓴다(표준 라이브러리 범위 유지).

**개인키 파일 포맷** (`MFAK1`, 관리자 로컬 전용)
```
magic "MFAK1" | ver | salt(16) | n(4) r(4) p(4) | nonce(12) | ciphertext+tag
plaintext = X25519 개인키 원시 32바이트
```
scrypt(n=2^15, r=8, p=1) 로 패스프레이즈 유도. 파일 권한 0600.

## 3. 수집 내용 (전부 포함 + 하드 캡)

| 항목 | 내용 |
|---|---|
| 신원 | `archive_id`(uuid), 시각(UTC), 커밋 sha, 트리 dirty 여부, 서비스·배포 정보 |
| 단계 원장 | `tombstone_written`/`revoked`/`doc_deleted`/`user_deleted` 각 단계의 성공 여부·HTTP 상태·시각 |
| 사후 검증 | (a) 흔적 존재 (b) `users/{uid}` 부재 (c) Auth 계정 부재 → 어긋난 항목 |
| 로그 | 프로세스 링 버퍼(최근 N건, 요청 상관 ID 우선) — 기본 256KB 까지 |
| 소스 | `backend/`·`mockup/` 파일 트리(경로·크기·sha256) + 내용 tar — 기본 2MB 까지 |
| 런타임 | 환경변수 **이름** 목록, 파이썬/패키지 버전, 인메모리 상태 요약(`is_erased` 캐시 크기 등) |
| 예외 | 타입·메시지·트레이스백(자격증명 스크럽 후) |

- 모든 섹션은 캡을 넘으면 **잘라내고 `truncated: true`** 를 남긴다(실패를 실패로 만들지 않는다).
- 총량 상한 `ARCHIVE_MAX_BYTES`(기본 1MB, 청크 512KB) — 넘으면 잘라내고 `truncated` 를 남긴다. Firestore 문서 1MiB 제한 때문에 청크로 나눠 담는다.

## 4. 트리거

1. **탈퇴 시퀀스 실패** — `POST /account/erase` 안에서 예외. (원장 포함)
2. **사후 검증 불일치** — 성공 응답 후 `verify_erased` 가 흔적/문서/계정 중 하나라도 어긋나면 "생략"으로 간주.
3. **클라이언트 불일치 보고** — 화면이 403 `account_deleted` 를 받았는데 **강제 갱신이 성공**(계정 생존)하거나, 탈퇴가 예상 밖 상태로 끝나면 `POST /diagnostics/withdraw` 로 보고.

**스로틀(남용 방지)**: uid 당 1시간 1회, **전역 하루 5회**(무료 한도 유지), 아카이브 생성은 **백그라운드**(응답 지연 금지) + 예외는 전부 삼킨다(봉인 실패가 탈퇴 실패를 악화시키면 안 된다).

## 5. 저장·통보

| 대상 | 위치 | 비고 |
|---|---|---|
| 봉인 아카이브 | **Firestore 청크 문서** `evidence_archives/{archive_id}/parts/{n}` (base64, 원본 512KB 단위) | 문서 1MiB 제한 회피. **Blaze·카드 불필요**, 기존 서비스 계정 재사용 |
| 봉인 메타 | `evidence_archives/{archive_id}` (key_id·sha256·commit·크기·청크 수·트리거·만료일) | 암호문이 아니어도 비밀이 아니다(키·본문 없음) |
| 자동 소멸 | 두 컬렉션 그룹에 **TTL 정책**(`expire_at`, 기본 90일) | 탈퇴 실패 데이터를 영구 보관하지 않는다(암호 파기 = 문서 삭제) |
| 통보 | GitHub 이슈 — **메타데이터만** | 이슈 첨부 API 없음. 본문에 id·key_id·sha·원장 요약·경로·sha256·만료일 |

이슈 본문에 넣지 않는 것: 아카이브 본문, 어떤 키, 사용자 콘텐츠, 토큰.

## 6. 관리자 CLI (`tools/opsarchive/`) — 앱과 독립 프로세스

| 명령 | 하는 일 |
|---|---|
| `keygen [--dir]` | X25519 키쌍 생성 → `admin-<key_id>.key`(scrypt+AES-GCM, 소유자 전용 권한). 공개키·지문·권한 적용 여부 출력 |
| `publish --service <name>` | `render services list -o json` 으로 서비스 ID 확인 → **Render REST API** 로 `ARCHIVE_PUBKEY`/`EVIDENCE_PUBKEY` 설정 → `render deploys create --wait` → `render logs` 로 적용 확인 |
| `doctor` | Render 런타임 env 와 `/health` 의 **키 지문**을 로컬 개인키의 공개 절반과 대조("회전 후 복호화 불가" 예방) |
| `rotate` | keygen → publish → 이전 키는 복호화 전용으로 유지 |
| `list --project --sa [--limit]` | Firestore 아카이브 목록(경로·크기·key_id·트리거·만료) — firebase CLI 사전 점검 포함 |
| `decrypt --project --sa --id --key [--out]` | 내려받아 개인키로 열고 요약 출력(임시 디렉터리, `--out` 를 주면 평문 파일도 남긴다) |
| `selftest` | 로컬에서 봉인→해제 왕복 검증(키 없이도 가능) |
| `pin --key --health-url [--out]` | 개인키에서 **역산한** 지문으로 `security/evidence-key-pin.json` 작성(세대는 올리기만 허용) |
| `pin-check [--pin]` | 핀 파일과 배포된 `/health` 의 지문·세대 대조(CI cron 과 같은 검사, 불일치면 exit 1) |
| `iam-check --project --sa` | 앱 자격증명으로 카나리아를 만들어 **삭제·덮어쓰기가 거부되는지** 시험(목표 미달이면 exit 1) |
| `tui` | rich 기반 화면(위 명령을 메뉴로) |

**필수 CLI 사용**: `render` CLI(서비스 조회 `services -o json`·재배포 `deploys create --wait`·로그 `logs`)와 `firebase` CLI(프로젝트 사전 점검 `projects:list`, 규칙 배포 `deploy --only firestore:rules`)를 쓴다.
**단, 환경변수 변경은 Render CLI 로 불가**(`services update` 에 `--env-var` 없음 — 공식 문서 확인)하므로 그 한 단계만 REST API(`RENDER_API_KEY`)를 쓴다.

**누출 방지 규칙(CLI)**
- 패스프레이즈는 **TTY 프롬프트로만** 받는다. argv·환경변수 금지(프로세스 목록·크래시 덤프로 샌다).
- 개인키는 0600, 어떤 로그·출력에도 키·패스프레이즈를 넣지 않는다.
- 비밀은 `bytearray` 로 다루고 사용 즉시 덮어쓴다(최선노력).
- CLI 는 앱 상태를 읽지 않는다(아카이브만 다룬다).

## 7. 앱 훅 (`backend/app/evidence.py`) — **구현됨**

- `EVIDENCE_PUBKEY` 가 없으면 **완전 비활성**(기본 꺼짐). 있으면 수집·봉인·보관·통보가 켜지고, 루트 로거에 링 버퍼가 붙는다.
- 수집(`collect`): 신원(uuid·시각·커밋·서비스), 단계 원장, 사후 검증 결과, 예외(타입·메시지·트레이스백), 최근 로그(링 버퍼), **소스 트리**(경로·크기 + 내용), 런타임(환경변수 **이름**만·파이썬 버전), `uid`는 솔트 없는 해시 16자.
- 캡: 총 1MB / 소스 512KB / 로그 64KB — 넘으면 잘라내고 `truncated` 에 표시한다. **자격증명은 기본 스크럽**(`[MASKED]`), `EVIDENCE_INCLUDE_SECRETS=1` 로 해제.
- 저장(`store`): MFA1 봉인문을 512KB 청크로 `evidence_archives/{id}` + `.../parts/{n}` 에 쓴다(관리자 권한, 규칙 우회). 모든 문서에 `expire_at`(기본 90일) → TTL 자동 삭제 = 암호 파기.
- 통보(`notify`): GitHub 이슈에 **메타데이터만**(id·trigger·key_id·commit·sha256·크기·원장·검증·경로). 토큰/리포가 없으면 건너뛴다. 실패해도 보관은 되돌리지 않는다.
- 스로틀: uid 당 1시간 1회, 전역 하루 5회(프로세스 단위 — 다중 인스턴스면 느슨해진다). **어떤 실패도 예외를 밖으로 내보내지 않는다.**
- 배선: `POST /account/erase` 가 단계 원장을 넘기고, 실패하면 `erase_failed`, 성공해도 `verify_erased` 가 불일치면 `verify_mismatch` 로 백그라운드 봉인. 화면 보고는 `POST /diagnostics/withdraw`(인증·레이트리밋).
- `/health` 에 `evidence: {key_id, fingerprint, generation}` 노출 — 핀 검증이 보는 값이다.
- 스코프: 기존 `datastore` 로 충분하다(Storage 를 쓰지 않는다). 저장은 REST 직접 호출이라 새 무거운 의존성이 없다(`cryptography` 는 requirements 에 고정).

환경변수: `EVIDENCE_PUBKEY`, `EVIDENCE_KEY_GENERATION`, `EVIDENCE_GH_TOKEN`, `EVIDENCE_GH_REPO`,
`EVIDENCE_MAX_BYTES`, `EVIDENCE_MAX_SOURCE_BYTES`, `EVIDENCE_MAX_LOGS_BYTES`,
`EVIDENCE_PER_UID_SECONDS`, `EVIDENCE_DAILY_CAP`, `EVIDENCE_TTL_DAYS`, `EVIDENCE_INCLUDE_SECRETS`.

- `EVIDENCE_PUBKEY` 가 없으면 **완전 비활성**(기본 꺼짐). 있으면 봉인·업로드가 켜진다.
- 저장은 기존 스타일대로 **REST 직접 호출**(Firestore 문서 쓰기) — 새 무거운 의존성을 넣지 않는다. 서비스 계정에 `roles/datastore.user`(이미 있음)만 필요하다.
- Google 스코프는 기존 `datastore` 로 충분하다(Storage 를 쓰지 않는다).
- 실패 경로는 전부 삼키고 로컬 로그만 남긴다(봉인이 탈퇴 실패를 악화시키면 안 된다).

## 8. 런북 — 최초 1회

```
1. (Blaze 불필요) Firestore `evidence_archives` 와 `evidence_archives/*/parts` 에 `expire_at` TTL 정책(90일)을 건다.
2. tools/opsarchive: python -m opsarchive keygen          # 관리자 개인키(오프라인 백업)
3. tools/opsarchive: python -m opsarchive publish --service codyssey-final --key ~/.opsarchive/admin-<id>.key --base-url https://codyssey-final.onrender.com
4. tools/opsarchive: python -m opsarchive doctor --service codyssey-final --key ~/.opsarchive/admin-<id>.key --base-url https://codyssey-final.onrender.com
5. 이슈 라벨 'evidence-seal' 생성 + 전역 상한(5/일)·uid 상한(1/시간) 값 확정.
6. **IAM(§9)**: 아카이브 전용 SA + 커스텀 롤(create/get/list) → 앱 훅이 그 자격증명으로 쓰게 한다.
   검증: `python -m opsarchive iam-check --project <id> --sa <앱 SA.json>` 판정이 `ok`.
7. **핀(§9)**: `python -m opsarchive pin --key <파일> --health-url <url>` → `security/evidence-key-pin.json` 커밋 → `pin-check` 통과 확인 → main 보호 규칙에 `verify-key-pin` 을 필수 검사로 등록.
   검증: 핀을 일부러 틀리게 두면 크론이 실패; `armed: true` 로 바꾼 뒤 회전하면 `generation` 을 올려 커밋하지 않은 상태에서 실패해야 한다.
8. (앱 훅 배포 뒤) 실패 리허설: 탈퇴를 일부러 실패시켜 아카이브 생성 → decrypt 로 열어 확인
```

## 9. 발신자 인증 — 위조 탐지와 삭제 예방 (연구 결과 반영)

깊은 조사 결과(보고서: [`reports/증거 봉인 발신자 인증.md`](../../reports/증거%20봉인%20발신자%20인증.md), 조사 노트 5개)를 이 시스템에 맞춘 두 겹을 먼저 깐다.

### 두 실패는 다르다
| 실패 | 성질 | 이 스택에서 |
|---|---|---|
| **위조**(가짜 아카이브) | 저장소만 아는 공격자면 **탐지** 가능(서명·해시체인) | 앱을 완전히 장악하면 **불가**(TEE 없이는 원리적으로 구분 불가) |
| **누락**(아카이브 없음) | 서명으로는 **불가**. 앱 밖 증인/사전 커밋먼트로만 **탐지** | 클라이언트 영수증·앵커 로그·heartbeat 로 가시화 |

**정직한 천장**: 이 스택에서 말할 수 있는 상한은 *"핀 고정된 키가 서명한 이후 이 암호문은 변하지 않았고, 앵커된 로그가 아는 아카이브는 무결하며 그 밖의 것은 플래그된다"* 까지다. "이건 진짜 우리 코드가 만들었다"와 "누락이 없다"는 TEE/독립 증인 없이는 주장할 수 없다.

### (e) IAM — 앱이 증거를 **지우지 못하게** 한다 (먼저, $0)
목표 상태: 증거 아카이브를 쓰는 주체는 **생성·읽기만** 가능하고 **삭제·덮어쓰기는 불가**.
- 권장 방법: **아카이브 전용 서비스 계정 + 커스텀 롤**(`datastore.entities.create/get/list` 만). 앱의 기존 SA(Auth+Firestore 공용)와 분리한다 → 앱 훅은 아카이브 쓰기에 이 별도 자격증명을 쓴다.
- 대안: IAM **Deny 정책**으로 앱 SA 의 `datastore.entities.delete/update` 를 막는다. 조건 표현식이 컬렉션 경로까지 좁힐 수 있는지는 **UNKNOWN(확인 필요)** — 되면 더 정밀하다.
- **검증은 선언이 아니라 행동으로**: `python -m opsarchive iam-check --project <id> --sa <앱 SA.json>` 가 카나리아 문서를 만들어 (a) 생성 성공 (b) 삭제 거부 (c) 덮어쓰기 거부를 실제로 시험한다. 판정이 `ok` 가 아니면 목표 미달이다.
- 지금 이게 **가장 잘못된 모양**인 이유: 앱이 쥔 자격증명 하나로 증거를 지울 수 있으면, 침해 시 "증거만 골라 지우기"가 가능하다.

### (a) 핀 고정 — 예상 밖 키를 조기에 잡는다 ($0)
- `security/evidence-key-pin.json`: `armed`·`generation`·`key_id`·`fingerprint_sha256`·`public_key`·`health_url`·`rotated_by_commit`.
  **앱이 알려준 값을 넣지 않는다** — 관리자가 개인키에서 역산해 `python -m opsarchive pin --key <파일> --health-url <url>` 로 만든다(오프라인).
- 회전과 대입을 구분한다: 회전이면 `generation` 을 **올려서** 커밋한다. 파일이 세대를 **낮추는 것을 거부**한다(`PinError: generation_regression`).
- CI `.github/workflows/verify-key-pin.yml`(cron 6시간): 핀 파일과 `/health` 의 `evidence.fingerprint`·`generation` 을 대조한다. 서드파티 액션을 쓰지 않고 `curl`+표준 라이브러리만 쓴다(액션 SHA 고정 대상 자체를 없앤다).
  - `armed: false` 동안은 **경고만** 하고 통과(레드 크론 소음 방지), `armed: true` 부터는 불일치·미보고·연결 실패가 **실패**다.
- 지금은 `armed: false` 다 — 앱은 이미 `/health` 에 `evidence` 를 노출하므로, 관리자가 키를 만들고 `pin` 으로 채우면 활성화된다(§8 7단계).

### 아직 안 넣은 겹(다음 단계)
- **(b) 매니페스트 서명 + (d) 해시체인·앱 밖 앵커**: 관리자 오프라인 Ed25519 키로 `{count, head, prev_head}` 체크포인트를 서명하고 저장소 밖(로컬·서명 태그·투명성 로그)에 앵커. 누락 대조는 `verify` 가 한다.
- **(f) 클라이언트 서명 영수증**: 탈퇴 응답에 JWS 영수증을 주고 화면이 "영수증 없으면 상태 불명"을 보이게 한다(nonce 로 재사용 방지, uid 는 솔트 해시만).
- **(g) 감시·canary**: heartbeat, 쿼터 알림, canary 계정 주기 삭제.
- **(c) Cloud KMS**: 카드/Blaze 수용 시에만. **키 비유출**을 더하지만 **app-control 위조는 여전히 못 막는다**.

### 이 두 겹의 한계 (같은 문서에 남긴다)
- 핀 파일은 **저장소+CI를 함께 장악한 공격자가 바꿀 수 있다** → 신뢰 뿌리를 저장소 밖으로 옮기는 것이 (d)의 목적이다.
- `iam-check` 는 **권한만** 본다. 앱이 다른 자격증명으로 우회하거나 Firestore 대신 다른 곳에 쓰면 탐지되지 않는다.
- 두 겹 모두 **누락을 막지 못한다**(가시화도 아직 없다 — 영수증·앵커가 들어와야 한다).


## 10. (b) 매니페스트 서명 + (d) 해시체인·앱 밖 앵커 — **구현됨**

무엇을 하는가: 앱이 봉인한 아카이브를 **순서대로 사슬로 묶고**, 관리자가 **앱 밖에서** 주기적으로
체크포인트(개수·머리·집합 해시)에 서명해 두면, 나중에 아카이브가 **사라지거나 개수가 줄어도** 검증에서 드러난다.

- **앱(체인 만들기)**: 매니페스트 `SEAL-SIG-v1` 을 아카이브 메타 문서에 넣는다 —
  `ciphertext_sha256`(봉인문 해시)·`size`·`chunks`·`recipient_key_id`·`trigger`, 그리고 `seq`/`prev_digest`/`digest`.
  `digest = sha256("EVIDENCE-SEAL/v1/manifest" ‖ canonical_json(prev_digest 포함 매니페스트))` 라서 순서가 사슬로 묶인다.
  머리 문서 `evidence_chain/head`={seq,digest} 를 마지막에 옮긴다(머리 이동이 실패해도 아카이브는 남고, 다음 아카이브가 **갈래**가 되어 검증이 보고한다 — 조용히 덮지 않는다).
- **CLI(앱 밖 앵커)**: `signkey` 로 관리자 **Ed25519 서명 키**를 만든다(봉투 X25519 키와 용도 분리).
  `anchor` 는 저장소의 매니페스트를 읽어 체인을 확인하고 `{schema, seq, count, head_digest, archive_ids_sha256, created_at}` 에 서명해
  `checkpoints/<seq>.json` 으로 남기며, 개별 대조용 `checkpoints/anchors/<seq>.json`(아이디 목록)도 함께 쓴다(아이디는 무작위 hex — 개인정보 없음).
  `verify-chain` 은 ① 각 서명·본문 정합 ② `seq` 연속성·`count` **롤백 탐지** ③ 체인 연속성·**갈래 보고**
  ④ 앵커 이후 구간(`unanchored`) ⑤ 앵커 목록과 지금 저장소의 차집합 → **사라진 아카이브(`missing_now`)** 를 보고한다.
- 핀 파일에 서명 키의 공개키·지문을 넣는다(`pin --sign-key`). 검증은 그 핀을 신뢰 뿌리로 쓴다.

### 한계 (같은 문서에 남긴다)
- **사전 커밋먼트가 없다**: 앱을 장악한 공격자가 처음부터 체인을 만들지 않으면 탐지되지 않는다. 체크포인트는 "관리자가 본 시점 이후"만 되돌릴 수 없게 한다.
- **앵커 주기가 곧 사각지대**다. 관리자가 자주 서명하지 않으면 그 사이 구간은 증명되지 않는다.
- 체크포인트 파일은 **저장소 안**에 둘 수 있으나, 저장소와 CI 를 함께 장악한 공격자는 그것도 다시 쓴다 → 신뢰 뿌리는 **관리자 로컬 서명 키**다(저장소 체크포인트는 편의·감사용).
- 아직 **자동 앵커(cron 워크플로)와 heartbeat 는 없다** — 지금은 관리자가 `anchor`/`verify-chain` 을 직접 돌린다.
- 앵커는 서명 검증에 **읽기 권한**(서비스 계정)이 필요하다. CI 에서 돌리려면 앱과 **다른 읽기 전용 자격증명**을 써야 한다(앱 SA 재사용 금지).



## 11. 남은 위험 / 미검증 (라운드 6 교차검증 + 발신자 인증 조사 + (b)(d) 구현 뒤 갱신)

- **실제 탈퇴 실패 왕복은 아직 관측하지 않았다**(§7 은 구현됐지만 실계정·실배포에서 돌려보지 않았다).
- **발신자 인증 없음**(§1). 지문 핀 고정으로 "예상 밖 키"만 잡는다.
- **Python 메모리 0화 불가** — 언어 한계. 경계는 "앱에 복호화 가능한 것 없음"이다.
- **아카이브가 곧 미삭제 개인정보의 사본**이다 — TTL·암호 파기로 수명을 제한한다.
- **Windows 파일 권한**: `os.open(0o600)` 은 Windows 에서 ACL 을 바꾸지 않는다(실측 0o666) → `icacls` 로 상속을 끊고 소유자만 남긴다. 실패하면 결과에 `permissions: inherited_warning` 이 찍힌다(조용히 넘어가지 않는다).
- **플랫폼 제약 3가지의 출처**: Render CLI 의 env 변경 불가·GitHub 이슈 첨부 API 부재·Firebase Storage 의 Blaze 요구는 **공식 문서로 확인**했으나 **저장소 안에는 근거 문서가 없다**(이 문서가 유일한 기록이다).
- **압축 폭탄·KDF 파라미터**: 컨테이너 수준 상한(평문 32MB)과 scrypt 파라미터 검사(2¹⁴≤n≤2²⁰)를 넣었지만, 이는 CLI 가 여는 **신뢰할 수 없는 파일**을 전제로 한 방어다. 서비스 계정이 탈취되면 그 전에 다른 경로로 피해가 난다.
