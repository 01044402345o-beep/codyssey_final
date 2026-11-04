#!/usr/bin/env python3
"""관리자용: 음소 노드들을 점검하고 Render 에 넣을 PHONEME_REMOTE_URLS 한 줄을 만든다. 표준 라이브러리만 쓴다.

    python tools/check_phoneme_nodes.py https://pc1.<tailnet>.ts.net https://pc2.<tailnet>.ts.net
    python tools/check_phoneme_nodes.py --token-file backend/phoneme-node/token.txt https://pc2....

토큰은 --token-file, 환경변수 PHONEME_TOKEN, 기본 파일 backend/phoneme-node/token.txt 순으로 찾는다.
노드마다: ① 주소 규칙(https) ② /healthz ready ③ 토큰 일치(무음 1초를 보내 401 이 아닌지) ④ 응답 시간.
무음만 보내므로 사용자 음성은 쓰지 않는다. 통과한 노드만 마지막 줄의 목록에 넣는다(입력 순서 유지).
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
import wave
from pathlib import Path

DEFAULT_TOKEN_FILE = Path(__file__).resolve().parent.parent / "backend" / "phoneme-node" / "token.txt"


def token_from(args: argparse.Namespace) -> str:
    if args.token_file:
        return Path(args.token_file).read_text(encoding="utf-8").strip()
    if os.getenv("PHONEME_TOKEN", "").strip():
        return os.environ["PHONEME_TOKEN"].strip()
    if DEFAULT_TOKEN_FILE.is_file():
        return DEFAULT_TOKEN_FILE.read_text(encoding="utf-8").strip()
    return ""


def silence_wav(seconds: float = 1.0) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * int(16000 * seconds))
    return buf.getvalue()


def check(url: str, token: str, timeout: float) -> dict:
    url = url.strip().rstrip("/")
    row = {"url": url, "ok": False, "notes": []}
    if not url.startswith("https://"):
        row["notes"].append("https:// 주소가 아님 — Render 는 Funnel 주소(https://…ts.net)만 쓴다")
        return row
    t = time.monotonic()
    try:
        with urllib.request.urlopen(url + "/healthz", timeout=timeout) as res:
            h = json.loads(res.read(4096).decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        row["notes"].append(f"/healthz 안 닿음 ({type(exc).__name__}) — PC 켜짐·노드 실행·funnel_on 확인")
        return row
    row["health_ms"] = int((time.monotonic() - t) * 1000)
    if not h.get("ready"):
        row["notes"].append(f"노드는 떴지만 모델 준비 전 (error={h.get('error')}) — 잠시 뒤 다시")
        return row
    boundary = "----check" + uuid.uuid4().hex
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="text"\r\n\r\nseat\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="audio"; filename="a.wav"\r\n'
            "Content-Type: audio/wav\r\n\r\n").encode() + silence_wav() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(url + "/phoneme-check", data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    req.add_header("X-Phoneme-Token", token)
    t = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            res.read(65536)
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            row["notes"].append("토큰 불일치(401) — 그 PC 의 token.txt 를 관리자 토큰과 같게")
        else:
            row["notes"].append(f"분석 요청 HTTP {exc.code}")
        return row
    except Exception as exc:  # noqa: BLE001
        row["notes"].append(f"분석 요청 실패 ({type(exc).__name__})")
        return row
    row["check_ms"] = int((time.monotonic() - t) * 1000)
    row["ok"] = True
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description="음소 노드 점검 + PHONEME_REMOTE_URLS 만들기")
    ap.add_argument("urls", nargs="+", help="노드 주소들(우선순위 순서)")
    ap.add_argument("--token-file", help="token.txt 경로(없으면 PHONEME_TOKEN 또는 backend/phoneme-node/token.txt)")
    ap.add_argument("--timeout", type=float, default=15.0)
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    token = token_from(args)
    if len(token) < 24:
        print("토큰이 없거나 24자 미만이다. --token-file 로 관리자 token.txt 를 지정하라.")
        return 2
    good = []
    for u in dict.fromkeys(a.strip().rstrip("/") for a in args.urls if a.strip()):
        r = check(u, token, args.timeout)
        mark = "OK  " if r["ok"] else "FAIL"
        ms = f"healthz {r.get('health_ms', '-')}ms · 분석 {r.get('check_ms', '-')}ms" if r["ok"] else ""
        print(f"[{mark}] {r['url']}  {ms}")
        for n in r["notes"]:
            print(f"       - {n}")
        if r["ok"]:
            good.append(r["url"])
    print()
    if not good:
        print("통과한 노드가 없다. Render 값을 바꾸지 마라.")
        return 1
    print("Render → Environment 에 넣을 값 (통과한 노드만, 입력 순서 = 우선순위):")
    print()
    print(f"PHONEME_REMOTE_URLS={','.join(good)}")
    return 0 if len(good) == len(set(args.urls)) else 1


if __name__ == "__main__":
    sys.exit(main())
