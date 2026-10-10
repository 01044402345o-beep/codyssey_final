# 참고문헌 — 말하기 채점 설계 근거

작성: 2026-10-07. 조사 범위(사용자 승인): ① 신경망 VAD 와 에너지 기반 VAD ② Whisper 환각과 no_speech 신호 ③ L2 발음·말하기 자동평가(ASR 기반 vs LLM 기반).
주제마다 조사 에이전트 1개가 원문을 찾아 확인했다. **지어낸 인용은 넣지 않았다.** 원문을 열지 못하고 초록·검색 요약만 본 것은 `(초록만)` 으로 표시했다.
결정 기록은 `speak-hallucination.md`, 설계 요약은 `backend/README.md` 3-1절.

## A. 말소리 검출(VAD) — 데시벨이 아니라 신경망

| # | 문헌 | 우리 설계와의 관계 |
|---|---|---|
| A1 | ITU-T (2005). *G.729 Appendix II: Optimization of the Annex B VAD for VoIP*. https://itu.int/dms_pubrec/itu-t/rec/g/T-REC-G.729-200508-S!AppII!SUM-HTM-E.htm (요약 페이지) | 표준 문서가 고전 VAD 의 저 SNR·고소음 성능 저하를 인정 |
| A2 | Sohn, J., Kim, N. S., & Sung, W. (1999). A statistical model-based voice activity detection. *IEEE SPL*, 6(1). (초록만) | 에너지 방식의 소음 취약성을 통계 모델로 보완하려 한 고전 |
| A3 | Silero Team. *Silero VAD* 와 Wiki "Quality Metrics". https://github.com/snakers4/silero-vad/wiki/Quality-Metrics | ROC-AUC v6 0.97 / WebRTC 0.73, 환경소음만 있는 ESC-50 정확도 v6 0.87 / WebRTC 0. **벤더 자체 평가**. 우리 실측(큰 잡음·신호음 → 말소리 0초)과 같은 방향 |
| A4 | Jia, F., Majumdar, S., & Ginsburg, B. (2021). MarbleNet. *ICASSP 2021*. https://arxiv.org/abs/2010.13886 (초록만) | 경량 신경망 VAD 의 다른 예 |
| A5 | Bredin, H. et al. (2020). pyannote.audio. *ICASSP 2020*. https://arxiv.org/abs/1911.01255 (초록만) | 두 번째 검출기로 쓴 pyannote 계열의 기반. 실제로는 segmentation-3.0 ONNX(onnx-community, MIT)를 서버에서 실행 |
| A6 | Plaquet, A., & Bredin, H. (2023). Powerset multi-class cross entropy loss for neural speaker diarization. *Interspeech 2023*. https://arxiv.org/abs/2310.13025 (초록만) | segmentation-3.0, 검출 임계값 하이퍼파라미터 불필요 |
| A7 | Bain, M. et al. (2023). WhisperX. *Interspeech 2023*. https://arxiv.org/abs/2303.00747 | VAD 로 자른 뒤 Whisper → TED-LIUM WER 10.52→9.70, "무음 구간 환각 회피" |
| A8 | Aliyev, A. (2024). DISPLACE 2023 system description. https://arxiv.org/abs/2406.15516 | Silero 임계값 0.15/0.5/0.75 에서 놓침 17.3/30.5/35.4%, 오탐 5.4/2.1/1.7% — 임계값은 놓침과 오탐의 맞교환 |
| A9 | Pîrlogeanu, G. et al. (2024). Hybrid-diarization system… DISPLACE 2024. *Interspeech 2024*. https://www.isca-archive.org/interspeech_2024/pirlogeanu24_interspeech.pdf | **두 검출기 합의의 직접 근거이자 경고**: Silero·pyannote 다수결 → 오탐 최저(4.72) 대신 놓침 증가(3.95), 총오류는 단독보다 나쁨 |
| A10 | Han, H., & Kumar, N. (2024). Cross-talk robust multichannel VAD. https://arxiv.org/abs/2402.09797 (초록만) | VAD 는 '사람 말'을 찾을 뿐 '본인'을 찾지 않는다 — TV·옆 사람 말은 통과 |
| A11 | Yang, G. et al. (2026). Foreground voice activity detection. https://arxiv.org/abs/2609.19856 (초록만) | 같은 한계(배경 화자) |

