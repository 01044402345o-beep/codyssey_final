"""로컬에서 일정 장소 조회를 한 번 하고, 키를 지운 JSON을 남긴다.

CI는 이 파일을 돌리지 않는다. Render에서 ITINERARY_ENABLED 를 켜지 않는다.
키가 없으면 종료 코드 2이고, 그 실행은 수집 성공이 아니다.

  cd backend
  $env:ITINERARY_ENABLED = "1"
  $env:GOOGLE_MAPS_API_KEY = "<키>"
  ..\.venv\Scripts\python.exe scripts\itinerary_live_once.py --out C:\경로\저장소밖.json

저장소 디렉터리 안에는 쓰지 않는다. 출력 JSON에 queries, places[].provider_id,
places[].source_url, places[].fetched_at 이 있어야 실제 수집으로 말한다.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[2]


def _redact(value, secret: str):
    if isinstance(value, str):
        return value.replace(secret, "***") if secret and secret in value else value
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item, secret) for key, item in value.items()}
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--city", default="New York")
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    key = (os.getenv("GOOGLE_MAPS_API_KEY") or "").strip()
    if os.getenv("ITINERARY_ENABLED", "0").strip() != "1" or not key:
        print("ITINERARY_ENABLED=1 과 GOOGLE_MAPS_API_KEY 가 있어야 한다. 키 값은 출력하지 않는다.", file=sys.stderr)
        return 2
    out = Path(args.out).resolve() if args.out else None
    if out is not None and (out == REPO or REPO in out.parents):
        print("저장소 안에는 쓰지 않는다.", file=sys.stderr)
        return 2

    from app.agents.itinerary import collect_itinerary

    req = SimpleNamespace(
        city=args.city, days=1, start_date=None, places=[], itinerary_kinds=["restaurant"])
    body = _redact(collect_itinerary(req), key)
    text = json.dumps(body, ensure_ascii=False, indent=2)
    if out is None:
        print(text)
    else:
        out.write_text(text + "\n", encoding="utf-8", newline="\n")
        print(f"wrote {out}")
    places = body.get("places") or []
    ok = body.get("queries") and places and all(
        p.get("provider_id") and p.get("source_url") and p.get("fetched_at") for p in places)
    if not ok:
        print("응답에 queries 와 provider_id, source_url, fetched_at 이 없다. 수집 성공이 아니다.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
