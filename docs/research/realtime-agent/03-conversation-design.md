# 3. 실시간 음성 롤플레이 — 대화·학습 설계 조사

작성: 2026-10-20 · 대상: 마디(MADI) 확장 계획 1순위 "AI 가 입국심사관·점원 역할로 영어로 묻고 사용자가 말로 답하는 실시간 음성 회화 상대"(`docs/user-test/results.md` 5절 7-2)

읽은 자료(읽기만 함, 수정 없음):
- `codyssey_navfix/docs/user-test/results.md` (P1–P6, 설문 S1–S11)
- `codyssey_navfix/docs/product/conversation-practice-review.md` (공통 30문장 `talk`)
- `codyssey_navfix/mockup/app.js` (`speakHtml` 2179행, `sheetHtml` 1801행, `uploadSpeech` 2305행), `mockup/ai.js` (`weakDecision` 285행, `WEAK_THRESHOLD = 70`)
- `codyssey_navfix/backend/app/main.py` (`FEEDBACK_PROMPT` 639행)
- `codyssey_navfix/docs/measurement/score_측정_실행법.md`, `LATENCY_분석과_측정.md`, `docs/research/references.md`

표기 규칙: **[근거]** 문헌이 직접 말하는 것 · **[우리 자료]** 저장소 문서·코드에서 확인한 것 · **[설계 판단]** 근거에서 추론한 우리 결정(검증 전). 원문을 열지 못하고 초록이나 2차 요약만 본 문헌은 `(초록·2차)`로 표시했다.

---

## 0. 핵심 사용자 가정 검증

| 가정 | 저장소 자료 | 판정 |
|---|---|---|
| 40–60대가 많다 | 설문 연령: 50대 5 · 40대 2 · 60대 이상 2 · 20대 2 → **40대 이상 9/11** (results.md 6.3) | **지지됨** (n=11, 익명, 한 사람이 모은 표본) |
| 자유여행을 준비한다 | P4 "여행을 앞두고 기간별·장소를 특정해 연습", 설문 제목이 "여행 중 불편사항" | 지지됨 |
| 영어 수준이 낮거나 기초다 | P1–P6 영어 수준은 **모두 "미기록"**. 질적 신호만 있음: P6 "나처럼 영어까막눈은", S7(60대+) "통역앱을 써도 통역이 안되니", S6 "현지인이 자국언어만 사용했을 때 답답함" | **부분 지지** — 측정값은 없다 |
| 말하기 불안이 있다 | FLCAS 같은 측정 없음. 직접 언급도 없음. 간접 신호: P6·S6 이 "상대 질문을 영어로 미리 보여 달라"(준비하고 싶다는 뜻), S10 "내 발음을 들어 보고 싶다" | **미검증 — 가설로 둔다**. 2차 테스트에서 짧은 불안 문항(예: FLCAS 일부 문항)을 넣어 확인할 것 |
| 디지털 리터러시가 낮은 사용자가 있다 | P2 "다른 브라우저 여는 것 자체를 생각하지 못해 앱을 닫아 버림" | 지지됨 — UI 는 버튼 하나·단계 적게 |

가장 많이 불편한 상황(Q3): **낯선 지역의 교통 7/11**, 언어 장벽·식당 4/11.

---

## 1. 학습 원리 요약 (근거)

### 1-1. 과업 중심 교수(TBLT)·롤플레이

- **[근거]** TBLT 프로그램의 효과는 양(+)이지만 크기는 연구 선정 방식에 따라 크게 달라진다. Bryfonski & McKay(2019) 메타분석은 d = 0.93 을 보고했으나, Boers & Faez 는 그 27개 비교연구가 대부분 목적에 맞지 않는다고 재검토했고, Xuan·Cheung·Liu(2025) 재분석은 g = 0.61 로 더 작은 효과를 냈다. (초록·2차)
  - Bryfonski, L., & McKay, T. H. (2019). TBLT implementation and evaluation: A meta-analysis. *Language Teaching Research*, 23(5). https://todoele.net/bibliografia/tblt-implementation-and-evaluation-meta-analysis
  - Boers, F., & Faez, F. (2023/2026). Meta-analysis to estimate the relative effectiveness of TBLT programs: Are we there yet? *Language Teaching Research*, 30(3). https://journals.sagepub.com/doi/reader/10.1177/13621688231167573
- **[근거]** Willis(1996)의 과업 틀은 **사전 과업(주제·어휘 제시) → 과업 수행(교사는 지켜보되 고치지 않음) → 언어 초점(끝에서 형태를 본다)** 순서다. 형태 교정을 마지막에 둔다는 점이 PPP 와 다르다. (2차)
  - Willis, J. (1996). *A Framework for Task-Based Learning*. Longman. 요약: https://www2.vobs.at/Ludescher/Grammar/task_based_learning.htm
- **[근거]** 상호작용(의미 협상·피드백)이 습득에 도움이 된다는 메타분석이 있다. (서지만 확인, 효과크기 원문 미확인)
  - Mackey, A., & Goo, J. (2007). Interaction research in SLA: A meta-analysis and research synthesis. In *Conversational Interaction in SLA*, OUP. https://eprints.lancs.ac.uk/id/eprint/59863/
- **[설계 판단]** 입국심사·버스 타기는 목표가 분명한 "과업"이다(예: 입국 도장 받기, 맞는 정류장에서 내리기). 회화 연습을 "문장 따라 말하기"가 아니라 **과업 완수**로 정의한다.

### 1-2. 대화형 시스템(챗봇·음성 AI)의 효과

- **[근거]** 대화형 CALL 메타분석: L2 숙달도에 중간 효과 **d = 0.58**(17개 연구, 효과크기 100개). 목표 지향·시스템 주도형 상호작용, 교정 피드백 제공, 게임 요소가 효과를 뒷받침했고, **숙달도가 낮은 학습자**에게서 효과가 확인됐다.
  - Bibauw, S., Van den Noortgate, W., François, T., & Desmet, P. (2022). Dialogue systems for language learning: A meta-analysis. *Language Learning & Technology*, 26(1), 1–24. https://scholarspace.manoa.hawaii.edu/items/2e7868cd-8f01-43ca-ac54-44425cd487a9
- **[근거]** 말하기에 한정한 3수준 메타분석: **g = .61**(16개 연구, 효과크기 89개). 유의한 조절변수는 시스템 유형·**의미 제약 정도**·모달리티. 숙달도·개입 기간·교정 피드백 유무는 유의하지 않았다. 저자들도 포함 연구 대부분이 **생성형 AI 이전 규칙 기반 시스템**이라고 밝힌다.
  - Hou, Z., & Min, S. (2025). Dialogue-based CALL systems for second language speaking development: A three-level meta-analysis. *ReCALL*. https://www.cambridge.org/core/product/31847710516602398819C5E594038E7B
- **[설계 판단]** 이 근거는 **대본이 있고 의미가 제약된 시스템**에서 나왔다. 우리 `talk` 데이터 기반의 반(半)대본 롤플레이가 근거와 더 가깝다. 완전 자유 대화(LLM 즉흥)는 근거가 더 얇다.

### 1-3. 교정 피드백 (recast · prompt · 명시적 교정)

