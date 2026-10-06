# 말하기 채점 환각과 "AI 최소 권한" 설계 근거

작성: 2026-10-07 · 대상: `POST /speak-check` · 결정: 받아쓰기(AI) → 판정(코드) → 피드백(AI, 오디오 없음)

## 1. 문제 — 배포 서버 실측

기존 구조는 **녹음 + 목표 문장을 한 번에** Gemini 에 주고 `{heard, score, fix_one, tip}` 를 받았다.
프롬프트에 "무음이면 heard 를 비우고 점수를 빼라"고 적혀 있었다.

| 입력 (목표: "I have a peanut allergy.") | 호출 | 결과 |
|---|---:|---|
| **1초 완전 무음 WAV** | 10 | **10/10 `usable:true`, heard = 목표 문장 그대로, 95~100점** |
| 맞게 읽은 음성 (macOS TTS) | 3 | 3/3 heard 정확, 95~100점 |
| 다른 문장 "Where is the subway station?" | 3 | 3/3 heard 정확, 10~20점 |

→ 소리가 분명하면 정직하지만, **오디오에 근거가 없으면 목표 문장으로 빈칸을 채운다.** 연습하지 않아도 만점이 나온다.
원본: 측정 스크립트 `backend/scripts/measure_score_rate.py`, 2026-10-06 배포 `01d29ae`.

## 2. 조사 — 출처 집단 4개를 나눠 조사

한쪽 출처에 치우치지 않도록 학술·상용·개발자 커뮤니티·설계 지침을 각각 조사했다(각 집단 6~15개 출처).

| 원칙 | 학술 | 상용 | 커뮤니티 | 지침 |
|---|:-:|:-:|:-:|:-:|
| 모델 **앞에서 무음 차단** (VAD·음량) | ✅ | ✅ | ✅ 8곳 | ✅ |
| AI 에게 **목표 문장을 주지 않고** 받아쓰기 | ✅ | ✅ | ✅ | ✅ |
| **점수·저장은 코드**가 결정 (받아쓴 문장 ↔ 목표 비교) | ✅ | ✅ | ✅ | ✅ 6곳 |
| AI 는 계산된 결과로 **피드백 문장만** | 간접 | ✅ | ✅ | ✅ |
| "무음이면 비워라" **프롬프트만으로는 해결 안 됨** | ✅ | – | ✅ | – |

### 학술 — 이름 붙은 현상이다
- *When Audio and Text Disagree: Revealing Text Bias in LALMs* (EMNLP 2025, arXiv 2508.15407): 오디오와 글이 충돌하면 모델이 글을 따르고, 그러면서도 확신한다. 프롬프트 수정은 일부만 효과.
- *All That Glitters Is Not Audio* (arXiv 2604.24401): 오디오를 빼도 오디오 모델 8종이 점수의 60~72% 유지 — 답이 글과 사전 지식에서 나온다.
- *Prompt-Free Mispronunciation Detection* (arXiv 2604.22133): 목표 문장을 주면 인식이 목표 쪽으로 쏠린다("canonical information leakage").
- *Careless Whisper* (FAccT 2024), *Whisper hallucinations on non-speech* (ICASSP 2025): 무음·비음성 구간에서 문장을 지어낸다.
- *WhisperX* (Interspeech 2023): VAD 를 먼저 거치면 환각이 줄어든다.
- *Zero-Shot Speech LLMs for L2 Speech* (SLaTE 2025): LLM 채점은 나쁜 발화에 점수를 과하게 준다.
- ETS *Atypical Inputs* (NAACL 2018): 채점 전에 "채점 불가 응답" 필터를 둔다.

### 상용 — 9곳 중 "목표 문장을 본 LLM 이 받아쓰기·점수를 정하는" 곳 0곳
- **Azure Pronunciation Assessment**: ASR + 참조 문장 정렬로 점수. 무음은 점수 대신 `NoMatch`(`InitialSilenceTimeout`). LLM(gpt-4o)은 인식된 문장의 내용 평가에만 권장.
- **SpeechAce**: `error_no_speech`, `response_no_speech`. 프롬프트와 "너무 비슷한" 응답은 0점.
- **ETS SpeechRater**: 채점 불가 응답 필터 → 사람 검토.
- **Duolingo**: 판정은 인식기 + 문장 비교, GPT-4 는 이미 난 판정을 설명(Explain My Answer).
- 공통 구조: 음성 감지 → 인식/정렬 → **코드 게이트** → (선택) LLM 이 피드백 문장 작성.

