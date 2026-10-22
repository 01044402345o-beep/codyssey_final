# Cloud KMS 자동 앵커 — 설정 안내 (2026-10-22)

증거 봉인 체인을 **6시간마다 자동으로** 검증하고 새 체크포인트를 서명해 남깁니다. 지금까지는 관리자가 PC 에서
`anchor` 를 손으로 돌려야 했고, 그 사이 구간은 증명되지 않았습니다(EVIDENCE_SEAL.md §10 '앵커 주기가 곧 사각지대').

| 무엇 | 어떻게 |
|---|---|
| 서명 키 | **Cloud KMS** 의 Ed25519 키(`EC_SIGN_ED25519`). 키는 KMS 밖으로 나오지 않는다. CI 는 서명 '호출'만 한다 |
| CI 인증 | **Workload Identity Federation** — GitHub OIDC 토큰을 15분짜리 GCP 토큰으로 바꾼다. 서비스 계정 키 파일을 GitHub 에 넣지 않는다 |
| 체크포인트 저장 | Firestore `evidence_checkpoints/{seq 8자리}` — **만들기만** 가능(createDocument, 같은 seq 면 409). CI 계정에는 수정·삭제 권한을 주지 않는다 |
| 신뢰 뿌리 | 여전히 **관리자 핀**. KMS 공개키는 관리자가 직접 핀에 넣고(`kms-pin-add`), CI 는 Actions 변수로 받은 핀으로만 검증한다 |
| 실패 알림 | 검증 실패·체크포인트가 13시간보다 오래됨(자동 앵커가 멈춤)·권한 오류 → GitHub 이슈 `[evidence-anchor] 자동 앵커 실패` 하나에 모은다 |
| 켜기 | 저장소 변수 `EVIDENCE_AUTO_ANCHOR=on` 일 때만 돈다. 그 전에는 워크플로가 건너뛴다(빨간 크론 없음) |

검증이 실패하면 **새 체크포인트를 만들지 않습니다** — 문제를 덮는 '정상' 체크포인트를 쌓지 않기 위해서입니다.

---

## 1. 준비 — 결제(필수)