## B. Whisper 환각과 신뢰도 신호, 이종 모델 교차검증

| # | 문헌 | 우리 설계와의 관계 |
|---|---|---|
| B1 | Radford, A. et al. (2022/2023). Robust Speech Recognition via Large-Scale Weak Supervision. https://arxiv.org/abs/2212.04356 | 원문: *"the probability of the <\|nospeech\|> token alone is not sufficient … combining the no-speech probability threshold of 0.6 and the average log-probability threshold of −1 makes the voice activity detection of Whisper more reliable."* |
| B2 | openai/whisper `transcribe.py`. https://github.com/openai/whisper/blob/main/whisper/transcribe.py | 기본값 no_speech 0.6, logprob −1.0, compression 2.4 (AND 규칙) — 우리 필터의 두 번째 규칙 |
| B3 | Koenecke, A. et al. (2024). Careless Whisper. *FAccT '24*. https://arxiv.org/html/2402.08021v2 | 세그먼트 1.4% 환각(38% 유해). 환각 유발 오디오 187개를 **AssemblyAI** 등 비-Whisper 6종에 넣으면 유사 환각 **0건** — 이종 모델 교차검증의 가장 직접적 근거 |
| B4 | Barański, M. et al. (2025). Whisper hallucinations induced by non-speech audio. *ICASSP 2025*. https://arxiv.org/abs/2501.11378 | 비음성 30만 건 중 40.3% 환각, 상위 "thank you"·"thanks for watching"·"so". Silero VAD 앞단 → 0.2% |
| B5 | Wang, Y. et al. (2025). Calm-Whisper. *Interspeech 2025*. https://arxiv.org/abs/2505.12969 (초록만) | 디코더 헤드 3개가 비음성 환각 75%+ — 모델 수정 방식이라 API 사용자는 적용 불가 |
| B6 | Fiscus, J. G. (1997). ROVER. *IEEE ASRU*. https://people.csail.mit.edu/joe/sctk-1.2/doc/rover/rover.htm | 다중 ASR 정렬·투표로 WER 상대 11.8–12.5% 감소 — 다중 시스템 결합의 고전 |
| B7 | Jiang, H. (2005). Confidence measures for speech recognition: A survey. *Speech Communication*, 45. (초록만) | ASR 신뢰도 추정 표준 서베이 |
| B8 | Frieske, R., & Shi, B. E. (2024). Hallucinations in Neural ASR. https://arxiv.org/abs/2401.01572 (초록만) | WER 만으로는 환각 모델을 구분 못함 |
| B9 | Karbalaie, A. et al. (2026). Cross-Model ASR Disagreement… *Frontiers in AI*. https://arxiv.org/abs/2604.14152 (초록만) | ASR 8종 간 불일치 구간에 오류 집중 — 참조 없는 불확실성 신호 |
| B10 | Barański, M. et al. (2026). HALAS. *Interspeech 2026*. https://arxiv.org/abs/2606.23048 (초록만) | **반대 근거**: 최신 ASR 들의 환각 어휘가 겹친다 → 합의 ≠ 진실. 같은 계열(Groq·OpenAI Whisper)끼리의 합의는 독립 신호가 아니다 |

## C. L2 발음·말하기 자동평가 — ASR 기반 vs LLM 기반