- **[근거]** 교실 연구 메타분석(15개, N=827): 교정 피드백은 유의하고 지속적인 효과가 있다. 2차 요약에 따르면 **prompt(스스로 고치도록 유도)가 recast(맞는 형태로 다시 말해 줌)보다 효과적**이었고, **어린 학습자가 나이 든 학습자보다 더 많은 이득**을 봤다. (초록·2차)
  - Lyster, R., & Saito, K. (2010). Oral feedback in classroom SLA: A meta-analysis. *SSLA*, 32(2), 265–302. https://www.cambridge.org/core/product/4999EE1C8379B2BF026B148EAF373CA1
- **[근거]** 교사는 recast 를 압도적으로 많이 쓰지만 recast 는 학습자 스스로의 수정(uptake)을 잘 끌어내지 못한다(프랑스어 몰입 교실). 성인 ESL 반에서도 recast 뒤 바르게 반복한 비율은 21%에 그쳤다(Panova & Lyster 2002, 2차 인용). (초록·2차)
  - Lyster, R., & Ranta, L. (1997). Corrective feedback and learner uptake. *SSLA*, 19(1), 37–66. https://escholarship.mcgill.ca/downloads/0p096b851
- **[근거]** 33개 연구 메타분석(구두 교정 피드백). (서지 확인, 결과 수치 원문 미확인)
  - Li, S. (2010). The effectiveness of corrective feedback in SLA: A meta-analysis. *Language Learning*, 60(2), 309–365. https://doi.org/10.1111/j.1467-9922.2010.00561.x
- **[근거] 시점:** 즉시 피드백과 지연 피드백 모두 효과가 있었고, 문법성 판단에서는 즉시 피드백이 약간 앞섰다(중국 중학생 120명). 후속 연구에서는 **숙달도가 낮은 학습자에게는 즉시 피드백만 효과가 있었고**, 숙달도가 높은 학습자는 둘 다 비슷했다.
  - Li, S., Zhu, Y., & Ellis, R. (2016). The effects of the timing of corrective feedback on the acquisition of a new linguistic structure. *Modern Language Journal*, 100(1), 276–295. https://forrt.org/flora-replication-atlas/doi/10.1111/modl.12315/
  - Li, S., Ellis, R., & Shu, D. (2016). The differential effects of immediate and delayed feedback on learners of different proficiency levels. https://researchspace.auckland.ac.nz/handle/2292/28987
- **[설계 판단] 근거 사이의 긴장:** 문헌은 "낮은 수준 학습자에게는 즉시 피드백"을 시사하지만, 대화 흐름을 끊으면 불안이 커질 수 있다(Duolingo 도 같은 이유로 통화 중 피드백을 하지 않는다, 5절). 그래서 **대화 중에는 흐름을 끊지 않는 형태**(상대 역할의 자연스러운 되받기 + 화면에 "이렇게 말해 보세요" 힌트)만 쓰고, **명시적 교정은 대화가 끝난 뒤 한 가지만** 한다. 단, 가장 쉬운 단계(1단계)에서는 "다시 말해 보기"를 바로 제공한다. 이는 prompt 형식이라 Lyster & Saito 의 결과와도 맞는다.

### 1-4. 말하기 불안과 음성 AI

- **[근거]** 외국어 불안은 의사소통 불안·시험 불안·부정적 평가에 대한 두려움으로 구성되며, FLCAS(33문항)로 측정한다. 후속 연구들은 불안과 성취 사이에 일관된 중간 정도의 부(−)의 관계를 보고한다.
  - Horwitz, E. K., Horwitz, M. B., & Cope, J. (1986). Foreign language classroom anxiety. *Modern Language Journal*, 70(2), 125–132. https://doi.org/10.2307/327317
- **[근거]** Google Assistant 활동 2주(대만 중학생 112명, 사전·사후 설문): 의사소통 의지와 자신감이 오르고 말하기 불안이 줄었다. 통제집단은 없다.
  - Tai, T.-Y., & Chen, H. H.-J. (2023). The impact of Google Assistant on adolescent EFL learners' willingness to communicate. *Interactive Learning Environments*. https://scholar.lib.ntnu.edu.tw/en/publications/the-impact-of-google-assistant-on-adolescent-efl-learners-willing-2/
- **[근거]** 음성 챗봇을 쓴 8주 준실험(이란 중상급 60명, 통제집단 있음): 유창성과 말하기 불안을 함께 측정했다. (초록)
  - Azizimajd (2023). *TALE*, Razi University. https://tale.razi.ac.ir/article_2732.html
- **[근거]** ChatGPT 음성 대화 연구는 대부분 작은 표본, 자기보고, 단일집단 사전·사후 설계다(예: 42명 6주, 불안 3.71 → 2.84, 통제집단 없음). 질적 연구들은 "판단받지 않는 환경"이 부정적 평가에 대한 두려움을 줄인다고 보고한다.
  - ChatGPT as a Speaking Partner and Its Association with Reduced Speaking Anxiety among Online EFL Learners (2026). *Journal of Babylon Center for Humanities Studies*. https://bcchj.uobabylon.edu.iq/index.php/bcchj/en/article/view/3341
  - The role of ChatGPT's voice conversation feature in enhancing EFL students' speaking confidence. *ELTIN Journal*. https://e-journal.stkipsiliwangi.ac.id/index.php/eltin/article/view/7154
- **[근거]** 반대 방향의 경고: 서술적 리뷰는 챗봇이 불안에 주는 영향이 **상황과 설계에 따라 다르다**고 결론짓는다. 로봇 보조 학습 메타분석에서는 불안이 높을수록 효과크기가 커지는 의외의 결과도 나왔다. 불안 감소만 따로 묶은 메타분석은 찾지 못했다.
  - Zhang (2026), SHS Web of Conferences 235, 02014. https://www.shs-conferences.org/10.1051/shsconf/202623502014
- **[설계 판단]** "AI 는 판단하지 않는다"가 불안을 낮추는 핵심 기제로 보고된다. 따라서 **점수·빨간 표시·"틀렸습니다"를 대화 중에 보이지 않는다**. 근거 수준이 낮으므로 우리 사용자에게서 직접 확인한다(2차 테스트 문항).

### 1-5. 기다리는 시간(wait time)과 응답 지연

- **[근거]** 교사가 질문 뒤 약 1초 만에 넘어가던 것을 **3초 이상** 기다리면 학생의 답이 길어지고 무응답이 줄었다(Rowe). 수치는 2차 요약에 따라 차이가 커서 정확한 값으로 인용하지 않는다. 질문 뒤 기다림(Wait Time I)과 답 뒤 기다림(Wait Time II)을 구분한다. (2차)
  - Rowe, M. B. (1986). Wait time: Slowing down may be a way of speeding up! *Journal of Teacher Education*, 37(1), 43–50. 요약: https://iris.peabody.vanderbilt.edu/wp-content/uploads/misc_media/fss/pdfs/2018/IRIS_fundamental_skill_sheet_wait-time.pdf
- **[근거]** 10개 언어 모두 말 겹침을 피하고 **턴 사이 침묵을 최소화**한다. 언어 간 평균 간격 차이는 250ms 이내다. (흔히 인용되는 "200ms"는 2차 자료의 표현이라 인용하지 않는다.)
  - Stivers, T., et al. (2009). Universals and cultural variation in turn-taking in conversation. *PNAS*, 106(26), 10587–10592. https://doi.org/10.1073/pnas.0903616106
