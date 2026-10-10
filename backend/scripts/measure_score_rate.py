"""실제 /speak-check 를 반복 호출해 결과(채점·거부 사유)와 응답 시간을 센다.

현재 서버 구조(main): 말소리 검출(Silero → 로컬 pyannote) → 전사 2종(Groq/OpenAI · AssemblyAI) 교차검증
→ 점수는 코드가 계산. 그래서 점수는 "오거나 말거나"가 아니라 usable:true 이면 항상 숫자이고, 실패는
usable:false + 사유(vad / cross_validation / stt)로 온다. 이 스크립트는 그 사유별 분포를 센다(outcome).
말소리 검출은 키 없이도 동작하므로 --label silent 는 키 없는 서버에서도 측정할 수 있다.
good/bad 는 전사 키(교차검증 포함)가 있는 서버에서만 의미가 있고, 키가 없으면(mock·키 누락) 중단한다.

사용 예 (표준 라이브러리만 사용):
  python backend/scripts/measure_score_rate.py --base https://<앱>.onrender.com \\
      --audio good.webm --target "I have a peanut allergy." --label good --n 10

조건(label)별로 따로 실행한다: good(또박또박) / bad(일부러 틀리게) / silent(무음).
같은 파일을 n번 보내는 것이므로 "응답의 일관성"을 본다. 서로 다른 발화 n개를 평가한 것과 같지 않다.

보고 (분모가 다르다):
  0. outcome 분포 / 전체 요청  — scored · vad_silero · vad_pyannote · no_keys · cross_failed · stt_failed ·
     placeholder · mock · http_error · other
  0'. 응답 시간(초) min / 중앙값 / max  (콜드스타트 포함 여부는 호출 순서로 구분: JSONL 의 i)
  --label silent 는 scored 가 0 이어야 정상이다(무음이 채점되면 결함). good 은 scored 비율이 거부율의 여집합.
  아래 1~4 는 이전 구조(AI 가 점수를 낼 수도 생략할 수도 있던 때)의 지표로, 비교를 위해 남겨 둔다:
  1. HTTP 성공            / 전체 요청
  2. usable:true          / 실제 응답(HTTP 성공, mock 아님)
  3. 유효 score           / usable:true 응답
  4. 점수 누락(null/없음) + heard 있음 / usable:true 응답   (프론트의 다른 조건도 충족하면 'ask' 후보. ask 발생률이 아님)
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
    score_missing = res.get("score") is None
    discarded = res.get("score_discarded") is True
    return {
        "http_ok": http_ok,
        "mock": http_ok and res.get("mock") is True,
        "real": real,
        "usable": usable,
        "valid_score": valid_score,
        # 점수가 "없는"(null/누락) 경우만. 값이 있으나 무효(150, true, "40" 등)는 invalid_score 로 따로 센다.
        "no_score_with_heard": usable and score_missing and not discarded and heard,
        "invalid_score": usable and not score_missing and not valid_score,
        "score_discarded": real and discarded,
        "heard_empty": real and not heard,
    }


def outcome(status: int | None, res: dict | None, error: str | None = None) -> str:
    """응답을 한 가지 결과로 분류한다 (main.py /speak-check 의 반환 모양 기준)."""
    if status != 200 or error is not None or not isinstance(res, dict) or not res:
        return "http_error"
    if res.get("mock") is True:
        return "mock"
    if res.get("usable") is True:
        return "scored" if is_valid_score(res) else "other"
    failed_at = res.get("failed_at")
    cv = res.get("cross_validation") if isinstance(res.get("cross_validation"), dict) else {}
    if failed_at == "cross_validation":
        return "no_keys" if cv.get("missing_keys") else "cross_failed"
    if failed_at == "stt":
        return "stt_failed"
    if "heard_raw" in res or "heard_checker_raw" in res:
        return "placeholder"          # 전사 결과가 환각/빈 문장이라 거부
    if "detector" in cv:
        return "vad_pyannote"         # Silero 는 말소리라 했으나 두 번째 검출기가 아니라고 함
    if "vad" in res:
        return "vad_silero"           # 첫 검출기에서 말소리 0초
    return "other"


OUTCOMES = ("scored", "vad_silero", "vad_pyannote", "placeholder", "no_keys", "cross_failed", "stt_failed",
            "mock", "http_error", "other")


def latency_stats(values: list[float]) -> dict[str, float] | None:
    v = sorted(x for x in values if isinstance(x, (int, float)))
    if not v:
        return None
    mid = v[len(v) // 2] if len(v) % 2 else (v[len(v) // 2 - 1] + v[len(v) // 2]) / 2
    return {"min": v[0], "median": mid, "max": v[-1]}


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
        "4 점수 누락(null)+heard 있음 / usable:true": (sum(r["no_score_with_heard"] for r in rows), usable),
        "  (참고) 값은 있으나 무효한 점수 / usable:true": (sum(r["invalid_score"] for r in rows), usable),
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

    rows: list[dict] = []
    secs_list: list[float] = []
    with out.open("a", encoding="utf-8") as f:
        for i in range(1, a.n + 1):
            t0 = time.monotonic()
            status, res, err = post_audio(a.base, a.audio, a.target, a.timeout)
            secs = round(time.monotonic() - t0, 2)
            c = classify(status, res, err)
            oc = outcome(status, res, err)
            c["outcome"] = oc
            # 전사 키가 없으면(mock·교차검증 키 누락) good/bad 는 측정할 수 없다. silent 는 말소리 검출만으로 판정되므로 계속한다.
            if oc in ("mock", "no_keys") and a.label != "silent":
                print(f"서버가 채점할 수 없는 상태입니다 ({oc}: {None if not res else res.get('reason')}). 측정할 수 없습니다.")
                return 2
            rows.append(c)
            secs_list.append(secs)
            f.write(json.dumps({"i": i, "label": a.label, "status": status, "error": err, "seconds": secs,
                                "outcome": oc, "response": res, "class": c}, ensure_ascii=False) + "\n")
            f.flush()
            vad = (res or {}).get("vad") or {}
            print(f"[{i}] http={status} {secs}s outcome={oc} usable={None if not res else res.get('usable')} "
                  f"score={None if not res else res.get('score')!r} heard={None if not res else res.get('heard')!r} "
                  f"vad_speech_sec={vad.get('speech_sec')}"
                  + (f" err={err}" if err else ""))
            if i < a.n:
                time.sleep(a.sleep)

    print(f"\n=== {a.label}: {a.n}회 (원본: {out}) ===")
    counts = {o: sum(r["outcome"] == o for r in rows) for o in OUTCOMES}
    print("0 결과(outcome) 분포 / 전체 요청")
    for o in OUTCOMES:
        if counts[o]:
            print(f"    {o:14s} {counts[o]:3d} / {len(rows):3d}  ({counts[o] / len(rows):.0%})")
    lat = latency_stats(secs_list)
    if lat:
        print(f"0' 응답 시간(초)  min {lat['min']}  중앙값 {lat['median']}  max {lat['max']}")
    if a.label == "silent" and counts["scored"]:
        print(f"!! 결함: 무음인데 {counts['scored']}회 채점됨 (JSONL 의 response 확인)")
    for k, (num, den) in summarize(rows).items():
        print(f"{k:42s} {num:3d} / {den:3d}" + (f"  ({num / den:.0%})" if den else "  (분모 0)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
