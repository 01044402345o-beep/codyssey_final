"""실제 /speak-check 를 반복 호출해 "유효한 score"가 얼마나 오는지 센다.

키가 있는 서버(배포 URL 또는 GEMINI_API_KEY 를 넣은 로컬 서버)에서만 의미가 있다.
서버가 mock 모드면 측정할 수 없으므로 중단한다.

사용 예 (표준 라이브러리만 사용):
  python backend/scripts/measure_score_rate.py --base https://<앱>.onrender.com \\
      --audio good.webm --target "I have a peanut allergy." --label good --n 10

조건(label)별로 따로 실행한다: good(또박또박) / bad(일부러 틀리게) / silent(무음).
같은 파일을 n번 보내는 것이므로 "응답의 일관성"을 본다. 서로 다른 발화 n개를 평가한 것과 같지 않다.

보고하는 네 가지 (분모가 다르다):
  1. HTTP 성공            / 전체 요청
  2. usable:true          / 실제 응답(HTTP 성공, mock 아님)
  3. 유효 score           / usable:true 응답
  4. score 없음 + heard 있음 / usable:true 응답   (heardCoverage 경로가 쓰이는 경우)
유효 score = bool 제외 · 유한한 숫자 · 0~100 · score_discarded 아님.
호출마다 원본 JSON 을 --out(기본 measure_<label>.jsonl)에 남긴다.
"""
from __future__ import annotations

import argparse
import json
import math
import mimetypes
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path


def is_valid_score(res: dict) -> bool:
    s = res.get("score")
    if isinstance(s, bool) or not isinstance(s, (int, float)):
        return False
    return math.isfinite(s) and 0 <= s <= 100 and res.get("score_discarded") is not True


def classify(status: int | None, res: dict | None, error: str | None = None) -> dict[str, bool]:
    """한 번의 호출을 분류한다. 네트워크 오류·JSON 오류는 http_ok=False."""
    res = res if isinstance(res, dict) else {}
    http_ok = status == 200 and error is None and bool(res)
    real = http_ok and res.get("mock") is not True
    usable = real and res.get("usable") is True
    valid_score = usable and is_valid_score(res)
    heard = isinstance(res.get("heard"), str) and bool(res["heard"].strip())
    return {
        "http_ok": http_ok,
        "mock": http_ok and res.get("mock") is True,
        "real": real,
        "usable": usable,
        "valid_score": valid_score,
        "no_score_with_heard": usable and not valid_score and res.get("score_discarded") is not True and heard,
        "score_discarded": real and res.get("score_discarded") is True,
        "heard_empty": real and not heard,
    }


def post_audio(base: str, audio: Path, target: str, timeout: float) -> tuple[int | None, dict | None, str | None]:
    boundary = uuid.uuid4().hex
    mime = mimetypes.guess_type(audio.name)[0] or "audio/webm"
    body = b"".join([
        f'--{boundary}\r\nContent-Disposition: form-data; name="target"\r\n\r\n{target}\r\n'.encode(),
        (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{audio.name}"\r\n'
         f"Content-Type: {mime}\r\n\r\n").encode(),
        audio.read_bytes(),
        f"\r\n--{boundary}--\r\n".encode(),
    ])
    req = urllib.request.Request(
        base.rstrip("/") + "/speak-check", data=body, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
            status = r.status
    except urllib.error.HTTPError as e:
        return e.code, None, f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:200]}"
    except Exception as e:  # noqa: BLE001 — 타임아웃·연결 오류가 반복 측정을 멈추면 안 된다
        return None, None, f"{type(e).__name__}: {e}"
    try:
        return status, json.loads(raw), None
    except ValueError as e:
        return status, None, f"invalid JSON: {e}: {raw[:200]!r}"


def summarize(rows: list[dict[str, bool]]) -> dict[str, tuple[int, int]]:
    n = len(rows)
    real = sum(r["real"] for r in rows)
    usable = sum(r["usable"] for r in rows)
    return {
        "1 HTTP 성공 / 전체 요청": (sum(r["http_ok"] for r in rows), n),
        "2 usable:true / 실제 응답": (usable, real),
        "3 유효 score / usable:true": (sum(r["valid_score"] for r in rows), usable),
        "4 score 없음+heard 있음 / usable:true": (sum(r["no_score_with_heard"] for r in rows), usable),
        "  (참고) score_discarded / 실제 응답": (sum(r["score_discarded"] for r in rows), real),
        "  (참고) heard 비어 있음 / 실제 응답": (sum(r["heard_empty"] for r in rows), real),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--audio", required=True, type=Path)
    ap.add_argument("--target", required=True)
    ap.add_argument("--label", default="run")
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--sleep", type=float, default=4.0)   # 서버 기본 제한 20회/60초
    ap.add_argument("--timeout", type=float, default=90.0)  # 첫 호출은 콜드스타트로 느릴 수 있다
    ap.add_argument("--out", type=Path, default=None, help="호출별 원본 JSON(jsonl). 기본 measure_<label>.jsonl")
    a = ap.parse_args()
    out = a.out or Path(f"measure_{a.label}.jsonl")

    rows: list[dict[str, bool]] = []
    with out.open("a", encoding="utf-8") as f:
        for i in range(1, a.n + 1):
            status, res, err = post_audio(a.base, a.audio, a.target, a.timeout)
            c = classify(status, res, err)
            if c["mock"]:
                print("서버가 mock 모드입니다 (GEMINI_API_KEY 없음). 측정할 수 없습니다.")
                return 2
            rows.append(c)
            f.write(json.dumps({"i": i, "label": a.label, "status": status, "error": err, "response": res, "class": c}, ensure_ascii=False) + "\n")
            f.flush()
            print(f"[{i}] http={status} err={err} usable={None if not res else res.get('usable')} "
                  f"score={None if not res else res.get('score')!r} heard={None if not res else res.get('heard')!r}")
            if i < a.n:
                time.sleep(a.sleep)

    print(f"\n=== {a.label}: {a.n}회 (원본: {out}) ===")
    for k, (num, den) in summarize(rows).items():
        print(f"{k:42s} {num:3d} / {den:3d}" + (f"  ({num / den:.0%})" if den else "  (분모 0)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
