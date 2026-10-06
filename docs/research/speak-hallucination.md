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

## 3. 결정 — 권한을 나눈다 (2차: transcribe_app 방식 적용, 2026-10-07)

1차 결정(PR #10)은 브라우저 **음량(RMS) 무음 판정** + Gemini 블라인드 받아쓰기였다. 음량 판정은 데시벨 방식이라
큰 잡음·신호음을 말소리로 통과시킨다. 그래서 seongbin45/transcribe_app 의 방식(신경망 VAD + 전용 STT)으로 바꿨다.

```
녹음 → [서버·코드] PyAV 디코드 16kHz mono → Silero 신경망 VAD          (app/speech_vad.py)
          말소리 0구간 → 끝. 외부 API 0회
     → [전용 STT] 말소리 구간만, 목표 문장 없이, temperature 0, en       (app/stt_providers.py)
          Groq Whisper → OpenAI Whisper → AssemblyAI, 공급자마다 최소 30회
     → [코드] 환각 필터(no_speech_prob·avg_logprob·알려진 문구)         (speech_compare.filter_segments)
     → [코드] 단어 비교 → 일치율·빠진/다른/덧붙인 단어                  (speech_compare.compare)
     → [AI] 오디오 없이 상황·목표·받아쓴 문장·차이만 받아 피드백 문장   (main.py FEEDBACK_PROMPT)
            AI 가 준 score 는 버린다. 실패하면 사실 기반 문장 틀
     → [코드] 복습 목록 저장 여부                                      (mockup/ai.js weakDecision)
```

| 결정 | AI | 코드 |
|---|:-:|:-:|
| 말이 있었는가 | | ✅ Silero VAD(신경망, 데시벨 아님) + 전사 세그먼트의 no_speech 신호 |
| 무엇을 말했는가 | ✅ 전용 STT(목표 문장 모름) | |
| 맞게 말했는가 · 점수 | | ✅ |
| 복습 목록 저장 | | ✅ |
| 피드백 문장 | ✅ Gemini(점수 변경 불가, 오디오 없음) | 실패 시 문장 틀 |

**음량 판정 대비 실측(로컬, Silero v6, faster-whisper 1.2.1)** — 큰 소리지만 말소리가 아닌 입력:

| 입력 | RMS | Silero 말소리 |
|---|---:|---:|
| 1초 디지털 무음 | 0 | 0초 |
| 백색잡음 σ=0.3, 2초 | 0.30 | 0초 |
| 440Hz 신호음 진폭 0.5, 2초 | 0.35 | 0초 |
| 1kHz 단속 신호음 | ≈0.14 | 0초 |
| Chrome 실제 녹음: 440Hz 1.5초(webm/opus) | – | 0초 |
| Chrome 실제 녹음: 소리 입력 없는 스트림(프레임 없는 110바이트) | – | 0초(400 아님) |
| TTS "I have a peanut allergy."(wav·webm·mp4·ogg) | – | 1.3초(검출) |

## 3-1. transcribe_app 정독·커밋 교차검증 (30커밋, 2026-08-29~09-01)

| 항목 | 문서·커밋 주장 | 코드 대조 | 우리 적용 |
|---|---|---|---|
| VAD | Silero 로 발화 구간만 전사 | ✅ 첫 커밋 `d0abceb` 부터 `get_speech_timestamps(..., VadOptions(min_silence_duration_ms=500, speech_pad_ms=200))`, 구간 없으면 `[]` | 같은 함수·옵션 |
| 오디오 | 16kHz mono | ✅ ffmpeg `-ac 1 -ar 16000 pcm_s16le` | PyAV 로 같은 형식 |
| 전사 | 전용 STT(Whisper·Groq·AssemblyAI) | ✅ 어떤 경로에도 목표 문장 없음 | 같은 원칙(테스트로 강제) |
| 환각 필터 | "필터 정상 동작" | ⚠️ `no_speech_prob>0.85`+문구 목록이 **로컬 엔진에만** 있음 | 모든 공급자에 적용 + openai/whisper 기본 규칙 추가 |
| 모델 하드코딩 | LLM 은 제거(`8baf38c`) | ⚠️ STT 는 고정(`whisper-large-v3-turbo`, `universal-3-5-pro`, `precision-2`) | `/models` 동적 선택, AssemblyAI 는 `speech_models` 생략 |
| 재시도 | pyannoteAI 만 추가(`1e9f537`) | ⚠️ Groq·AssemblyAI 재시도 없음 | 최소 30회 |
| 타임아웃 | – | ⚠️ AssemblyAI `requests` 4곳 timeout 없음 | 모든 요청 timeout |
| 테스트 | "단위 테스트 6개" 등 다수 언급 | ⚠️ 30커밋 어디에도 테스트 파일 없음 → 재현 불가 | 테스트를 커밋·CI 실행 |
| 실측 수치 | Groq RTF 0.017~0.030 등 | ⚠️ `output/` gitignore → 원자료 없음, 참고만 | 원자료(jsonl)와 함께 기록 |
| LLM 권한 | 제안만·근거 인용 대조·교차 제공자·사람 승인 | ✅ `llm_refine.py` 와 일치 | 같은 원칙 |

### 공급자 응답 형태 — 실제 호출 검증(배포 서버 `STT_SELFTEST=1`)
키는 Render 에만 있으므로 배포 서버가 직접 호출해 `/health` 의 `stt_selftest` 로 보고한다. 결과는 아래에 채운다.

| 가정 | 공급자 | 결과 |
|---|---|---|
| `verbose_json` 세그먼트에 `no_speech_prob`·`avg_logprob` 가 있다, 현재 whisper 모델 목록 | Groq | (배포 후 기록) |
| whisper 계열 `verbose_json` 필드 / gpt-4o-transcribe 제외 | OpenAI | (배포 후 기록) |
| `speech_models` 생략 가능, `language_code: en`, 무음 응답 | AssemblyAI | (배포 후 기록) |

## 4. 한계 (정직하게)
- 점수는 **단어 일치율**이다. 억양·강세·음소 수준의 **발음 품질은 재지 않는다**. 그러려면 Azure Pronunciation Assessment 같은 음향 기반 채점이 필요하다.
- Whisper 도 무음·잡음 구간에서 문장을 지어낼 수 있다("Thanks for watching" 류). 그래서 VAD 로 말소리 구간만 보내고, 세그먼트의 no_speech 신호와 문구 목록으로 한 번 더 거른다. 말소리처럼 들리는 소음(TV 대화 등)은 VAD 를 통과할 수 있다.
- AssemblyAI 는 세그먼트별 no_speech 확률을 주지 않아 문구 규칙만 적용된다(보충 공급자라 1순위 Groq 가 실패할 때만 쓰인다).
- 정상 발화는 외부 호출이 2번이다(전사 + 피드백). 말소리가 없으면 0번.

## 5. 검증
- 수정 전·후 실측: `docs/score_측정_실행법.md` "무음 실측"
- 테스트: `backend/tests/test_speech_vad.py`(실제 Silero: 무음·큰 잡음·신호음·실제 브라우저 녹음), `backend/tests/test_speak_pipeline.py`(STT 요청에 목표 문장 없음, 말소리 없으면 외부 호출 0회, 환각 필터, 공급자 체인·쿨다운, AI 점수 무시), `e2e/test_silence.py`(디지털 무음·큰 440Hz 신호음 → 서버 VAD 판정)
- 뮤테이션: VAD 게이트 제거 / STT 요청에 목표 문장 삽입 / 환각 필터 제거 / 공급자 폴백 제거 → 각각 테스트 실패
