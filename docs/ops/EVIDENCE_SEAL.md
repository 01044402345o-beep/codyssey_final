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
- **발신자 인증·부인방지**: 앱은 서명할 수 없다(서명키를 두면 같은 침해로 노출). 공개키 **지문을 저장소·CI에 핀 고정**하고 `/health`에 지문만 노출해 "예상 밖 키"를 조기에 발견한다.
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
| `tui` | rich 기반 화면(위 명령을 메뉴로) |

**필수 CLI 사용**: `render` CLI(서비스 조회 `services -o json`·재배포 `deploys create --wait`·로그 `logs`)와 `firebase` CLI(프로젝트 사전 점검 `projects:list`, 규칙 배포 `deploy --only firestore:rules`)를 쓴다.
**단, 환경변수 변경은 Render CLI 로 불가**(`services update` 에 `--env-var` 없음 — 공식 문서 확인)하므로 그 한 단계만 REST API(`RENDER_API_KEY`)를 쓴다.

**누출 방지 규칙(CLI)**
- 패스프레이즈는 **TTY 프롬프트로만** 받는다. argv·환경변수 금지(프로세스 목록·크래시 덤프로 샌다).
- 개인키는 0600, 어떤 로그·출력에도 키·패스프레이즈를 넣지 않는다.
- 비밀은 `bytearray` 로 다루고 사용 즉시 덮어쓴다(최선노력).
- CLI 는 앱 상태를 읽지 않는다(아카이브만 다룬다).

## 7. 앱 훅 (`backend/app/evidence.py`) — **다음 단계(아직 없음)**

아래는 설계이며, 이 파일과 배선(원장·사후 검증·`POST /diagnostics/withdraw`·`/health` 의 `evidence` 지문)은
다음 PR 에서 만든다. 그 전까지 `publish`/`doctor` 의 `/health` 지문 대조는 `health_has_evidence: false` 로 보고된다.

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
6. (앱 훅 배포 뒤) 실패 리허설: 탈퇴를 일부러 실패시켜 아카이브 생성 → decrypt 로 열어 확인
```

## 9. 남은 위험 / 미검증 (라운드 6 교차검증 뒤 갱신)

- **앱 훅이 아직 없다**(§7). 그래서 지금은 "탈퇴 실패 → 봉인 → 이슈"가 실제로 돌지 않는다. 실계정 왕복도 미관측이다.
- **발신자 인증 없음**(§1). 지문 핀 고정으로 "예상 밖 키"만 잡는다.
- **Python 메모리 0화 불가** — 언어 한계. 경계는 "앱에 복호화 가능한 것 없음"이다.
- **아카이브가 곧 미삭제 개인정보의 사본**이다 — TTL·암호 파기로 수명을 제한한다.
- **Windows 파일 권한**: `os.open(0o600)` 은 Windows 에서 ACL 을 바꾸지 않는다(실측 0o666) → `icacls` 로 상속을 끊고 소유자만 남긴다. 실패하면 결과에 `permissions: inherited_warning` 이 찍힌다(조용히 넘어가지 않는다).
- **플랫폼 제약 3가지의 출처**: Render CLI 의 env 변경 불가·GitHub 이슈 첨부 API 부재·Firebase Storage 의 Blaze 요구는 **공식 문서로 확인**했으나 **저장소 안에는 근거 문서가 없다**(이 문서가 유일한 기록이다).
- **압축 폭탄·KDF 파라미터**: 컨테이너 수준 상한(평문 32MB)과 scrypt 파라미터 검사(2¹⁴≤n≤2²⁰)를 넣었지만, 이는 CLI 가 여는 **신뢰할 수 없는 파일**을 전제로 한 방어다. 서비스 계정이 탈취되면 그 전에 다른 경로로 피해가 난다.
