# Tripsy 해부: 8년 된 2인 인디 앱이 MCP까지 간 이유

**한 줄 결론:** Tripsy는 2018년 10월 App Store에 조용히 올라온 2인 체제 인디 앱이고, 제품의 승부수는 "여행 데이터를 구조화된 객체로 갖고 있다"는 점이다. 그 자산을 2026년 MCP 서버·공개 API·CLI로 밖에 열어주면서 AI 여행 플래너 시장의 '데이터 레이어'로 포지션을 바꿨다. 다만 팀 규모·런웨이·구독 전환율은 공개 정보로 확인되지 않는다.

---

## 1. 기원과 타임라인

출발점은 창업자의 이탈리아 여행이다. Rafael K. Streit은 2018년 이탈리아 여행을 준비하다 "호텔 예약과 가고 싶은 장소가 흩어져 있어 오프라인에서도 볼 수 있는 정리가 필요했다"고 적었다. 공동창업자와 2018년 개발을 시작했고, 2019년 1월 24일 블로그로 정식 런칭을 알렸다 [rafaelks.com/tripsy.html](https://rafaelks.com/tripsy.html) · [Introducing Tripsy](https://tripsy.blog/introducing-tripsy/).

- **1.0.0 — 2018년 10월 25일.** 공식 체인지로그의 첫 줄이 "First version in the App Store"다 [tripsy.app/updates](https://tripsy.app/updates). 즉 블로그 런칭 공지보다 App Store 등록이 약 3개월 빠르다. 같은 시기 9to5Mac이 "all-in-one iOS travel app"으로 소개했고, 브라질 MacMagazine은 2018년 12월 15일 이미 리뷰를 냈다(블로그 자체 링크).
- **2.0 — 2019년 9월, iOS 13과 동시.** 협업, 문서 보관, iPad 멀티윈도, Sign in with Apple, 다크모드가 들어왔고 MacStories가 심층 리뷰를 썼다. 리뷰는 "거의 1년 전에 처음 출시됐다"고 명시한다 [MacStories](https://www.macstories.net/reviews/tripsy-review-the-ultimate-trip-planner-for-iphone-and-ipad/).
- **2.1 / 2.7 / 2.15** — 웹 기반 일정 공유, 캘린더 동기화, 날씨·시간대·커스터마이징 순으로 붙었다 [MacStories 2.1](https://www.macstories.net/reviews/tripsy-2-1-adds-web-based-itineraries-and-expanded-travel-email-forwarding/) · [3.8 블로그](https://tripsy.blog/tripsy-3-8/).
- **3.0 — 2024년 9월 16일.** 체인지로그 표현 그대로 "거의 5년 만의 가장 큰 업데이트"로 앱을 전면 재작성했다. 경비 추적·여행 통계·경로 자동 계산·데이터 내보내기가 이때 들어왔다 [tripsy.app/updates](https://tripsy.app/updates). The Verge의 Installer가 9월 22일자로 소개했고 [The Verge](https://www.theverge.com/2024/9/22/24249948/socialai-snap-spectacles-snapchat-penguin-installer), 그해 Apple App Store Awards에서 'iPhone App of the Year' 파이널리스트에 올랐다 [Apple Newsroom](https://www.apple.com/newsroom/2024/11/apple-reveals-45-app-and-game-finalists-for-the-2024-app-store-awards/).
- **3.1(2024-11-01) → 3.2(2025-01-15, 여행 합치기) → 3.3(2025-02-20) → 3.4(2025-05-07, Shortcuts/App Intents) → 3.5(2025-08-13, Favorite Guests) → 3.6(2025-09-15, iOS 26 Liquid Glass) → 3.7(2025-12-11, Recap) → 3.8(2026-03-25, 캘린더 연동) → 3.9(2026-08-26, Smart Routes) → 3.10(2026-09-14, Smart Import)** [tripsy.app/updates](https://tripsy.app/updates).

주의할 점: 마케팅에서 말하는 "Apple Design Award" 수상은 확인되지 않는다. 확인되는 것은 **2024 App Store Awards 파이널리스트**이며, 자사 사이트도 그 표현을 쓴다 [tripsy.app](https://tripsy.app/). ADA 수상·노미네이션 기록은 확인 못함.

## 2. 팀 구조

공개된 얼굴은 두 명이다. Rafael K. Streit(개발, iOS/Mac), Thiago Sanchez(디자인, 공동창업자) — 블로그·App Store 'Meet the creator' 스토리·Reddit 환영글 모두 이 구도를 확인한다 [블로그](https://tripsy.blog/introducing-tripsy/) · [App Store 스토리](https://apps.apple.com/us/iphone/story/id1501245244). 여기에 **커뮤니티 매니저 James**가 합류해 r/TripsyApp을 직접 운영한다("I'm James, the community manager for Tripsy") [Reddit](https://www.reddit.com/r/TripsyApp/comments/1uovxgo/welcome_to_rtripsyapp_share_your_journey_with/).

- **현재 인원:** 확인 못함. 공식 about 페이지는 존재하지 않거나 크롤링 불가였고, LinkedIn 회사 페이지는 로그인 벽이다. 확인 가능한 것은 "창업자 2인 + 커뮤니티/서포트 담당 최소 1인"까지다.
- **투자:** 3자 DB Tracxn은 "unfunded, 브라질 소재, 2018년 설립"으로 분류한다 [Tracxn](https://tracxn.com/d/companies/tripsy/__nk5ScB2m3bIuLbcUqfqa5pwIdmvot5jSlcvIfC1107w). 1차 출처(공시·인터뷰)로 확인한 것은 아니므로 "확인 못함에 가까운 3자 정보"로 취급해야 한다. Crunchbase는 접근 실패.
- **수익 모델:** 구독 + 평생구매. 인디 2인이 8년을 버틴 근거는 명확히 구독이지만, ARR·전환율은 비공개다.

## 3. 기술 스택

확인 가능한 사실만 정리하면 다음과 같다.

- **동기화는 CloudKit이 아니라 자체 백엔드.** 공개 API 문서는 `https://api.tripsy.app`의 REST 엔드포인트(`/v1/trips`, `/v2/trip/{id}/activities`, `/v1/storage/uploads` 등)와 `count/next/previous/results` 형태의 페이지네이션을 명시한다 [docs.api.tripsy.app](https://docs.api.tripsy.app/). 문서 업로드는 백엔드가 서명한 S3 업로드 URL을 쓴다("Create raw backend-signed S3 upload URLs") [CLI README](https://github.com/tripsyapp/cli).
- **Swift/SwiftUI 여부:** 개발자 본인은 Xcode를 주력으로 쓰고 iOS/Mac 앱을 만든다고 밝히지만 [rafaelks.com](https://rafaelks.com/), SwiftUI 채택을 명시한 1차 자료는 찾지 못했다 → **확인 못함**.
- **프라이버시 라벨:** App Store 기준 "Data Not Linked to You" — Identifiers, Usage Data, Diagnostics만 수집하고 **사용자 신원과 연결하지 않는다**고 표시한다. 여행 일정·문서 자체는 라벨에 없다 [App Store](https://apps.apple.com/us/app/tripsy-travel-planner/id1429967544).
- **MCP 서버:** 호스팅 엔드포인트는 `https://mcp.tripsy.app` 하나이고, **동적 OAuth만 지원**한다("as long as your tool supports dynamic OAuth"). 앱 안에서 토큰을 관리하는 UI는 아직 없고, 회수는 메일 요청으로 처리한다고 헬프센터가 인정한다 [tripsy.help/97](https://tripsy.help/article/97-ai-tools) · [tripsy.app/mcp](https://tripsy.app/mcp).
- **노출 도구:** 활동 생성/수정(`latitude`·`longitude` 필수, 시간은 UTC ISO-8601 + IANA 타임존), 여행·숙소·교통·경비·카테고리·협업자·즐겨찾는 게스트·문서·인박스·원시 API 요청까지 CLI 명령 표로 전부 공개돼 있다 [CLI README](https://github.com/tripsyapp/cli). 도구 이름은 `tripsy_collaborators_invite`, `tripsy_guests_favorites_list` 같은 스네이크케이스 규칙을 따른다.
- **구현 언어:** CLI와 로컬 STDIO MCP 서버는 **Go**(저장소 언어 표기 Go, `go install github.com/tripsyapp/cli/cmd/tripsy`) [GitHub](https://github.com/tripsyapp/cli).
- **기술 블로그·컨퍼런스 발표:** 확인 못함. 엔지니어링 글은 없고 제품 블로그와 체인지로그가 전부다.

## 4. 배포 전략

- **표면:** iPhone/iPad/Mac/Apple Watch/Vision. App Store 호환성에 visionOS 2.0, watchOS 10, macOS 15이 명시된다 [App Store](https://apps.apple.com/us/app/tripsy-travel-planner/id1429967544). iOS 18 미만은 설치 불가로 요구사항이 올라갔다 [tripsy.help/46](https://tripsy.help/article/46-installing).
- **Setapp:** 3.10.6 버전이 등재돼 있고, Setapp 구독자는 Mac 앱에서 QR을 받아 iOS Pro를 활성화한다 [Setapp](https://setapp.com/apps/tripsy) · [tripsy.help/103](https://tripsy.help/article/103-setapp). 즉 구독 번들 유통과 자체 구독을 동시에 굴린다.
- **가격:** 사이트 기준 Free / 연 $59 / 평생 $299(Family 공유) [tripsy.app/pro](https://tripsy.app/pro). App Store 인앱 목록은 월 $7.99, 연 $39.99, 패밀리 연 $59.99, 평생 $299 등 지역·시점별로 갈린다 [App Store](https://apps.apple.com/us/app/tripsy-travel-planner/id1429967544). 9to5Mac은 2026년 9월 기사에서 "$39/년 또는 평생 $199"로 적어 사이트와 어긋난다 [9to5Mac](https://9to5mac.com/2026/09/16/tripsys-ios-27-update-includes-smarter-imports-on-device-ai-insights-more/). → 가격은 변동 중이며 단일 값으로 인용하면 안 된다.
- **Free vs Pro:** 1차 확인 가능한 경계는 **Smart Import와 Smart Insights가 Pro 전용**이라는 점이다(9to5Mac 및 App Store 설명 "requires Tripsy Pro"). 2019년에는 무료=여행 1개, Pro=무제한+클라우드 동기화였다 [블로그](https://tripsy.blog/introducing-tripsy/). 현재 /pro 페이지는 무제한 여행·클라우드 동기화·무제한 게스트를 Free 항목으로 나열하지만 마크업이 접혀 정확한 체크 표 분리가 판독되지 않는다 → **항목별 정확한 무료/유료 경계는 확인 못함**.
- **Apple 관계:** App Store 'Meet the creator' 스토리, 2024 Awards 파이널리스트, 2026년 9월 Siri AI 발표에서 "식당 추천을 Tripsy에 추가" 예시로 호명 [Apple Newsroom](https://www.apple.com/newsroom/2026/09/siri-ai-a-profoundly-more-capable-and-personal-assistant-is-here/). 유통에서 Apple 편집팀 노출을 상당히 활용한 케이스다.
- **Android:** 네이티브 앱 없음. `my.tripsy.app` 웹 일정으로 우회하고 대기자 명단만 받는다 [tripsy.app/android](https://tripsy.app/android).

## 5. 커뮤니티 운영

- **r/TripsyApp:** 커뮤니티 매니저 James(u/tripsyjames)가 개설·운영하고, 창업자 계정(u/rafaelkstreit, u/thiago_sanchez)이 직접 답글을 단다. 지원은 Reddit이 아니라 앱 내 Settings > Talk to Us로 유도하며 "72시간 내 회신"을 공개 약속한다 [환영글](https://www.reddit.com/r/TripsyApp/comments/1uovxgo/welcome_to_rtripsyapp_share_your_journey_with/).
- **구독자 수:** 확인 못함. Reddit이 크롤러를 차단해 about.json·구독자 카운터를 얻지 못했다(3회 시도, 모두 빈 셸).
- **응답 방식:** 실제 스레드에서 James는 버그를 부정하지 않고 "다른 리포트는 없었다"면서도 재현 질문을 항목별로 던지고 지원 채널을 재안내한다 [게스트 동기화 스레드](https://www.reddit.com/r/TripsyApp/comments/1vj2f9o/syncing_issues_with_guests/). 로드맵 질문에는 "Apple Maps API가 그 데이터를 주지 않아 대안을 찾는 중, 일정은 약속 못 함"이라고 선을 긋는다 [환영글](https://www.reddit.com/r/TripsyApp/comments/1uovxgo/welcome_to_rtripsyapp_share_your_journey_with/).
- **체인지로그 리듬:** 3.10.x만 2026-09-14 → 10-23 사이 6개(3.10, .1, .2, .3, .4, .5), App Store 기준 3.10.6까지. 사실상 1~2주 단위 [업데이트](https://tripsy.app/updates).
- **TestFlight 베타:** 공개 프로그램 근거 확인 못함. Discord/공식 포럼도 확인 못함(채널은 Reddit·X·Instagram·Threads·Bluesky 중심).

## 6. 소스코드 공개 범위

- **앱 소스: 비공개.** iOS/Mac 앱 저장소는 존재하지 않는다.
- **공개된 것:** GitHub 조직 `tripsyapp`에 3개 저장소 — `cli`(Go, CLI + 로컬 MCP 서버), `api`(문서용), `docs-helpscout-css`(헬프센터 CSS). 조직 페이지와 GitHub API로 확인 [github.com/tripsyapp](https://github.com/tripsyapp) [CLI](https://github.com/tripsyapp/cli).
- **개발자 개인 계정 `rafaelks`:** 공개 저장소는 전부 **포크**(AFNetworking, SDWebImage, HorizonCalendar, SwiftyStoreKit 등) 또는 개인 사이트(`rafaelks.github.io`), 2012~2014년 Titanium 모듈, 대학 논문(`TCC-Research`)이다. Tripsy 앱 코드·SDK는 없다 [GitHub API 결과](https://github.com/rafaelks?tab=repositories).
- **MCP 서버:** 호스팅 서버 자체는 비공개, **로컬 STDIO MCP 서버와 CLI는 오픈소스로 공개**. 라이선스 파일은 저장소에서 확인하지 못했다 → 라이선스 확인 못함.
- **공개 API:** 문서는 공개지만 서버 구현은 비공개 [docs.api.tripsy.app](https://docs.api.tripsy.app/).

## 7. 실패·사고 이력

- **iOS 17 지원 중단 (3.6.0, 2025-09-15).** 체인지로그에 "Dropped support for iOS 17" 한 줄 [업데이트](https://tripsy.app/updates). 사용자 반발이 실제로 남아 있다: "Kinda sad that iOS 17 has been dropped recently. I skipped iOS 18" [r/iosapps](https://www.reddit.com/r/iosapps/comments/1qvtabu/we_made_a_trip_planner_for_iphone/). iOS 26 Liquid Glass 대응과 같은 릴리스에 묶인 점이 비판 지점이다.
- **게스트 동기화 버그 (2026년).** MCP로 만든 항목이 다른 게스트에게 안 보이고 'Places' 바로가기가 사라지는 리포트 [r/TripsyApp](https://www.reddit.com/r/TripsyApp/comments/1vj2f9o/syncing_issues_with_guests/). 체인지로그에도 "Fixed an issue where friends..." 취지의 게스트 관련 수정과 3.10.6의 "More reliable guest invitations and clearer sync status messages"가 반복 등장한다 [App Store](https://apps.apple.com/us/app/tripsy-travel-planner/id1429967544).
- **크래시 연쇄 (2026년 9월).** 3.9.2 "crash when opening Tripsy, copying trips, and using maps", 3.9.3 "crash when adding an activity", 3.9.4 "crashes when browsing nearby places" — 3주간 크래시 핫픽스 3연속 [업데이트](https://tripsy.app/updates).
- **구독 팝업·강제 업그레이드 논란.** "Tripsy App seems now to have a forced premium" 스레드와, 협업 게스트가 구독 팝업에 시달린다는 사용자 지적 [r/TripsyApp](https://www.reddit.com/r/TripsyApp/comments/1s5utq9/tripsy_app_seems_now_to_have_a_forced_premium/) · [기능 요청 스레드](https://www.reddit.com/r/TripsyApp/comments/1uoyo67/tripsy_my_biggest_missing_features/). App Store 리뷰에도 "popups do get annoying", "too expensive"가 반복된다(미러 기준) [chartoo](https://www.chartoo.com/itunes/app/1429967544-tripsy-travel-planner).
- **데이터 정확성.** 2026-10-19 리뷰 "Imported an entire trip's worth of reservations only to have the app import all the dates wrong" [chartoo](https://www.chartoo.com/itunes/app/1429967544-tripsy-travel-planner). 대규모 데이터 유실 사고의 1차 공지는 확인 못함.
- **환불 불가 조항.** 약관은 "서비스는 여행 일정에 대한 사용자 불만족으로 인한 환불을 제공하지 않는다"고 명시한다 [tripsy.app/terms](https://tripsy.app/terms).

---

## Tripsy에서 마디가 배울 것 5가지

1. **출시보다 데이터 구조가 먼저다.** 3.0에서 일정·경비·문서를 객체로 재정의했기에 2026년 MCP로 그대로 밖에 열 수 있었다. AI 기능을 앱에 하드코딩하는 대신 자산을 API로 노출한 순서가 옳았다.
2. **엔진은 하나, 표면은 여럿.** 호스팅 MCP + 공개 REST + Go CLI를 같은 API 위에 얹었다. 클라이언트별 통합을 따로 만들지 않는 구조다.
3. **창업자가 커뮤니티에 직접 나온다.** 2인 체제에서도 창업자 계정과 전담 매니저가 같은 스레드에서 답한다. 이건 아웃소싱이 안 되는 자산이다.
4. **릴리스 리듬을 제품 서사로 쓴다.** 1~2주 단위 포인트 릴리스와 공개 체인지로그가 "살아있는 앱" 신호를 만든다.
5. **Apple 편집 노출을 유통 채널로 설계했다.** App Store 스토리, 어워드 파이널리스트, Siri AI 발표 예시 — 마케팅 예산 없이 얻는 배치다.

## 배우지 말 것 3가지

1. **OS 최소 버전을 기능 업데이트에 묶지 마라.** iOS 17 지원 중단이 Liquid Glass 대응과 같은 릴리스에 묶여 이탈 리뷰를 만들었다. 여행 앱에서 기기 교체를 강요하는 비용은 크다.
2. **유료화 경계를 흐리게 두지 마라.** 무료/Pro 목록이 사이트·App Store·보도자료에서 서로 다르고, 협업 게스트에게까지 구독 팝업이 뜨면 바이럴 루프(초대)가 죽는다.
3. **호스팅 MCP의 토큰 관리 UI 없이 출시하지 마라.** 토큰 회수를 메일 요청으로 받는 구조는 보안·신뢰 서사에 구멍이다. 최소한 연결 목록과 해제 버튼은 있어야 한다.
