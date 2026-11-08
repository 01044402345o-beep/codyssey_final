"""화면(mockup/)을 Firebase Hosting 에 올린다 — firebase CLI 없이 Hosting REST API 로, 표준 라이브러리만.

왜 따로 만들었나: 화면 PR 이 병합돼도 Hosting 은 누가 `firebase deploy --only hosting` 을 해야 바뀐다.
11/08 에 병합된 동의 창·랜딩 문구가 운영에 안 나온 원인이 이것이었다. CI 가 main 에서 통과하면
hosting-deploy 워크플로가 이 스크립트로 올린다. 토큰은 gcp_wif_token.py 가 만든 GCP_ACCESS_TOKEN(15분).

명령
  drift   운영 URL 의 파일을 받아 저장소 파일과 바이트로 비교한다. 다르면 changed=true (GITHUB_OUTPUT).
  deploy  새 버전을 만들어 파일을 올리고 채널(live 또는 미리보기)에 릴리스한다.
  verify  drift 를 몇 번 다시 해서, 끝까지 다르면 실패한다(배포 뒤 확인·정기 점검).

firebase.json 의 hosting 설정 중 public·ignore·headers·cleanUrls·trailingSlash 만 옮긴다.
redirects·rewrites·i18n 이 생기면 이 스크립트가 거부한다 — 조용히 빠뜨리지 않게.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://firebasehosting.googleapis.com/v1beta1"
SUPPORTED_KEYS = {"public", "ignore", "headers", "cleanUrls", "trailingSlash"}


class DeployError(Exception):
    pass


# ── firebase.json ────────────────────────────────────────────────────────────
def glob_regex(pattern: str) -> re.Pattern:
    """firebase.json ignore 에 쓰는 glob(**, *, ?)을 정규식으로. 경로는 public 기준, '/' 구분."""
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out += "(?:.*/)?"; i += 3
        elif pattern.startswith("**", i):
            out += ".*"; i += 2
        elif pattern[i] == "*":
            out += "[^/]*"; i += 1
        elif pattern[i] == "?":
            out += "[^/]"; i += 1
        else:
            out += re.escape(pattern[i]); i += 1
    return re.compile(out + r"\Z")


def load_hosting(root: Path) -> dict:
    cfg = json.loads((root / "firebase.json").read_text(encoding="utf-8"))
    hosting = cfg.get("hosting")
    if not isinstance(hosting, dict):
        raise DeployError("firebase.json 에 hosting 이 하나(객체)여야 합니다")
    extra = sorted(set(hosting) - SUPPORTED_KEYS)
    if extra:
        raise DeployError("이 스크립트가 옮기지 못하는 hosting 설정: %s — firebase CLI 로 배포하거나 스크립트를 고치세요" % extra)
    return hosting


def list_files(root: Path, hosting: dict) -> list[str]:
    """올릴 파일(public 기준 '/경로'). ignore 는 firebase CLI 와 같게 경로 전체에 맞춘다."""
    public = (root / hosting.get("public", "public")).resolve()
    ignores = [glob_regex(p) for p in hosting.get("ignore", [])]
    out = []
    for p in sorted(public.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(public).as_posix()
        if any(rx.match(rel) for rx in ignores):
            continue
        out.append("/" + rel)
    return out


def version_config(hosting: dict) -> dict:
    conf: dict = {}
    headers = []
    for h in hosting.get("headers", []):
        src = h.get("source") or h.get("glob")
        if not src or not isinstance(h.get("headers"), list):
            raise DeployError("headers 항목에 source 와 headers 목록이 있어야 합니다")
        headers.append({"glob": src, "headers": {x["key"]: x["value"] for x in h["headers"]}})
    if headers:
        conf["headers"] = headers
    if hosting.get("cleanUrls"):              # firebase CLI 처럼 기본값(false)은 보내지 않는다
        conf["cleanUrls"] = True
    if "trailingSlash" in hosting:
        conf["trailingSlashBehavior"] = "ADD" if hosting["trailingSlash"] else "REMOVE"
    return conf


# ── HTTP ─────────────────────────────────────────────────────────────────────
def _req(method: str, url: str, token: str, body: bytes | None = None, ctype: str = "application/json",
         opener=urllib.request.urlopen, quota_project: str = "") -> dict:
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", "Bearer " + token)
    if body is not None:
        req.add_header("Content-Type", ctype)
    if quota_project:
        req.add_header("x-goog-user-project", quota_project)
    try:
        with opener(req, timeout=60) as res:
            raw = res.read()
    except urllib.error.HTTPError as exc:     # 응답 본문엔 토큰이 없다 — 원인을 보이게 앞부분만 남긴다
        detail = exc.read()[:300].decode("utf-8", "replace") if hasattr(exc, "read") else ""
        raise DeployError("%s %s → HTTP %s %s" % (method, url.split("?")[0], exc.code, detail)) from exc
    except Exception as exc:                  # noqa: BLE001
        raise DeployError("%s %s 실패(%s)" % (method, url.split("?")[0], type(exc).__name__)) from exc
    return json.loads(raw or b"{}")


def fetch_public(url: str, opener=urllib.request.urlopen) -> bytes | None:
    """운영 URL 의 파일 바이트. 압축을 요청하지 않는다(Accept-Encoding 없음 → 원본 바이트)."""
    req = urllib.request.Request(url, headers={"Cache-Control": "no-cache", "User-Agent": "hosting-deploy-check"})
    try:
        with opener(req, timeout=30) as res:
            return res.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise DeployError("GET %s → HTTP %s" % (url, exc.code)) from exc
    except Exception as exc:                  # noqa: BLE001
        raise DeployError("GET %s 실패(%s)" % (url, type(exc).__name__)) from exc


# ── 명령 ─────────────────────────────────────────────────────────────────────
def drift(root: Path, base_url: str, opener=urllib.request.urlopen) -> list[str]:
    """운영과 바이트가 다른 파일 목록. 비어 있으면 운영이 저장소와 같다."""
    hosting = load_hosting(root)
    public = (root / hosting.get("public", "public")).resolve()
    diff = []
    for path in list_files(root, hosting):
        local = (public / path.lstrip("/")).read_bytes()
        live = fetch_public(base_url.rstrip("/") + urllib.parse.quote(path), opener)
        if live != local:
            diff.append(path)
    return diff


def deploy(root: Path, site: str, channel: str, token: str, opener=urllib.request.urlopen,
           quota_project: str = "", label: str = "") -> str:
    hosting = load_hosting(root)
    public = (root / hosting.get("public", "public")).resolve()
    files = list_files(root, hosting)
    if not files:
        raise DeployError("올릴 파일이 없습니다")
    blobs: dict[str, bytes] = {}
    manifest: dict[str, str] = {}
    for path in files:
        gz = gzip.compress((public / path.lstrip("/")).read_bytes(), mtime=0)
        digest = hashlib.sha256(gz).hexdigest()
        manifest[path] = digest
        blobs[digest] = gz
    call = lambda m, u, b=None, ct="application/json": _req(m, u, token, b, ct, opener, quota_project)  # noqa: E731

    labels = {"deployment-tool": "github-actions-hosting-deploy"}
    if label:
        labels["commit"] = re.sub(r"[^a-z0-9_-]", "", label.lower())[:63]
    ver = call("POST", "%s/sites/%s/versions" % (API, site),
               json.dumps({"config": version_config(hosting), "labels": labels}).encode())
    name = ver.get("name", "")
    if not re.fullmatch(r"sites/[a-z0-9-]+/versions/[a-z0-9]+", name):
        raise DeployError("버전 생성 응답에 이름이 없습니다")
    pop = call("POST", "%s/%s:populateFiles" % (API, name), json.dumps({"files": manifest}).encode())
    need, upload_url = pop.get("uploadRequiredHashes", []), pop.get("uploadUrl", "")
    if need and not upload_url:
        raise DeployError("populateFiles 응답에 uploadUrl 이 없습니다")
    for digest in need:
        if digest not in blobs:
            raise DeployError("서버가 모르는 해시를 요구했습니다")
        call("POST", "%s/%s" % (upload_url, digest), blobs[digest], "application/octet-stream")
    call("PATCH", "%s/%s?update_mask=status" % (API, name), json.dumps({"status": "FINALIZED"}).encode())
    if channel == "live":
        rel_url = "%s/sites/%s/releases?versionName=%s" % (API, site, urllib.parse.quote(name, safe="/"))
    else:
        rel_url = "%s/sites/%s/channels/%s/releases?versionName=%s" % (API, site, channel, urllib.parse.quote(name, safe="/"))
    call("POST", rel_url, json.dumps({"message": label or "hosting-deploy"}).encode())
    print("배포함: %s → %s (파일 %d, 새로 올린 것 %d)" % (name, channel, len(files), len(need)))
    return name


def _write_output(key: str, value: str) -> None:
    target = os.environ.get("GITHUB_OUTPUT")
    if target:
        with open(target, "a", encoding="utf-8") as fh:
            fh.write("%s=%s\n" % (key, value))


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["drift", "deploy", "verify"])
    ap.add_argument("--root", default=".")
    ap.add_argument("--base-url", default="")
    ap.add_argument("--site", default="")
    ap.add_argument("--channel", default="live")
    ap.add_argument("--label", default="")
    ap.add_argument("--attempts", type=int, default=6)
    ap.add_argument("--wait", type=float, default=20.0)
    a = ap.parse_args(argv)
    root = Path(a.root)
    try:
        if a.cmd == "deploy":
            token = os.environ.get("GCP_ACCESS_TOKEN", "")
            if not token or not re.fullmatch(r"[a-z0-9-]{6,63}", a.site or ""):
                print("::error::GCP_ACCESS_TOKEN 과 --site 가 필요합니다")
                return 1
            deploy(root, a.site, a.channel, token, quota_project=os.environ.get("GCP_QUOTA_PROJECT", ""), label=a.label)
            return 0
        if not a.base_url.startswith("https://"):
            print("::error::--base-url 은 https 주소여야 합니다")
            return 1
        attempts = a.attempts if a.cmd == "verify" else 1
        for n in range(attempts):
            diff = drift(root, a.base_url)
            if not diff or n == attempts - 1:
                break
            time.sleep(a.wait)
        _write_output("changed", "true" if diff else "false")
        if diff:
            shown = ", ".join(diff[:10]) + (" 외 %d개" % (len(diff) - 10) if len(diff) > 10 else "")
            level = "::error::" if a.cmd == "verify" else "::notice::"
            print("%s운영 화면이 저장소와 다릅니다(%d개): %s" % (level, len(diff), shown))
            return 1 if a.cmd == "verify" else 0
        print("운영 화면이 저장소와 같습니다")
        return 0
    except DeployError as exc:
        print("::error::" + str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
