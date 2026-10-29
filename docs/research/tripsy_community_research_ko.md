# Tripsy 유저 커뮤니티 리서치 (r/TripsyApp)

조사일: 2026-10-29 · 출처: r/TripsyApp, r/iosapps, r/TripIt

## 먼저, 브리프의 전제 두 개가 틀렸다

1. **"Rafael / 커뮤니티 매니저 James"는 확인되지 않는다.** 서브레딧에서 실제로 답글을 다는 계정은 **u/thiago_sanchez** 하나뿐이고, 유저들은 그를 "Hi Thiago"라고 부른다. 프로필에 Reddit "Top 1% 기여자" 배지가 붙어 있고, 모든 릴리즈 공지도 이 계정이 올린다. Rafael이나 James라는 이름은 관측된 어떤 스레드에도 등장하지 않는다. (확인 불가 — 없다고 단정하지는 않음)
2. **1s0ekyj는 Tripsy 스레드가 아니다.** r/TripIt의 "A new, feature complete alternative to tripit"은 **TripWaffle** 런치 글이고, 본문도 "I was sick of the slow dereliction of tripit"이다. Tripsy 신호로 쓰면 안 되고, 경쟁사 벤치마크로만 쓸 수 있다.

또 하나: 이 서브레딧은 "유저 커뮤니티"라기보다 **개발사 릴리즈 노트 채널**에 가깝다. 2026년 10월 프론트페이지는 "Tripsy x ChatGPT"(10-12), "3.10.3"(10-13), "MCP 2.0"(10-08), "iPhone Duo Day"(5일 전), "Raycast and Tripsy"(3일 전) — 전부 개발사 글이다. 유저 글은 드물고 업보트 10 내외, 댓글 1~2개 수준. **포스트 리듬은 주 2~4회지만 그 대부분이 공지**라는 게 실질적인 그림이다.

- 구독자 수: 직접 확인 실패. 검색 스니펫에 "164 subscribers in the TripsyApp community"라는 문구가 잡히지만 이는 **미검증 수치**다. 규모가 작다는 방향성만 신뢰할 것.
- 모더레이터: 확인 실패 (Reddit이 about/JSON 접근을 차단).

> 접근 제약: reddit.com HTML·JSON·RSS 모두 403/Blocked. `render_js` 크롤러로만 부분 수집했고, 일부 스레드는 본문 없이 댓글 일부만, 일부는 개발자 답글 1개만 반환됐다. 아래 인용은 실제 반환된 텍스트만 사용했다.

## 스레드별 요약

**"Tripsy - My Biggest Missing Features" (1uoyo67, 약 2026-06)** — 유저 업보트 4·댓글 15로 이 서브 최대 토론. 최상위 댓글이 항목별로 동조: 웹 인터페이스, Mac 앱 사이드바 폭, 게스트 구독 팝업, 좌표 기반 목적지. 인용: *"a web version would let family members on Android engage with a trip on some level, which is currently a hard barrier"*, *"invited family members consistently complain about being inundated with subscribe popups they'll never act on"*, *"pasting coordinates snaps the pin to the nearest physical address"*. 개발자 답글 존재: *"We do also give guests on a trip the PRO features for that trip"*.

**"1 Month In... Tripsy is 99% there for me!" (1vk2twh, 약 2026-08)** — TripIt 15년 사용자가 한 달 병행 후 *"now just about ready to cancel my TripIt subscription altogether"*. 핵심은 **이탈하지 않으려고 유저가 직접 땜질했다**는 점: *"I've since solved both problems using Claude Code"* — 사설 웹 대시보드 + 3개 메일함을 12시간마다 스캔하는 자동 임포터 + 일정 충돌 검사. 제품 결함(웹 없음, 수동 포워딩)을 유저가 외부에서 메꾼 사례.

**"Feature requests" (1s9oyps, 약 2026-03)** — 본문은 "기능 요청을 추적하는 곳이 있냐"는 질문 하나. 답: *"Yes, please send to support@tripsy.app"*, *"You can also check if we've already done it on our help page. tripsy.help"*. **공개 로드맵·이슈 트래커가 없다**는 뜻이고, 실제로 유저 요청의 추적이 안 되는 구조다.

**"App Crashing Upon Launching" (1xc6y95, 2026-10 추정)** — 개발자 답변만 수집: *"Can you try reinstalling Tripsy… we'll need to move this across to our support email, as there's only so much technical support we can do on a subreddit :-)"*. 서브레딧을 서포트 채널로 쓰지 않겠다는 명시적 입장.

**Welcome post (1uovxgo, 약 2026-06)** — 본문은 쿠키 배너만 잡혀 실질 내용 없음. 실패로 기록.

**r/iosapps 1s7wy11 (2026-03)** — "We launched Tripsy 3.8" 런치 글. 반응은 우호적: *"I have been using Tripsy for quite a few trips now and I absolutely love it"*, 단 *"Kinda sad that iOS 17 has been dropped recently"*.

**웹/브라우저 요청 (1xfzy0l, 2026-10-26)** — 가장 최신이자 가장 직답적인 개발자 코멘트: *"We do have a read-only interface available at my.tripsy.app and we are carefully considering a fully featured web version… no timeframe just yet."* 웹은 **읽기 전용**만 존재.

