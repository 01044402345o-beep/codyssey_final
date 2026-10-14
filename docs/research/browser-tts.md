# 브라우저 듣기 음성 — 발음이 틀리거나 다른 단어가 섞이는 문제

작성: 2026-10-15 · 대상: `mockup/app.js` `speak()` · 요구: FR-07 카드 학습·듣기

QA: 브라우저 자체 음성으로 발음이 정확하지 않거나, 정확하지 않은 단어가 같이 들린다.

이 문서는 그 현상을 네 모집단에서 대표 집단만 골라 조사한 기록이다. `speak()` 는 바꾸지 않았다. `mockup/` 은 2026-10-22까지 동결이다.

## 1. 우리 코드가 하는 일

`speak()` 는 Web Speech API `speechSynthesis` 만 쓴다.

1. `speechSynthesis.cancel()` 을 호출한다.
2. `SpeechSynthesisUtterance` 를 하나 만들고 `speak()` 를 한 번 호출한다. `pause()` · `resume()` 는 없다.
3. `lang` 은 `en-US` 다.
4. 음성은 이름이 Google, Samantha, Aria, Jenny, Guy, Zira, Natural 중 하나를 포함하는 `en-US` 를 먼저 고르고, 없으면 아무 `en-US`, 그다음 아무 영어 음성이다.
5. `rate` 는 사용자가 고른 `S.ttsRate` 다.
6. `[name]` · `[destination]` 은 `your name` · `your destination` 으로 바꾼 뒤 읽는다.

음성 목록이 비어 있으면 `ttsState()` 는 `ok` 다. `novoice` 는 목록이 있는데 영어 음성이 없을 때만이다. 목록이 도착하기 전에 듣기를 누르면 `utterance.voice` 가 비고, 그때는 브라우저 기본 음성으로 읽는다. 목록은 기동 시와 `voiceschanged` 에서 `getVoices()` 로 채운다.

듣는 문장은 짧은 여행 영어다.

## 2. 조사 방법

전체를 훑지 않았다. 모집단마다 그 특성을 가장 잘 보여주는 집단만 봤다.

| 모집단 | 대표 집단 | 보려는 특성 |
|---|---|---|
| 엔진 결함 | Chromium·WebKit에서 대기열·`cancel()` 이 이전 문장과 새 문장을 섞는 보고 | 문장에 없는 단어가 같이 들리는 쪽 |
| 한국 로캘 기기 | Chrome Android·데스크톱에서 지정한 영어 음성이 무시되거나 기기 TTS 언어로 읽는 보고 | 영어 발음이 틀린 쪽 |
| 문장 재생이 본업인 학습 앱 | Duolingo, Anki. ELSA 는 재생 엔진 사례가 아니라 빼 둠 | 그 문장의 소리를 어떻게 고정했는가 |
| API 안에 남는 수정 | 이슈와 MDN에 반복된 `voiceschanged`, `cancel()` 대기, `pause()`/`resume()`, 문장 분할, `rate` | 음소를 고칠 수 있는가 |

상태: 일부만 확인. Chromium 이슈 본문과 Stack Overflow 스레드는 로그인·챌린지로 전문을 열지 못한 것이 있어, 그 주장은 검색 발췌다. 아래 「빼 둔 주장」은 검증에서 출처와 어긋나 기록하지 않은 것이다.

## 3. 확인된 것

### 3.1 문장에 없는 단어

