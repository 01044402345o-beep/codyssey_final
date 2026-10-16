# 키 핀 고정과 CI 검증 (Key Pinning, CI-Enforced Verification, Build-to-Artifact Binding)

*스코프: 단일 저장소(공개 포크 → org 저장소 PR 머지), Render 자동배포(default 브랜치), Firebase Spark(Firestore/Auth), 증거 아카이브는 관리자 X25519 공개키(Render 환경변수)로 암호화, 관리자 개인키는 로컬 CLI. 목표: **공개키 대입(substitution)과 실행 중 빌드 대입을 탐지 가능**하게 만드는 것 — Git·GitHub Actions·무료 도구만으로. 모든 문서 인용은 2026-10-17 열람 기준.*

## Q1. 핀 고정 메커니즘: 어디에 무엇을 두고, 어떻게 크게 실패시키며, 대입과 정당한 회전을 구분하는가

### Takeaway
핀은 **저장소 파일**(예: `security/evidence-key-pin.json`)에 두고 CODEOWNERS + 브랜치 보호 + **필수 상태 검사(required status check)** 로 고정한다. CI는 배포된 앱의 `/health` 지문을 그 파일과 비교해 **불일치면 exit 1로 크게 실패**시킨다. "대입 vs 정당한 회전"의 구분은 **세대(generation) 카운터**로 한다 — 대입은 같은 세대에서 지문이 바뀐 것(경보), 회전은 서명된 커밋/PR로 세대가 오른 것(정보). 핀 자체의 불변 기록은 **서명 태그 + 외부 투명성 로그(Rekor)** 로 앵커링한다(둘 다 무료). 핵심 원리: **변조 가능한 저장소 안의 핀은 같은 저장소 안의 CI로 증명할 수 없다** — 신뢰 루트는 공격자가 못 쓰는 곳(로컬 CLI, 서명 태그, 투명성 로그)에 있어야 한다.