- **[우리 자료]** 지금 말해 보기 채점은 정상 상태에서 **요청당 약 5초**다(두 전사 병렬 + Gemini 피드백, `score_측정_실행법.md`). 콜드스타트는 아직 측정하지 못했다(`LATENCY_분석과_측정.md`).
- **[설계 판단]** 두 방향을 따로 다룬다.
  1. **사용자에게 주는 시간은 길게.** 학습자, 특히 나이 든 학습자는 응답 준비에 시간이 필요하다(1-7). 침묵을 끊는 재촉은 최소 8초 뒤, 그것도 힌트를 보여 주는 방식으로 한다(2-3).
  2. **AI 의 응답 지연은 짧게, 또는 티 나지 않게.** 사람 대화의 턴 간격은 매우 짧아 5초 침묵은 "고장"처럼 느껴진다. 상대 역할의 다음 대사는 대부분 `talk` 데이터에 이미 있으므로 **미리 TTS 로 만들어 두고**, 분기 판정만 서버에서 한다. 판정을 기다리는 동안 "듣는 중…" 표시와 짧은 맞장구("Okay.")를 낸다.

### 1-6. 비계(scaffolding): 힌트, 한국어 지원, 느린 말

- **[근거]** 비계는 초보자가 혼자서는 못 하는 과업을 해내게 하는 일시적 지원이다. 과업 단순화, 이상적 답과의 차이 표시, 시범 보이기가 포함되며, 능력이 오르면 지원을 줄인다(fading).
  - Wood, D., Bruner, J. S., & Ross, G. (1976). The role of tutoring in problem solving. *Journal of Child Psychology and Psychiatry*, 17(2), 89–100. https://pubmed.ncbi.nlm.nih.gov/932126/
- **[근거]** 의사소통 전략(돌려 말하기, 시간 벌기 표현 등)은 6주 집중 지도로 사용 빈도와 질이 좋아졌다(헝가리 109명). (초록·2차)
  - Dörnyei, Z. (1995). On the teachability of communication strategies. *TESOL Quarterly*, 29(1), 55–85. https://doi.org/10.2307/3587805
- **[근거] 느린 말:** 결과가 엇갈린다. 하중급 학습자에게 느린 말은 이득이 적었지만 빠른 말은 이해를 떨어뜨렸다(Griffiths 1990). 다른 연구는 느린 속도와 구문 단순화의 이득을 보고했다. (초록·2차)
  - Griffiths, R. (1990). Speech rate and NNS comprehension. *Language Learning*, 40(3). 정리: https://jalt-publications.org/jj/articles/2690-pausology-and-listening-comprehension-theory-research-and-practice
- **[근거] 한국어(L1) 지원:** 저숙련 학습자에게 구조화된 L1 지원과 영어 전용 비계를 직접 비교한 연구는 찾지 못했다. 소규모 연구(일본 대학생 17명)는 L1 활용이 발표 불안을 줄였다고 보고했다. **근거가 얇다.**
  - PCE2023 (IAFOR) L1 techniques and L2 presentation anxiety. https://papers.iafor.org/wp-content/uploads/papers/pce2023/PCE2023_69276.pdf
- **[우리 자료]** P3 "speaking 속도 조절이나 듣고 말해보기… 반복 연습 가능한 점에 만족도 높음". 공통 문장에 이미 "Can you speak more slowly, please?"(돌발 상황/천천히)가 있다.
- **[설계 판단]** 비계는 **보이게 시작하고 단계마다 줄인다**: 1단계 = 영어 답 문장 화면 표시, 2단계 = 첫 단어·한국어 뜻만, 3단계 = 숨김(요청할 때만). "Sorry? / More slowly, please." 같은 **되묻기 표현 자체를 과업의 일부로 가르친다**(Dörnyei). 실제 여행에서 가장 쓸모 있는 생존 전략이기 때문이다.

### 1-7. 나이 든 성인의 제2언어 학습

- **[근거]** 노년기 L2 학습은 단일 이론으로 설명할 수 없고, 인지·사회정서·맥락 요인이 함께 작용한다. 소규모 예비연구(12명, 4주 영어)는 실행 기능·자신감·자율성·웰빙에 긍정적 효과를 보고했고, 나이 관련 사회·심리·맥락 요인이 성숙 요인만큼 중요해 보인다고 했다.
  - Pfenninger, S. E., & Singleton, D. 노년기 다언어 학습 비판적 리뷰. *Language Teaching*. https://resolve.cambridge.org/core/journals/language-teaching/article/abs/critical-review-of-research-relating-to-the-learning-use-and-effects-of-additional-and-multiple-languages-in-later-life/DBABAAD4094B635DB2D606733927B18C
  - Pfenninger, S. E., & Polz, S. (2018). *Journal of the European Second Language Association*, 2(1). https://euroslajournal.org/articles/36
- **[근거]** 65세 이상 스페인어 초급 7개월 과정에서 **작업기억**이 학습 궤적을 예측했다(학회 초록). 64–75세 30주 개입 연구(Kliesch et al. 2022, *Applied Linguistics*). (초록)
  - https://research.rug.nl/en/publications/cognitive-benefits-of-learning-additional-languages-in-old-adulth/ · https://eurosla30.dryfta.com/program-schedule/program/detail/28/session-1b
- **[근거]** 노인은 빠른 말을 더 어려워하며, 원인은 고주파 청력 손실·시간 처리 같은 감각 요인과 인지 요인이 섞여 있다. 노인은 스스로 고를 때 더 느린 재생 속도를 택했다. Wingfield 등은 노인이 모든 속도에서 더 늦게 답했고, 정확도는 가장 빠른 속도에서만 뒤처졌다고 보고했다. (초록·2차)
  - Wingfield, A., et al. (2006). *Seminars in Hearing*, 27(4), 273–283. https://www.thieme-connect.com/products/ejournals/pdf/10.1055/s-2006-954854.pdf
  - Wingfield, Peelle & Grossman (2003). Speech rate and syntactic complexity as multiplicative factors. https://profiles.wustl.edu/en/publications/speech-rate-and-syntactic-complexity-as-multiplicative-factors-in/
- **[설계 판단]** 작업기억 부담 줄이기 = 짧은 문장, 한 턴에 질문 하나, 화면에 텍스트 동시 표시, 다시 듣기 무제한. 응답 시간 넉넉히. 속도는 사용자가 고르게 한다(노인은 느린 속도를 스스로 고른다는 근거).

### 1-8. 회차 길이와 반복

- **[근거]** 분산 학습 메타분석(317개 실험): 같은 학습 시간이면 나눠서 하는 것이 몰아서 하는 것보다 오래 기억된다. 가장 좋은 간격은 기억해야 하는 기간이 길수록 길어진다.
  - Cepeda, N. J., Pashler, H., Vul, E., Wixted, J. T., & Rohrer, D. (2006). Distributed practice in verbal recall tasks. *Psychological Bulletin*, 132(3), 354–380. https://pubmed.ncbi.nlm.nih.gov/16719566/
