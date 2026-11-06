"""Render 공개 상태와 증거 체인 앵커 결과를 GitHub Issue에 기록한다.

GitHub Actions에서 실행한다. Render/Firestore에만 남는 상태를 별도 관리 plane의
감사 이력에 남기며, 토큰·서비스 계정·개인정보는 Issue 본문에 쓰지 않는다.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.parse
import urllib.request

TITLE = "[evidence-anchor] 일일 오프사이트 앵커"


def api(method: str, path: str, token: str, body=None):
    req = urllib.request.Request(
        "https://api.github.com" + path,
        method=method,
        data=None if body is None else json.dumps(body).encode(),
    )
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=20) as res:
        return json.loads(res.read() or b"null")


def fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "codyssey-evidence-anchor"})
    with urllib.request.urlopen(req, timeout=30) as res:
        return json.loads(res.read() or b"{}")


def health_record(health: dict) -> dict:
    # 공개 /health 계약 중 지문·배포 상태에 필요한 필드만 보존한다.
    public = {k: health.get(k) for k in ("status", "situations", "categories", "evidence") if k in health}
    canonical = json.dumps(public, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return {"sha256": hashlib.sha256(canonical).hexdigest(), "public": public}


def result_record(result: dict) -> dict:
    verify = result.get("verify") if isinstance(result.get("verify"), dict) else {}
    anchor = result.get("anchor") if isinstance(result.get("anchor"), dict) else {}
    return {
        "anchored": bool(result.get("anchored")),
        "verified": bool(verify.get("ok")),
        "last_anchor_seq": verify.get("last_anchor_seq"),
        "last_anchor_age_hours": verify.get("last_anchor_age_hours"),
        "head_seq": anchor.get("head_seq"),
        "head_digest": anchor.get("head"),
        "chain_count": verify.get("chain_count"),
        "unanchored": verify.get("unanchored"),
    }


def body(repo: str, health: dict, result: dict, run_url: str) -> str:
    record = {
        "health": health_record(health),
        "chain": result_record(result),
        "run": run_url,
    }
    return "자동 생성된 오프사이트 체크포인트입니다.\n\n```json\n" + json.dumps(record, ensure_ascii=False, indent=2) + "\n```\n\n이 기록은 Render 상태와 Firestore 체인의 마지막 위치를 GitHub 관리 plane에 남긴 것입니다."


def main() -> int:
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GH_TOKEN", "")
    health_url = os.environ.get("ANCHOR_HEALTH_URL", "").strip()
    result_path = sys.argv[1] if len(sys.argv) > 1 else "anchor-result.json"
    if not repo or not token or not health_url:
        print("::error::GITHUB_REPOSITORY/GH_TOKEN/ANCHOR_HEALTH_URL 필요", file=sys.stderr)
        return 2
    try:
        health = fetch_json(health_url)
        with open(result_path, encoding="utf-8") as fh:
            result = json.load(fh)
        run_url = "%s/%s/actions/runs/%s" % (
            os.environ.get("GITHUB_SERVER_URL", "https://github.com"), repo, os.environ.get("GITHUB_RUN_ID", "")
        )
        text = body(repo, health, result, run_url)
        query = urllib.parse.quote('repo:%s is:issue is:open in:title "%s"' % (repo, TITLE))
        found = api("GET", "/search/issues?q=" + query, token) or {}
        items = [i for i in found.get("items") or [] if i.get("title") == TITLE]
        if items:
            number = items[0]["number"]
            api("POST", "/repos/%s/issues/%d/comments" % (repo, number), token, {"body": text})
            print(json.dumps({"recorded": True, "issue": number}, ensure_ascii=False))
        else:
            made = api("POST", "/repos/%s/issues" % repo, token, {"title": TITLE, "body": text})
            print(json.dumps({"recorded": True, "issue": made.get("number")}, ensure_ascii=False))
        return 0
    except Exception as exc:  # noqa: BLE001
        print("::error::오프사이트 앵커 기록 실패: %s" % type(exc).__name__, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