Chromium [41362336](https://issues.chromium.org/issues/41362336) 은 대기열 버그다. `cancel()` 뒤 `speak()`, `pause()`, 다시 `speak()`, `resume()` 를 하면 대기 중인 문장 대신 첫 문장이 재생되고, 원문에 없는 말(“speak one hundred twenty-three slash speak”)이 들어간다.

우리 `speak()` 는 `cancel()` 다음 `speak()` 한 번이다. 이 재현 순서와 같지 않다. 이 버그가 우리 듣기의 섞인 단어라고 단정하지 않는다.

15초 근처에서 끊기는 것은 다른 버그다. Chromium 679437 은 localService 가 아닌 Google 음성이 긴 발화에서 약 15초 뒤 멈춘다고 확인됐다. 확인된 음성은 Google US English 이고 Microsoft David 에서는 재현되지 않았다. PhET utterance queue 는 데스크톱 Chromium 에서만 10초마다 `pause()` 다음 `resume()` 를 호출한다. 같은 호출은 Android Chrome 에서 재생을 멈추고 다시 시작되지 않는다. Caktus 가 유지하는 읽어 주기 코드는 말하는 동안 14초마다 같은 호출을 한다. 둘 다 긴 글을 끝까지 읽히기 위한 것이다. 그 타이머를 섞인 단어·반복·겹친 소리와 연결한 출처는 없다.

Safari 쪽을 전문으로 읽은 결과는 섞인 소리가 아니다. WebKit 191745 는 `speak(); cancel(); speak(); speak()` 가 마지막 문장만 읽는다. WebKit 238189 는 Safari iOS 15.4 에서 `cancel()` 직후 넣은 문장은 들리는데 `onstart` · `onend` · `onboundary` 가 오지 않는다. Samsung Internet 이 문장을 겹친다는 기록은 찾지 못했다. MDN 호환 표는 Chrome Android 와 Samsung Internet Android 에서 `pause()` 가 현재 문장을 끝내고 `cancel()` 처럼 동작한다고 적는다.

### 3.2 지정한 영어 음성이 쓰이지 않음

Chrome for Android 는 `utterance.voice` 의 음성 이름을 엔진에 넘기지 않는다. Chromium [433161438](https://issues.chromium.org/issues/433161438) 과 소스 `TtsPlatformImpl.java` 가 같다. `setLanguage` 만 하고 `setVoice` 는 하지 않는다. `lang` 은 그 언어의 기본 음성만 고른다. Firefox 는 지정한 음성을 쓴다고 보고되어 있다. 그 실패의 체감이 전화기 로컬 언어로 읽는 것인지, 품질이 낮은 영어 음성인지는 이슈가 나누어 적지 않는다.

2026년 코멘트는 영어 음성 팩이 있으면 `lang` 을 `en-US` 로 두면 그 언어의 기본 음성이 선택된다고 한다. 2020–2023년 보고는 `lang` 이 무시됐다고 한다.

데스크톱 Chrome 의 Google `en-US` · `ko-KR` 음성은 네트워크 전용이고 오프라인 대체가 없다. `ko-KR` 음성은 맞는 영어 음성이 없을 때만 `en-US` 문장에 쓰인다. 정확한 로캘 일치 점수는 128, 앱 로캘은 2다. 출처는 Readium 의 WebSpeech 정리와 Chromium `tts_controller_impl.cc` 다.

한국어 로캘 Chrome 이 `en-US` 문장을 `ko-KR` 음성으로 읽는 별도 버그 번호는 확인하지 못했다. 확인된 것은 고른 음성 이름이 Android 에서 무시되고, `lang` 이 그 언어의 기본 음성을 고른다는 점이다.

명세([SpeechSynthesisUtterance.voice](https://webaudio.github.io/web-speech-api/#dom-speechsynthesisutterance-voice))는 `voice` 가 비어 있으면 사용자 에이전트 기본 음성을 쓰라고 한다. `getVoices()` 는 음성을 알기 전에는 빈 목록이고, Chrome 은 페이지 로드 시점에 목록이 비어 있다. 기본이 아닌 음성은 `voiceschanged` 에서 넣어야 한다.

### 3.3 학습 앱이 문장 소리를 고정한 방법

| 제품 | 확인된 방법 | 출처 |
|---|---|---|
| Duolingo (2017) | 문장마다 Amazon Polly MP3 를 한 번 만들어 저장한다. 영어 음성은 Sally. Polly 오류는 SSML 로 고칠 수 있었다 | [Powering Language Learning on Duolingo with Amazon Polly](https://aws.amazon.com/blogs/machine-learning/powering-language-learning-on-duolingo-with-amazon-polly/) |
| Duolingo (2021) | 성우 녹음으로 학습한 자체 음성. 강좌 문장을 읽을 수 있고, 같은 철자 `read` 의 현재와 과거를 구분한다. 발음 모델로 쓴다 | [Giving our characters voices](https://blog.duolingo.com/character-voices/) |
| Anki | 같은 녹음을 카드 모음의 소리 파일로 넣으면 기기와 상관없이 그 파일이 재생된다. `speechSynthesis` 는 AnkiMobile 2.0.56 이전의 사용자 스크립트에만 등장한다 | [Text to speech support](https://docs.ankiweb.net/faqs/text-to-speech-support) |

이 글들은 “Web Speech API 를 버렸다”고 적지 않는다. Polly 글은 성우 스튜디오 녹음 대신 수만 문장을 생성한 결정이고, `speechSynthesis` 를 언급하지 않는다. 확인된 공통점은 그 문장의 소리를 파일로 남긴다는 것이다. Anki 의 OS TTS 는 복습 시점에 기기마다 달라질 수 있다.

ELSA 는 발음 인식과 튜터링이라 문장 재생 엔진의 사례로 쓰지 않았다.

### 3.4 API 안에 남는 수정이 다루는 범위

| 수단 | 출처가 말하는 효과 |
|---|---|
| `voiceschanged` 이후에 기본이 아닌 음성을 넣기 | 음성을 알기 전에는 `getVoices()` 가 빈다. 기본이 아닌 음성은 그 핸들러에서 지정한다 |
| `cancel()` 뒤 짧은 대기, `pause()` / `resume()` | Chrome 에서 재생이 시작되지 않거나 끊기는 쪽에 인용된다. 음성을 고르거나 발음을 고친다고 적혀 있지 않다. Chrome Android 와 Samsung Internet Android 에서는 `pause()` 가 현재 발화를 끝내고 `cancel()` 처럼 동작한다 |
| 문장부호로 나눠 여러 utterance | 나누는 기준은 문장부호다. non-native 음성의 절단은 보통 200–300자 근처다. 너무 긴 텍스트는 시스템 음성으로 바뀐 뒤 그 음성이 유지될 수 있다. 조각마다 음성을 복사해도 발음은 바뀌지 않는다 |
| `rate` | 속도만 바꾼다. 0.1–10, 기본 1. 두 배 빠르거나 느려도 시간 절단 위치는 그대로였다고 보고됐다 |

명세는 utterance 텍스트 안 SSML 과 `mark` 이벤트를 허용한다. 엔진이 처리하지 않는 태그는 제거된다. 음소 제어가 보장되지는 않는다. Windows SAPI 가 XML 태그를 소리내어 읽는다는 검색 발췌의 이슈 본문은 열지 못했다. `pause()` / `resume()`, `cancel()` 뒤 대기, 문장 분할, `rate` 가 잘못된 음소를 고친다는 출처는 없다.

## 4. 빼 둔 주장

검증에서 출처와 문장이 어긋나 빼 둔 것이다.

- Chromium 댓글의 재생 횟수(1번, 2번, 3번)와 `setTimeout(..., 0)` 우회가 그 댓글에 있다는 주장. 이슈와 `handleSpeakingCompleted()` 의 `startTime` 검사는 맞지만, 연 댓글 본문에 그 횟수와 우회는 없었다. 프로덕션 사이트가 그 대기를 베꼈다는 기록도 없다.
- 음성 팩이 없으면 Chrome 이 기기의 현재 TTS 언어를 유지한다는 주장. 이슈는 Conservative-to-Aggressive 언어 감지가 기본 언어로 돌아가는 것을 고쳤다고 할 뿐, 팩 부재를 그렇게 적지 않는다.
- 선택 실패의 체감이 영어 문장을 전화기 로컬 TTS 언어로 읽는 것이고, 그것이 낮은 품질의 영어 음성과 다른 현상이라는 단정. 한국어 음소는 한국어 엔진이 필요하고, 영어 팩이 없을 때 다른 영어 지역으로 떨어지는 것은 별개의 대체다.
- 한국어 Windows 가 Heami 만 있고 `en-US` SAPI 음성이 없다는 주장. 일본어 Windows 에 Zira 가 없다는 기록과, Microsoft 가 `ko-KR` 에 Heami 를 둔다는 기록은 있다. 한국어 Windows 가 영어 음성을 빼 둔다는 문장은 없다.
- Anki 필드 TTS 가 모든 OS 에서 기기 음성을 쓴다는 단정. Windows·macOS·iOS 는 OS 음성이고 Linux 는 TTS 엔진이 없다고 매뉴얼이 적는다. 브라우저 `speechSynthesis` 는 언급하지 않는다.
- Speechling 이 문장마다 원어민 녹음을 두고, 학습자가 기계 발음을 따라 할까 봐 기계 TTS 를 거절했다는 해석. 원어민 재생과 기계 음성의 대비는 문서에 있다. 거절 이유는 그 문서에 없다.
- Duolingo 가 Microsoft 와 6,000줄 이상 녹음으로 바꿨다는 2025년 소셜 캡션. 2021년 캐릭터 음성 글은 그 판매자를 적지 않아 빼 두었다.
- 고른 Google 음성이 약 20% 발화에서 무시된다는 Chromium 40852978 의 우회. `voiceschanged` 고정과 별개이고, 찾은 Stack Overflow 답은 우회가 없다고 한다. 이슈 전문은 열지 못했다.

## 5. 우리 호출에 대면 범위

| QA 증상 | 우리 `speak()` | 조사에서 닫힌 범위 |
|---|---|---|
| 다른 단어가 같이 들림 | `cancel()` 직후 `speak()` 한 번. `pause()` 없음 | 없는 단어가 삽입된 재현은 `pause()` 와 두 번째 `speak()`, `resume()` 가 있는 41362336 이다. 우리 순서의 재현은 아니다 |
| 발음이 틀림 | `voice` 와 `lang=en-US` 를 같이 넣음 | Android Chrome 은 음성 이름을 엔진에 넘기지 않는다. `lang` 은 그 언어의 기본 음성만 고른다. `pause()`/`resume()`, `cancel()` 뒤 대기, 문장 분할, `rate` 가 음소를 고친다는 출처는 없다 |
| 첫 듣기가 다른 음성 | 목록이 비어도 `ok` | 명세상 `voice` 가 비면 기본 음성이다 |
| 긴 문장 절단 | 여행 영어 한 문장 | 약 15초 정지는 Chromium 679437 의 긴 발화 절단이다. 10초·14초마다 `pause()` 다음 `resume()` 는 그 절단의 우회다. 우리 문장 길이를 그 절단과 견준 측정은 없다. 같은 호출은 Android Chrome 에서 재생을 멈추고 다시 시작되지 않는다 |

2017 Duolingo 와 Anki 에서 확인된 같은 녹음의 공유는 그 문장의 소리 파일이다. 2021 Duolingo 는 성우 녹음으로 학습한 음성이다. 이 기록은 그 교체를 결정하지 않는다.

## 출처

| # | 문헌 | 이 기록에서 쓰는 범위 |
|---|---|---|
| S1 | Chromium 41362336. https://issues.chromium.org/issues/41362336 | 대기열이 첫 문장과 원문에 없는 말을 재생. 검색 발췌 |
| S2 | PhET utterance-queue issue 60, commit `6d5b3c1`. https://github.com/phetsims/utterance-queue/issues/60 | 데스크톱 Chromium 한정 10초 `pause()`/`resume()`. 긴 발화 절단용 |
| S3 | Caktus, The Halting Problem (2025-11-03). https://www.caktusgroup.com/blog/2025/11/03/the-halting-problem/ | 말하는 동안 14초마다 같은 호출 |
| S4 | Chromium `TtsPlatformImpl.java`. https://source.chromium.org/chromium/chromium/src/+/main:content/public/android/java/src/org/chromium/content/browser/TtsPlatformImpl.java | Android 는 `setLanguage` 만 하고 `setVoice` 를 하지 않음 |
| S5 | Chromium 433161438. https://issues.chromium.org/issues/433161438 | Android 에서 Web Speech 음성 이름이 무시됨 |
| S6 | Readium WebSpeech.md. https://github.com/readium/speech/blob/main/docs/WebSpeech.md | 데스크톱 Google 음성은 네트워크 전용. 로캘 점수 128 대 2 |
| S7 | AWS, Duolingo × Polly. https://aws.amazon.com/blogs/machine-learning/powering-language-learning-on-duolingo-with-amazon-polly/ | 문장마다 Polly MP3, 영어 Sally. Polly 오류는 SSML 로 고칠 수 있었다 |
| S8 | Duolingo, Giving our characters voices. https://blog.duolingo.com/character-voices/ | 2021 성우 기반 자체 음성, `read` 시제 구분 |
| S9 | Anki, Text to speech support. https://docs.ankiweb.net/faqs/text-to-speech-support | 카드 모음의 소리 파일. `speechSynthesis` 는 옛 사용자 스크립트 |
| S10 | Web Speech API, `getVoices`. https://webaudio.github.io/web-speech-api/#dom-speechsynthesis-getvoices | 목록은 음성을 알기 전에 빈다 |
| S11 | Web Speech API, `voice`. https://webaudio.github.io/web-speech-api/#dom-speechsynthesisutterance-voice | `voice` 가 없으면 기본 음성 |
| S12 | Stack Overflow, cancel() problems. https://stackoverflow.com/questions/39391502/js-speechsynthesis-problems-with-the-cancel-method | `cancel()` 뒤 대기. 발음 수정이라고 적히지 않음. 검색 발췌 |
| S13 | Stack Overflow, longer texts. https://stackoverflow.com/questions/21947730/chrome-speech-synthesis-with-longer-texts | 문장 분할과 시스템 음성 전환. 검색 발췌 |
| S14 | MDN, `rate`. https://developer.mozilla.org/en-US/docs/Web/API/SpeechSynthesisUtterance/rate | 속도만 변경 |

## 검토

검토 에이전트 01a13b96-b142-7882-a604-7214d55f87b7 은 이 문서가 우리 cancel 다음 speak 한 번을 Chromium 41362336 의 재현이라고 단정하지 않고, 검증에서 뺀 주장을 확인된 사실로 다시 적지 않았다고 통과로 봤다.
