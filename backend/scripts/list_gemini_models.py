"""지금 이 API 키로 쓸 수 있는 Gemini 모델 목록을 조회한다.

서버(app/gemini.py)와 같은 규칙을 쓴다: 목록 조회도 최소 30회 시도, 같은 필터·우선순위.

    cd backend
    GEMINI_API_KEY=... python scripts/list_gemini_models.py [--json models.json]

GitHub Actions 에서는 결과 표를 $GITHUB_STEP_SUMMARY 에 쓴다.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import gemini as ai  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", help="결과를 저장할 JSON 파일 경로")
    args = ap.parse_args()

    if not os.getenv("GEMINI_API_KEY"):
        print("GEMINI_API_KEY 가 없습니다. (Actions: 저장소 Settings → Secrets → GEMINI_API_KEY)", file=sys.stderr)
        return 2

    client = ai.make_client()
    try:
        raw, attempts, _ = ai.retry("models.list", lambda _a: list(client.models.list()))
    except ai.AttemptsExhausted as exc:
        print(f"목록 조회 실패: {exc}", file=sys.stderr)
        return 1

    selected = ai.pick_models(raw)
    rows = [
        {
            "name": (m.name or "").removeprefix("models/"),
            "display_name": getattr(m, "display_name", None),
            "supported_actions": list(getattr(m, "supported_actions", None) or []),
            "input_token_limit": getattr(m, "input_token_limit", None),
            "output_token_limit": getattr(m, "output_token_limit", None),
        }
        for m in raw
    ]
    result = {"attempts": attempts, "selected_in_order": selected, "all": rows}

    print(f"조회 시도 {attempts}회, 전체 {len(rows)}개, 서비스가 쓸 모델 {len(selected)}개")
    for i, name in enumerate(selected, 1):
        print(f"  {i:2d}. {name}")

    if args.json:
        Path(args.json).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        lines = [
            "## Gemini 사용 가능 모델",
            "",
            f"조회 시도 {attempts}회 · 전체 {len(rows)}개 · 서비스 사용 대상 {len(selected)}개",
            "",
            "### 서비스가 시도하는 순서 (`app/gemini.py` 규칙)",
            "",
            "| 순서 | 모델 |",
            "|---:|---|",
            *[f"| {i} | `{n}` |" for i, n in enumerate(selected, 1)],
            "",
            "<details><summary>전체 목록</summary>",
            "",
            "| 모델 | 지원 기능 | 입력 토큰 | 출력 토큰 |",
            "|---|---|---:|---:|",
            *[
                f"| `{r['name']}` | {', '.join(r['supported_actions'])} | "
                f"{r['input_token_limit'] or ''} | {r['output_token_limit'] or ''} |"
                for r in rows
            ],
            "",
            "</details>",
        ]
        with open(summary, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    return 0 if selected else 1


if __name__ == "__main__":
    sys.exit(main())
