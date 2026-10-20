# 실시간 회화 에이전트 구축을 위한 번역 서비스 API와 GitHub 레퍼런스

> **목적**: 실시간 회화 에이전트의 번역 계층을 설계할 때 참고할 주요 번역 서비스 API와 오픈소스 GitHub 저장소를 체계적으로 정리한다.
> **작성일**: 2026-10-20
> **연관 프로젝트 문서**:
> - [실시간 회화 에이전트 조사 종합 (realtime-agent/README.md)](realtime-agent/README.md)
> - [기술 아키텍처 및 단계별 경로 (realtime-agent/02-tech.md)](realtime-agent/02-tech.md)
> - [대화 및 롤플레이 설계 (realtime-agent/03-conversation-design.md)](realtime-agent/03-conversation-design.md)
> - [위험·개인정보·비용 (realtime-agent/04-risk-cost.md)](realtime-agent/04-risk-cost.md)

---

## 목차

1. [실시간 회화 에이전트와 번역 계층의 역할](#1-실시간-회화-에이전트와-번역-계층의-역할)
2. [실시간 음성 번역 특화 서비스](#2-실시간-음성-번역-특화-서비스)
3. [텍스트 번역 API와 회화 에이전트 통합 전략](#3-텍스트-번역-api와-회화-에이전트-통합-전략)
4. [실시간 음성 회화 번역 GitHub 저장소 레퍼런스](#4-실시간-음성-회화-번역-github-저장소-레퍼런스)
5. [실시간 회화 에이전트 번역 모듈 설계 지침](#5-실시간-회화-에이전트-번역-모듈-설계-지침)
6. [시나리오별 추천 조합과 참고 자료 정리](#6-시나리오별-추천-조합과-참고-자료-정리)
7. [검증과 마디 적용 (2026-10-20 보강)](#7-검증과-마디-적용-2026-10-20-보강)

---

## 1. 실시간 회화 에이전트와 번역 계층의 역할

### 1.1 기본 구조와 번역 요구

실시간 회화 에이전트는 지연이 거의 없는 상태에서 대화 흐름을 끊김 없이 유지하는 시스템이다. 다국어 환경에서 가장 먼저 등장하는 요구는 **서로 다른 언어를 사용하는 참여자 간의 의미 전달**을 정확하고 빠르게 보장하는 번역 기능이다.

#### 두 가지 설계 방향

```mermaid
graph LR
    subgraph "모듈형 파이프라인"
        A["🎤 음성 입력"] --> B["STT<br/>Speech-to-Text"]
        B --> C["MT<br/>Machine Translation"]
        C --> D["TTS<br/>Text-to-Speech"]
        D --> E["🔊 음성 출력"]
    end
```

```mermaid
graph LR
    subgraph "통합형 Realtime 모델"
        F["🎤 음성 입력"] --> G["Realtime Translation<br/>Model (e.g. gpt-realtime-translate)"]
        G --> H["🔊 번역된 음성 + 📝 텍스트"]
    end
```

| 구분 | 모듈형 STT+MT+TTS | 통합형 Realtime Translation |
|------|--------------------|-----------------------------|
| **장점** | 각 단계별 최적 서비스 선택 가능, 도메인 커스터마이즈 용이 | 설계 단순화, 지연 최소화, 단일 세션 유지 |
| **단점** | 각 단계 지연 누적, 통합 복잡성 | 세밀한 커스터마이즈 어려움, 특정 벤더 종속 |
| **적합 시나리오** | 엔터프라이즈 콜센터, 도메인 특화 | 프로토타입, 교육용, 라이브 이벤트 |

### 1.2 번역 서비스 선택 시 고려 요소

| 요소 | 설명 | 관련 서비스 예시 |
|------|------|------------------|
| **지연 & 스트리밍** | 문장 완성 전 부분 번역 지원 여부 | Azure Speech Translation, OpenAI Realtime |
| **음성 통합** | STT/TTS 별도 연동 필요 여부 | Azure (Speech+Translator), Google (STT+Translation+TTS) |
| **도메인 커스터마이즈** | 용어집·스타일 규칙·번역 메모리 | DeepL (Glossary), Google Advanced (Glossary, Adaptive MT) |
| **라이선스 & 보안** | 데이터 보존 정책, 컴플라이언스 | DeepL (비보존), Google (IAM), Azure (엔터프라이즈급) |

---

## 2. 실시간 음성 번역 특화 서비스

### 2.1 OpenAI Realtime Translation: gpt-realtime-translate

> [!IMPORTANT]
> 통합형 실시간 음성 번역 모델. WebRTC(브라우저)와 WebSocket(서버) 두 가지 연결 방식을 제공한다.

**엔드포인트**: `/v1/realtime/translations`

**연결 방식 비교**:

| 방식 | 적합 환경 | 특징 |
|------|-----------|------|
| **WebRTC** | 브라우저 기반 웹 앱 | 미디어 트랙으로 음성 전송/수신, PCM 직접 처리 불필요 |
| **WebSocket** | 서버(Twilio, SIP, 방송) | 24 kHz PCM16 base64 인코딩 전송, 음성 델타 직접 처리 |

**클라이언트 시크릿 생성 (Node.js Express)**:

```javascript
app.post("/session", async (req, res) => {
  const language = req.body.targetLanguage ?? "en";
  const response = await fetch(
    "https://api.openai.com/v1/realtime/translations/client_secrets",
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${process.env.OPENAI_API_KEY}`,
        "Content-Type": "application/json",
        "OpenAI-Safety-Identifier": "hashed-user-id",
      },
      body: JSON.stringify({
        session: {
          model: "gpt-realtime-translate",
          audio: { output: { language } },
        },
      }),
    }
  );
  res.status(response.status).json(await response.json());
});
```

**WebSocket 연결 주소**: `wss://api.openai.com/v1/realtime/translations?model=gpt-realtime-translate`

**참고 자료**:
- 🔗 [OpenAI Realtime Translation 가이드 (중국어 번역)](https://github.com/hl8086/openai-developer-doc-zh/blob/main/zh/guides/realtime-translation.md)
- 🔗 [GPT-Realtime-Translate Live Event Interpreter](https://github.com/backblaze-b2-samples/gpt-realtime-translate-live-event-interpreter) — FastAPI + Next.js 기반 라이브 이벤트 통역 시스템

---

### 2.2 Azure Translator + Azure Speech (Foundry Tools)

> [!NOTE]
> Microsoft의 엔터프라이즈급 번역·음성 서비스. 콜센터·다국어 에이전트에 특히 적합하다.

**Azure Translator**:
- 100개 이상 언어 지원
- 실시간·배치 텍스트 번역, 문서 번역
- 언어 자동 감지, 양방향 사전, 커스텀 번역
- 🔗 [Azure Translator](https://azure.microsoft.com/en-us/products/ai-foundry/tools/translator)

**Azure Speech**:
- Speech-to-Text, Text-to-Speech, Speech Translation, 화자 인식
- C#, C++, Java 등 다중 언어 SDK
- 실시간 스트리밍 음성 처리 지원
- 🔗 [Azure Speech](https://azure.microsoft.com/en-us/products/ai-foundry/tools/speech)

**통합 구조**:

```mermaid
graph LR
    A["🎤 음성"] --> B["Azure Speech SDK<br/>Speech Translation"]
    B --> C["번역된 텍스트"]
    C --> D["Azure Translator<br/>(품질 개선/도메인 커스텀)"]
    D --> E["Azure Speech TTS"]
    E --> F["🔊 번역된 음성"]
```

**참고 저장소**: 🔗 [Azure Speech SDK C# 샘플](https://github.com/Azure-Samples/cognitive-services-speech-sdk/tree/master/samples/csharp/dotnetcore/console)

---

### 2.3 DeepL API + Voice WebSocket 프로토콜

> [!TIP]
> 고품질 번역과 도메인 커스터마이즈(용어집·스타일 룰·번역 메모리)에 강점. Voice WebSocket으로 실시간 음성 번역도 지원.

**인증**: `Authorization: DeepL-Auth-Key <api-key>`

| 플랜 | 엔드포인트 |
|------|-----------|
| Free | `https://api-free.deepl.com` |
| Pro | `https://api.deepl.com` |

**주요 엔드포인트**:
- `/v2/translate` — 텍스트 번역
- `/v2/document` — 문서 번역
- Voice WebSocket — 실시간 음성 번역 스트리밍

**명세 파일**:
- REST API: `openapi.yaml`
- Voice WebSocket: `voice.asyncapi.yaml`

**참고 링크**:
- 🔗 [DeepL 인증·액세스 문서](https://developers.deepl.com/docs/getting-started/auth)
- 🔗 [Voice WebSocket 프로토콜 명세](https://developers.deepl.com/api-reference/voice/voice.asyncapi.yaml)

---

### 2.4 Google Cloud Translation + Speech-to-Text + Text-to-Speech

> [!NOTE]
> 189개 언어 지원, Basic/Advanced 에디션. 대규모 서비스에 안정적인 선택.

**에디션 비교**:

| 기능 | Basic (v2) | Advanced (v3) |
|------|-----------|---------------|
| 인증 | API 키 | IAM 서비스 계정 |
| Glossary | ❌ | ✅ |
| Batch Translation | ❌ | ✅ |
| Document Translation | ❌ | ✅ |
| Adaptive Translation | ❌ | ✅ |
| TLLM 모델 선택 | ❌ | ✅ |

**통합 파이프라인 (콜센터 시나리오)**:

```mermaid
sequenceDiagram
    participant Customer as 고객 (한국어)
    participant STT as Cloud Speech-to-Text
    participant MT as Cloud Translation
    participant TTS as Cloud Text-to-Speech
    participant Agent as 상담원 (영어)

    Customer->>STT: 한국어 음성
    STT->>MT: 한국어 텍스트
    MT->>Agent: 영어 텍스트
    Agent->>MT: 영어 응답
    MT->>TTS: 한국어 텍스트
    TTS->>Customer: 한국어 음성
```

**참고 링크**:
- 🔗 [Google Cloud Translation](https://cloud.google.com/translate)
- 🔗 [API 개요](https://docs.cloud.google.com/translate/docs/api-overview)
- 🔗 [REST API 레퍼런스](https://docs.cloud.google.com/translate/docs/reference/rest)

---

### 2.5 Amazon Translate

**주요 작업**:
- `TranslateText` — 단일 텍스트 블록 실시간 번역
- `TranslateDocument` — 텍스트/HTML/DOCX 문서 번역

**AWS CLI 예시**:

```bash
aws translate translate-text \
  --region us-east-1 \
  --source-language-code "en" \
  --target-language-code "es" \
  --text "hello, world"
```

**통합 조합**: AWS Transcribe (STT) + Amazon Translate (MT) + Amazon Polly (TTS)

**참고 링크**: 🔗 [Amazon Translate 실시간 번역 문서](https://docs.aws.amazon.com/translate/latest/dg/sync-api.html)

---

### 2.6 Naver Papago & NHN Cloud

> [!WARNING]
> 네이버 개발자센터의 **무료 Papago 오픈 API**(`openapi.naver.com/v1/papago/n2mt`)는 종료됐다고 알려져 있다. 다만 종료일(2024-02-29)은 2026-10-20 검색에서 공지 원문을 찾지 못해 **[미확인]**이다.
> **정정(2026-10-20):** "Papago 는 신규 서비스에서 쓸 수 없다"는 틀렸다. Papago Translation 은 **네이버 클라우드 플랫폼(NCP) 유료 API**로 제공된다(텍스트 `https://papago.apigw.ntruss.com/nmt/v1`, 문서·웹 번역, 언어 감지, 용어집, NCP 콘솔 Application 의 Client ID/Secret 인증). NCP 문서는 **원문을 저장하거나 학습에 쓰지 않는다**고 밝힌다. 국내 사업자라 국외 이전 문제가 줄어드는 선택지다(아래 7절). 출처: [NCP Papago Translation API](https://api.ncloud-docs.com/docs/ai-naver-papagonmt)

**Papago NMT API (구 개발자센터, 과거)**:
- 엔드포인트: `https://openapi.naver.com/v1/papago/n2mt`
- 29개 언어쌍, 최대 5,000자
- 비로그인 방식 클라이언트 ID/Secret 인증
- 🔗 [Papago NMT API 문서 (아카이브)](https://developers.naver.com/docs/papago/papago-nmt-api-reference.md)
- 🔗 [Papago API 프로파일 (GitHub)](https://github.com/api-evangelist/papago)

**NHN Cloud Public API**:
- 외부 시스템 연동을 위한 REST API
- 번역 특화 서비스는 별도 확인 필요
- 🔗 [NHN Cloud Public API 개요](https://docs.nhncloud.com/en/nhncloud/en/public-api/overview/)

---

## 3. 텍스트 번역 API와 회화 에이전트 통합 전략

### 3.1 STT+MT+TTS 파이프라인 설계 원칙

지연 최소화를 위한 핵심 전략:

1. **STT 스트리밍**: 발화 종료 전 부분 인식 결과 수신
2. **MT 분할 요청**: 문장 경계·구절 단위로 나누어 번역 요청
3. **TTS 부분 합성**: 이전 부분을 먼저 재생하여 인터랙션 지연 감소

### 3.2 주요 텍스트 번역 서비스 비교 표

| 서비스 | 주요 특징 | 커스터마이즈 | 회화 에이전트 적합성 | 문서 링크 |
|--------|-----------|-------------|---------------------|-----------|
| **OpenAI (모델 기반)** | 범용 LLM 번역, 문맥 이해, 복합 작업 동시 수행 | 프롬프트 기반 제어 | LLM 에이전트와 번역을 한 모델에서 처리 → 설계 단순화 | OpenAI Responses/Translations 문서 |
| **Azure Translator** | Foundry Tools, 100개+ 언어, 에이전트형 사용 사례 | Custom Translator + Speech 연동 | 엔터프라이즈 회화 에이전트에 적합 | [링크](https://azure.microsoft.com/en-us/products/ai-foundry/tools/translator) |
| **DeepL API** | 고품질, 용어집·스타일 룰·번역 메모리 | 용어집, 스타일 규칙 | 도메인 특화 전문 용어·브랜드명 번역 | [링크](https://developers.deepl.com/docs/getting-started/auth) |
| **Google Cloud Translation** | 189개 언어, Glossary·Adaptive MT | Glossary, 사용자 정의 모델 | 다국어 콜센터·영상 자막·음성 더빙 | [링크](https://docs.cloud.google.com/translate/docs/api-overview) |
| **Amazon Translate** | TranslateText/Document, AWS 생태계 통합 | 자동 언어 감지 | AWS 마이크로서비스 아키텍처 내 자연스러운 통합 | [링크](https://docs.aws.amazon.com/translate/latest/dg/sync-api.html) |
| **Papago (구 오픈 API 종료 → NCP 유료)** | 한국어 중심 | 용어집·언어 감지 | 구 무료 API 는 종료, **NCP Papago Translation 으로 사용 가능**(원문 미저장·미학습 명시) | [링크](https://developers.naver.com/docs/papago/papago-nmt-api-reference.md) |

### 3.3 언어 감지와 다국어 회화 흐름 관리

**음성 기반 언어 감지 → 번역 API 연동 흐름**:

```mermaid
graph TD
    A["🎤 음성 입력"] --> B{"STT 언어 감지"}
    B -->|한국어| C["Translation API<br/>ko → en"]
    B -->|영어| D["Translation API<br/>en → ko"]
    B -->|일본어| E["Translation API<br/>ja → ko"]
    C --> F["TTS (영어 음성)"]
    D --> G["TTS (한국어 음성)"]
    E --> H["TTS (한국어 음성)"]
```

> [!TIP]
> STT 단계에서 이미 언어를 감지할 수 있으므로, 번역 API에서 중복 감지를 피할 수 있다. Azure Speech SDK와 Google Speech-to-Text 모두 다중 후보 언어 설정을 지원한다.

---

## 4. 실시간 음성 회화 번역 GitHub 저장소 레퍼런스

### 4.1 GPT-Realtime-Translate Live Event Interpreter

🔗 **저장소**: [backblaze-b2-samples/gpt-realtime-translate-live-event-interpreter](https://github.com/backblaze-b2-samples/gpt-realtime-translate-live-event-interpreter)

| 항목 | 내용 |
|------|------|
| **스택** | FastAPI (백엔드) + Next.js (프론트엔드) |
| **기능** | 발표자 1명 → N개 언어 동시 번역, 실시간 캡션, 음성 재생 |
| **API** | OpenAI Realtime API (`openai_realtime.py` 래핑) |
| **아카이브** | 원본 음성/트랜스크립트, VTT/SRT 캡션, 번역 음성 → Backblaze B2 저장 |

**배울 수 있는 설계 패턴**:
1. 하나의 소스 음성 → 여러 대상 언어 동시 번역 구조
2. 브라우저 마이크 → OpenAI Realtime 세션 연결
3. 참가자에게 WebSocket/SSE로 번역 결과 스트리밍
4. 이벤트 아카이브를 클라우드 저장소에 구조화 저장

---

### 4.2 local-multilingual-voice-translator

🔗 **저장소**: [dwain-barnes/local-multilingual-voice-translator](https://github.com/dwain-barnes/local-multilingual-voice-translator)

| 항목 | 내용 |
|------|------|
| **스택** | HTML/JS 웹 앱 + LM Studio + Chatterbox TTS |
| **기능** | 23개+ 언어, 로컬 LLM 기반 음성 번역, 실시간 트랜스크립트 |
| **특징** | 클라우드 의존도 최소화, EventSource 기반 TTS 스트리밍 |

**배울 수 있는 요소**:
1. 소스·타겟 언어 선택 UI 설계 & 언어 코드 매핑 패턴
2. EventSource/WebSocket을 이용한 TTS 오디오 브라우저 재생
3. 로컬 LLM+TTS 아키텍처로 클라우드 비용 절감

---

### 4.3 speech-to-speech-translator

🔗 **저장소**: [acyclics/speech-to-speech-translator](https://github.com/acyclics/speech-to-speech-translator)

| 항목 | 내용 |
|------|------|
| **환경** | Linux/Unix 로컬 데스크톱 |
| **구조** | STT + MT + TTS 전통적 파이프라인 조합 |
| **특징** | 오픈소스 구성 요소 + 타사 API 조합, 마이크 입력 → 음성 출력 |

**배울 수 있는 요소**:
1. 로컬 오디오 파이프라인 (마이크 입력 → 음성 출력)
2. 여러 API를 조합한 Speech-to-Speech Translation 코드 구조
3. Linux/Unix 환경에서 의존성 설치·녹음·재생 장치 관리

---

### 4.4 Azure Speech SDK C# 샘플

🔗 **저장소**: [Azure-Samples/cognitive-services-speech-sdk (C# Console)](https://github.com/Azure-Samples/cognitive-services-speech-sdk/tree/master/samples/csharp/dotnetcore/console)

- .NET 8.0+ 콘솔 앱
- 음성 인식, 의도 인식, **번역**, 발음 평가, 키워드 인식 등 다양한 시나리오
- Azure Speech 서비스 구독 키 인증
- Azure 기반 음성 번역 구현 시 필수 참조

---

### 4.5 Papago API 프로파일

🔗 **저장소**: [api-evangelist/papago](https://github.com/api-evangelist/papago)

- Papago NMT 번역, 언어 감지, 문서/웹사이트 번역, 용어집 API 정리
- 29개 언어쌍, 한국어 중심
- ⚠️ 오픈 API 종료로 **과거 설계 분석용** 참고 자료

---

## 5. 실시간 회화 에이전트 번역 모듈 설계 지침

### 5.1 통합형 vs 모듈형 선택 가이드

```mermaid
graph TD
    A{"프로젝트 규모?"} -->|소규모/프로토타입| B["통합형 Realtime<br/>(OpenAI gpt-realtime-translate)"]
    A -->|대규모/엔터프라이즈| C{"도메인 특화 필요?"}
    C -->|예| D["모듈형 파이프라인<br/>(STT + DeepL/Cloud Translation + TTS)"]
    C -->|아니오| E{"클라우드 환경?"}
    E -->|Azure| F["Azure Speech + Translator"]
    E -->|GCP| G["Cloud STT + Translation + TTS"]
    E -->|AWS| H["Transcribe + Translate + Polly"]
```

### 5.2 WebRTC & WebSocket 스트리밍 구조

**브라우저 환경 (WebRTC)**:
```
브라우저 → RTCPeerConnection → SDP Offer → 서버/번역 세션
                                          ↓
브라우저 ← Remote Audio Track ← 번역된 음성 ← 세션 응답
```

**서버 환경 (WebSocket)**:
```
Twilio/SIP → PCM 오디오 → 서버 → 24kHz PCM16 base64 → WebSocket
                                                        ↓
Twilio/SIP ← 번역 음성 ← 서버 ← 음성·텍스트 델타 ← WebSocket 응답
```

### 5.3 코드 예시: OpenAI Realtime Translation WebSocket (Node.js)

```javascript
import WebSocket from "ws";
import fs from "fs";

const apiKey = process.env.OPENAI_API_KEY;
const safetyId = "hashed-user-id";

const ws = new WebSocket(
  "wss://api.openai.com/v1/realtime/translations?model=gpt-realtime-translate",
  {
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "OpenAI-Safety-Identifier": safetyId,
    },
  }
);

// ⚠️ 2026-10-20 정정: 처음 실린 예시의 이벤트 이름(input_audio_buffer.append·commit,
// output_audio_delta, output_text_delta)은 번역 세션의 이름이 아니었다. 번역 세션은 모든 이벤트가
// `session.` 으로 시작하고 commit·response.create 가 없다. 아래는 공식 가이드와
// backblaze 샘플(services/api/app/repo/openai_realtime.py·tests/test_realtime.py)로 확인한 형태다.
ws.on("open", () => {
  // 1) 출력 언어를 정한다(세션 하나 = 출력 언어 하나)
  ws.send(JSON.stringify({
    type: "session.update",
    session: { audio: { output: { language: "en" } } },
  }));

  // 2) 24kHz PCM16 mono 를 조금씩(예: 100ms = 4,800바이트) base64 로 보낸다
  const pcm = fs.readFileSync("input.pcm");
  for (let i = 0; i < pcm.length; i += 4800) {
    ws.send(JSON.stringify({
      type: "session.input_audio_buffer.append",
      audio: pcm.subarray(i, i + 4800).toString("base64"),
    }));
  }
});

ws.on("message", (data) => {
  const event = JSON.parse(data.toString());
  if (event.type === "session.output_audio.delta") {          // 번역된 음성(base64 PCM16)
    const audioBytes = Buffer.from(event.delta, "base64");
    console.log("translated audio bytes:", audioBytes.length);
  } else if (event.type === "session.output_transcript.delta") { // 번역 자막
    process.stdout.write(event.delta);
  } else if (event.type === "session.input_transcript.delta") {  // 원문 전사
    // 원문 자막이 필요하면 여기서 쓴다
  }
});

// 끝낼 때: ws.send(JSON.stringify({ type: "session.close" })) → 서버가 session.closed 를 보낸다

ws.on("close", () => console.log("WebSocket closed"));
ws.on("error", (err) => console.error("WebSocket error:", err));
```

### 5.4 코드 예시: Azure Speech Translation (C#)

```csharp
using System;
using Microsoft.CognitiveServices.Speech;
using Microsoft.CognitiveServices.Speech.Translation;

class Program
{
    static async Task Main(string[] args)
    {
        var subscriptionKey = Environment.GetEnvironmentVariable("AZURE_SPEECH_KEY");
        var region = Environment.GetEnvironmentVariable("AZURE_SPEECH_REGION");

        var config = SpeechTranslationConfig.FromSubscription(subscriptionKey, region);
        config.SpeechRecognitionLanguage = "ko-KR";
        config.AddTargetLanguage("en");

        using var recognizer = new TranslationRecognizer(config);

        Console.WriteLine("Speak into your microphone.");
        var result = await recognizer.RecognizeOnceAsync();

        if (result.Reason == ResultReason.TranslatedSpeech)
        {
            Console.WriteLine($"Recognized: {result.Text}");
            foreach (var element in result.Translations)
            {
                Console.WriteLine($"Translated into {element.Key}: {element.Value}");
            }
        }
        else
        {
            Console.WriteLine($"Error: {result.Reason}");
        }
    }
}
```

> [!TIP]
> 실시간 스트리밍에는 `StartContinuousRecognitionAsync`를 사용하여 이벤트 기반 처리 구조를 구성한다.

### 5.5 코드 예시: DeepL 텍스트 번역 (Python)

```python
import requests
import os

auth_key = os.environ["DEEPL_AUTH_KEY"]
endpoint = "https://api.deepl.com/v2/translate"

params = {
    "text": "안녕하세요. 실시간 회화 에이전트 번역 테스트입니다.",
    "source_lang": "KO",
    "target_lang": "EN",
}

headers = {
    "Authorization": f"DeepL-Auth-Key {auth_key}",
}

response = requests.post(endpoint, data=params, headers=headers)
response.raise_for_status()

data = response.json()
for translation in data["translations"]:
    print("Translated text:", translation["text"])
```

### 5.6 코드 예시: Google Cloud Translation Advanced (Python)

```python
from google.cloud import translate_v3 as translate

client = translate.TranslationServiceClient()

project_id = "your-gcp-project-id"
location = "global"
parent = f"projects/{project_id}/locations/{location}"

response = client.translate_text(
    request={
        "parent": parent,
        "contents": ["실시간 회화 에이전트 번역 테스트입니다."],
        "mime_type": "text/plain",
        "source_language_code": "ko",
        "target_language_code": "en",
    }
)

for translation in response.translations:
    print("Translated text:", translation.translated_text)
```

---

## 6. 시나리오별 추천 조합과 참고 자료 정리

### 6.1 교육용 실시간 회화 에이전트

| 요소 | 추천 |
|------|------|
| **번역 코어** | OpenAI gpt-realtime-translate (브라우저 WebRTC) |
| **학습 피드백** | GPT-4 계열 LLM 에이전트 (문법·어휘·발음 피드백) |
| **연결 방식** | WebRTC (브라우저 마이크) |
| **참고 저장소** | [GPT-Realtime-Translate Live Event Interpreter](https://github.com/backblaze-b2-samples/gpt-realtime-translate-live-event-interpreter), [local-multilingual-voice-translator](https://github.com/dwain-barnes/local-multilingual-voice-translator) |

> **여행영어(MADI) 프로젝트 적용 시사점**:
> - **1b단계 (턴 단위 자유 응답)**: 대화 상대의 대사 생성 시 한국어 번역 힌트 제공을 위해 경량 MT API(DeepL API 또는 Gemini 내장 번역)를 `/talk/turn` 백엔드에 통합.
> - **2단계 (실시간 스트리밍 모드)**: Gemini Live(임시 토큰)의 단일 전사 한계를 보완하기 위해 브라우저 WebRTC 기반 OpenAI `gpt-realtime-translate` 또는 Azure Speech Translation과의 성능·비용·지연 비교 기준으로 활용([02-tech.md](realtime-agent/02-tech.md) 참조).

### 6.2 콜센터·고객 지원용 회화 에이전트

| 클라우드 | 추천 조합 | 참고 저장소 |
|---------|-----------|------------|
| **Azure** | Azure Speech + Azure Translator + Microsoft Agent Framework | [Azure Speech SDK 샘플](https://github.com/Azure-Samples/cognitive-services-speech-sdk/tree/master/samples/csharp/dotnetcore/console) |
| **GCP** | Cloud STT + Cloud Translation + Cloud TTS + Customer Engagement Suite | [Google Cloud Translation 문서](https://docs.cloud.google.com/translate/docs/api-overview) |
| **AWS** | Transcribe + Translate + Polly | [Amazon Translate 문서](https://docs.aws.amazon.com/translate/latest/dg/sync-api.html) |

### 6.3 회의·웨비나·라이브 이벤트 통역

| 요소 | 추천 |
|------|------|
| **번역 코어** | OpenAI gpt-realtime-translate (다중 언어 세션) |
| **아키텍처** | 1 소스 → N 언어 동시 번역, WebSocket/SSE 스트리밍 |
| **아카이브** | 원본·번역 음성/텍스트, VTT/SRT 캡션 → 클라우드 저장소 |
| **핵심 참고** | [GPT-Realtime-Translate Live Event Interpreter](https://github.com/backblaze-b2-samples/gpt-realtime-translate-live-event-interpreter) |

---

## 7. 검증과 마디 적용 (2026-10-20 보강)

이 문서와 함께 받은 추가 조사(Gemini Live Translation, DeepL Voice, Azure Live Interpreter, Sokuji, Agora, LiveKit 다중 사용자 번역)를 **공식 문서와 받아 둔 저장소 코드로 대조**했다. 저장소는 읽기만 했고 실행하지 않았다.

### 7.1 검증표

| 주장 | 결과 | 근거 |
|---|---|---|
| OpenAI `gpt-realtime-translate`, `wss://…/v1/realtime/translations`, `…/translations/client_secrets` | **맞음.** WebRTC 용 `…/translations/calls` 도 있다 | [OpenAI 가이드](https://developers.openai.com/api/docs/guides/realtime-translation) |
| 번역 세션 이벤트 이름 | **처음 실린 예시가 틀렸다**(5.3 정정). 실제는 `session.update`·`session.input_audio_buffer.append`·`session.output_audio.delta`·`session.output_transcript.delta`·`session.input_transcript.delta`·`session.close`/`session.closed`. commit·`response.create` 없음 | 위 가이드, backblaze 샘플 `services/api/app/repo/openai_realtime.py`·`tests/test_realtime.py` |
| 입력 24kHz PCM16, 200ms 청크 권장 | 24kHz PCM16 은 맞음. **200ms 권장은 [미확인]** — 가이드 Ruby 예시는 4,800바이트(약 100ms) | 위 가이드 |
| 번역 세션과 도구 호출형 에이전트 세션은 별개 | **맞음.** 가이드는 도구 호출을 음성 에이전트 세션에만 둔다 | 위 가이드 |
| Gemini Live Translation | **있음.** `gemini-3.5-live-translate-preview`, `generationConfig.translationConfig`(`targetLanguageCode`, `echoTargetLanguage`), 70+ 언어(ko 포함), 입력 16kHz·출력 24kHz PCM, 100ms 청크 권장, 임시 토큰은 v1beta. **"번역만 — 도구·지시 미지원", 오디오 입력만(텍스트 불가)** | [Gemini Live Translate](https://ai.google.dev/gemini-api/docs/live-api/live-translate) |
| DeepL Voice API | **맞음.** WebSocket 으로 전사·번역·번역 음성, 여러 용어집 우선순위 적용. **유료 DeepL API 구독**이면 사용 가능. 한국어 지원 여부는 개요에 없음 **[미확인]** | [DeepL Voice 개요](https://developers.deepl.com/docs/voice/overview) |
| Azure Live Interpreter 는 제한 접근 승인 필요 | **부분적으로 틀림.** 승인이 필요한 것은 **개인 음성(BYO voice)** 뿐이다. Live Interpreter 자체는 입력 언어 자동 감지·대화 중 언어 전환을 제공 | [Azure Speech translation](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/speech-translation) |
| Papago 신규 사용 불가 | **틀림** — NCP 유료 API 로 제공(2.6 정정) | [NCP Papago](https://api.ncloud-docs.com/docs/ai-naver-papagonmt) |
| LiveKit 다중 사용자 번역 예제 | **있음.** `examples/other/translation/multi-user-translator.py`: 참가자 토큰 속성의 언어별로 번역 작업을 만들고 LLM 번역 + TTS 음성 트랙 `"{입력트랙}-{언어}"` 과 자막 텍스트 스트림을 방에 게시 | 받아 둔 `livekit/agents` |
| Sokuji | **있음.** 양방향 회의 통역 앱. 클라우드(OpenAI·Gemini 등) 또는 **기기 안 추론(WASM·WebGPU, 오프라인)**. **라이선스 AGPL-3.0** — 코드를 가져오면 우리 코드도 AGPL 의무가 생기므로 **구조만 참고** | 받아 둔 `kizuna-ai-lab/sokuji` README |
| Agora 번역 레시피 | **있음.** Deepgram STT → OpenAI 번역 → MiniMax TTS, MIT | 받아 둔 `AgoraIO-Conversational-AI/recipe-agent-translator` README |

### 7.2 마디에 주는 의미

1. **번역 전용 모드는 회화 상대가 될 수 없다.** OpenAI·Gemini 모두 번역 세션은 지시·도구를 받지 않는다. 그래서 "천천히·쉬운 영어로·막히면 한국어 힌트" 같은 학습 규칙([realtime-agent/03](realtime-agent/03-conversation-design.md))을 걸 수 없다. 회화 상대는 지금 계획대로 **에이전트 세션**(1b Gemini 텍스트 → 2 Gemini Live)이고, 번역 API 는 보조 역할이다.
2. **"내가 하고 싶은 말 → 영어로"(참고 도구 ④) 후보:**
   - **Gemini 텍스트(지금 쓰는 스택):** 프롬프트로 "짧고 공손한 여행 영어, 15단어 이하, 한국어 뜻 확인"을 지시할 수 있다. 다만 결과는 AI 생성물이라 'AI 생성' 표시가 필요하다.
   - **NCP Papago:** 국내 사업자이고 원문을 저장·학습하지 않는다고 명시한다. 국외 이전 고지 부담이 작다. 대신 학습 수준 조절(쉬운 말)은 못 한다.
   - **Gemini Live Translate:** 말로 한 한국어를 바로 영어 음성으로 바꾼다. 하지만 오디오 입력만 받고 지시를 받지 않아, 학습용으로는 쓰기 어렵다.
   - **선택은 [realtime-agent/README.md](realtime-agent/README.md) 8절의 팀 결정과 묶여 있다.** 유료 등급, 처리방침과 국외 이전 고지가 먼저다.
3. **개인정보 측면의 장기 선택지:** Sokuji 처럼 STT·번역·TTS 를 **기기 안에서** 돌리면 음성이 밖으로 나가지 않는다. 다만 모델 크기와 저사양 Android 성능을 실측해야 한다(대표 집단의 기기). AGPL 이라 코드는 가져오지 않는다.
4. **비교 실험 기준(실서비스 전):** 한국어↔영어 실제 음성으로 다섯 가지를 비교한다. ① 첫 번역 음성까지의 지연 ② 끼어들기 ③ 자막 동기화 ④ 고유명사·숫자 정확도 ⑤ 재연결. 카톡 인앱 브라우저도 포함한다([mobile-audio-pipeline-constraints.md](mobile-audio-pipeline-constraints.md)).

### 7.3 받아 둔 참고 저장소 (로컬 `reference/realtime-voice/`, git 무시 · 읽기 전용)

| 경로 | 저장소 | 커밋(받은 날) |
|---|---|---|
| `translation/backblaze-b2-samples_gpt-realtime-translate-live-event-interpreter` | 번역 세션 래퍼와 이벤트 테스트 — 이벤트 이름의 근거 | 2026-10-20 받음 |
| `translation/kizuna-ai-lab_sokuji` | 양방향 통역, 기기 안 추론 (AGPL-3.0) | 〃 |
| `translation/AgoraIO-Conversational-AI_recipe-agent-translator` | STT→LLM 번역→TTS 레시피 (MIT) | `c7f12dc` (2026-08-17) |
| `translation/dwain-barnes_local-multilingual-voice-translator` | 로컬 LLM·TTS 번역 UI | 2026-10-20 받음 |
| `translation/acyclics_speech-to-speech-translator` | STT+MT+TTS 장치형 예제 | 〃 |
| `translation/api-evangelist_papago` | Papago API 표면 정리 | `a064307` (2026-10-17) |
| `translation/Azure-Samples_cognitive-services-speech-sdk` | C#·JS 브라우저·Python 샘플만 (sparse) | `6e3d0b2` (2026-09-30) |
| `core/livekit_livekit` | WebRTC SFU 서버 | `39622cc` (2026-10-19) |
| `core/livekit_agents` (기존) | `examples/other/translation/multi-user-translator.py` | 기존 |

## 부록: 전체 링크 정리

### 서비스 API 문서

| 서비스 | 링크 |
|--------|------|
| OpenAI Realtime Translation | [공식 가이드](https://developers.openai.com/api/docs/guides/realtime-translation) · [중국어 번역본](https://github.com/hl8086/openai-developer-doc-zh/blob/main/zh/guides/realtime-translation.md) |
| Azure Translator | [제품 페이지](https://azure.microsoft.com/en-us/products/ai-foundry/tools/translator) |
| Azure Speech | [제품 페이지](https://azure.microsoft.com/en-us/products/ai-foundry/tools/speech) |
| DeepL API 인증 | [문서](https://developers.deepl.com/docs/getting-started/auth) |
| DeepL Voice WebSocket | [명세](https://developers.deepl.com/api-reference/voice/voice.asyncapi.yaml) |
| Google Cloud Translation | [제품](https://cloud.google.com/translate) · [API 개요](https://docs.cloud.google.com/translate/docs/api-overview) · [REST](https://docs.cloud.google.com/translate/docs/reference/rest) |
| Amazon Translate | [실시간 번역 문서](https://docs.aws.amazon.com/translate/latest/dg/sync-api.html) |
| Papago | [NCP Papago Translation (현행)](https://api.ncloud-docs.com/docs/ai-naver-papagonmt) · [구 개발자센터 NMT (종료)](https://developers.naver.com/docs/papago/papago-nmt-api-reference.md) |
| Gemini Live Translation | [문서](https://ai.google.dev/gemini-api/docs/live-api/live-translate) |
| DeepL Voice API | [개요](https://developers.deepl.com/docs/voice/overview) |
| Azure Speech translation (Live Interpreter) | [개요](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/speech-translation) |
| NHN Cloud | [Public API 개요](https://docs.nhncloud.com/en/nhncloud/en/public-api/overview/) |

### GitHub 저장소

| 저장소 | 설명 |
|--------|------|
| [gpt-realtime-translate-live-event-interpreter](https://github.com/backblaze-b2-samples/gpt-realtime-translate-live-event-interpreter) | FastAPI+Next.js 라이브 이벤트 통역 |
| [local-multilingual-voice-translator](https://github.com/dwain-barnes/local-multilingual-voice-translator) | LM Studio+Chatterbox TTS 로컬 음성 번역 |
| [speech-to-speech-translator](https://github.com/acyclics/speech-to-speech-translator) | STT+MT+TTS 파이프라인 음성 번역 |
| [cognitive-services-speech-sdk (C#)](https://github.com/Azure-Samples/cognitive-services-speech-sdk/tree/master/samples/csharp/dotnetcore/console) | Azure Speech SDK 샘플 |
| [openai-developer-doc-zh](https://github.com/hl8086/openai-developer-doc-zh/blob/main/zh/guides/realtime-translation.md) | OpenAI 문서 중국어 번역 |
| [papago (API Evangelist)](https://github.com/api-evangelist/papago) | Papago API 프로파일 (아카이브) |
| [sokuji](https://github.com/kizuna-ai-lab/sokuji) | 양방향 통역, 기기 안 추론 (AGPL-3.0 — 구조만 참고) |
| [recipe-agent-translator](https://github.com/AgoraIO-Conversational-AI/recipe-agent-translator) | Agora STT→번역→TTS 레시피 (MIT) |
| [livekit/agents 다중 사용자 번역 예제](https://github.com/livekit/agents/blob/main/examples/other/translation/multi-user-translator.py) | 참가자별 언어로 자막·음성 트랙 |
| [livekit/livekit](https://github.com/livekit/livekit) | WebRTC SFU 서버 |

---

> **출처**: OpenAI API Docs, Azure AI Foundry, DeepL Developer Docs, Google Cloud Docs, AWS Docs, Naver Developers, NHN Cloud Docs, 각 GitHub 저장소 README
