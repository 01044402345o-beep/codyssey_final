# 실시간 통역 — 제공자 조사와 우리 구현 (2026-10-21)

여행 중 화면의 **통역**은 지금까지 검수된 문장을 보여 주고 들려주는 데까지만 했다(단방향, AI 호출 0회).
이 문서는 **실제 양방향 통역**(내 말 한국어 ↔ 상대 영어)을 넣기 위해 제공자를 비교하고, 고른 것과 구현 범위를 적는다.

## 1. 요구

| 항목 | 기준 |
|---|---|
| 방향 | ko ↔ en 양방향. 한 화면에서 두 사람이 번갈아 말한다 |
| 지연 | 첫 자막 1초 안팎, 말이 끝난 뒤 확정 자막 2초 안 |
| 비용 | 2차 테스트(사용자 5명, 각 10~20분)에서 부담 없는 수준 |
| 개인정보 | 음성이 국외 제공자로 간다 → 동의·고지 필수. 우리 서버는 저장하지 않는다 |
| 실패 시 | 조용히 멈추지 말고 "지금은 못 쓴다"고 화면에 적는다 |

## 2. 비교 (문서에서 직접 확인한 것만)

| 제공자 | 방식 | 양방향 | 비용(문서 기준) | 비고 |
|---|---|---|---|---|
| **Soniox** | WebSocket, STT + 번역 한 세션 | **`two_way`(a↔b) 지원** | 실시간 **$0.12/시간** 상당(토큰 과금), 번역 포함 | 토큰마다 `translation_status` 로 원문/번역 구분. 60+ 언어 |
| **OpenAI `gpt-realtime-translate`** | 전용 `/v1/realtime/translations` (WebRTC/WebSocket) | 방향마다 세션 1개 | **$0.034/분** (≈$2.04/시간) | 70+ 입력 → **13 출력** 언어. 번역 음성까지 바로 나옴 |
| **Azure Speech (Live Interpreter)** | Speech SDK, 실시간 음성 번역 | 세션 안 언어 전환·자동 언어 식별 | 목록가 예시 **$2.50/시간**(대상 2개), 언어 추가 시 문자 과금 | 화자 스타일 보존, BYO voice. 한국어 포함 |
| **DeepL Voice API** | WebSocket | 세션당 원문 1스트림 → 여러 대상 언어 | 문서에 단가 미표기(영업 문의) | 원문 자막 + 번역 + 번역 음성. 용어집·고유명사 보정 |
| **Gemini Live API** | WSS, 16 kHz in / 24 kHz out | Live Translation 가이드 별도 | 무료 등급은 입력이 제품 개선에 쓰일 수 있음 | 팀이 이미 Gemini 를 쓰지만 **무료 등급 약관**이 걸림 |

- Soniox 실시간 번역: https://soniox.com/docs/translation/stt-translation/rt-translation
- Soniox 가격: https://soniox.com/pricing
- OpenAI 실시간 번역 가이드: https://developers.openai.com/api/docs/guides/realtime-translation
- OpenAI 모델 페이지: https://developers.openai.com/api/docs/models/gpt-realtime-translate
- Azure 음성 번역 개요(Live Interpreter 포함): https://learn.microsoft.com/en-us/azure/ai-services/speech-service/speech-translation
- Azure 언어 지원(ko-KR 포함): https://learn.microsoft.com/en-us/azure/ai-services/speech-service/language-support?tabs=speech-translation
- DeepL Voice API: https://developers.deepl.com/docs/voice/overview
- Gemini Live API: https://ai.google.dev/gemini-api/docs/live
- Gemini Live Translation: https://ai.google.dev/gemini-api/docs/live-api/live-translate

## 3. 고른 것

**기본 Soniox, 대안 OpenAI.**

1. 두 사람이 번갈아 말하는 화면에서는 **한 세션에서 양방향**이 되는 쪽이 구조가 단순하다. OpenAI 는 방향마다 세션을 따로 열어야 하고, 출력 언어가 13개로 좁다(한국어 포함 여부는 문서에서 확인하지 못했다).
2. 비용 차이가 크다. 2차 테스트 5명 × 15분 = 75분이면 Soniox 약 $0.15, OpenAI 약 $2.55.
3. 자막을 우리가 조립할 수 있다(Soniox 토큰 → 원문/번역 분리). OpenAI 는 자막 델타가 오지만 오디오까지 같이 와서 재생 경로가 하나 더 늘어난다.

Azure 는 자동 언어 식별·음성 스타일 보존이 가장 좋지만 시간당 단가가 높고 SDK 의존이 커서, 사용자 테스트 뒤 품질이 모자랄 때 올리는 카드로 둔다.

## 4. 우리 구현

- `backend/app/interp.py` — `/interp/stream` WebSocket. 브라우저 PCM16(16 kHz mono) → 제공자 → 자막·음성.
  - `soniox`: `translation.type=two_way` 로 a↔b 한 세션. 토큰을 원문/번역으로 나눠 `caption` 이벤트로 보낸다.
  - `openai`: `/v1/realtime/translations`. `session.update` 로 출력 언어를 정하고 오디오를 계속 append. 번역 음성은 `audio` 이벤트로 그대로 재생.
  - `fake`: 키 없이 파이프만 검사(시험 모드). 화면에 "시험 모드"라고 밝힌다. `INTERP_ALLOW_FAKE=1` 일 때만.
- 키는 서버에만 둔다(`SONIOX_API_KEY` / `OPENAI_API_KEY`). 브라우저로 내보내지 않는다.
- 한 세션 **180초** 상한, 오디오 누적 상한으로 비용·악용을 막는다.
- 서버는 오디오를 저장하지 않는다. 화면에서 나가면 마이크를 즉시 끈다.
- 첫 사용 전 동의: 보내는 것·받는 곳(제공자)·국외 이전·보관 안 함·민감정보 주의.

## 5. 아직 정해야 할 것

1. **무료/유료 등급**: Gemini 무료 키는 입력이 제품 개선에 쓰일 수 있다. Soniox·OpenAI 는 유료 API 전제다. 어느 등급으로 시연할지.
2. **개인정보 처리방침**: 음성 국외 이전·제3자 제공 조항. 지금 앱에는 통역용 조항이 없다(동의 창은 임시).
3. **로그**: 오류 추적을 위해 자막 일부를 남길지. 남긴다면 보관 기간·접근 권한을 정해야 한다.
4. **실측**: 같은 문장으로 Soniox·OpenAI 지연을 재서 표에 넣는다(키 필요).

## 6. 참고 저장소

- ufal/whisper_streaming — 스트리밍 STT 기준 구현: https://github.com/ufal/whisper_streaming
- DeepL 공식 Python 예제(Voice CLI): https://github.com/DeepL/deepl-python/tree/main/examples/voice/cli
- Azure Speech SDK 샘플(번역·Live Interpreter): https://github.com/Azure-Samples/cognitive-services-speech-sdk