- **[근거]** Hou & Min(2025)에서 **개입 기간은 유의한 조절변수가 아니었다**. 대화 턴 수나 회차 길이의 최적값을 직접 다룬 연구는 찾지 못했다.
- **[설계 판단]** 한 회차 = **한 장면, 사용자 턴 3–5회, 2–4분**. 우리 앱에는 이미 날짜별 학습과 복습일 규칙(새 문장 3일 + 복습 1일, 출발 전 2일 총복습)이 있으므로, 롤플레이도 이 일정에 끼워 넣어 분산 반복한다. 근거가 약한 숫자이므로 사용 로그(완주율·중도 이탈 턴)로 조정한다.

---

## 2. 대화 설계

### 2-1. 시나리오 구조 — `talk` 데이터에서 만들기

`talk` 한 건의 모양(`mockup/data.js`):

```
{ situation, en(내 문장), ko,
  talk: { ask?: {en,ko},                 // 상대가 먼저 (입국심사 5개·기내식·체크인 등 일부만)
          replies: [{en,ko,label?}, ...], // 상대의 예상 답변 1~2개, label = 가능한 경우/불가능한 경우 등
          next: {en,ko} } }               // 내가 이어서
```

이를 한 **장면(scene)**의 노드로 바꾼다.

```
[A0 상대가 먼저(ask)]  ──or──  [U0 사용자가 먼저 시작(en)]
        ↓                                ↓
[U1 사용자 답 = en]                [A1 상대 답 = replies 중 하나]
        ↓                                ↓   (label 이 있으면 분기, 없으면 무작위/순서)
[A1 replies[i]]                    [U2 사용자 = next]
        ↓                                ↓
[U2 next]  →  [다음 talk 노드로 연결 또는 마무리 대사]
```

규칙:
1. **장면 = 같은 묶음의 talk 2–4개를 이어 붙인 것.** 예: 입국심사 = 방문 목적 → 숙소 설명 → 귀국 항공권 → 동행 여부. 이어 붙이는 데 필요한 연결 대사는 **사람이 검수한 고정 문장**으로 추가한다(AI 즉흥 생성 금지, `agent_contract/README.md` 1절 원칙과 같음).
2. **`label` 이 있는 replies 는 진짜 분기다.** "(가능한 경우)/(불가능한 경우)", "(서는 경우)/(안 서는 경우)". AI 는 둘 중 하나를 고르고, 사용자의 다음 말(`next`)이 그 분기에 맞는지 본다. 예: 정차 확인에서 "No. Take the next train on the other side." 다음에 사용자가 "Thanks. How long does it take?"라고 하면 어색하다. 이 경우 분기별 `next` 가 필요하다 → **데이터 보완 과제**: label 있는 replies 마다 `next` 를 따로 둔다(지금은 `next` 가 하나뿐).
3. **`label` 이 없는 replies 2개는 "같은 질문의 다른 답"**이다. 회차마다 바꿔 가며 써서 듣기 변이를 준다.
4. **`ask` 가 없는 상황은 사용자가 먼저 말한다.** 교통·쇼핑·호텔 대부분이 이렇다. 실제 여행에서도 길을 묻는 쪽은 여행자다. 앱이 "역무원에게 길을 물어보세요"라는 한국어 과업 카드를 먼저 보여 준다.
5. **자리표시자** `[name]`·`[destination]` 은 회차 시작 때 사용자 여행 정보(도시·숙소)나 예시 값으로 채운다. 실제 여권번호·실명은 받지 않는다(6절).

### 2-2. 난이도 단계

| 단계 | 화면 | AI 상대 | 판정 | 대상 |
|---|---|---|---|---|
| **1. 대본 따라** | 상대 대사(영·한) + **내 답 영어 문장 전체** 표시, 듣기 버튼 | `talk` 대사만, 느린 속도 기본 | 목표 문장과 단어 일치(지금 채점 재사용) | 처음 하는 사람, "영어 까막눈"(P6) |
| **2. 반(半)자유** | 상대 대사 영어만, 내 답은 **한국어 뜻 + 첫 단어**만. "힌트" 누르면 전체 | `talk` 대사 + replies 변이 | 핵심어 포함 여부(예: sightseeing, week, hotel) — 문장 전체 일치 요구 안 함 | 1단계를 2회 이상 마친 사람 |
| **3. 자유** | 과업 카드만("관광으로 5일 머문다고 답하세요"). 힌트는 요청 시 | 검수된 대사 풀 + 제한된 변형(숫자·이름 바꾸기 정도) | 과업 달성 여부를 **사용자에게 묻는 방식 + 전사 보여 주기**. 점수 없음 | 여행 직전 총복습 |

- 단계는 **사용자가 고른다**. 추천만 한다("1단계를 두 번 마쳤어요. 2단계 해 볼까요?"). 자동 강등은 하지 않는다(실패감).
- 근거: 의미 제약이 강한 시스템이 효과를 보인 메타분석(1-2), 비계 줄이기(1-6).

### 2-3. AI 상대의 말하기 규칙

| 항목 | 규칙 | 근거 |
|---|---|---|
| 속도 | 기본 **느리게**(TTS rate 약 0.8), 사용자가 0.6 / 0.8 / 1.0 선택. 선택값 기억 | 1-6, 1-7; P3 만족 |
| 문장 길이 | 한 턴 **한 문장, 질문 하나**. 대략 12단어 이하 — `talk` 대사가 이미 이 범위(예: "What's the purpose of your visit?") | 작업기억(1-7) |
| 어휘 | `talk` 에 있는 단어 + 여행 기본어. 관용구·속어·축약 연쇄 피함. 숫자는 짧게("three dollars") | — |
| 화면 | 상대 대사는 **항상 텍스트로도 표시**(1–2단계는 한국어 뜻까지). 다시 듣기 무제한 | 청력 저하(1-7), S6 "질문도 영어로 들을 수 있게" |
| "Sorry?" / "Pardon?" / "Again, please." | **같은 문장을 더 느리게 그대로** 반복(1회차). 두 번째 요청이면 **더 쉬운 말로 바꿔** 말하고 한국어 뜻을 화면에 띄움. 바꿔 말하는 문장도 미리 검수해 둔다(예: "What's the purpose of your visit?" → "Why are you here? Travel? Work?") | 의사소통 전략 지도(1-6) |
| "More slowly, please." | 0.6 속도로 반복 + 이후 턴 속도도 낮춤. **이 표현을 쓴 것을 칭찬 목록에 넣는다**(실제 여행에서 가장 쓸모 있는 기술) | 공통 문장 '천천히' |
| 사용자 침묵 | 8초: 화면 힌트(1단계 수준) 자동 표시, 음성 재촉 없음. 15초: 상대가 질문을 한 번 더 천천히. 25초: "괜찮아요, 같이 해 볼까요?" + 따라 말하기 모드로 전환. **녹음 상한 15초**(`app.js` 2303행 `setTimeout(stopSpeak, 15000)`)와 맞출 것 | Wait time(1-5), P6 "녹음 끝내기 안 눌러도"(무음 자동 종료 요청) |
| 한국어로 답함 | 상대 역할은 깨지 않고 **"Sorry, in English, please?"를 한 번만** 말한다. 동시에 화면 아래에 한국어 안내("영어로는 이렇게: I'm here for sightseeing.") 표시. 두 번째부터는 상대 대사 없이 바로 따라 말하기로. 한국어 발화를 꾸짖거나 점수화하지 않음 | 2-5 |
| 틀린 영어 | 의미가 통하면 **그대로 대화를 진행**한다. 상대 역할이 자연스럽게 되받아 확인할 수는 있다(implicit recast: 사용자 "I'm here for sighting." → AI "Sightseeing? Great. How long will you be staying?"). 명시적 교정은 하지 않는다 | 1-3 |
| 의미가 안 통함 | "Sorry, I don't understand." + 힌트 표시. 같은 노드에 최대 2회 머문 뒤 모범 답을 들려주고 다음으로 넘어감(막힘 방지) | — |
| 대본 밖 질문 | 사용자가 대본 밖 내용을 물으면(예: "Can I bring kimchi?") AI 는 **규칙·사실로 답하지 않고** "Please ask the officer at the desk." 수준으로 돌리고 장면으로 복귀. 6절 참조 | 6절 |

