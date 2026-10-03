"""실제 /speak-check 를 반복 호출해 score 가 얼마나 오는지 센다.

키가 있는 서버(배포 URL 또는 GEMINI_API_KEY 를 넣은 로컬 서버)에서만 의미가 있다.
키가 없으면 mock 응답이라 이 스크립트가 중단한다.

사용 예 (표준 라이브러리만 사용):
  python backend/scripts/measure_score_rate.py --base https://<앱>.onrender.com \\
      --audio good.webm --target "I have a peanut allergy." --label good --n 10

조건(label)별로 따로 실행해서 비교한다:
  good   목표 문장을 또박또박 읽은 녹음
  bad    일부러 단어를 빼거나 틀리게 읽은 녹음
  silent 말하지 않고 녹음한 파일

호출 사이에 --sleep 초만큼 쉰다 (서버 기본 제한 20회/60초).
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import time
import urllib.error
import urllib.request
import uuid
from collections import Counter
from pathlib import Path


def post_audio(base: str, audio: Path, target: str, timeout: float) -> tuple[int, dict]:
    boundary = uuid.uuid4().hex
    mime = mimetypes.guess_type(audio.name)[0] or "audio/webm"
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="target"\r\n\r\n{target}\r\n'.encode(),
        (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{audio.name}"\r\n'
         f"Content-Type: {mime}\r\n\r\n").encode(),
        audio.read_bytes(),
        f"\r\n--{boundary}--\r\n".encode(),
    ]
    req = urllib.request.Request(
        base.rstrip("/") + "/speak-check",
        data=b"".join(parts),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode("utf-8", "replace")[:200]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--audio", required=True, type=Path)
    ap.add_argument("--target", required=True)
    ap.add_argument("--label", default="run")
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--sleep", type=float, default=4.0)
    ap.add_argument("--timeout", type=float, default=90.0)  # 첫 호출은 콜드스타트로 느릴 수 있다
    a = ap.parse_args()

    tally: Counter[str] = Counter()
    scores: list[float] = []
    for i in range(1, a.n + 1):
        status, res = post_audio(a.base, a.audio, a.target, a.timeout)
        if status != 200:
            tally[f"http_{status}"] += 1
            print(f"[{i}] HTTP {status} {res}")
        elif res.get("mock"):
            print("서버가 mock 모드입니다 (GEMINI_API_KEY 없음). 측정할 수 없습니다.")
            return 2
        else:
            tally["ok_calls"] += 1
            tally["usable" if res.get("usable") else "unusable"] += 1
            if isinstance(res.get("score"), (int, float)):
                tally["score_present"] += 1
                scores.append(float(res["score"]))
            else:
                tally["score_absent"] += 1
            if res.get("score_discarded"):
                tally["score_discarded"] += 1
            if not str(res.get("heard") or "").strip():
                tally["heard_empty"] += 1
            print(f"[{i}] usable={res.get('usable')} score={res.get('score')} heard={res.get('heard')!r} fix_one={res.get('fix_one')!r}")
        if i < a.n:
            time.sleep(a.sleep)

    ok = tally["ok_calls"] or 1
    print(f"\n=== {a.label}: {a.n}회 호출, 정상 응답 {tally['ok_calls']}회 ===")
    for k in ("usable", "unusable", "score_present", "score_absent", "score_discarded", "heard_empty"):
        print(f"{k:16s} {tally[k]:3d}  ({tally[k] / ok:.0%})")
    for k in sorted(k for k in tally if k.startswith("http_")):
        print(f"{k:16s} {tally[k]:3d}")
    if scores:
        print(f"score 범위 {min(scores):.0f}~{max(scores):.0f}, 평균 {sum(scores) / len(scores):.0f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
