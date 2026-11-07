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


def fetch_bytes(url: str) -> tuple[int, dict[str, str], bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": "codyssey-evidence-anchor"})
    with urllib.request.urlopen(req, timeout=30) as res:
        return res.status, {k.lower(): v for k, v in res.headers.items()}, res.read()


def health_record(health: dict) -> dict:
    # 정상 동작 중에도 바뀔 수 있는 status·카운터는 앵커 지문에서 제외한다.
    # 증거 지문, 배포 커밋, 체인 위치만 보존해 실제 드리프트 신호를 안정화한다.
    public = {k: health.get(k) for k in ("evidence", "deploy") if k in health}
    canonical = json.dumps(public, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return {"sha256": hashlib.sha256(canonical).hexdigest(), "public": public}


def hosting_record(base_url: str) -> dict:
    """Firebase Hosting의 실행 자산 지문과 보안 헤더만 기록한다(본문은 저장하지 않는다)."""
    base = base_url.rstrip("/")
    paths = ("/", "/index.html", "/ai.js", "/auth.js", "/app.js", "/proof-crypto.js")
    assets = []
    for path in paths:
        status, headers, payload = fetch_bytes(base + path)
        csp = headers.get("content-security-policy", "")
        report_only = headers.get("content-security-policy-report-only", "")
        assets.append({
            "path": path,
            "status": status,
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "cache_control": headers.get("cache-control", ""),
            "etag": headers.get("etag", ""),
            "last_modified": headers.get("last-modified", ""),
            "csp": "enforce" if csp else ("report-only" if report_only else "missing"),
            "hosted_api_guard": bool(path == "/ai.js" and b"devOrigin" in payload),
        })
    return {"base": base, "assets": assets}


def validate_hosting(record: dict) -> None:
    assets = {item["path"]: item for item in record.get("assets", [])}
    for path, item in assets.items():
        if item.get("status") != 200:
            raise RuntimeError("hosting asset unavailable: " + path)
    root = assets.get("/") or {}
    if root.get("csp") != "enforce":
        raise RuntimeError("hosting CSP is not enforced")
    if "max-age=0" not in root.get("cache_control", ""):
        raise RuntimeError("hosting root is cacheable")
    if not (assets.get("/ai.js") or {}).get("hosted_api_guard"):
        raise RuntimeError("hosting ai.js lacks development-only API origin guard")


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


def body(repo: str, health: dict, result: dict, hosting: dict, run_url: str) -> str:
    record = {
        "health": health_record(health),
        "chain": result_record(result),
        "hosting": hosting,
        "run": run_url,
    }
    return "자동 생성된 오프사이트 체크포인트입니다.\n\n```json\n" + json.dumps(record, ensure_ascii=False, indent=2) + "\n```\n\n이 기록은 Render 상태·Firebase Hosting 실행 자산·Firestore 체인의 마지막 위치를 GitHub 관리 plane에 남긴 것입니다."


def main() -> int:
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GH_TOKEN", "")
    health_url = os.environ.get("ANCHOR_HEALTH_URL", "").strip()
    hosting_url = os.environ.get("ANCHOR_HOSTING_URL", "https://com-example-myapplicatio-3bb36.web.app").strip()
    result_path = sys.argv[1] if len(sys.argv) > 1 else "anchor-result.json"
    if not repo or not token or not health_url:
        print("::error::GITHUB_REPOSITORY/GH_TOKEN/ANCHOR_HEALTH_URL 필요", file=sys.stderr)
        return 2
    try:
        health = fetch_json(health_url)
        hosting = hosting_record(hosting_url)
        validate_hosting(hosting)
        with open(result_path, encoding="utf-8") as fh:
            result = json.load(fh)
        run_url = "%s/%s/actions/runs/%s" % (
            os.environ.get("GITHUB_SERVER_URL", "https://github.com"), repo, os.environ.get("GITHUB_RUN_ID", "")
        )
        text = body(repo, health, result, hosting, run_url)
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
