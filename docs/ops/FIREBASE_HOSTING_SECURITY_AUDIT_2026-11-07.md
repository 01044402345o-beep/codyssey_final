# Firebase Hosting 배포면 보안 전수조사

검사 대상은 `https://com-example-myapplicatio-3bb36.web.app`, 대응 `firebaseapp.com` 호스트, Render API, 저장소의 Hosting·인증·배포·앵커 설정이다. 결론은 **소스의 보강과 라이브 배포본이 일치하지 않는다**는 것이다. 아래 H0는 “문제가 없다”는 영가설이며, 관찰 결과가 그 가설을 기각하는지 기록한다.

## 판정

### H0-1 — Firebase Hosting CSP가 실제로 강제된다

**기각.** 저장소의 `firebase.json`은 `Content-Security-Policy`를 선언하지만, 라이브 `/`와 `/index.html`은 `Content-Security-Policy-Report-Only`를 반환했다. Report-Only는 위반을 기록할 뿐 차단하지 않는다. `X-Frame-Options: DENY`와 `nosniff`는 확인됐지만, CSP의 스크립트·연결·프레임 제한은 운영에서 강제되지 않는다.

### H0-2 — 루트 진입 문서는 배포 후 즉시 재검증된다

**기각.** `/index.html`과 JS/CSS는 `no-cache`였지만 `/`는 `max-age=3600`이었다. 앱의 진입점은 `/`이므로 보안 수정 뒤에도 한 시간 동안 이전 HTML이 제공될 수 있다. HTML이 `app.js`, `auth.js`, `ai.js` 같은 고정 파일명을 참조하므로 혼합 버전도 가능하다.

### H0-3 — Firebase Hosting의 `?api=`는 공격자 서버로 API를 바꾸지 못한다

**기각(라이브 배포본).** 저장소의 최신 소스는 Firebase Hosting에서 `?api=`를 무시하지만, 라이브 `ai.js`는 이전 구현으로 임의 HTTP(S) 주소를 받아들였다. 로그인 후에는 ID 토큰, 계정 상태, 통역 기록, 동의된 음성이 그 API 주소로 전송될 수 있다. 이는 현재 가장 높은 우선순위의 운영 취약점이다.

### H0-4 — Render CORS는 Firebase Hosting 두 출처만 허용한다

**기각.** 라이브 Render API가 `evil.example`, Firebase 출처, `null` 출처의 preflight와 응답에 `Access-Control-Allow-Origin: *`를 반환했다. 저장소 `render.yaml`의 allowlist와 라이브 프로세스가 다르다. 현재 계정 API는 Bearer 토큰이 없으면 401이지만, wildcard CORS는 공개 API의 교차 출처 호출을 허용하고 향후 인증 실수의 피해 범위를 넓힌다.

### H0-5 — Firestore와 공개 Firebase 설정이 비인가 데이터를 노출한다

**현재까지 수용.** 비인증 Firestore REST 조회는 403이었고, 규칙은 UID 일치·비익명 공급자·허용 필드·크기 제한·기타 경로 거부를 사용한다. `/auth/config`의 API key, authDomain, projectId, appId는 브라우저용 공개 설정으로 보이며 서비스 계정 키는 관찰되지 않았다. 다만 인증된 교차 사용자 규칙 테스트는 Emulator 또는 테스트 계정으로 별도 수행해야 한다.

### H0-6 — Firebase와 Render가 감사한 소스/PR과 같은 릴리스다

**기각.** 로컬 PR 브랜치는 `98fd7ce`였고, 라이브 Render `/health`는 `94850b1`을 보고했다. 라이브 `ai.js`, `auth.js`, `app.js`, `index.html`의 SHA-256도 현재 소스와 달랐다. ETag와 Last-Modified만으로는 Git 커밋이나 PR을 증명할 수 없다.

### H0-7 — 오프사이트 앵커가 사용자-facing Firebase 배포본의 롤백·드리프트를 감지한다

**기각.** 기존 앵커는 Render `/health`와 Firestore 체인만 기록했다. Firebase Hosting 자산 해시, ETag, CSP 모드, 캐시 정책, `ai.js`의 Hosting origin guard는 기록하지 않았다. 따라서 Render가 정상이어도 Firebase가 구 버전으로 롤백되거나 캐시되어 있는 상황을 놓칠 수 있다.

현재 보강 후에도 GitHub Issue는 **독립 provider가 아니다**. 같은 GitHub 조직·저장소 권한을 가진 공격자가 저장소와 Issue를 함께 삭제하거나 수정할 수 있다. H3를 완전히 닫으려면 별도 계정의 저장소, 메일 보관함, 또는 다른 타임스탬프 provider로 동일한 앵커를 복제해야 한다.

### H0-8 — 운영 배포는 테스트·provenance·rollback으로 자동 게이트된다

**기각 또는 미결.** 저장소에는 Firebase Hosting 자동 배포 workflow가 없고 manual `firebase deploy --only hosting` 절차만 문서화되어 있다. immutable Hosting release ID와 자산 manifest를 PR·Render commit과 묶는 자동 게이트도 확인되지 않았다. rollback 명령은 문서에 있지만 실제 rollback 훈련 기록은 없다.

## 이번 보강

- 관리형 Render 환경에서 `ALLOW_ORIGINS`가 없거나 `*`이면 CORS를 **fail-closed**로 변경했다. 로컬 개발 기본값만 기존 wildcard를 유지한다.
- Firebase Hosting 루트 `/`에도 `Cache-Control: no-cache, max-age=0, must-revalidate`를 추가했다.
- 오프사이트 앵커가 Render `/health`의 `deploy` 정보와 Firebase `/`, `/index.html`, `/ai.js`, `/auth.js`, `/app.js`의 상태·SHA-256·ETag·Last-Modified·CSP 모드·캐시 정책을 기록하도록 확장했다.
- 앵커는 Hosting CSP가 enforce가 아니거나, 루트가 cacheable하거나, `ai.js`에 개발 출처 전용 API origin guard가 없으면 실패한다.
- 앵커의 Hosting 불변조건, CORS fail-closed, Firebase root header 회귀 테스트를 추가했다.

## 배포 후 종료 조건

다음 조건이 모두 충족되기 전에는 “취약점 해결”로 닫지 않는다.

1. Firebase `/`와 `/index.html`에서 `Content-Security-Policy`가 존재하고 `Content-Security-Policy-Report-Only`가 없다.
2. Firebase `/`의 Cache-Control에 `max-age=0`과 `no-cache`가 있다.
3. 라이브 `ai.js`가 `*.web.app` 및 `*.firebaseapp.com`에서 `?api=`를 무시한다.
4. Render의 hostile preflight(`evil.example`, `null`)에 `Access-Control-Allow-Origin`이 없고, 두 Firebase 출처만 정확히 허용된다.
5. Render `/health`의 commit, Firebase 자산 manifest, PR merge commit이 기록된 release manifest와 일치한다.
6. 오프사이트 앵커의 Hosting 검증이 성공하고, Firebase rollback을 한 번 재현해 자산 지문 변화가 기록된다.

라이브 배포는 소스 변경과 별개로 수행해야 한다. Hosting 배포 뒤에는 `GET`으로 검사한다. 이 API는 `HEAD /health`를 404로 처리할 수 있으므로 HEAD를 배포 검증에 사용하지 않는다.
