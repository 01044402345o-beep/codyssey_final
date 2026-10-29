# Tripsy 딥다이브 — 개발 과정 · 커뮤니티 · 소스코드

2026-10-29 조사. 근거는 전부 링크. 확인 못한 것은 "확인 못함"으로 남겼다.

---

## 0. 한 줄 결론

Tripsy는 **8년 된 2인 인디 앱**인데, 2026년에 **"여행 데이터를 API로 열어 AI 에이전트의 데이터 레이어가 된"** 쪽으로 포지션을 바꿨다.
앱 기능이 아니라 **데이터 구조**가 자산이다. 이건 마디가 배울 것 중 가장 값비싼 항목이다.

---

## 1. 개발 과정 — 연표

| 시점 | 사건 | 근거 |
|---|---|---|
| 2018 | Rafael K. Streit이 이탈리아 여행 준비 중 "호텔 예약과 장소가 흩어져 오프라인에서도 볼 정리가 필요했다" → 공동창업자와 개발 시작 | [rafaelks.com/tripsy](https://rafaelks.com/tripsy.html) |
| **2018-10-25** | **App Store 1.0.0** — 체인지로그 첫 줄 "First version in the App Store" | [업데이트](https://tripsy.app/updates) |
| 2019-01 | 블로그 정식 런칭 공지 / 9to5Mac 소개 | [9to5Mac](https://9to5mac.com/2019/01/22/tripsy-all-in-one-ios-travel-app/) |
| 2019-09 | **2.0** — 협업·문서 보관·iPad 멀티윈도·Sign in with Apple·다크모드. MacStories 심층 리뷰 | [MacStories](https://www.macstories.net/reviews/tripsy-review-the-ultimate-trip-planner-for-iphone-and-ipad/) |
| 2020~2023 | 2.1 웹 일정 공유 → 2.7 캘린더 동기화 → 2.15 날씨·시간대 | [MacStories 2.1](https://www.macstories.net/reviews/tripsy-2-1-adds-web-based-itineraries-and-expanded-travel-email-forwarding/) |
| **2024-09-16** | **3.0** — "거의 5년 만의 가장 큰 업데이트". 경비·통계·경로 자동 계산·내보내기 | [업데이트](https://tripsy.app/updates) |
| 2024-09-22 | The Verge Installer 소개 | [The Verge](https://www.theverge.com/2024/9/22/24249948/socialai-snap-spectacles-snapchat-penguin-installer) |
| 2024-11 | **Apple 2024 App Store Awards 'iPhone App of the Year' 파이널리스트** | [Apple Newsroom](https://www.apple.com/newsroom/2024/11/apple-reveals-45-app-and-game-finalists-for-the-2024-app-store-awards/) |
| 2025-09-15 | 3.6 — iOS 26 Liquid Glass 대응 **+ iOS 17 지원 중단** | [업데이트](https://tripsy.app/updates) |
| 2025-12-11 | 3.7 — Recap(연말 회고) | 동일 |
| 2026-03-25 | 3.8 — 캘린더 연동 | 동일 |
| 2026-08-26 | 3.9 — Smart Routes | 동일 |
| 2026-09-14 | **3.10 — Smart Import** (스크린샷·문서·붙여넣기·구글맵 목록을 장소·예약으로) | 동일 |
| 2026-09 | **Apple Siri AI 발표에 Tripsy가 예시로 호명** — "식당 추천을 Tripsy에 추가" | [Apple Newsroom](https://www.apple.com/newsroom/2026/09/siri-ai-a-profoundly-more-capable-and-personal-assistant-is-here/) |
| 2026-09~10 | 3.10.1 → 3.10.5, **한 달에 5번 패치** | [업데이트](https://tripsy.app/updates) |

**릴리스 리듬**: 3.10 계열만 2026-09-14~10-23 사이 5개. 사실상 1~2주 단위 포인트 릴리스 + 공개 체인지로그.
이건 마케팅이 아니라 **"살아있는 앱" 신호**를 계속 발행하는 운영 방식이다.

---

## 2. 팀 구조

- 공개된 얼굴: **Rafael K. Streit**(개발, @rafaelks) + **Thiago Sanchez**(디자인·공동창업자). 둘이 2018년부터.
- 여기에 **커뮤니티 매니저 James**(u/tripsyjames)가 붙어 r/TripsyApp을 직접 운영한다.
  내가 직접 읽은 스레드에서 **Thiago와 James가 같은 스레드에서 연속으로 답글**을 달았다 — 이건 1차 확인이다.
- **현재 인원: 확인 못함.** 공식 about 페이지 크롤링 실패, LinkedIn 로그인 벽.
- **투자: 확인 못함.** 3자 DB(Tracxn)는 "unfunded, 브라질, 2018 설립"으로 분류하지만 1차 출처 아님.
- **매출·구독 전환율: 비공개.**

**2인이 8년 버틴 구조**: 구독 + 평생구매. 그리고 2026년부터 MCP/API로 **자사 앱 밖에서도 쓰이게** 만들었다.

---

## 3. 소스코드 — 정확히 무엇이 공개이고 무엇이 아닌가

GitHub API로 직접 확인했다 (2026-10-29).

### 공개 (조직 `tripsyapp`)
| 저장소 | 언어 | 스타 | 라이선스 | 최근 푸시 |
|---|---|---|---|---|
| **`cli`** | **Go** | 22 | **MIT** | 2026-10-27 |
| `api` | CSS | 1 | 없음 | 2026-10-02 |
| `docs-helpscout-css` | CSS | 0 | 없음 | 2026-06-23 |

→ **실질 공개는 `cli` 하나.** Go로 된 CLI + **로컬 STDIO MCP 서버**, MIT 라이선스.
`go install github.com/tripsyapp/cli/cmd/tripsy-mcp` ([GitHub](https://github.com/tripsyapp/cli))

### 비공개
- **iOS/Mac/watchOS/visionOS 앱 소스: 없음.** 조직에 앱 저장소가 없다.
- **호스팅 MCP 서버(`mcp.tripsy.app`): 비공개.** 동적 OAuth만 지원, 토큰 관리 UI 없음 — 회수는 메일 요청([tripsy.help/97](https://tripsy.help/article/97-ai-tools)).
- **개발자 개인 계정 `rafaelks`**: 저장소 44개 중 대부분이 포크(AFNetworking, SDWebImage, HorizonCalendar, SwiftyStoreKit, jitsi-meet 등). 본인 것이 눈에 띄는 건 `RKSBonjourManager`(2014, Obj-C, MIT), `rafaelks.github.io`, 그리고 2016년 `iOS-SDK`. **Tripsy 앱 코드는 없다.**

### 공개 API
- REST 문서: [docs.api.tripsy.app](https://docs.api.tripsy.app/) — `https://api.tripsy.app/v1/trips`, `/v2/trip/{id}/activities`, `/v1/storage/uploads`, `count/next/previous/results` 페이지네이션.
- 문서 업로드는 **백엔드 서명 S3 URL** 방식.
- **동기화가 CloudKit이 아니라 자체 백엔드**라는 증거가 이것이다.
- MCP 도구명은 `tripsy_collaborators_invite`, `tripsy_guests_favorites_list` 식으로 **동사_대상** 규약을 따른다.

**판정**: "소스코드를 공개한 회사"가 아니다. **"API 표면을 공개한 회사"**다. 앱은 닫혀 있고, 통합 지점만 열려 있다. 마디가 참고할 것은 코드가 아니라 이 경계 설정이다.

---

## 4. 커뮤니티 — 실측

r/TripsyApp을 직접 읽었다. **정정**: 서브레딧은 "유저 커뮤니티"라기보다 **개발사 릴리즈 노트 + 지원 창구**에 가깝다.
2026-10 프론트페이지는 ChatGPT 연동(10-12), 3.10.3(10-13), MCP 2.0(10-08), iPhone Duo, Raycast 연동 — 대부분 개발사 글. 유저 글은 업보트 10 내외, 댓글 1~2개.
**구독자 수: 확인 못함** (Reddit 크롤러 차단).

### 유저가 실제로 말한 것 (원문)

**① 웹 편집 버전 — 가장 뜨거운 요청, 가장 명확한 거절**
> "We do have a read-only interface available at my.tripsy.app and we are carefully considering a fully featured web version… **no timeframe just yet**."

**② 파워유저가 제품 결함을 직접 코딩으로 메꿨다** (2026-08, TripIt 15년 사용자)
> "now just about ready to cancel my TripIt subscription altogether" — 웹 대시보드와 자동 이메일 임포터를 **"I've since solved both problems using Claude Code"**로 자체 제작.
단일 사례이지만 신호는 강하다: **파워유저가 이미 워크플로를 앱 밖에서 완성하고 있다.**

**③ 기능 요청은 추적되지 않는다**
> "Is there a place the team tracks feature requests?" → **"Yes, please send to support@tripsy.app"**
공개 로드맵 없음. 이건 2인 팀의 합리적 선택이지만, 파워유저에게는 "내 요청이 어디 갔는지 모른다"로 읽힌다.

**④ 결제 불만의 실체는 "비싸다"가 아니다**
> 초대된 가족이 **"inundated with subscribe popups they'll never act on"**
> 평생권 할인 요청 → **"Unfortunately only on Black Friday"**
즉 **비소유 협업자에게 반복되는 결제 압박 UX**가 실질 불만. James의 반론은 "Pro 기능 접근 시에만"이고, 게스트에게는 그 여행의 Pro 기능을 준다고 답했다.

### 요청 기능 표
| 요청 | 언급 | 개발자 응답 |
|---|---|---|
| 웹 편집 버전 | 3회+ | 있음 — 읽기 전용만, "no timeframe" |
| Android | 2회 | 없음 (웹으로 우회) |
| 이메일 자동 스캔(포워딩 아님) | 2회 | 없음 — 서드파티 자동화/MCP로 대체 제안 |
| 위젯 on/off·최소화 | 1회 | "Next Activity·Itinerary만 남기고 스와이프로 제거" |
| 좌표 직접 입력 | 1회 | 답변 있음(공유 확장 우회) |
| 캘린더 피드 커스터마이즈 | 1회 | 답변 있음(ICS 설정) |

### 반복 버그
- 실행 즉시 크래시 → "reinstalling 해보라"로 종결, **원인 미공개**
- 2026-09 3주간 크래시 핫픽스 3연속 (3.9.2 개방/복사/지도, 3.9.3 활동 추가, 3.9.4 주변 장소)
- 게스트 동기화: MCP로 만든 항목이 다른 게스트에게 안 보이고 'Places' 탭이 사라짐
- 임포트 날짜 오류: "imported… only to have the app import all the dates wrong" (2026-10-19 리뷰)

### TripIt 대비 우위 (유저 언어)
> "super slow, outdated… dying slowly" · "doesn't feel bloated with crap or premium features to unlock" · "smarter for sending trip plans"
전환 장벽은 기능이 아니라 **"15 years… muscle memory"**.

---

## 5. 수익화 — 페이지마다 숫자가 다르다

| 채널 | 값 |
|---|---|
| 공식 [/pro](https://tripsy.app/pro) | Free $0 / **Annual $59** / **Lifetime $299** (Family 공유) |
| App Store IAP | 월 $7.99 · 연 $39.99 · 패밀리 연 $59.99 · 평생 $299 등 |
| 9to5Mac(2026-09) | "$39/년 또는 평생 $199" ← 사이트와 어긋남 |
| 이전 조사(v1) | 주 $4.99 / 월 $7.99 표기 |

**가격은 변동 중**이다. 단일 값으로 인용하면 틀린다. Free/Pro 경계도 사이트 마크업이 접혀 있어 항목별 판독 불가(1차 확인: **Smart Import·Smart Insights는 Pro 전용**).
Setapp 번들도 병행 — Setapp 구독자는 Mac 앱 QR로 iOS Pro 활성화.

---

## 6. 마디가 배울 것 5 / 배우지 말 것 3

### 배울 것
1. **데이터 구조가 먼저, AI는 나중.** 3.0에서 일정·경비·문서를 객체로 재정의했기에 2026년 MCP로 그대로 열 수 있었다. 마디의 `place/sentence/weak` 구조도 지금 제대로 잡아두면 나중에 API가 된다.
2. **엔진 하나, 표면 여럿.** 호스팅 MCP + 공개 REST + Go CLI를 같은 API 위에 얹었다. 클라이언트별 통합을 따로 만들지 않는다.
3. **창업자가 커뮤니티에 직접 나온다.** 2인 체제에서도 창업자와 매니저가 같은 스레드에서 답한다. 아웃소싱 불가 자산.
4. **릴리스 리듬을 제품 서사로.** 1~2주 포인트 릴리스 + 공개 체인지로그.
5. **Apple 편집 노출을 유통으로.** App Store 스토리 → 어워드 파이널리스트 → Siri AI 발표 예시. 마케팅비 0으로 얻는 배치.

### 배우지 말 것
1. **OS 최소 버전을 기능 업데이트에 묶지 마라.** iOS 17 중단이 Liquid Glass 대응과 같은 릴리스에 묶여 이탈 리뷰를 만들었다. 여행 앱에서 기기 교체 강요는 비싸다.
2. **유료화 경계를 흐리게 두지 마라.** 무료/Pro 목록이 사이트·스토어·보도에서 서로 다르고, 게스트에게까지 구독 팝업이 뜨면 초대 기반 바이럴이 죽는다.
3. **MCP를 토큰 관리 UI 없이 열지 마라.** 회수를 메일 요청으로 받는 구조는 보안 서사에 구멍이다.

---

## 7. 마디에 그대로 옮길 수 있는 것 하나

Tripsy가 2026년에 한 일은 **"내 앱 안에 AI를 넣는"** 게 아니라 **"AI가 내 앱을 쓰게 만드는"** 것이다.
마디의 조사 파이프라인(`/research`)이 이미 그 모양이다 — 도시·날짜를 받아 구조화된 보고서를 낸다.
그걸 **MCP 도구 3개**로 노출하면(`madi_trip_plan`, `madi_place_list`, `madi_sentences`) ChatGPT·Claude 사용자가 마디를 도구로 쓴다.
앱을 안 깔아도 마디의 데이터가 쓰인다. 2인 팀이 앱 하나로 유통을 못 이기는 상황에서 이건 현실적인 우회로다.

**단, 지금은 하지 말 것.** 발표 3일 전이고, 지금 필요한 건 배포 안정성이다. 발표 후 첫 과제로 두는 게 맞다.

---

## 8. 확인 못함 (발표에서 쓰지 말 것)

- 팀 인원(2인 + 매니저 1인 이상, 정확히 몇 명인지)
- 투자 여부(3자 DB만 "unfunded")
- r/TripsyApp 구독자 수
- TestFlight 베타 운영 여부
- SwiftUI 채택 여부(개발자는 Xcode 주력이라고만 밝힘)
- `cli` 외 공개 저장소의 라이선스
- Apple Design Award 수상 — **확인되는 건 2024 App Store Awards 파이널리스트뿐.** "ADA 수상"이라고 쓰면 틀린다.