### Cited Findings
- TUF는 키 관리의 일부로 "생성·안전한 보관/백업·로테이션"을 명시적 결정 사항으로 둔다; Root 역할이 신뢰 공개키를 관리하고 키 추가/제거를 담당하며, Root 키 임계값이 깨지면 Root 파일을 **out-of-band로 재배포**해야 한다 — [TUF FAQ](https://theupdateframework.io/docs/faq/)
- TUF 명세: "역할에 대한 새 키 신뢰는 쉬워야 한다. Root 키 임계값 미만이 침해되면 침해된 키에 대한 신뢰를 폐기해야 한다" — 회전과 폐기를 정상 운영으로 취급 — [TUF spec](https://github.com/theupdateframework/specification/blob/master/tuf-spec.md)
- TUF는 "일반적으로 키를 공유하지 말 것", Timestamp/Snapshot만 온라인 키 허용, 나머지는 오프라인 키; 메타데이터 만료(Timestamp/Snapshot ~1일, Root/Targets ~1년)를 권고 — [TUF FAQ](https://theupdateframework.io/docs/faq/)
- TOFU는 "첫 사용 시 신뢰를 확립"하는 인증 방식으로, 첫 관찰값이 오염되면 이후 전부를 오염시킨다 — [Wikipedia: Trust on first use](https://en.wikipedia.org/wiki/Trust_on_first_use)
- GitHub 커밋 서명 검증은 **영속 기록**을 남긴다: 한 번 검증되면 편집 불가, 서명 키가 이후 회전·폐기·만료돼도 검증 상태가 유지되며, REST API `verified_at` 필드로 확인 가능, 저장소 네트워크(포크 포함)로 스코프됨 — [GitHub: About commit signature verification](https://docs.github.com/en/authentication/managing-commit-signature-verification/about-commit-signature-verification)
- 같은 문서: **Rebase and Merge** 는 head 브랜치 커밋의 서명 검증 없이 베이스에 올린다(서명 강제의 우회로) — [동일](https://docs.github.com/en/authentication/managing-commit-signature-verification/about-commit-signature-verification)
- gitsign은 Sigstore **keyless** 커밋/태그 서명을 제공하고, 서명을 Rekor 투명성 로그에 기록한다(단, GitHub는 gitsign 서명을 "Verified"로 표시하지 않음; 서명 검증은 `gitsign verify`가 권장됨) — [sigstore/gitsign README](https://github.com/sigstore/gitsign)
- 브랜치 보호 규칙은 **기본적으로 저장소 admin에게 적용되지 않는다**(admin 또는 "bypass branch protections" 커스텀 역할이 우회 가능) — [GitHub: About protected branches](https://docs.github.com/repositories/configuring-branches-and-merges-in-your-repository/defining-the-mergeability-of-pull-requests/about-protected-branches); [GitHub Changelog 2022-08-18](https://github.blog/changelog/2022-08-18-bypass-branch-protections-with-a-new-permission/)

### Inferences
- **핀 파일의 권장 스키마**: `{ key_id, fingerprint_sha256, public_key_b64, generation, not_before, rotated_by_commit, health_url }`. 공개키는 비밀이 아니므로 **파일에 공개키를 커밋**해 두고 지문을 그 파일에서 로컬 재계산할 수 있게 한다(출처가 앱이 아닌 저장소가 됨 — 순환 제거).
- **대입/회전 판별 규칙(알림 피로 방지)**:
  - 앱 보고 세대 == 핀 세대, 지문 불일치 → **HARD FAIL + 경보**(대입).
  - 앱 보고 세대 > 핀 세대 → **INFO**(회전 진행 중; 핀을 올리는 PR이 필요) — 자동으로 조용히 통과시키지 말 것.
  - 앱 보고 세대 < 핀 세대 → **HARD FAIL**(롤백/다운그레이드 공격).
  - 핀 파일 diff가 있는데 서명 커밋/서명 태그가 없거나 CODEOWNERS 리뷰가 없음 → **HARD FAIL**.
- **불변 기록 3중**: (1) 회전마다 **서명 태그**(예: `evidence-key-v2`) 생성 → GitHub 서명 검증 영속 기록이 키 회전 후에도 남음; (2) 핀 파일 지문의 sha256을 **Rekor**에 기록(gitsign 또는 cosign) → 저장소 히스토리 재작성 탐지; (3) 핀 파일 자체를 CODEOWNERS 소유로 지정. 세 겹이 곧 "신뢰 루트를 저장소 밖으로 앵커링"하는 최소 무료 구현.
- TOFU 함정: **최초 핀을 앱이 보고한 값으로 만들면** 대입된 키가 영원히 신뢰된다. 최초 핀은 **관리자가 로컬 개인키로부터 공개키를 역산해 직접 생성**하고(앱 보고값이 아님) 관리자 서명으로 커밋해야 한다.
- 저장소 파일 + 같은 저장소 CI만으로는 **자가 검증의 순환**이 남는다(공격자가 PR로 핀과 CI를 같이 바꾸면 초록). 따라서 진짜 방어선은 (a) CODEOWNERS+보호+서명 강제, (b) 관리자 로컬 CLI가 핀을 **독립 검증**하는 것.

### Gaps
- GitHub "필수 상태 검사"가 **포크 PR**에서 실행되는 워크플로에도 강제되는지, 그리고 required check 우회(admin force-push) 시 감사 흔적의 정확한 형태는 이번에 1차 문서로 확정하지 못함 → UNKNOWN(브랜치 보호 admin 예외는 확인됨).
- CODEOWNERS 강제는 브랜치 보호의 "Require review from Code Owners"와 결합할 때만 효력이 있음(개별 문서 확인은 못 함) → 표준 GitHub 문서(`about-code-owners`)로 확인 필요.

## Q2. PaaS(Render)에서의 빌드 출처: 실행 중 커밋을 증명할 수 있는가

### Takeaway
Render는 **배포 객체에 커밋을 노출**하고 zero-downtime 배포 시 "현재 배포 커밋"을 갱신하므로 커밋 수준 추적은 가능하다. 그러나 이것은 **Render의 진술**이지 서명된 출처 증명이 아니며, `/health`의 커밋 값이 진짜 그 빌드에 박힌 값이려면 빌드 시 커밋을 심어야 한다. **"배포 커밋 == 리뷰된 커밋"은 중간 강도**다: 커밋 바인딩은 되지만 **키 대입(환경변수)은 커밋을 바꾸지 않으므로 커밋 바인딩만으로는 못 막는다**. 그래서 핀(Q1)과 `/health` 키 지문을 커밋 바인딩과 **함께** 봐야 한다.

### Cited Findings
- Render 자동배포: `On Commit`(기본) / `After CI Checks Pass` / `Off`; "After CI Checks Pass"는 체크 결론이 `success`/`neutral`/`skipped`면 통과로 간주하되, **체크가 0개 감지되면 배포하지 않음**, 하나라도 실패면 배포 안 함 — [Render: Deploying on Render](https://render.com/docs/deploys)
- zero-downtime 배포 3단계: 새 인스턴스가 정상 기동하면 **Render가 현재 배포 커밋을 갱신**한다 — [동일](https://render.com/docs/deploys)
- **"Restart service"** 는 특수한 수동 배포로, **현재 실행 중 인스턴스와 정확히 같은 Git 커밋·설정**을 쓴다 → 최근 환경변수를 바꿨지만 재배포하지 않았다면 **재시작은 그 변경을 반영하지 않는다** — [동일](https://render.com/docs/deploys)
- 특정 커밋 배포: 대시보드/배포 훅으로 하면 **자동배포가 꺼지고**, CLI/API로 하면 자동배포는 안 꺼진다; 배포 훅은 `ref=<sha>`로 특정 커밋 배포 지원 — [동일](https://render.com/docs/deploys)
- 배포 훅 URL은 **시크릿**이며, URL을 아는 누구나 배포를 트리거할 수 있다; 유출 시 "Regenerate Hook"으로 교체; 잘못된 `key`면 401, 링크된 저장소에 없는 커밋이면 404 — [Render: Deploy Hooks](https://render.com/docs/deploy-hooks)
- Render CLI `deploys create --commit [SHA]` 로 특정 커밋 배포 가능 — [Render CLI 문서](https://render.com/docs/cli)
- 이 프로젝트 라이브 관측(프로젝트 메모리): Render 배포 객체의 `deploy.commit` 값이 실제로 존재·조회됨(예: 머지 전 `96261bb`).

### Inferences
- **무엇이 깨는가(실패 모드별)**:
  - *런타임 환경변수 변경*: 커밋은 그대로인데 `EVIDENCE_ADMIN_PUBKEY`만 바뀔 수 있다(대시보드/API/`Save and deploy`). 커밋 바인딩은 초록인데 키가 대입됨 → **커밋 바인딩은 키 대입에 무력**; `/health` 키 지문 핀(Q1)이 필수.
  - *정당한 시크릿 회전*: 환경변수 변경 자체는 정상 운영 → 세대 카운터로 구분하지 않으면 경보 피로.
  - *공격자의 배포 훅 호출*: 훅 URL을 알면 `ref`로 **링크된 저장소에 존재하는 임의 커밋**을 배포할 수 있다(없는 커밋은 404). 즉 공격자는 먼저 악성 커밋을 저장소 어딘가(비-default 브랜치 포함)에 넣어야 한다 → **default 브랜치 보호 + Render가 default 브랜치만 자동배포**하도록 하는 것이 완화책.
  - *"Save and deploy" 재시작*: 재빌드가 아니므로 빌드에 박힌 커밋은 유지되지만 **환경변수 변경은 실효되지 않음** → "회전했다고 생각했는데 안 됐다"는 운영 혼동.
- **강도 평가**: `/health`에 (a) 빌드 시 심은 커밋 SHA, (b) 키 지문, (c) 키 세대를 함께 보고하면, 커밋 바인딩 + 키 바인딩을 동시에 얻는다. 하지만 그 값을 **앱이 스스로 말하는 것**이므로, Render가 서명한 출처(provenance)를 주지 않는 한 "증명"이 아니라 "진술"이다 → **중간 강도**.
- 실무 구현: 빌드 시 커밋 SHA를 코드/아티팩트에 심고 `/health`로 노출한다. 이 프로젝트 메모리에 따르면 라운드 6에서 `/health`가 `evidence.key_id`/`fingerprint`를 보고하도록 수정하는 작업이 계획되어 있다.

### Gaps
- Render가 **서명된 빌드 출처(provenance)** 나 OIDC 기반 배포 자격증명을 제공하는지: 이번 조사에서 1차 문서를 찾지 못함 → **UNKNOWN(없을 가능성 높음)**. 현실적으론 정적 API 키/배포 훅 시크릿에 의존.
- 앱이 자기 커밋을 `/health`로 보고하기 위한 **Render 환경변수 이름**(예: 커밋 SHA를 주입하는 변수)의 정확한 목록 → 이번에 1차 문서 미확인 → UNKNOWN(배포 객체 `commit`은 확인됨).
- Render 무료 티어에서 배포 이력/커밋 메타데이터의 보존 기간 → UNKNOWN.

## Q3. GitHub 네이티브 무결성 프리미티브: 각각 무엇을 증명하고, 비용은, PaaS 배포에 적용되는가

### Takeaway
소스(커밋/태그) 무결성은 **무료로 강하게** 얻을 수 있다(서명 커밋, 보호 브랜치, 리뷰, CODEOWNERS, 공개 저장소 한정 환경 필수 리뷰어). 반면 **아티팩트 출처(attestation)/SLSA/OIDC는 무료지만 "내가 만든 빌드 산출물"을 대상**으로 하며, **Render가 대신 빌드하는 PaaS 배포에는 직접 적용되지 않는다**. PaaS에서는 "핀 번들/릴리스 태그" 같은 대상에만 attestation을 붙일 수 있고, 실행 중 서비스를 Render가 attest해 주지는 않는다.

### Cited Findings
- **artifact attestations**: GitHub Actions로 서명된 출처 증명 생성; 공개 저장소는 **Sigstore Public Good Instance**를 쓰고 생성된 번들은 GitHub에 저장되며 **인터넷에서 공개 열람 가능한 불변 투명성 로그**에 기록됨; **비공개 저장소는 GitHub 자체 Sigstore 인스턴스**(투명성 로그 없음, Actions와만 연동); attestation은 서명·검증되어야 효력 발생; `gh attestation verify`로 검증 — [GitHub: Artifact attestations](https://docs.github.com/en/actions/concepts/security/artifact-attestations)
- attestation 단독 사용은 **SLSA v1.0 Build Level 2**; 재사용 워크플로(reusable workflow)로 격리를 얻으면 **Level 3** — [GitHub: Artifact attestations](https://docs.github.com/en/actions/concepts/security/artifact-attestations)
- SLSA 레벨: L0 없음 · L1 출처 존재(위조 쉬움) · L2 호스티드 빌드 플랫폼 + 서명된 출처(빌드 *후* 변조 방지) · L3 강화 빌드(빌드 *중* 변조 방지, **사용자 빌드 스텝이 서명용 시크릿에 접근 못 하게 격리**) — [SLSA v1.0 Security levels](https://slsa.dev/spec/v1.0/levels)
- **OIDC**: 워크플로가 클라우드 제공자로부터 **단명 토큰**을 직접 교환; 장기 클라우드 시크릿을 GitHub에 복제할 필요 없음; 토큰은 단일 job에만 유효하고 자동 만료; `sub` 클레임에 저장소/환경/ref/sha 등 포함 — [GitHub: OpenID Connect](https://docs.github.com/en/actions/concepts/security/openid-connect)
- **커밋 서명 검증**: GPG/SSH/S/MIME로 서명 시 "Verified" 표시; 브랜치에 **서명 커밋 강제** 가능; GitHub 웹 UI 커밋은 자동 서명됨; **Rebase and Merge는 서명 검증을 우회** — [GitHub: About commit signature verification](https://docs.github.com/en/authentication/managing-commit-signature-verification/about-commit-signature-verification)
- **브랜치 보호**: 기본적으로 admin에게 적용 안 됨 / bypass 권한 존재 — [About protected branches](https://docs.github.com/repositories/configuring-branches-and-merges-in-your-repository/defining-the-mergeability-of-pull-requests/about-protected-branches)
- **환경(deployment environments) 필수 리뷰어**: GitHub Free/Pro/Team에서는 **공개 저장소에만** required reviewers 사용 가능; 비공개는 Enterprise Cloud 필요 — [GitHub: Deployments and environments](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments); [Community #170307](https://github.com/orgs/community/discussions/170307)
- **포크 PR 시크릿**: "GITHUB_TOKEN을 제외하면, 포크 저장소에서 트리거된 워크플로에는 시크릿이 러너로 전달되지 않는다" — [GitHub: Using secrets in GitHub Actions](https://docs.github.com/actions/security-guides/using-secrets-in-github-actions)
- **in-toto**: layout(단계 정의)과 서명된 link metadata로 엔드투엔드 검증; link는 "어떤 스텝이 실행됐는지" 기록하는 서명 문서 — [in-toto](https://in-toto.io/); [in-toto/attestation link predicate](https://github.com/in-toto/attestation/blob/main/spec/predicates/link.md)
- **tj-actions/changed-files 침해(CVE-2025-30066)**: 2025-03-14경 침해, 공격자가 **기존 버전 태그를 악성 코드로 재지정**; **SHA로 핀한 사용자는 영향 없음**(단, 공격 기간에 영향받는 해시로 갱신한 경우 제외); 공격자는 봇의 GitHub PAT를 침해; 악성 페이로드가 CI 러너 메모리의 시크릿을 덤프해 공개 저장소 로그에 노출 — [Wiz Blog 2025-03-15](https://www.wiz.io/blog/github-action-tj-actions-changed-files-supply-chain-attack-cve-2025-30066)

### Inferences
- **적용 매트릭스(무료 기준)**:
  | 프리미티브 | 증명하는 것 | 무료 여부 | PaaS 배포에 적용? |
  |---|---|---|---|
  | 서명 커밋/태그(GPG/SSH) | 그 커밋이 특정 키 소유자에 의해 만들어짐(영속 기록) | 무료 | 소스에만(실행 중 빌드는 별개) |
  | gitsign(keyless) | OIDC 신원 + Rekor 기록 | 무료 | 소스/태그; GitHub "Verified" 아님 |
  | 보호 브랜치 + 필수 리뷰 + 필수 체크 | "리뷰/CI 통과 없이는 머지 불가"(admin 예외) | 공개 무료 | 간접(머지된 커밋만 배포 가정) |
  | CODEOWNERS | 소유자 자동 리뷰 요청 | 무료 | 보호 규칙과 결합 시 강제 |
  | 환경 + 필수 리뷰어 | 배포 job 앞 수동 승인 게이트 | **공개 저장소만 무료** | **PaaS 배포와 직접 관련**(단 이 프로젝트는 공개 포크→org) |
  | OIDC | 단명·job 스코프 배포 자격증명 | 무료 | **Render가 OIDC 미지원이면 미적용** → 정적 훅 시크릿에 의존 |
  | actions/attest-build-provenance | 업로드한 아티팩트의 SLSA L2 출처 | 공개 무료 | **Render가 빌드하므로 실행 서비스엔 미적용**; 릴리스 태그/핀 번들엔 적용 가능 |
  | SLSA L3 | 강화 빌드 플랫폼 | (GitHub reusable workflow로 가능) | Render 빌드엔 미적용 |
- **결론적 정렬**: 이 프로젝트에서 실효성 있는 무료 프리미티브는 (1) 보호 브랜치 + 필수 리뷰 + 필수 체크, (2) CODEOWNERS, (3) **공개 저장소이므로** 환경 required reviewers(있으면), (4) 서명 커밋/태그 + Rekor, (5) 포크 PR에 시크릿 미전달의 기본값 유지. attestations/OIDC는 "PaaS 배포"라는 대상 때문에 대부분 적용 밖 → **엔터프라이즈급은 Render측 서명 출처/OIDC가 생기면 채워진다**.

### Gaps
- **Render 측** SLSA/attestation/OIDC 지원 여부 → UNKNOWN(위 Q2 갭과 동일).
- 공개 저장소에서 환경 required reviewers를 실제로 켤 수 있는지(플랜 조건은 확인했으나, org 저장소 소유 구도에서의 적용) → 문서상 공개면 가능으로 보이나 실계정 미확인.

## Q4. 핀/검증 자료를 제3자에게 어떻게 공개하는가 (투명성 로그 포함)

### Takeaway
**저장소에 핀 파일 + 회전별 서명 태그**를 공개하고, 핀 지문을 **투명성 로그(Rekor)에 앵커링**하면, 제3자(이슈 독자·관리자 CLI)가 저장소 히스토리 재작성까지 탐지하며 독립 검증할 수 있다. 무료이며, GitHub 공개 저장소의 artifact attestation도 자동으로 공개 불변 투명성 로그에 기록된다.

### Cited Findings
- Sigstore **Rekor**는 서명 투명성 로그로, **append-only(update-only) 공개 로그**; 서명 이벤트가 기록되어 감사 가능한 시점 기록을 제공 — [Sigstore: Rekor overview](https://docs.sigstore.dev/logging/overview/)
- gitsign은 서명 검증을 위해 **커밋과 코드서명 인증서를 Rekor에 기록**(임시 인증서가 만료된 뒤에도 검증 가능) — [sigstore/gitsign README](https://github.com/sigstore/gitsign)
- GitHub 공개 저장소의 artifact attestation 번들은 GitHub에 저장되고 **인터넷에서 공개 열람 가능한 불변 투명성 로그**에 기록 — [GitHub: Artifact attestations](https://docs.github.com/en/actions/concepts/security/artifact-attestations)
- GitHub 이슈에는 **파일 첨부 공식 API가 없음**(REST/GraphQL 모두) → 이슈에는 메타데이터(식별자·경로·sha256)만 넣어야 함(프로젝트 메모리, 2026-10-16 공식 문서 확인).

### Inferences
- **발행 체계(무료 최소)**:
  1. `security/evidence-key-pin.json` 커밋(공개키 + 지문 + 세대).
  2. 회전마다 서명 태그 `evidence-key-vN` push → GitHub 서명 검증 영속 기록 + 로컬 `gitsign verify`로 신원 확인.
  3. 핀 파일의 sha256을 Rekor에 기록(예: cosign attest 또는 gitsign 태그 서명) → 히스토리 재작성 탐지.
  4. 각 증거 봉인 이슈 본문에는 파일 자체 대신 **지문·경로·sha256 메타데이터**만 기재(이슈 첨부 API 부재 때문).
  5. 관리자 CLI가 **로컬에서** (a) `/health` 지문 vs 핀 파일 vs 공개키에서 재계산한 지문을 비교하고, (b) 태그 서명/Rekor 항목을 검증한 뒤에만 암호화·전송.
- 순환 방지의 핵심: 제3자(독자·CLI)가 검증하는 대상에 **저장소 히스토리 밖 앵커**(서명 태그 + Rekor)가 포함되어야, 저장소/CI가 핀을 재작성해도 탐지된다.

### Gaps
- Rekor에 "핀 지문"을 기록하는 표준 predicate/관례(예: cosign attest vs gitsign 커밋)의 모범 사례 → 이번 조사에서 확정된 1차 권고를 찾지 못함 → UNKNOWN(기술적으로는 투명성 로그 사용은 확인됨).
- GitHub Release asset을 "불변"으로 취급할 수 있는 기간/정책 → UNKNOWN.

## Q5. 이름 붙일 가치가 있는 실패 모드

### Takeaway
가장 위험한 것은 **"같은 저장소·같은 CI가 핀과 검사를 함께 바꿀 수 있다"** 는 순환이다. 여기에 시크릿 탈취(CI·Render 환경변수), 초록 CI 뒤의 악성 PR, 배포 훅 시크릿 유출, 운영자 노트북 침해가 겹친다. 각각은 부분 완화만 가능하며, **무료 최소 구성으로는 "탐지"까지가 한계**다.

### Cited Findings
- CI 컴프로마이즈 실사례: tj-actions가 **기존 버전 태그를 악성 커밋으로 재지정**, 러너 메모리에서 시크릿 덤프 → 공개 저장소 로그로 유출; 완화는 **액션을 full commit SHA로 핀** — [Wiz Blog](https://www.wiz.io/blog/github-action-tj-actions-changed-files-supply-chain-attack-cve-2025-30066)
- 같은 사고: 공격자는 봇의 **GitHub PAT**를 침해해 태그를 조작; `ghs_` 접두 단명 토큰은 24시간/잡 종료 시 만료되어 장기 위험은 제한적 — [동일](https://www.wiz.io/blog/github-action-tj-actions-changed-files-supply-chain-attack-cve-2025-30066)
- 보호 브랜치 규칙은 **admin에게 기본 미적용**(bypass 가능) → org 소유자/침해된 admin이 우회 가능 — [About protected branches](https://docs.github.com/repositories/configuring-branches-and-merges-in-your-repository/defining-the-mergeability-of-pull-requests/about-protected-branches)
- 포크 PR에는 (GITHUB_TOKEN 제외) 시크릿이 전달되지 않음 — [GitHub: Using secrets](https://docs.github.com/actions/security-guides/using-secrets-in-github-actions)
- 배포 훅 URL은 시크릿; 아는 누구나 배포 트리거 가능 — [Render: Deploy Hooks](https://render.com/docs/deploy-hooks)
- attestation은 "안전 보장"이 아니고 출처를 연결해 줄 뿐이며, 소비자가 정책을 정의해 판단해야 함 — [GitHub: Artifact attestations](https://docs.github.com/en/actions/concepts/security/artifact-attestations)

### Inferences
- **순환(self-verification)**: 저장소/CI가 핀과 검사 로직을 함께 바꾸면 초록이 된다 → 완화는 CODEOWNERS+보호+서명 강제+**로컬 CLI 독립 검증**. 완전 제거는 불가(무료).
- **시크릿 저장소 탈취**: Render 환경변수(공개키지만 대입 대상), GitHub 시크릿(배포 훅 URL 등). 코드가 접근 권한을 가지면 유출 가능 → 최소 권한, 포크 PR에 시크릿 미부여 유지, `pull_request_target`로 PR 코드를 체크아웃하지 말 것(간접).
- **초록 CI 뒤 악성 PR**: 공격자가 코드와 테스트를 함께 작성하면 required check가 통과 → 리뷰(특히 CODEOWNERS)와 서명 커밋이 실질 방어선.
- **배포 훅 유출 → 임의 배포**: 링크된 저장소에 존재하는 커밋만 배포 가능(404)이므로, 비-default 브랜치에 악성 커밋을 심어 `ref`로 배포하는 경로가 열린다 → default 브랜치 보호 + Render 자동배포를 default로 한정.
- **운영자 노트북이 최약 고리**: X25519 개인키가 로컬(MFAK1, scrypt+AES-GCM)에만 있고 메모리 0화 불가(프로젝트 메모리); 노트북 침해 시 개인키 + Render API 접근으로 전체 붕괴 → 개인키 오프라인 보관·패스프레이즈·최소 API 키 권한.
- **환경변수 변경은 커밋을 바꾸지 않음** → 커밋 바인딩만으로 키 대입을 못 막음(Q2) → 핀 필수.

### Gaps
- `pull_request_target` 오용 등 구체적 트리거별 시크릿 노출 패턴의 1차 문서 확정 → UNKNOWN(일반 원칙만 확인).
- Firebase 서비스 계정 키를 CI에 두는 경우의 위험 평가 → 이 프로젝트 관리자 경로는 Render 환경변수에 SA JSON을 넣는 구조(프로젝트 메모리)로, CI 시크릿과 분리 필요 — 구체 수치/권고는 미확인.

## Q6. 1인 프로젝트 권장 최소 구성 (정확한 GitHub Actions 스텝과 시크릿 위치)

### Takeaway
**저장소 파일 핀 + 필수 상태 검사 + 서명 태그 + 주기적(크론) 검사 + 로컬 CLI 독립 검증**의 5종이 무료 최소선이다. 시크릿은 "사설키=노트북, 공개키=Render 환경변수, 배포 훅/API키=GitHub 시크릿(포크 PR에 노출 금지)"으로 배치한다. 핵심은 **대입은 크게 실패(exit 1 + 경보), 회전은 PR 절차로만 허용**하도록 세대 카운터를 두는 것.

### Cited Findings
- 포크 PR에는 시크릿 미전달 → 배포/시크릿이 필요한 워크플로는 포크 PR 트리거에 노출되지 않게 설계 — [GitHub: Using secrets](https://docs.github.com/actions/security-guides/using-secrets-in-github-actions)
- After CI Checks Pass는 **체크 0개면 배포 안 함**, 실패 시 미배포 — 필수 체크를 반드시 등록 — [Render: deploys](https://render.com/docs/deploys)
- 액션은 **full commit SHA**로 핀 — tj-actions 교훈 — [Wiz Blog](https://www.wiz.io/blog/github-action-tj-actions-changed-files-supply-chain-attack-cve-2025-30066)
- 환경 required reviewers는 **공개 저장소 무료** — [GitHub: Deployments and environments](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments)
- 서명 커밋 강제 + 영속 검증 기록 — [About commit signature verification](https://docs.github.com/en/authentication/managing-commit-signature-verification/about-commit-signature-verification)

### Inferences

**배치(무엇을 어디에)**
- 관리자 X25519 **개인키**: 운영자 노트북만(MFAK1). 어디에도 업로드 금지.
- **공개키 + 지문 + 세대**: 저장소 파일 `security/evidence-key-pin.json`(공개키는 비밀 아님). Render 환경변수에는 공개키 문자열.
- **배포 훅 URL / Render API 키 / Firebase SA JSON**: GitHub 저장소 시크릿(가능하면 환경 스코프). 포크 PR 워크플로에서는 절대 참조하지 않음.
- 회전 이력: 서명 태그 `evidence-key-vN`(+ Rekor 항목).

**핀 파일 스키마(예)**
```json
{
  "key_id": "evk-2026-10",
  "generation": 3,
  "fingerprint_sha256": "<sha256(public_key_raw_32B) hex>",
  "public_key_b64": "<32-byte X25519 raw, base64>",
  "health_url": "https://<app>.onrender.com/health",
  "rotated_by_commit": "<sha>"
}
```

**필수 상태 검사 워크플로(대입 vs 회전 구분, 크게 실패)**
```yaml
# .github/workflows/verify-key-pin.yml
name: verify-key-pin
on:
  schedule: [{ cron: "17 */6 * * *" }]      # 런타임 환경변수 몰래 바꾼 경우 탐지
  workflow_dispatch:
  push: { branches: [main] }
permissions:
  contents: read
jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@<full-commit-SHA>   # 태그 금지, SHA 핀
      - name: Compare live /health fingerprint to pin
        run: |
          python - <<'PY'
          import json, sys, urllib.request, hashlib, base64
          pin = json.load(open("security/evidence-key-pin.json"))
          h = json.load(urllib.request.urlopen(pin["health_url"]))
          ev = h.get("evidence", {})
          live_gen = int(ev.get("key_generation", -1))
          live_fp  = ev.get("fingerprint")
          if live_fp is None:
              print("::error::/health has no evidence.fingerprint (silent-false 금지)"); sys.exit(1)
          if live_gen == pin["generation"] and live_fp != pin["fingerprint_sha256"]:
              print("::error::KEY SUBSTITUTION: same generation, fingerprint changed"); sys.exit(1)
          if live_gen < pin["generation"]:
              print("::error::DOWNGRADE: live generation < pinned"); sys.exit(1)
          if live_gen > pin["generation"]:
              print("::warning::rotation in progress; open a signed PR to bump the pin"); sys.exit(0)
          # 커밋 바인딩: 리뷰된 main HEAD 와 /health 커밋 비교
          expected = "${{ github.sha }}"
          if h.get("commit") and not h["commit"].startswith(expected[:7]):
              print(f"::error::BUILD MISMATCH: /health commit != {expected[:7]}"); sys.exit(1)
          print("pin OK")
          PY
```

**머지 게이트 설정(무료)**
- `main` 보호: Require PR + Require approvals(≥1) + Require review from Code Owners + Require status checks(`verify-key-pin`, 기존 `ci`) + Require signed commits + Dismiss stale approvals. admin bypass는 인지하고, 최소 인원 유지.
- `security/evidence-key-pin.json` 을 CODEOWNERS에 등록(관리자만 리뷰).
- 공개 저장소면 배포 관련 환경에 required reviewers 지정.
- 모든 서드파티 액션은 full SHA 핀.

**회전 절차(정당한 회전을 조용히 만들지 않기)**
1. 관리자 로컬에서 새 키 생성 → 공개키 역산.
2. 별도 PR: `generation + 1`, `public_key_b64`/`fingerprint`/`rotated_by_commit` 갱신 + 서명 커밋. **같은 PR에서 코드/CI 로직은 바꾸지 않음**(대입과 회전의 diff를 분리).
3. 머지·배포 후 Render 환경변수 공개키 교체(대시보드/API) → 실배포.
4. `verify-key-pin`가 새 지문 == 새 핀 확인. 회전 태그 `evidence-key-vN` push + (선택) Rekor 기록.

**관리자 CLI(독립 검증)**
- 전송 전: `/health` 지문 == 로컬 핀 파일 지문 == 공개키에서 재계산한 지문; 세대 일치; 태그 서명/Rekor 항목 검증. 불일치면 **암호화·전송 거부 + 경보**. (프로젝트 메모리: `/health`에 `evidence.key_id`/`fingerprint` 를 추가하는 작업이 다음 단계로 계획됨.)

**엔터프라이즈급이 추가하는 것(참고)**
- Render측 서명된 빌드 출처 + OIDC 기반 단명 배포 자격증명(정적 훅 시크릿 제거).
- 전 브랜치 서명 커밋 강제, org 액션 allowlist, SLSA L3 강화 빌드, Sigstore 키리스 서명 강제, 전 릴리스 투명성 로그, 전 환경 required reviewers.

### Gaps
- 위 워크플로에서 Render가 앱에 커밋 SHA를 주입하는 정확한 환경변수 이름(예: 커밋/브랜치 메타데이터) 미확인 → `h["commit"]` 브랜치를 실제 값에 맞게 조정 필요(UNKNOWN).
- `/health`의 정확한 응답 스키마(`evidence.key_generation` 필드 존재 여부)는 이 프로젝트의 미구현 항목 → 스키마 확정 필요(프로젝트 메모리상 라운드 7 검증 예정).
- 공개 org 저장소에서 환경 required reviewers의 실제 활성화 가능 여부 실계정 미확인.
