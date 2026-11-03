# 발음 사전

| 파일 | 출처 | 라이선스 | SHA256 (압축 푼 내용) |
|---|---|---|---|
| `cmudict.dict.gz` (915,089 B, 원본 3,618,488 B · 135,166줄) | [cmusphinx/cmudict](https://github.com/cmusphinx/cmudict) `cmudict.dict`, 커밋 `74790861f652b15e4ac49015a90074ad62a27690` | BSD 계열 — `CMUDICT_LICENSE` 원문 | `81917843c7f44ce2b094ac63873c2c7a4cf802040792c455ba3ca406891c3d22` |

미국 영어 표준 발음 사전(ARPAbet 39음소, 모음 뒤 숫자는 강세 0·1·2). `app/phonemes.py` 가 처음 쓸 때 한 번 읽고,
압축을 푼 내용의 SHA256 을 확인한다(다르면 읽지 않는다).

- 한 줄: `단어 음소 음소 …`. 같은 단어의 다른 발음은 `the(2)` 처럼 괄호 번호로 이어진다. `# place, danish` 같은 꼬리 주석은 버린다.
- PyPI 의 `cmudict` 패키지는 코드가 GPL-3.0 이라 쓰지 않고, 사전 파일만 그대로 넣었다.
- 사전에 없는 단어(고유명사·숫자·신조어)는 음소를 지어내지 않는다 — `unknown` 으로 두고 음소 오류율 계산에서 뺀다.
  신경망 G2P(g2p_en 등)는 이 단계에서 넣지 않았다.

압축은 `gzip.GzipFile(mtime=0, compresslevel=9)` 로 만들었다(같은 원본이면 같은 바이트).
