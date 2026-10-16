# opsarchive — 탈퇴 실패 증거 봉인 도구

탈퇴가 **완료되지 않았거나 단계가 생략/실패**한 순간의 상태를, **앱도 관리자도 풀 수 없는 형태**로 봉인해
비공개 저장소에 격리하고, GitHub 이슈로는 메타데이터만 통보하는 파이프라인의 **관리자 쪽 도구**다.
전체 설계·위협 모델·런북은 [`docs/ops/EVIDENCE_SEAL.md`](../../docs/ops/EVIDENCE_SEAL.md).

## 이 도구가 지키는 경계

- **앱과 완전히 독립**이다. `backend/` 의 어떤 모듈도 import 하지 않는다(별도 패키지·별도 의존성).
- **개인키는 이 프로세스의 로컬 파일에만** 있다. 파일은 scrypt+AES-256-GCM 으로 잠그고 0600 으로 만든다.
- **패스프레이즈는 TTY 입력으로만** 받는다. 명령줄 인자·환경변수로 받지 않는다(프로세스 목록·크래시 덤프로 샌다).
- 네트워크로 나가는 것은 **공개키**와 **봉인된 아카이브**뿐이다. 평문 키·개인키는 어디에도 보내지 않는다.
- 어떤 출력에도 키·패스프레이즈를 넣지 않는다(지문만 보여준다).

## 설치

```bash
cd tools/opsarchive
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt                    # cryptography, google-auth, (선택) rich
```

## 쓰는 순서(최초 1회)

```bash
python -m opsarchive selftest                      # 봉인·해제·변조 감지·키 잠금 왕복 확인
python -m opsarchive keygen                        # 관리자 키쌍 생성(개인키는 ~/.opsarchive, 0600)
RENDER_API_KEY=rnd_... python -m opsarchive publish --service codyssey-final --key ~/.opsarchive/admin-<id>.key --base-url https://codyssey-final.onrender.com
python -m opsarchive doctor  --service codyssey-final --key ~/.opsarchive/admin-<id>.key --base-url https://codyssey-final.onrender.com
```

`publish` 는 **render CLI** 로 서비스 ID 를 찾고, **Render REST API** 로 환경변수를 바꾼 뒤,
**render CLI** 로 재배포하고 런타임 `/health` 의 키 지문과 대조한다.
(Render CLI 에는 환경변수를 바꾸는 명령이 없어 그 한 단계만 REST 를 쓴다 — 공식 CLI 레퍼런스 확인.)

## 아카이브 열람

```bash
python -m opsarchive list    --project com-example-myapplicatio-3bb36 --sa ./sa.json
python -m opsarchive decrypt --project com-example-myapplicatio-3bb36 --sa ./sa.json --id <archive-id> --key ~/.opsarchive/admin-<id>.key
python -m opsarchive tui                            # rich 메뉴(선택)
```

## 운영 메모

- **회전(rotate)**: 새 키를 만들고 발행한다. **이전 개인키 파일을 지우지 마라** — 옛 아카이브의 `key_id` 가 그 키를 가리킨다.
- **백업**: 개인키는 오프라인 매체에 보관한다. 잃으면 아카이브를 영구히 못 연다(설계상 복구 수단이 없다).
- **`doctor` 를 배포 전에 돌린다** — "회전했는데 옛 키만 들고 있다"는 상태를 조기에 잡는다.

## 컨테이너 형식(MFA1)

```
magic(4) alg(1) ver(1) key_id(8) wrapped_len(2) wrapped(32+48) iv(12) ciphertext+tag(16)
wrapped = ephemeral_pub(32) + AES-GCM(kek, data_key)        kek = HKDF(공유비밀)
본문    = gzip(payload) → AES-256-GCM(data_key, iv, aad=헤더 전체)
```
앱(`backend/app/evidence.py`)이 같은 형식을 독립 구현하고, 백엔드 테스트가 이 패키지의 `unseal` 로
실제로 열어보며 호환을 검증한다.