### 개발자 커뮤니티 — 실제로 효과 있던 것
- OpenAI 포럼: gpt-4o-transcribe 가 무음·짧은 구간에서 **프롬프트의 글을 출력**(우리와 같은 증상). 프롬프트 수정으로는 해결 안 됨.
- Whisper GitHub 토론: Silero VAD + 음량 기준이 가장 일관된 해결.
- Gemini 로 발음 앱을 만든 두 사례 모두 **받아쓰기 후 코드 비교**(`difflib`) 또는 **무음 차단**을 밖에 붙였다. 한 사례는 "정답 쪽으로 듣게 만든다"며 맞춤 어휘조차 넣지 않았다.

### 설계·보안 지침 — "AI 최소 권한"
- OWASP LLM06 Excessive Agency: *"Implement authorization in downstream systems rather than relying on an LLM to decide…"*
- OWASP LLM05: *"Treat the model as any other user, adopting a zero-trust approach…"*
- Google SAIF: *"Use least-privilege principle as the upper bound…"*
- NIST AI 600-1: confabulation("확신에 찬 잘못된 내용"), 정답 데이터와 대조, 적대적 테스트.
- Anthropic: 모델에게 "모른다"고 할 길을 열어 주고, 중요한 정보는 검증한다. 아첨(sycophancy) 연구: 모델은 기대에 맞는 답을 한다.

## 3. 결정 — 권한을 나눈다

```
녹음 → [브라우저] 음량 감지: 소리 300ms 미만이면 전송하지 않음      (mockup/ai.js isSilent)
     → [AI ①] 목표 문장 없이 받아쓰기만, temperature 0              (main.py TRANSCRIBE_PROMPT)
     → [코드] 빈 값·[silence] 류면 채점하지 않음                    (speech_compare.is_placeholder)
     → [코드] 단어 비교 → 일치율·빠진/다른/덧붙인 단어               (speech_compare.compare)
     → [AI ②] 오디오 없이 상황·목표·받아쓴 문장·차이만 받아 피드백   (main.py FEEDBACK_PROMPT)
               AI 가 준 score 는 버린다. 실패하면 사실 기반 문장 틀.
     → [코드] 복습 목록 저장 여부                                   (mockup/ai.js weakDecision)
```

| 결정 | AI | 코드 |
|---|:-:|:-:|
| 말이 있었는가 | | ✅ (브라우저 음량 + 받아쓰기 결과 검사) |
| 무엇을 말했는가 | ✅ (목표 문장 모름) | |
| 맞게 말했는가 · 점수 | | ✅ |
| 복습 목록 저장 | | ✅ |
| 피드백 문장 | ✅ (점수 변경 불가, 오디오 없음) | 실패 시 문장 틀 |

## 4. 한계 (정직하게)
- 점수는 **단어 일치율**이다. 억양·강세·음소 수준의 **발음 품질은 재지 않는다**. 그러려면 Azure Pronunciation Assessment 같은 음향 기반 채점이 필요하다.
- 받아쓰기 AI 도 무음·소음에서 지어낼 수 있다(목표 문장 없이도 Whisper 류는 "Thanks for watching" 같은 문장을 만든다). 그래서 브라우저 무음 차단을 앞에 둔다. 서버만 직접 호출하면 이 차단을 거치지 않는다.
- 정상 발화는 AI 호출이 2번이다(받아쓰기 + 피드백). 무음·인식 실패는 1번 또는 0번.

## 5. 검증
- 수정 전·후 실측: `docs/score_측정_실행법.md` "무음 실측"
- 테스트: `backend/tests/test_speak_pipeline.py`(받아쓰기 프롬프트에 목표 문장이 없는지, 무음은 점수·피드백 없음, AI 점수 무시), `mockup/ai.test.js`(`isSilent`), `e2e/test_silence.py`(무음 녹음은 전송 0회)
