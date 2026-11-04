# 음소 노드 — 상시 가동 PC 설치 (Windows + Tailscale Funnel)

본체(Render 무료, 512MB)는 음소 모델(+358MB)을 못 올린다. 늘 켜 둔 개인 PC 가 그 일만 하고,
본체는 말하기 채점 때 그 PC 에 녹음 구간을 보내 **실제 소리 기준 음소 분석**을 받아 온다.
노드가 꺼져 있거나 느려도 채점은 그대로 나간다(음소 줄만 빠진다).

```
사용자 → Render(/speak-check) ──HTTPS + 토큰──▶ https://<PC>.<tailnet>.ts.net (Tailscale Funnel)
                                                    └─▶ 127.0.0.1:8443  python -m app.acoustic.server
```

## 0. Tailscale IP(100.x.y.z)로는 안 된다

`100.x.y.z` 는 tailnet 안에서만 닿는 주소다. Render 는 tailnet 밖(공인 인터넷)이라 그 주소로 보내면 타임아웃이다.
그래서 **Funnel** 로 그 PC 의 로컬 포트를 `https://<PC>.<tailnet>.ts.net` 공개 HTTPS 주소로 연다.
TLS 는 그 PC 에서 끝나므로 Tailscale 중계 서버는 내용을 못 본다. 서버는 127.0.0.1 에만 붙고, 밖에서 닿는 길은 Funnel 하나다.

## 1. 준비 (노드 PC)

| 항목 | 내용 |
|---|---|
| Python | 3.10 이상(python.org), 설치 화면에서 **Add python.exe to PATH** 체크 |
| 저장소 | `git clone https://github.com/01044402345o-beep/codyssey_final` (어디든) |
| Tailscale | 설치·로그인. 관리 콘솔에서 **MagicDNS 켜기**, **HTTPS Certificates 켜기**, 정책 파일에 Funnel 허용(`nodeAttrs` 의 `funnel`) |
| 전원 | 절전·최대 절전 끄기(설정 → 시스템 → 전원), 디스크 여유 1GB |

## 2. 설치 — `backend\phoneme-node` 폴더에서 순서대로

1. **`make_token.cmd`** — `token.txt`(공유 비밀) 생성. 화면에 나온 값을 적어 둔다(4단계에서 Render 에 넣는다).
2. **`serve_phoneme.bat` 을 더블클릭해 손으로 한 번 실행** — 가상환경·패키지·모델(317MB, SHA256 확인)을 준비하고 서버를 띄운다.
   `[4/4] node on http://127.0.0.1:8443` 이 보이면 성공. **창을 닫는다**(다음 단계가 숨겨서 다시 띄운다).
   - 실패하면 창이 멈춰 이유를 보여 준다. 로그: `logs\server.log`
   - 스케줄러에 먼저 등록하면 창이 없어 실패를 못 본다 — 이 단계를 건너뛰지 않는다.
3. **`register_task.cmd`** — 작업 스케줄러 등록 후 바로 시작(창 없음).
   - 기본: **이 사용자가 로그온할 때** 시작(관리자 권한 불필요). PC 가 자동 로그온이 아니면 아래 `startup` 을 쓴다.
   - `register_task.cmd startup` (관리자 권한으로 실행): **부팅할 때 SYSTEM 으로** 시작 — 아무도 로그온하지 않아도 뜬다.
   - 실행 시간 제한 없음, 실패 시 1분 간격 3회 재시작, 배터리 무관, 중복 실행 안 함.
     (`schtasks` 기본값은 72시간 뒤 강제 종료라 쓰지 않았다.)
4. **`funnel_on.cmd`** — Funnel 켜기(처음 한 번은 브라우저 승인). 출력의 `https://<PC>.<tailnet>.ts.net` 을 적어 둔다.
5. **`check_node.cmd`** — 로컬과 공개 주소 둘 다 `"ready": true` 인지 확인.

## 3. Render 연결

Render → codyssey-api → Environment:

| 키 | 값 |
|---|---|
| `PHONEME_REMOTE_URL` | `https://<PC>.<tailnet>.ts.net` (끝에 `/` 없이) |
| `PHONEME_TOKEN` | `token.txt` 와 같은 값 |
| `PHONEME_REMOTE_TIMEOUT` | (선택) 초, 기본 8 |

저장하면 재배포된다. 둘 중 하나라도 없으면 본체는 노드를 부르지 않는다(음성이 새 수신처로 가지 않는다).
확인: 관리자 토큰으로 `/health` 상세를 보면 `"phoneme_node": {"configured": true}`.
말하기 결과 줄에 `소리 분석(실제 음성): …` 이 나오면 연결된 것이다.

## 4. 끄기·되돌리기

| 하고 싶은 것 | 방법 |
|---|---|
| 공개 주소만 닫기 | `funnel_off.cmd` |
| 노드 완전히 끄기 | `unregister_task.cmd` |
| 본체가 노드를 안 부르게 | Render 에서 `PHONEME_REMOTE_URL` 삭제 |
| 토큰 바꾸기 | `token.txt` 삭제 → `make_token.cmd` → Render `PHONEME_TOKEN` 갱신 → 작업 다시 시작 |

## 5. 개인정보 — 켜기 전에

- 사용자 녹음이 **이 PC 로 간다.** 앱 동의 문구 v8 ④와 처리방침 초안 표(`docs/product/privacy-policy-draft.md`)에 적었다.
  PC 위치(국가)는 표에 **[확인 필요]** 로 남아 있다 — 채워 넣는다.
- 노드는 음성을 디스크에 저장하지 않고, 로그에도 음성·문장을 남기지 않는다(`app/acoustic/server.py`).
- 토큰이 24자 미만이거나 없으면 노드는 시작하지 않는다(인증 없는 공개 음성 엔드포인트를 만들지 않는다).

## 6. 이 PC 에서 잰 값 (Windows, 합성음 'Can I have a window seat, please?')

| 항목 | 값 |
|---|---|
| 모델 로드 | 1.2초(SHA256 확인 포함) |
| 메모리 | 약 410MB |
| 추론 | 0.3~0.7초 / 3초 발화 (로컬, 왕복 제외) |
| 'seat' 정확히 | 음소 100%, 지적 없음 |
| 'sit' 로 말함 | `seat` 의 /iː/ → /ɪ/ 를 짚음 |

한계: 합성음 표본이고 사람 평가와 맞춘 점수가 아니다. 'think'→'sink'(θ→s)는 이 표본에서 못 잡았다.
이어 말할 때의 소리 변화(예: 'for sightseeing' 의 /ɹ/)는 가끔 약하게 잡힌다.