Cloud KMS 는 결제가 연결된 프로젝트에서만 됩니다(Firebase 는 Blaze 요금제). 비용은 작습니다:
소프트웨어 키 버전 1개 월 약 $0.06, 서명 1만 번에 약 $0.03 → 하루 4번 서명이면 월 1센트 미만입니다.
(가격은 [Cloud KMS 가격](https://cloud.google.com/kms/pricing) 에서 확인하세요.)

프로젝트: `com-example-myapplicatio-3bb36` (운영 앱의 Firebase 프로젝트)

## 2. API 켜기

Google Cloud 콘솔 → API 및 서비스 → 라이브러리에서 셋을 켭니다.

- Cloud Key Management Service (KMS) API — `cloudkms.googleapis.com`
- IAM Service Account Credentials API — `iamcredentials.googleapis.com`
- Security Token Service API — `sts.googleapis.com`

## 3. KMS 키 만들기

콘솔 → 보안 → Key Management → **키링 만들기**

| 항목 | 값 |
|---|---|
| 키링 이름 | `opsarchive` |
| 위치 | `asia-northeast3` (서울, Firestore 와 같은 곳) |
| 키 이름 | `checkpoint-signer` |
| 보호 수준 | 소프트웨어 |
| 목적 | **비대칭 서명** |
| 알고리즘 | **Elliptic Curve Ed25519** (`EC_SIGN_ED25519`) — 다른 알고리즘은 도구가 거절한다 |

만든 뒤 키 버전 1 의 **리소스 이름**을 복사합니다:
`projects/com-example-myapplicatio-3bb36/locations/asia-northeast3/keyRings/opsarchive/cryptoKeys/checkpoint-signer/cryptoKeyVersions/1`

## 4. CI 전용 서비스 계정(앱 계정과 따로)

콘솔 → IAM → 서비스 계정 → 만들기: `evidence-anchor` (키는 **만들지 않는다** — WIF 로만 쓴다)

권한(최소):

| 어디에 | 역할 | 왜 |
|---|---|---|
| KMS 키 `checkpoint-signer` (키 화면 → 권한) | Cloud KMS CryptoKey 서명자/검증자 `roles/cloudkms.signerVerifier` | 서명 호출 |
| 같은 키 | Cloud KMS 공개 키 뷰어 `roles/cloudkms.publicKeyViewer` | 공개키 읽기 |
| 프로젝트 | **커스텀 역할** `evidenceAnchor`: `datastore.entities.get`, `datastore.entities.list`, `datastore.entities.create` | 증거·체크포인트 읽기, 체크포인트 **만들기만** |

> 커스텀 역할에 `update`·`delete` 를 넣지 마세요. 그래야 CI 가 침해돼도 과거 체크포인트를 고치거나 지울 수 없습니다.
> 관리자 PC 의 `iam-check` 처럼, 첫 실행 뒤 Firestore 에서 이 계정으로 체크포인트를 지울 수 없는지 확인하면 좋습니다.

## 5. Workload Identity Federation (GitHub → GCP, 키 없이)

콘솔 → IAM → Workload Identity 제휴 → **풀 만들기**

| 항목 | 값 |
|---|---|
| 풀 ID | `github-pool` |
| 공급자 | OpenID Connect(OIDC), ID `github-repo` |
| 발급자(Issuer) URL | `https://token.actions.githubusercontent.com` |
| 대상(Audience) | 기본값(허용된 대상: 기본 대상) |
| 속성 매핑 | `google.subject = assertion.sub`, `attribute.repository = assertion.repository`, `attribute.ref = assertion.ref` |
| **속성 조건** | `assertion.repository == '01044402345o-beep/codyssey_final' && assertion.ref == 'refs/heads/main'` |

속성 조건이 없으면 **다른 GitHub 저장소도** 이 풀로 토큰을 받을 수 있습니다. 반드시 넣으세요.

그다음 서비스 계정 `evidence-anchor` → 권한 → 주 구성원 추가:
`principalSet://iam.googleapis.com/projects/<프로젝트 번호>/locations/global/workloadIdentityPools/github-pool/attribute.repository/01044402345o-beep/codyssey_final`
역할: **워크로드 아이덴티티 사용자** `roles/iam.workloadIdentityUser`

공급자 리소스 이름(다음 단계에 씀): `projects/<프로젝트 번호>/locations/global/workloadIdentityPools/github-pool/providers/github-repo`

## 6. 관리자 PC — 핀에 KMS 키 넣기

1. opsarchive GUI → **설정** 탭 → `KMS 서명 키` 에 3단계의 리소스 이름 → 저장
   (관리자 PC 의 서비스 계정에도 그 키의 `signerVerifier`·`publicKeyViewer` 가 있어야 시험 서명이 됩니다)
2. **검증** 탭 → ⑤ `KMS 점검·핀 추가` — 시험 서명을 하고 공개키를 핀의 **자동 서명 키**로 넣습니다
3. **Render** 탭 → ⑨ `변수로 올리기` — 핀 공개값과 함께 `EVIDENCE_PIN_SIGNING_KEYS` 가 Actions 변수로 올라갑니다

CLI 로는: `python -m opsarchive kms-check --kms-key <이름> --sa <JSON>` → `kms-pin-add --kms-key <이름> --sa <JSON>` → `pin-publish --repo 01044402345o-beep/codyssey_final`

## 7. 저장소 변수(Settings → Secrets and variables → Actions → **Variables**)

| 변수 | 값 |
|---|---|
| `GCP_WIF_PROVIDER` | 5단계 공급자 리소스 이름 |
| `GCP_ANCHOR_SA` | `evidence-anchor@com-example-myapplicatio-3bb36.iam.gserviceaccount.com` |
| `EVIDENCE_KMS_KEY` | 3단계 키 버전 리소스 이름 |
| `EVIDENCE_PIN_SIGNING_KEYS` | 6단계에서 자동으로 올라감 |
| `EVIDENCE_AUTO_ANCHOR` | **마지막에** `on` |

전부 **변수**입니다(비밀 아님 — 공개키·리소스 이름뿐). 비밀(Secrets)은 하나도 필요 없습니다.

## 8. 첫 실행과 확인

1. Actions → `evidence-anchor` → **Run workflow** (수동 실행)
2. 성공하면 Firestore `evidence_checkpoints/00000001` 이 생깁니다
3. 관리자 PC → GUI **검증** 탭 → ⑥ `자동 앵커 검증` — 로컬·자동 체크포인트를 함께 검증하고, 어느 키가 서명했는지(`signed_by: admin / auto`)와 마지막 체크포인트 나이를 보여 줍니다

## 9. 한계(숨기지 않는다)

- **KMS 는 '누가 서명을 요청했는지'를 막지 못합니다.** CI 서비스 계정(또는 main 브랜치 워크플로)이 침해되면 그럴듯한 체크포인트를 서명할 수 있습니다. 그래서 (1) 요청할 수 있는 주체를 좁히고(§4 IAM·§5 저장소 조건·§11 main 보호), (2) 감사 로그로 **누가 서명했는지 드러나게** 합니다(§10). 자동 키는 핀에서 `auto` 로 구분하고 관리자 로컬 키 체크포인트를 상위 근거로 둡니다 — 관리자는 계속 주기적으로 직접 `anchor` 하세요.
- 워크플로 파일 고정(WIF 조건에 `job_workflow_ref`)은 적용하지 않았습니다(2026-10-22 결정). main 에 새 워크플로를 넣는 경로는 §11 의 코드 소유자 승인으로 막습니다.
- 자동 체크포인트는 **만들기만** 되므로 과거 기록을 고치거나 지울 수는 없지만, 프로젝트 소유자 권한이 있는 사람은 여전히 지울 수 있습니다. 관리자 PC 의 로컬 체크포인트 사본이 그 경우의 근거입니다.
- GitHub 은 저장소가 60일 동안 활동이 없으면 예약 워크플로를 끕니다. 그때는 관리자 검증의 `anchor_stale`(13시간 초과)로 드러납니다.
- **봉투(복호화) 키는 KMS 로 옮기지 않았습니다.** KMS 비대칭 복호화는 RSA 만 지원하고 X25519 를 지원하지 않아, 옮기려면 아카이브 형식을 바꿔야 합니다. 복호화 개인키는 지금처럼 관리자 PC 에만 있습니다.
- 이 설정은 코드·테스트(가짜 KMS·Firestore·GitHub)로 검증했고, **실제 KMS·WIF 로는 아직 돌려 보지 않았습니다**(이 저장소 쪽에서 GCP 리소스를 만들 수 없어서). 첫 수동 실행이 그 확인입니다.

## 10. KMS 서명 감사 로그 — 누가 서명했는지 드러내기

KMS 서명은 Cloud 감사 로그의 **데이터 액세스(DATA_READ)** 기록 `AsymmetricSign` 으로 남습니다. **기본으로 꺼져 있습니다.**

1. 콘솔 → IAM 및 관리자 → **감사 로그** → `Cloud Key Management Service (KMS) API` 선택 → **데이터 읽기** 체크 → 저장
   (이 프로젝트의 KMS 데이터 접근이 모두 기록됩니다. 우리 키 하나라 양이 적고, 기본 버킷 보존은 30일입니다)
2. 관리자 PC 서비스 계정에 **비공개 로그 뷰어** `roles/logging.privateLogViewer` 를 줍니다(데이터 액세스 로그는 비공개 로그)
3. GUI **검증** 탭 → ⑦ `KMS 서명 감사 대조` (CLI: `python -m opsarchive kms-audit --project <id> --sa <JSON> --kms-key <이름> --days 7`)

판정:

| 결과 | 뜻 |
|---|---|
| `matched` | 체크포인트와 짝이 맞는 서명(정상) — 누가 했는지 함께 기록 |
| `retry` | seq 경합 재시도로 생긴 추가 서명(같은 주체·같은 시각) — 경고 |
| `admin_probe` | 관리자 계정의 짝 없는 서명(`kms-check` 시험 서명 등) — 경고 |
| **`unexplained`** | **짝 없는 서명(무단 서명 의심)** — CI 계정이라도 체크포인트 없이 서명했으면 여기에 들어갑니다. 어느 계정인지 보여 줍니다 |
| `denied` | 실패한 서명 요청 — **누가 시도했는지** 보여 줍니다 |
| `logs_missing` | 체크포인트는 있는데 서명 기록이 하나도 없음 = 1단계 로그가 꺼져 있음 |

이 대조는 막지는 못하지만, 무단 서명이 있으면 **반드시 드러나게** 합니다. CI 안에서 돌리지 않고 관리자 PC 에서 돌립니다 —
CI 가 침해된 경우 CI 스스로의 감사는 믿을 수 없기 때문입니다. 주 1회 이상 돌리기를 권합니다.

## 11. main 브랜치 보호 + 코드 소유자 승인

`.github/CODEOWNERS` 가 워크플로·스크립트·관리자 도구(`tools/opsarchive/`)의 소유자를 정합니다. 보호 설정을 켜야 효과가 있습니다.
**저장소 admin(소유자 계정 `01044402345o-beep`)만 켤 수 있습니다** — 작성자 계정은 write 권한이라 바꿀 수 없습니다.

웹에서: Settings → Branches → `main` 규칙 추가

- Require a pull request before merging
  - Required approvals: **0** (보호 경로가 아닌 PR 은 지금처럼 승인 없이 머지)
  - **Require review from Code Owners** ✔ — 보호 경로를 바꾸는 PR 은 다른 소유자의 승인이 필요
  - Dismiss stale pull request approvals when new commits are pushed ✔
  - Require approval of the most recent reviewable push ✔
- Do not allow bypassing the above settings ✔ (관리자도 우회하지 않음)
- Allow force pushes ✘, Allow deletions ✘

또는 소유자 계정으로 터미널에서 한 번:

```bash
gh api -X PUT repos/01044402345o-beep/codyssey_final/branches/main/protection --input - <<'JSON'
{
  "required_status_checks": null,
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "required_approving_review_count": 0,
    "require_code_owner_reviews": true,
    "dismiss_stale_reviews": true,
    "require_last_push_approval": true
  },
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}
JSON
```

확인: `gh api repos/01044402345o-beep/codyssey_final/branches/main/protection --jq '.required_pull_request_reviews.require_code_owner_reviews'` → `true`

영향: 보호 경로를 바꾸는 PR 은 **작성자가 아닌 다른 소유자**가 승인해야 머지됩니다(seongbin45 가 낸 PR 은 01044402345o-beep 가, 그 반대도 마찬가지).
main 에 직접 푸시는 막힙니다(지금도 팀 규칙상 PR 로만 반영하므로 바뀌는 흐름은 없습니다).
