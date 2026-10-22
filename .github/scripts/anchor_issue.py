"""자동 앵커가 실패하면 GitHub 이슈 하나에 모아 알린다(같은 제목의 열린 이슈가 있으면 댓글).

표준 라이브러리만 쓴다. 본문에는 실행 링크와 결과 요약만 넣는다 — 토큰·개인정보 없음
(결과의 아카이브 id 는 무작위 hex 다).
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request

TITLE = "[evidence-anchor] 자동 앵커 실패"


def _api(method: str, path: str, token: str, body=None, opener=urllib.request.urlopen):
    req = urllib.request.Request("https://api.github.com" + path, method=method,
                                 data=None if body is None else json.dumps(body).encode())
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    with opener(req, timeout=20) as res:
        return json.loads(res.read() or b"null")


def summary(result_path: str) -> str:
    try:
        with open(result_path, encoding="utf-8") as fh:
            text = fh.read()
        data = json.loads(text[text.index("{"):]) if "{" in text else {}
    except (OSError, ValueError):
        return "결과 파일을 읽지 못했습니다(토큰·KMS·권한 단계에서 실패했을 수 있습니다 — 실행 로그를 보세요)."
    keep = {k: data.get(k) for k in ("error", "verified", "anchored", "verify") if k in data}
    return "```json\n" + json.dumps(keep, ensure_ascii=False, indent=2)[:3000] + "\n```"


def report(repo: str, token: str, run_url: str, body_extra: str, opener=urllib.request.urlopen) -> str:
    q = urllib.parse.quote('repo:%s is:issue is:open in:title "%s"' % (repo, TITLE))
    found = _api("GET", "/search/issues?q=" + q, token, opener=opener) or {}
    body = "실행: %s\n\n%s\n\n- 체크포인트 검증이 실패했으면 새 체크포인트는 만들지 않았습니다.\n" \
           "- 관리자 PC 에서 `python -m opsarchive verify-chain --source both` 로 확인하세요." % (run_url, body_extra)
    items = [i for i in found.get("items") or [] if i.get("title") == TITLE]
    if items:
        _api("POST", "/repos/%s/issues/%d/comments" % (repo, items[0]["number"]), token, {"body": body}, opener)
        return "commented #%d" % items[0]["number"]
    made = _api("POST", "/repos/%s/issues" % repo, token, {"title": TITLE, "body": body}, opener)
    return "opened #%s" % (made or {}).get("number")


def main() -> int:
    repo, token = os.environ.get("GITHUB_REPOSITORY", ""), os.environ.get("GH_TOKEN", "")
    run_url = "%s/%s/actions/runs/%s" % (os.environ.get("GITHUB_SERVER_URL", "https://github.com"), repo,
                                         os.environ.get("GITHUB_RUN_ID", ""))
    if not repo or not token:
        print("::error::GITHUB_REPOSITORY/GH_TOKEN 없음")
        return 1
    print(report(repo, token, run_url, summary(sys.argv[1] if len(sys.argv) > 1 else "anchor-result.json")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