## (a) 기능 요청 순위

표본이 작아 빈도는 "관측된 스레드 수" 기준이다. 과대 해석 금지.

| 요청 기능 | 언급 빈도 | 개발자 응답 여부 |
|---|---|---|
| 웹 버전(편집 가능한 대시보드) | 3회+ (1uoyo67, 1vk2twh, 1xfzy0l) | 있음 — 읽기 전용만 제공, "no timeframe just yet" |
| Android 지원 | 2회 (1uoyo67, 서브 외 r/Cortex) | 없음(웹으로 우회 제안) |
| 이메일 자동 임포트(수동 포워딩 제거) | 2회 (1uoyo67, 1vk2twh) | 없음 — MCP/AI 연동으로 대체 제안 |
| 캘린더 전역 싱크·통합 피드 | 2회 (1s0ekyj, 1thr3o4 계열) | 부분 — 3.8에서 캘린더 연동 출시 |
| 오프라인 접근 | 2회 (1s0ekyj 계열) | 확인된 답변 없음 |
| 여행 병합(편도 2건 → 여행 2개 생성) | 2회 | 답변 미확인 |
| 위젯 on/off·편집 | 1회 (1uoyo67) | 미확인 |
| 좌표 기반 목적지 | 1회 (1uoyo67) | 있음(부분 동의) |
| 게스트 구독 팝업 억제 | 1회 (1uoyo67) | 있음 — PRO 기능은 이미 제공된다는 반박 |
| 과거 여행 숨기기 토글 | 1회 (1s0ekyj) | 미확인 |
| 항공 소요시간 표시 / 날짜 없는 이벤트 / 이벤트 추가 시 날짜 UX | 각 1회 | 미확인 |

## (b) 반복 버그

- **실행 즉시 크래시** (1xc6y95) — 재설치 안내로 종결, 원인 공개 없음
- **드라이브 타임이 표시될 때와 안 될 때가 갈림** — *"sometimes it shows drive time between two spots, but more often doesn't"*
- **지도 앱 선택 안 뜸(iPhone)** — *"there are no maps apps in the selection (no Google Maps, Apple Maps…)"*
- **이벤트 추가 시 랜덤 날짜** — *"it shows random dates and I always need to remember what date should I set"*
- **중복 제거 없음** — *"I resent updated reservation email and result was duplicate entry for every flight segment"*
- 위젯 로딩·통계 스크롤 문제는 3.7.5 릴리즈 노트에서 개발사가 자체 인정

## (c) 가격·구독 불만

**"비싸다"는 직접 불만은 표본에서 관측되지 않았다.** 실제로 나온 건 두 가지다. ① **평생권 할인 요청** — *"would it be possible to get any kind of discount on the lifetime subscription!!"* → 답: *"Unfortunately only on Black Friday"*, 이어서 *"Is it Black Friday yet? 🤣"*. ② **게스트 팝업 피로** — 초대된 가족이 *"inundated with subscribe popups"*. 즉 가격 자체보다 **비소유 협업자에게 결제 압박이 반복되는 UX**가 실질 불만이다.

## (d) TripIt 대비 우위

- 속도·완성도: *"Tripit is super slow, outdated and it looks like dying slowly"*
- 과금 구조: *"doesn't feel like it's bloated with crap or premium features to unlock"*
- 공유: *"Seems smarter for sending trip plans than TripIt"*, *"I like the expenses view, it makes it easier to share a trip with someone"*
- 마이그레이션: *"I was able to import all my TripIt trips with no issues"*
- **TripIt 사용자의 진짜 전환 장벽은 기능이 아니라 근육 기억**: *"I've been using TripIt for over 15 years… muscle memory defaulting to TripIt"*

## (e) 떠나거나 못 넘어오는 이유

1. **웹/데스크톱 편집 부재** — 최대 이탈 요인. TripIt 잔류 사유 1순위이고, 1vk2twh는 이걸 직접 코딩해서 해결했다.
2. **수동 이메일 포워딩** — 자동화 기대치를 못 맞춤.
3. **Android 가족 구성원 배제** — iOS 전용이 협업 여행에서 구조적 허들.
4. **오프라인 미지원** — 기내에서 일정 확인 불가.
5. **게스트 결제 팝업** — 협업 경험 훼손.
6. 크래시·중복 데이터 같은 신뢰성 이슈.

## 실무적 판단

이 커뮤니티는 **수요 검증용으로는 신뢰도가 낮다**. 유저 글이 월 몇 건 수준이고, 개발사 공지가 피드를 채우며, 기능 요청은 공개 트래커가 아니라 `support@tripsy.app` 메일로 흩어진다. 다만 **웹 버전 부재 → 유저가 외부 툴로 자체 대시보드를 만든 사례(1vk2twh)** 는 단일 사례이지만 신호 강도가 높다. Tripsy가 웹을 "읽기 전용, no timeframe"으로 두는 동안, 파워유저는 이미 자기 워크플로를 밖에서 완성하고 있다.