### 2-4. 피드백 시점과 방식

| 시점 | 무엇을 | 무엇을 하지 않나 |
|---|---|---|
| **대화 중** | 상대 역할의 자연스러운 되받기(recast)만. 1단계에 한해 턴이 끝나면 작은 버튼 "↻ 이 줄 다시 말하기"(prompt) | 점수 숫자, 빨간색, "틀렸어요", 문법 설명 |
| **대화 직후 (요약 화면)** | ① 과업 완수 여부("입국 심사를 끝까지 마쳤어요") ② 대화 전사(상대 대사 + 들린 내 말) ③ **고칠 한 가지**(전체 회차에서 하나) ④ 잘한 점 하나 ⑤ 복습에 담을 문장 고르기 | 턴마다 교정 목록, 발음 점수 |
| **다음 회차 시작 때** | 지난번 "고칠 한 가지"를 1단계 힌트로 다시 보여 줌 | — |

- **한 번에 하나만**: 지금 앱의 "고칠 한 가지"(`fix_one`, 백엔드 `FEEDBACK_PROMPT` "the single most useful thing to fix next time") 원칙을 회차 단위로 넓힌다. 고칠 것 고르기 우선순위: (1) 의미를 바꾼 단어(sightseeing→sighting) (2) 빠진 핵심어 (3) 그 밖. 문법 세부(관사·시제)는 의미를 바꿀 때만.
- 근거: 과업 뒤 형태 초점(Willis), 대화 흐름 유지(Duolingo 설계 근거), 낮은 수준엔 즉시 prompt(Li et al.) — 1단계의 "다시 말하기" 버튼으로 반영.

### 2-5. 한국어 지원 정책

1. **안내·설명·피드백은 한국어**, **역할 대사는 영어**. 역할 중인 AI 는 한국어로 말하지 않는다(몰입 유지). 한국어는 화면 텍스트로만 준다.
2. 한국어 뜻 표시: 1단계 항상 / 2단계 상대 대사는 숨기고 "뜻 보기" 버튼 / 3단계 요청 시.
3. 사용자가 한국어로 말해도 실패로 세지 않는다. 요약에서 "이 부분은 한국어로 답했어요 → 영어로는: …"로 복습 후보에 올린다.
4. 과업 카드(장면 시작 설명)는 한국어: "입국심사대예요. 관광으로 일주일 머문다고 말해 보세요."
5. 근거가 얇은 영역이므로(1-6) 2차 테스트에서 "한국어 뜻이 도움이 됐는지/방해였는지"를 묻는다.

---

## 3. 시나리오 우선순위

### 3-1. 순서와 근거