| # | 문헌 | 우리 설계와의 관계 |
|---|---|---|
| C1 | Witt, S. M., & Young, S. J. (2000). Phone-level pronunciation scoring… *Speech Communication*, 30(2). https://mi.eng.cam.ac.uk/~sjy/papers/wiyo00.pdf (초록만) | GOP — '진짜 발음 점수'의 고전 기준. 단어 일치율로 대체 불가 |
| C2 | Eskenazi, M. (2009). An overview of spoken language technology for education. *Speech Communication*, 51(10). (서지만) | CAPT 개관 |
| C3 | El Kheir, Y., Ali, A., & Chowdhury, S. A. (2023). Automatic Pronunciation Assessment – A Review. *Findings of EMNLP 2023*. https://doi.org/10.18653/v1/2023.findings-emnlp.557 (초록만) | 음소·운율 두 차원 — 우리 점수는 둘 다 재지 않음 |
| C4 | Loukina, A., & Buzick, H. M. (2017). ETS RR-17-42. https://www.ets.org/research/policy_research_reports/publications/report/2017/jycv.html (초록만) | ASR 오류가 점수 왜곡으로 — 우리 점수도 STT 품질에 종속 |
| C5 | Michot, J. et al. (2024). Error-preserving ASR of Young English Learners' Language. *ACL 2024*. https://arxiv.org/abs/2406.03235 (초록만) | **한계**: 언어모델이 강한 ASR 은 학습자 오류를 '교정'해 전사 → 과대평가 가능 |
| C6 | Liu, H. et al. (2026). Unlocking LALMs for Interactive Language Learning. *Findings of EACL 2026*. https://arxiv.org/abs/2601.14744 (초록만, 교정률 수치는 검색 요약 — 인용 주의) | C5 의 정량화 시도 |
| C7 | Wang, K. et al. (2025). LMMs as alternatives for pronunciation assessment. https://arxiv.org/abs/2503.11229 (초록만) | GPT-4o zero-shot 은 문장 수준 '경쟁력', 전통 방법과 결합 권고 |
| C8 | Wang, K. et al. (2025). Fine-tuning LMMs for APA. https://arxiv.org/html/2509.15701v1 | zero-shot "extremely poor", 파인튜닝 후에도 음소 수준 PCC ≈0.39 |
| C9 | Wang, C. et al. (2025). When Audio and Text Disagree. *EMNLP 2025*. https://arxiv.org/abs/2508.15407 (초록만) | 오디오 LLM 은 충돌하는 텍스트를 따른다 — 무음에 95~100점이 나온 메커니즘 |
| C10 | Billa, J. (2026). When Audio-LLMs Don't Listen. https://arxiv.org/html/2602.11488v1 | "들은 것을 믿으라" 지시에도 **Gemini 2.0 Flash** 가 충돌 텍스트를 16.6% 따름(텍스트끼리 1.6%) |
| C11 | Geng, H. et al. (2026). Prompt-Free MDD. https://arxiv.org/abs/2604.22133 | 정답 텍스트를 주면 '정확한 발음'을 환각 → 추론 시 텍스트를 빼라 = 우리 '목표 문장 미전송' |
| C12 | Wang, R., & Sun, K. (2026). Prior over Evidence. https://arxiv.org/abs/2606.15325 (요약 페이지) | LLM 진단 근거 39.6% 가 그럴듯하지만 틀림 → LLM 은 '외부 측정치의 설명자'로만 = 우리 diff 기반 피드백 |
| C13 | OWASP GenAI (2025). LLM06:2025 Excessive Agency. https://genai.owasp.org/llmrisk/llm062025-excessive-agency/ | 판단·승인은 LLM 이 아니라 하위 시스템이 — 피드백 AI 는 점수를 바꿀 수 없다 |

## 문헌이 설계에 준 결론과 남은 한계

- **채택 근거**:
  - 데시벨 대신 신경망 VAD (A1·A3·B4·A7)
  - 전사에 목표 문장 미전송 (C9·C10·C11)
  - no_speech 단독 불충분 (B1) → 이종 모델 교차검증 (B3·B9·B6)
  - 점수는 코드, LLM 은 설명자 (C12·C13)
- **우리 실측으로 다시 확인한 것**:
  - 같은 1초 무음에 Groq whisper-large-v3 는 "you"(no_speech 0.70), OpenAI whisper-1 은 "you"(0.94), AssemblyAI 는 "" — B1·B3·B10 과 일치
- **남은 한계 (발표·문서에 명시)**
  - 점수는 '두 전사 모두에서 들린 단어 일치율' — 음소·운율 정확도 아님 (C1·C3). Whisper 의 자동 교정으로 과대평가될 수 있음 (C5).
  - 두 검출기 AND 는 오탐을 줄이지만 학습자의 작은·서툰 발화를 놓칠 수 있음 (A9·A8). 실제 학습자 녹음으로 거부율을 재야 한다.
  - VAD 는 TV·옆 사람 말을 막지 못함 (A10·A11).
  - 임계값(0.85, 0.6/−1.0)은 문헌·관례 값이며 우리 데이터로 보정하지 않았다 (B1·B7).
