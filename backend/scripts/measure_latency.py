"""배포 서버가 "얼마나 느린지"와 "어디서 느린지"를 숫자로 잰다. (멘토 지적: 대화 속도로 응답이 와야 한다)

세 가지를 따로 잰다 — 합쳐서 "1분"이라고 느끼면 원인을 구분할 수 없다:
  1. 콜드스타트: 첫 /health 가 걸린 시간. Render 무료 플랜은 15분 놀면 잠들고, 깨우는 데 수십 초가 걸린다.
  2. /generate (여행 문장 생성): 벽시계 시간 + 서버가 돌려준 timing_ms(시도별 모델 호출·검증 시간, 재시도 횟수).
  3. /speak-check (말하기, --audio 를 줄 때): 벽시계 시간 + timing_ms(read·decode·silero·pyannote·stt·feedback).

사용 예 (표준 라이브러리만 사용):
  python backend/scripts/measure_latency.py --base "$BASE_URL" --n 5 --audio good.wav --target "I have a peanut allergy."

주의: 콜드스타트를 재려면 15분 이상 쉰 서버에서 처음 실행해야 한다. 서버가 깨어 있으면 1번은 의미가 없다.
키 없는 서버(mock)에서는 /generate 가 AI 를 부르지 않으므로 2번은 의미가 없다 — 응답의 mock 으로 알 수 있다.
"""
from __future__ import annotations

import argparse
import json
import math
import mimetypes
import statistics
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

SAMPLE_GENERATE = {
    "category_id": "restaurant", "city": "New York",
    "places": [{"id": "p1", "name": "Joe's Pizza", "place_type": "restaurant"}],
    "weak_expressions": [],
}


def pct(values: list[float], q: float) -> float | None:
    """q(0~1) 분위수 (가까운 순위, 표본이 적을 때 과대평가하지 않도록 올림 대신 가장 가까운 값)."""
    v = sorted(x for x in values if isinstance(x, (int, float)) and not math.isnan(x))
    if not v:
        return None
    return v[min(len(v) - 1, max(0, round(q * (len(v) - 1))))]


def summarize(values: list[float]) -> dict[str, float | None]:
    return {"n": len(values), "p50": pct(values, .5), "p95": pct(values, .95), "max": max(values) if values else None}


def call(url: str, data: bytes | None, headers: dict[str, str], timeout: float) -> tuple[int | None, dict | None, float, str | None]:
    t0 = time.perf_counter()
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace"); status = r.status
    except urllib.error.HTTPError as e:
        return e.code, None, (time.perf_counter() - t0) * 1000, f"HTTP {e.code}"
    except Exception as e:  # noqa: BLE001 — 타임아웃·연결 오류가 측정을 멈추면 안 된다
        return None, None, (time.perf_counter() - t0) * 1000, f"{type(e).__name__}: {e}"
    try:
        return status, json.loads(raw), (time.perf_counter() - t0) * 1000, None
    except ValueError:
        return status, None, (time.perf_counter() - t0) * 1000, "invalid JSON"


def multipart(audio: Path, target: str) -> tuple[bytes, dict[str, str]]:
    b = uuid.uuid4().hex
    mime = mimetypes.guess_type(audio.name)[0] or "audio/webm"
    body = b"".join([
        f'--{b}\r\nContent-Disposition: form-data; name="target"\r\n\r\n{target}\r\n'.encode(),
        (f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="{audio.name}"\r\nContent-Type: {mime}\r\n\r\n').encode(),
        audio.read_bytes(), f"\r\n--{b}--\r\n".encode()])
    return body, {"Content-Type": f"multipart/form-data; boundary={b}"}


def fmt(x: float | None) -> str:
    return "—" if x is None else f"{x:,.0f}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--audio", type=Path, default=None)
    ap.add_argument("--target", default="I have a peanut allergy.")
    ap.add_argument("--sleep", type=float, default=4.0)      # 서버 기본 제한 20회/60초
    ap.add_argument("--timeout", type=float, default=150.0)
    ap.add_argument("--out", type=Path, default=Path("measure_latency.jsonl"))
    a = ap.parse_args()
    base = a.base.rstrip("/")
    rows: list[dict] = []

    def rec(kind: str, i: int, status, res, ms, err):
        rows.append({"kind": kind, "i": i, "status": status, "wall_ms": round(ms), "error": err, "timing_ms": (res or {}).get("timing_ms"),
                     "mock": (res or {}).get("mock"), "usable": (res or {}).get("usable"), "attempts": (res or {}).get("attempts")})

    print("=== 1. 콜드스타트 (첫 /health) ===")
    st, res, ms, err = call(base + "/health", None, {}, a.timeout); rec("health_first", 0, st, res, ms, err)
    print(f"첫 /health: {fmt(ms)} ms {'(오류: ' + err + ')' if err else ''}  ← 서버가 잠들어 있었다면 이 값이 '1분'의 정체일 수 있다")
    st, res, ms2, err = call(base + "/health", None, {}, a.timeout); rec("health_second", 0, st, res, ms2, err)
    print(f"두 번째 /health: {fmt(ms2)} ms  (깨어 있을 때의 기본 왕복)")
    if res:
        print(f"서버: has_api_key={res.get('has_api_key')} deploy.commit={(res.get('deploy') or {}).get('commit')} cross_validation_ready={res.get('cross_validation_ready')}")

    print(f"\n=== 2. /generate × {a.n} ===")
    body = json.dumps(SAMPLE_GENERATE).encode()
    for i in range(1, a.n + 1):
        st, res, ms, err = call(base + "/generate", body, {"Content-Type": "application/json"}, a.timeout); rec("generate", i, st, res, ms, err)
        t = (res or {}).get("timing_ms") or {}
        print(f"[{i}] {fmt(ms)} ms  status={st} mock={(res or {}).get('mock')} attempts={(res or {}).get('attempts')} 서버 total={fmt(t.get('total'))} 시도별 호출 ms={[x.get('call_ms') for x in t.get('attempt_ms', [])]}{' err=' + err if err else ''}")
        if i < a.n: time.sleep(a.sleep)

    if a.audio:
        print(f"\n=== 3. /speak-check × {a.n} ({a.audio.name}) ===")
        body, hdr = multipart(a.audio, a.target)
        for i in range(1, a.n + 1):
            st, res, ms, err = call(base + "/speak-check", body, hdr, a.timeout); rec("speak", i, st, res, ms, err)
            t = (res or {}).get("timing_ms") or {}
            print(f"[{i}] {fmt(ms)} ms  status={st} usable={(res or {}).get('usable')} 서버: " + " ".join(f"{k}={v}" for k, v in t.items()) + (f" err={err}" if err else ""))
            if i < a.n: time.sleep(a.sleep)

    print("\n=== 요약 (ms) ===")
    for kind in ("generate", "speak"):
        w = [r["wall_ms"] for r in rows if r["kind"] == kind and not r["error"]]
        if w:
            s = summarize(w); print(f"{kind:9s} 벽시계 n={s['n']} p50={fmt(s['p50'])} p95={fmt(s['p95'])} max={fmt(s['max'])}")
        keys = sorted({k for r in rows if r["kind"] == kind and r["timing_ms"] for k in r["timing_ms"] if k != "attempt_ms"})
        for k in keys:
            vals = [r["timing_ms"][k] for r in rows if r["kind"] == kind and r["timing_ms"] and k in r["timing_ms"]]
            s = summarize(vals); print(f"    서버 {k:9s} p50={fmt(s['p50'])} p95={fmt(s['p95'])} max={fmt(s['max'])}")
    a.out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    print(f"\n원본: {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