| 순위 | 장면 | 근거 | `talk` 준비 상태 |
|---|---|---|---|
| **1** | **입국심사** | P6·S6 의 "상대 질문을 영어로" 요청이 정확히 이 형태. 질문이 정해져 있어 대본화가 쉽고 위험이 낮음. 5개 상황 모두 `ask` 가 있음 | **완비** — 그대로 장면화 가능 |
| **2** | **대중교통(역·버스)** | Q3 가장 불편한 상황 **교통 7/11**, S11 "지하철 노선 활용·교통정보 누락" | 5개 상황, 모두 `ask` 없음(사용자 먼저). 버스 기사 대사는 없음 → 추가 검수 필요 |
| 3 | 호텔 체크인·짐 보관 | 체크인만 `ask` 있음. 분기 label 있음 | 대부분 준비 |
| 4 | 식당 주문 | Q3 언어 장벽·식당 4/11. 공통 30에는 식당 묶음이 없고 맛집 문장은 **AI 생성**(`ai: true`) | 고정 대본 없음 → 대본 작성·검수 후 |
| 5 | 길 묻기·쇼핑 | 교통과 겹침(역 찾기·거리 묻기) | 준비됨 |
| 보류 | 돌발 상황·응급 전화(S3) | 6절 위험. 고정 문장 4개('응급 전화' 묶음, #98)는 **1단계 대본 따라 말하기로만** 제공. AI 자유 대화 금지 | 고정 문장 있음 |

주의: S11 의 요청은 **교통 정보 자체**(노선·환승)이지 회화 연습이 아니다. 롤플레이는 "역무원에게 묻는 말"을 연습시켜 줄 뿐, 노선 정보를 주지 않는다. 롤플레이 안에서 AI 가 실제 노선을 말하면 틀린 정보가 될 수 있으므로(6절), 노선·역 이름은 **예시임을 표시한 가상 값**(Line 2, Central Station, green line)만 쓴다.

### 3-2. 예시 대화 ① 입국심사 (1–2단계, `talk` 데이터 그대로)

과업 카드(한국어): "입국심사대예요. 관광으로 일주일 머물고, 시내 호텔에 묵는다고 답해 보세요."

| 턴 | 화자 | 영어 (출처) | 한국어(화면) | 분기·처리 |
|---|---|---|---|---|
| 1 | 심사관 | What's the purpose of your visit? (`방문 목적.ask`) | 방문 목적이 무엇인가요? | — |
| 2 | 나 | **I'm here for sightseeing.** (`방문 목적.en`) | 관광하러 왔어요. | 핵심어 `sightseeing`. ① 맞음 → 3. ② "sighting" 등 → 심사관이 되받기 "Sightseeing? Okay." 후 3 (교정 후보 기록). ③ 침묵 8초 → 힌트, 15초 → 질문 반복. ④ 한국어 → "Sorry, in English, please?" + 화면 모범 답 |
| 3 | 심사관 | How long will you be staying? (`방문 목적.replies[0]`) | 얼마나 머무르실 건가요? | — |
| 4 | 나 | **About a week.** (`방문 목적.next`) | 일주일 정도요. | 2단계에서는 "Five days."·"For ten days." 등 기간 표현이면 통과(핵심: 숫자+day/week). "Sorry?" → 같은 문장 느리게 → 두 번째는 "How many days?" |
| 5 | 심사관 | Where will you be staying? (`숙소 설명.ask`) | 어디에서 머무르시나요? | 연결 대사 불필요(질문이 바로 이어짐) |
| 6 | 나 | **I'm staying at a hotel in the city.** (`숙소 설명.en`) | 시내 호텔에 묵어요. | 핵심어 `hotel` |
| 7 | 심사관 | What's the name of the hotel? (`숙소 설명.replies[0]`) | 호텔 이름이 뭔가요? | — |
| 8 | 나 | **Here is my hotel reservation.** (`숙소 설명.next`) | 여기 호텔 예약 확인서예요. | 실제 호텔명을 말해도 통과(전사는 이 탭에서만 보여 주고 저장 안 함) |
| 9 | 심사관 | Do you have a return ticket? (`귀국 항공권.ask`) | 귀국 항공권 있으세요? | **분기 A(짧은 판)**: 9–10 생략하고 13으로 |
| 10 | 나 | **Here is my return ticket.** (`귀국 항공권.en`) | 여기 귀국 항공권이에요. | — |
| 11 | 심사관 | Are you traveling alone? (`동행 여부.ask`) | 혼자 여행하시나요? | 검수 필요한 변이: 동행이 있는 사용자용 답 "I'm traveling with my wife." — 지금 데이터엔 없음 → **데이터 보완 과제** |
| 12 | 나 | **I'm traveling alone.** (`동행 여부.en`) | 혼자 여행 중이에요. | — |
| 13 | 심사관 | Okay. Do you have anything to declare? (`동행 여부.replies[0]`) | 알겠습니다. 신고할 물건 있으세요? | — |
| 14 | 나 | **No, nothing to declare.** (`동행 여부.next`) | 아니요, 신고할 건 없어요. | **"Yes"라고 답하거나 물건을 말하면**: AI 는 "Please talk to the officer at the customs desk."(검수된 고정 문장)로 끝냄. **무엇을 신고해야 하는지 절대 말하지 않음**(6절) |
| 15 | 심사관 | Welcome. Enjoy your stay. (`첫 방문.replies[0]`) | 환영합니다. 즐거운 시간 보내세요. | 마무리 고정 대사 |
| 16 | 나 | Thank you very much. (`첫 방문.next`) | 정말 감사합니다. | 과업 완료 |

사용자 턴 7회 — 길다. **1단계는 턴 1–8(사용자 4회)만**, 2단계부터 전체로 한다(1-8의 3–5턴 기준).

### 3-3. 예시 대화 ② 대중교통 — 역 매표소·승강장 (사용자가 먼저)

과업 카드(한국어): "시내에 있는 [Central Park](예시)에 가려고 해요. 역무원에게 가는 방법을 묻고 표를 사세요."
자리표시자 `[destination]` = 사용자 여행지의 예시 장소. 노선·역 이름은 가상 값이며 화면에 "예시 안내예요. 실제 노선은 현지 안내를 확인하세요."를 표시.

| 턴 | 화자 | 영어 (출처) | 한국어(화면) | 분기·처리 |
|---|---|---|---|---|
| 1 | 나 | **How do I get to Central Park?** (`길 찾기.en`) | 센트럴 파크에 어떻게 가요? | 2단계: "Central Park, how?"·"Where is Central Park?"도 통과 → 의미 전달 우선 |
| 2 | 역무원 | **분기 A** Take the subway, Line 2, and get off at the third stop. (`길 찾기.replies[0]`) / **분기 B** It's a ten-minute walk. Go straight and turn left. (`길 찾기.replies[1]`) | 지하철 2호선을 타고 세 번째 역에서 내리세요. / 걸어서 10분이에요… | 회차마다 A·B 번갈아. **B 로 가면** 턴 3 "Thank you. Is there a bus, too?"(`길 찾기.next`) → 역무원 "Yes, bus 10 stops outside."(**검수 필요 신규 대사**) → 종료(짧은 장면) |
| 3 | 나 | **Which line goes to Central Park?** (`노선 묻기.en`) — A 의 확인 질문으로 연결 | 센트럴 파크 가는 노선이 뭐예요? | "Sorry? / Again, please." → 턴 2 를 0.6 속도로 반복. 숫자 "Line 2", "third"는 화면에 굵게 |
| 4 | 역무원 | You need to transfer at Central Station. (`노선 묻기.replies[1]`) | 중앙역에서 갈아타셔야 해요. | 1단계에서는 replies[0] "Take the green line toward Downtown."(환승 없음, 더 쉬움) |
| 5 | 나 | **How many stops is it?** (`노선 묻기.next`) | 몇 정거장이에요? | — |
| 6 | 역무원 | It's three stops from here. (`하차 부탁.replies[1]`를 연결 대사로 재사용) | 여기서 세 정거장이에요. | — |
| 7 | 나 | **One ticket, please.** (`표 구매.en`) | 표 한 장 주세요. | — |
| 8 | 역무원 | One way or round trip? (`표 구매.replies[0]`) | 편도요, 왕복이요? | 선택 질문 — 사용자가 "Round trip."이라고 해도 통과(정답이 둘) |
| 9 | 나 | **One way, please. Can I pay by card?** (`표 구매.next`) | 편도로 주세요. 카드로 낼 수 있나요? | 문장이 2개 — 1단계에서는 앞 문장만 요구 |
| 10 | 역무원 | That's three dollars. (`표 구매.replies[1]`) + "Yes, card is fine."(**검수 필요 신규**) | 3달러예요. 카드 돼요. | **가격·결제 수단은 예시**. 실제 요금을 말하지 않음 |
| 11 | 나 | **Does this train stop at Central Park?** (`정차 확인.en`) — 장면 전환: 승강장 승객 | 이 열차 센트럴 파크에 서나요? | 장면 전환은 화면 카드("승강장에서 옆 사람에게 확인해요") |
| 12 | 승객 | **분기 (서는 경우)** Yes, it's the fourth stop. / **(안 서는 경우)** No. Take the next train on the other side. (`정차 확인.replies`) | 네, 네 번째 역이에요. / 아니요. 반대편에서 다음 열차를 타세요. | label 분기 |
| 13a | 나 (서는 경우) | **Thanks. How long does it take?** (`정차 확인.next`) | 감사합니다. 얼마나 걸려요? | — |
| 13b | 나 (안 서는 경우) | **Thank you. The other side?** (**신규, 분기별 `next` 필요**) | 감사합니다. 반대편이요? | 지금 `next` 는 하나뿐이라 13a 를 쓰면 어색 → 2-1 규칙 2 의 데이터 보완 |
| 14 | 승객 | About ten minutes. (**신규**) | 10분 정도요. | — |
| 15 | 나 | **Please let me know when we get there.** (`하차 부탁.en`) — 버스로 바꾸면 기사에게 | 도착하면 알려 주세요. | 버스 기사판: 같은 문장, 상대 대사 "Sure, I'll let you know."(`하차 부탁.replies[0]`) |

사용자 턴 최대 8회 → **회차를 둘로 나눈다**: (가) 길 묻기 + 표 사기(턴 1–10), (나) 승강장·버스 하차(턴 11–15). 각각 사용자 4–5회.

---

## 4. 피드백·평가 설계

### 4-1. 지금 점수가 무엇인지 (코드 확인)

- **[우리 자료]** 백엔드 점수는 두 전사기(Groq Whisper + AssemblyAI)가 **모두** 들은 단어를 목표 문장과 비교한 **단어 일치율**이다(`score_kind: "word_match"`). 피드백 AI 는 오디오를 듣지 않고, 프롬프트도 "do not comment on accent, intonation or sounds"라고 명시한다(`main.py` 639–651행).
- **[우리 자료]** `speakHtml`(app.js 2193행) 표시: `score_kind === 'word_match'` 이면 "**단어 일치 N% (발음 점수 아님)**", 그 밖이면 "점수 N". 교차검증을 못 한 제한 모드는 점수를 보이지 않는다(2191행). 점수 없이 들린 문장만 있으면 "참고: 목표 문장 단어 N% 일치 (실력 판정이 아니에요)".
- **[우리 자료] 자동 저장 규칙의 실제 적용 범위**: `weakDecision`(ai.js 285행)은 **`sentence.ai !== true` 이면 'none'**을 돌려준다. `data.js` 에는 `ai: true` 가 0건이다. 따라서 **회화 연습 시트의 공통 30문장은 점수가 70 미만이어도 복습 목록에 자동 저장되지 않고, 저장 제안 버튼도 뜨지 않는다**. 자동 저장(70 미만)과 "저장할까요"는 AI 생성 문장(맛집 등)에만 적용된다. 롤플레이를 공통 30문장으로 만들면 지금 규칙으로는 복습 목록과 연결되지 않는다. 의도된 동작인지 팀이 확인해야 한다.
- **[우리 자료]** 점수 측정의 한계: 같은 파일을 n번 보낸 일관성 측정일 뿐이고, 표본은 TTS 3개 파일이다. 실제 사용자 목소리(억양·속도·잡음) 다양성은 측정에 없다(`score_측정_실행법.md` 5절). 단어 일치율은 부정문을 같은 문장으로, 자연스러운 바꿔 말하기를 누락으로 볼 수 있다(ai.js 280행 주석).
- **[우리 자료] 문구 주의**: 실기기 기록 6.1의 3번 피드백은 "'sightseeing'으로 정확하게 **발음해** 보세요"였다. 단어 비교 결과에서 나온 말이지만 발음을 평가한 것처럼 읽힌다. 롤플레이 요약에서는 "**'sightseeing'이 'sighting'으로 들렸어요**"처럼 "들린 것"으로 표현한다.

### 4-2. 롤플레이에서 점수를 어떻게 쓸까

| 단계 | 표시 | 이유 |
|---|---|---|
| 1단계(대본) | 턴별 "들린 문장" + 목표 문장과 다른 단어 표시. **단어 일치 %는 요약 화면에서만**, 지금 문구 그대로("발음 점수 아님") | 목표 문장이 있으므로 단어 비교가 의미 있음 |
| 2단계(반자유) | 핵심어 포함 여부(✓ 표시). **% 없음** | "About a week" 대신 "Five days"도 맞는 답. 문장 전체 일치율은 맞는 답을 틀렸다고 함 |
| 3단계(자유) | 점수 없음. 전사 + 모범 답 나란히 + "원하는 말이 전달됐나요? 네/아니요"(사용자 자기평가) | LLM 의 '의도 전달' 판정은 검증되지 않음(`references.md` C12: LLM 진단 근거 39.6%가 그럴듯하지만 틀림) |

### 4-3. 회차 뒤 요약 화면 (보여 줄 것)

1. **과업 결과**(한 줄): "입국심사를 끝까지 마쳤어요 · 힌트 2번 · 다시 묻기 1번"
2. **잘한 점 하나**: 예) "'More slowly, please'로 다시 물어봤어요 — 실제로 가장 쓸모 있는 표현이에요." (되묻기를 칭찬 대상으로)
3. **고칠 한 가지**(회차 전체에서 하나): 들린 것 vs 목표, 듣기 버튼 2개(원어민 / **▶ 내 발음 듣기** — S10 요청, #109 의 재사용)
4. **대화 전사**(접기): 상대 대사 + 들린 내 말. 녹음은 지금처럼 이 탭 메모리에만, 회차 종료 시 삭제
5. **복습에 담기**: 힌트를 본 줄·한국어로 답한 줄·다시 물은 줄을 **후보로 체크해 두고, 사용자가 확인해서 저장**(지금의 `ask` 경로와 같은 "직접 선택"). 자동 저장 규칙(70 미만)은 롤플레이에 쓰지 않는다 — 2–3단계는 점수가 없고, 1단계 점수도 실제 목소리로 검증되지 않았다(4-1).
6. **다음 추천**: "같은 장면 2단계" 또는 "다음 날 복습일에 다시"(복습 일정과 연결)

### 4-4. 보여 주지 말 것

- **"발음 점수"·"발음 정확도"·"원어민 대비 N%"** — 우리 점수는 단어 일치이며 발음을 재지 않는다. "점수 N"(word_match 가 아닐 때 쓰는 문구)도 롤플레이에서는 쓰지 않는다.
- **CEFR·레벨·"입국 심사 통과 가능" 같은 준비도 판정** — 근거 없음, 실제 입국 결과와 혼동.
- **"입국 거절"·"실패" 같은 롤플레이 결말** — 불안 자극. 대화는 항상 완료로 끝난다(막히면 모범 답 들려주고 진행).
- **대화 중 점수·빨간색·턴마다 교정** (1-3, 1-4).
- **다른 사용자와의 비교·순위**.
- **고칠 점 여러 개 목록** — 한 번에 하나.
- **AI 가 만든 "이유 설명"을 사실처럼** — 피드백은 비교 결과(diff)에만 근거(지금 백엔드 원칙 유지).

---

## 5. 경쟁 서비스 비교

| 서비스 | 형태 | 대화 중 피드백 | 대화 후 | 한국어 지원·대상 | 효과 근거 | 근거 수준 |
|---|---|---|---|---|---|---|
| **Duolingo Max Video Call** (Lily, 초급용 Falstaff) | 캐릭터와 영상통화식 음성 대화. 초급은 안내된 연습, 중급은 열린 대화 | **없음**(FAQ: 흐름을 끊기 때문) | 전사 + 정확성·복잡성 피드백·팁 | 한국어 화자용 영어 코스 있음. 유료(Max) | 자사 연구 3건: Falstaff 사용 초급자 말하기 점수 높음, Lily 하루 2회 이상 한 달 → 표준 말하기 시험 향상, Lily → 자신감 향상 | **낮음** — 회사 블로그, 표본 수·효과크기·무작위 배정 여부 미공개(자기 선택 가능성) |
| **Speak(스픽)** | 시나리오 롤플레이·따라 말하기, OpenAI 기술 사용 | 앱 기능(공식 문서 미확인) | — | 한국 시장 중심 | 회사 수치만: 레슨 수·말한 문장 수·"한국인 약 300만 명" 등 **사용량**. 대만 설문(413명)은 브랜드 인지·전환율만 측정 | **매우 낮음** — 효과 연구 없음 |
| **Praktika** | AI 아바타 튜터와 대화 | — | — | 다국어 | 음성 공급사(ElevenLabs) 사례: 음성 교체 후 평균 세션 길이 +15%(참여도, 학습 효과 아님). 월 120만 사용자 주장 | **매우 낮음** — 마케팅 |
| **ELSA Speak** | 발음 교정 특화(음소 단위 채점) | 단어·음소 단위 즉시 | 점수 리포트 | 다국어 | 인도네시아·이집트 소규모 준실험 다수(9–71명), 대부분 긍정, 1건은 집단 간 차이 없음 | **낮음** — 비무작위·소표본·짧은 기간 |
| **ChatGPT 음성 모드** | 범용 LLM 음성 대화, 학습 설계 없음 | 요청하면 | 요청하면 | 한국어 가능 | 단일집단 사전·사후(42명, 불안 감소), 질적 연구(8명), 학부 논문(5명). 8주 혼합연구에서 유창성·어휘↑, 발음 변화 없음 | **낮음** — 통제집단 없는 연구가 대부분 |
| **연구용 대화 시스템**(메타분석 대상) | 대부분 규칙 기반·의미 제약 | 다양 | 다양 | — | d = 0.58(Bibauw 2022), g = .61(Hou & Min 2025) | **중간** — 메타분석이지만 생성형 AI 이전 시스템 |
| **마디(계획)** | `talk` 기반 반대본 롤플레이, 3단계 | 상대 역할의 자연스러운 되받기만 + 1단계 "다시 말하기" | 고칠 한 가지 + 전사 + 내 발음 듣기 + 복습 선택 | **한국어 안내 기본**, 40–60대 초급 | 없음(설계 단계) | 2차 테스트에서 수집 |

출처: Duolingo 연구 보고 https://blog.duolingo.com/video-call-research-report · Duolingo Max https://blog.duolingo.com/duolingo-max · Duolingo 대화형 AI 발표(Pendomonium 2024) https://pendo.io/pendomonium/wp-content/themes/pendomonium-tailpress-22/resources/pdf/How%20Duolingo%20built%20a%20conversational%20AI_Zan%20Gilani_PNDM2024.pdf · Speak 투자 기사 https://techcrunch.com/2024/12/10/openai-backed-speak-raises-78m-at-1b-valuation-to-help-users-learn-languages-by-talking-out-loud · Speak 대만 설문 https://tdr.lib.ntu.edu.tw/retrieve/c47067c3-413c-4027-a9c0-34ec05cf8158/ntu-113-2.pdf · Praktika https://elevenlabs.io/blog/praktika-scales-immersive-language-learning-with-elevenlabs-tts , https://techcrunch.com/2024/05/22/praktika-raises-35-5m-to-use-ai-avatars-to-make-learning-languages-feel-more-natural · ELSA 준실험 예 https://jele.or.id/index.php/jele/article/view/2073 · ChatGPT 음성 https://bcchj.uobabylon.edu.iq/index.php/bcchj/en/article/view/3341

시사점: 경쟁 서비스 중 **독립적인 통제 연구로 학습 효과가 확인된 곳은 없다**. "AI 회화가 실력을 올린다"고 말할 때 인용할 수 있는 것은 연구용 대화 시스템 메타분석뿐이며, 그것도 대본·의미 제약형 시스템의 근거다. 우리 차별점은 효과 주장이 아니라 **대상(40–60대 초급 여행자)에 맞춘 비계와 한국어 안내, 검수된 대본**이다.

---

## 6. 위험

| 위험 | 예 | 대응 |
|---|---|---|
| **AI 가 틀린 입국·세관 규칙을 말함** (환각) | "You need a visa for this country.", "You can bring up to 2 liters." "You must declare food." | 심사관·세관원 대사는 **검수된 고정 문장 풀에서만** 고른다. 3단계 변형도 숫자·이름 치환까지만. 사용자가 규칙을 물으면 고정 문장 "Please ask the officer at the desk."로 돌린다. 출력 필터: 비자·세관 한도·벌금·법 조항 관련 어휘가 나오면 그 턴을 버리고 고정 문장으로 대체. 화면 상시 문구: "연습용 대화예요. 실제 입국 규정은 대사관·항공사 안내를 확인하세요." 참고: OWASP GenAI LLM09:2025 Misinformation https://genai.owasp.org/llmrisk/llm092025-misinformation/ |
| **의료·법률 조언** | 진료 장면에서 AI 가 "Take ibuprofen.", 경찰 장면에서 법적 절차 안내 | 돌발 상황은 **도움 요청·위치·증상 말하기까지만**(`conversation-practice-review.md` 원칙, #98 결정). AI 자유 대화 금지, 1단계 대본만. 상대 대사에 약 이름·처치·진단이 나오면 안 됨(검수 체크리스트 항목) |
| **응급 전화(S3)를 실제 상황 대체로 오해** | 실제 응급 시 앱을 켜서 롤플레이 | 응급 묶음 화면에 "실제 응급 상황에서는 현지 긴급번호(미국 911·유럽 112 등)에 바로 전화하세요" — 번호는 검수된 고정 텍스트. 롤플레이는 "여행 전 연습"으로만 표시 |
| **틀린 교통 정보** | AI 가 실제 도시의 노선·요금을 지어냄 | 노선·역·요금은 가상 예시 값 고정, "예시 안내" 표시(3-3). 실제 교통 정보는 별도 기능(S11 확장 계획)이며 롤플레이와 섞지 않음 |
| **채점 신뢰도 과신** | 70 미만이면 "못한다"로 느낌 | 4-2·4-4. 2–3단계 점수 없음. 문구는 "들린 것" 중심 |
| **개인정보** | 실명·여권번호·호텔명·여행 일정을 말함 | 자리표시자 사용 권장, 전사·녹음은 탭 메모리에만(지금 정책 유지), 서버 로그에 전사 저장 금지. 녹음이 외부 STT(Groq·AssemblyAI)로 가는 것은 지금 동의 화면과 같은 문구로 다시 고지 |
| **불안 유발** | 침묵 재촉, 반복 실패, 빠른 말 | 2-3 침묵 규칙, 같은 노드 2회 뒤 모범 답 후 진행, 속도 선택 |
| **지연으로 대화가 끊김** | 채점 5초, 콜드스타트 미측정 | 상대 대사 TTS 사전 생성, 분기 판정만 서버. 시연 전 `/health` 로 깨우기(`score_측정_실행법.md`) |
| **역할 이탈·탈옥** | 사용자가 "역할 그만하고 시 써 줘" | 장면 밖 요청은 고정 문장으로 장면 복귀, 3회면 회차 종료 |
| **카톡 인앱 브라우저** | TTS 가 안 되면 상대 대사가 안 들림(P1·P2, 1c) | TTS 불가 시 롤플레이 시작 전에 막고 "Chrome 에서 열기" 안내(기존 배너 재사용). 상대 대사를 텍스트로만 진행하는 대체 모드는 듣기 연습이 빠지므로 명시 |

---

## 부록 A. 데이터 보완 과제 (이 조사에서 나온 것)

1. label 있는 replies 마다 분기별 `next` (예: 정차 확인 "안 서는 경우", 짐 보관 "어려운 경우", 좌석 "가능한 경우").
2. 장면 연결 대사·"Sorry?" 두 번째 응답용 쉬운 바꿔 말하기 문장(검수 대상).
3. 동행이 있는 사용자용 답("I'm traveling with my family.") 등 사용자 사정별 대체 답.
4. 버스 기사 대사(교통 2순위 장면용).
5. 2단계 판정용 상황별 핵심어 목록.
6. 공통 30문장도 복습 목록과 연결할지 결정(`weakDecision` 의 `ai === true` 조건).

## 부록 B. 2차 사용자 테스트에 넣을 질문

- 영어 수준 자기평가(1–5)와 짧은 말하기 불안 문항 3개(FLCAS 에서 발췌) — 0절 가설 검증
- "AI 와 말할 때가 사람과 말할 때보다 덜 긴장되나요?"
- "한국어 뜻 표시가 도움이 됐나요, 방해가 됐나요?"
- 과업 완주율, 힌트 사용 횟수, "Sorry?" 사용 횟수, 침묵으로 끊긴 턴 수(로그)
