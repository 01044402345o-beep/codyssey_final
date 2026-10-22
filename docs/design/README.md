# 화면

| 문서 | 내용 |
|---|---|
| [RESPONSIVE_STRATEGY.md](RESPONSIVE_STRATEGY.md) | 휴대폰·태블릿·PC, 라이트·다크 전략 |
| [material-spec.html](material-spec.html) | 카드·유리 재질 명세(브라우저로 열기): 떠 있는 층(L1)만 실제 유리, 컨텐츠 카드(L0)는 raised·tinted·ink 세 역할. 토큰은 `mockup/styles.css` 맨 위 `:root` 의 `--glass-*`·`--mat-*`·`--al-*`. 틴트 8% 는 사용자 테스트로 검증하지 않은 값이다. §07 은 '검정 강조'를 폐기로 적었지만 코드는 '화면당 ink 면 1개'(홈 히어로)를 허용한다 — 문서가 코드보다 엄격하다. |

`mockup/` 은 2026-10-22 2차 테스트까지 동결이다. `mockup/README.md`, `mockup/app.js`, `mockup/audit/responsive_audit.js` 는 이 파일의 예전 경로 `docs/RESPONSIVE_STRATEGY.md` 를 가리킨다.

상위 목록: [docs/README.md](../README.md)
