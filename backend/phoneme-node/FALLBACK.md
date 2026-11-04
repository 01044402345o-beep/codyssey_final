# 음소 분석 대체 경로 — PC 노드가 모두 실패할 때

PC 노드가 꺼지거나 절전·네트워크 단절로 **모두** 응답하지 못하면, 본체가 아래 순서로 넘어간다.
**어느 단계에서도 채점은 멈추지 않는다** — 맨 끝까지 실패하면 결과 카드에서 "소리 분석" 줄만 빠진다.

| 단계 | 언제 | 무엇 | 비용 | 설정 |
|---|---|---|---|---|
| 1 | 평소 | PC 노드(목록 순서, 쉬게 하기·자동 복구) | 0 | `PHONEME_REMOTE_URLS` — [ADD_NODE.md](ADD_NODE.md) |
| 1-b | 1의 PC 가 모두 실패 | **클라우드에 띄운 같은 노드**(Hugging Face Space 등) — 목록 맨 뒤 | Space 요금 | 아래 C |
| 2 | 노드가 모두 실패(또는 노드 설정 없음) | **Azure 발음 평가** → 실패하면 **Speechace** | 요청당, **하루 상한** | 아래 A·B |
| 3 | 2도 실패·상한 초과 | 받아쓴 글자 기준 음소 비교(두 받아쓰기가 같은 차이를 낸 단어) | 0 | 없음(항상) |
| 4 | 3도 표시할 게 없음 | 카드에 단어 쪽만(안 들린 단어 강조) | 0 | 없음(항상) |

- 1-b 는 PC 노드와 **같은 모델·같은 결과**다. 2 는 업체 모델이라 점수 기준이 조금 다르다(화면에 "Microsoft Azure 발음 평가"처럼 출처를 적는다).
- 2 는 유료라 **노드가 모두 실패했을 때만** 부르고, 하루 상한(`PHONEME_CLOUD_DAILY_CAP`, 기본 100회)을 넘으면 부르지 않는다.
- 사용자 녹음이 이 업체들로 가므로 앱 동의 문구 v9 ⑤ 와 처리방침 초안 표에 적었다. **키를 넣기 전에 처리방침의 [확인 필요] 칸을 채운다.**

---

## A. Azure 발음 평가 (2단계 첫 번째, 권장)

1. [Azure Portal](https://portal.azure.com) → **리소스 만들기** → "Speech" 검색 → **Speech service**(Azure AI services | Speech) → 만들기
2. 입력
   | 칸 | 값 |
   |---|---|
   | Region | 운영은 **East US**(`eastus`, 2026-11-04). Korea Central 을 고르면 음성이 국내에서 처리된다 — 어느 쪽이든 **처리방침 초안 표의 Azure 발음 평가 행 지역을 같이 고친다** |
   | Name | 아무 이름(예: `madi-phoneme`) |
   | Pricing tier | **Free F0**(월 5시간 무료) — 넘으면 Standard S0 로 바꾼다 |
3. 만들어지면 리소스 → **Keys and Endpoint** → **KEY 1** 과 **Location/Region**(예: `eastus`)을 복사한다
4. Render → codyssey-api → Environment
   | 키 | 값 |
   |---|---|
   | `PHONEME_AZURE_KEY` | KEY 1 |
   | `PHONEME_AZURE_REGION` | `eastus` 등 (Location 그대로, 소문자) |

통역용 `AZURE_SPEECH_KEY` 와는 **따로 둔다**(사용량·리전·상한을 분리). 같은 리소스의 키를 써도 동작은 한다.

## B. Speechace (2단계 두 번째, 선택)

1. [speechace.com](https://www.speechace.com) 에서 API 키를 받는다(유료 계약).
2. Render Environment: `PHONEME_SPEECHACE_KEY` = 받은 키.
   지역 전용 주소를 받았으면 `PHONEME_SPEECHACE_URL`(예: `https://api2.speechace.com`), 없으면 비워 둔다.

## C. Hugging Face Space 노드 (1-b, 선택)

PC 노드와 같은 서버를 Hugging Face 에 띄운다. **Docker Space 는 유료 계정(PRO 등)이 필요하다.**

1. 저장소 루트에서 Space 폴더 만들기:
   ```
   python tools/make_hf_space.py C:\temp\madi-space
   ```
2. Hugging Face → **New Space** → SDK **Docker** → **Private** 권장 → 만든 Space 에 위 폴더 내용을 올린다(웹 업로드 또는 git push)
3. Space → **Settings → Variables and secrets → New secret**: `PHONEME_TOKEN` = PC 노드와 **같은 토큰**
4. 빌드가 끝나면 주소 `https://<사용자>-<space>.hf.space` 를 관리자 점검 도구로 확인:
   ```
   python tools\check_phoneme_nodes.py https://<PC1>.<tailnet>.ts.net https://<사용자>-<space>.hf.space
   ```
5. 나온 `PHONEME_REMOTE_URLS=…` 를 Render 에 넣는다(Space 주소는 **맨 뒤** — PC 가 모두 실패했을 때만 쓰이게).

- Private Space 는 HF 로그인이 필요해 본체가 닿지 않을 수 있다. 그때는 Public 으로 두되 토큰이 지킨다(소스는 공개된다 — 비밀은 Secrets 에만).
- 쓰지 않으면 잠드는 Space 는 첫 요청에서 늦어 실패할 수 있다. 본체는 실패하면 다음(2단계)으로 넘어가고, 30초마다 다시 확인해 살아나면 되돌린다.
- 같은 이미지를 Cloud Run 등에도 쓸 수 있다: `docker build -f backend/phoneme-node/Dockerfile .`(BuildKit, 전용 `Dockerfile.dockerignore` 사용).

---

## 상한·시간 설정 (선택)

| 변수 | 기본 | 뜻 |
|---|---|---|
| `PHONEME_CLOUD_DAILY_CAP` | 100 | 2단계 하루 호출 상한. 0 이면 2단계 끔. 서버 메모리에 세므로 재시작하면 0부터 |
| `PHONEME_CLOUD_ORDER` | `azure,speechace` | 2단계 순서. 키가 있는 업체만 쓰인다 |
| `PHONEME_CLOUD_TIMEOUT` / `PHONEME_CLOUD_BUDGET` | 6 / 8 초 | 업체 한 곳 / 2단계 전체 |

피드백 문장 생성과 동시에 돌므로 응답 시간이 늘지 않는다(가장 느린 쪽만큼).

## 확인

- 관리자 토큰으로 `/health` 상세 → `phoneme_node`: 노드별 `up`·`fails`·`rest_s`, `cloud.providers`(키가 있는 업체), `cloud.cap.used/limit`
- 화면: 결과 카드 아래 `소리 분석은 AI 음소 인식 결과예요(Microsoft Azure 발음 평가)` 처럼 출처가 보이면 2단계로 처리된 것
- 강제로 시험하려면 PC 노드를 잠깐 끈다(`funnel_off.cmd`) — 2회 실패 뒤 60초 동안 노드를 건너뛰고 바로 클라우드로 간다

## 되돌리기

| 하고 싶은 것 | 방법 |
|---|---|
| 클라우드 대체 끄기 | `PHONEME_CLOUD_DAILY_CAP=0` 또는 `PHONEME_AZURE_KEY`·`PHONEME_SPEECHACE_KEY` 삭제 |
| Speechace 만 빼기 | `PHONEME_CLOUD_ORDER=azure` |
| HF 노드 빼기 | `PHONEME_REMOTE_URLS` 에서 그 주소 삭제 |
