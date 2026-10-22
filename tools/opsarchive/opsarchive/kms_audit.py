"""KMS 서명 감사 대조 — '누가 서명을 요청했는지'를 Cloud Audit Logs 로 드러낸다.

KMS 는 권한 있는 요청이면 어떤 내용이든 서명한다(내용을 모른다). 그래서 막는 대신 **탐지**한다:
정상 자동 앵커는 '실행 1번 = 체크포인트 1개 = 서명 1번(경합 재시도면 몇 번 더)'이다.
감사 로그의 서명 기록(누가·언제)을 체크포인트(언제·어느 키)와 맞춰 보고, 짝이 없는 서명을 보고한다.

- 로그: `cloudaudit.googleapis.com/data_access`, `protoPayload.methodName="AsymmetricSign"` (DATA_READ).
  **데이터 액세스 로그는 기본으로 꺼져 있다** — 켜야 기록이 남는다(docs/ops/KMS_AUTO_ANCHOR.md §10).
- 읽는 계정에는 `roles/logging.privateLogViewer` 가 필요하다(데이터 액세스 로그는 비공개 로그).
- 판정(엔트리마다):
  - `matched`       : 같은 키로 서명된 체크포인트가 ±window 초 안에 있다(누가 했든 그 주체를 기록).
  - `retry`         : 이미 짝지은 체크포인트 근처의 같은 주체 서명(seq 경합 재시도) — 경고.
  - `admin_probe`   : 짝 없음, 관리자 계정(kms-check 시험 서명 등) — 경고.
  - `unexplained`   : 짝 없음, 그 밖의 주체 — **위반**(무단 서명 의심).
  - `denied`        : 실패한 요청(권한 거부 등) — 누가 시도했는지 보고.
  체크포인트인데 서명 기록이 없으면 `checkpoint_without_log`(로그가 꺼졌거나 보존 기간 밖).
"""

from __future__ import annotations

import datetime
import json
import urllib.error
import urllib.request

LOGGING_API = "https://logging.googleapis.com/v2/entries:list"
LOGGING_SCOPE = "https://www.googleapis.com/auth/logging.read"
TIMEOUT = 30


class AuditError(Exception):
    """code: forbidden | http_error | bad_response"""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _iso(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _epoch(rfc: str) -> float:
    try:
        return datetime.datetime.fromisoformat(str(rfc).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def crypto_key_of(key_version: str) -> str:
    """…/cryptoKeys/<키>/cryptoKeyVersions/N → …/cryptoKeys/<키> (모든 버전의 서명을 본다)."""
    return key_version.split("/cryptoKeyVersions/")[0]


def sign_events(project_id: str, access_token: str, key_version: str, since: float, *, opener=None,
                max_pages: int = 20) -> list[dict]:
    """감사 로그의 AsymmetricSign 기록: [{at, principal, resource, ok, status}] (시간 순)."""
    log = "projects/%s/logs/cloudaudit.googleapis.com%%2Fdata_access" % project_id
    flt = ('logName="%s" AND protoPayload.methodName="AsymmetricSign" AND protoPayload.resourceName:"%s" '
           'AND timestamp>="%s"' % (log, crypto_key_of(key_version), _iso(since)))
    out: list[dict] = []
    token = ""
    for _ in range(max_pages):
        body = {"resourceNames": ["projects/" + project_id], "filter": flt, "orderBy": "timestamp asc", "pageSize": 1000}
        if token:
            body["pageToken"] = token
        req = urllib.request.Request(LOGGING_API, data=json.dumps(body).encode(), method="POST")
        req.add_header("Authorization", "Bearer " + access_token)
        req.add_header("Content-Type", "application/json")
        try:
            with (opener or urllib.request.urlopen)(req, timeout=TIMEOUT) as res:
                data = json.loads(res.read() or b"{}")
        except urllib.error.HTTPError as exc:
            raise AuditError("forbidden" if exc.code in (401, 403) else "http_error") from exc
        except json.JSONDecodeError as exc:
            raise AuditError("bad_response") from exc
        except Exception as exc:        # noqa: BLE001 — 토큰을 메시지에 담지 않는다
            raise AuditError("http_error") from exc
        for e in data.get("entries") or []:
            p = e.get("protoPayload") or {}
            status = p.get("status") or {}
            out.append({"at": _epoch(e.get("timestamp", "")), "time": str(e.get("timestamp", ""))[:19],
                        "principal": str((p.get("authenticationInfo") or {}).get("principalEmail", "") or "(알 수 없음)"),
                        "resource": str(p.get("resourceName", "")), "ok": not status.get("code"),
                        "status": status.get("message", "") if status.get("code") else ""})
        token = str(data.get("nextPageToken") or "")
        if not token:
            break
    return out


def classify(events: list[dict], checkpoints: list[dict], *, key_id: str, admin_principals: set,
             window: int = 120) -> dict:
    """서명 기록과 체크포인트(같은 키로 서명된 것)를 맞춰 본다. 위의 판정 규칙."""
    mine = sorted((c for c in checkpoints if c.get("signing_key_id") == key_id), key=lambda c: int(c.get("created_at", 0)))
    used: dict[int, str] = {}                # 체크포인트 seq → 짝지은 주체
    rows = []
    for ev in sorted(events, key=lambda e: e["at"]):
        if not ev["ok"]:
            rows.append({**ev, "verdict": "denied"})
            continue
        near = [c for c in mine if abs(int(c.get("created_at", 0)) - ev["at"]) <= window]
        free = [c for c in near if int(c.get("seq", 0)) not in used]
        if free:
            best = min(free, key=lambda c: abs(int(c.get("created_at", 0)) - ev["at"]))
            used[int(best.get("seq", 0))] = ev["principal"]
            rows.append({**ev, "verdict": "matched", "seq": best.get("seq")})
        elif any(used.get(int(c.get("seq", 0))) == ev["principal"] for c in near):
            rows.append({**ev, "verdict": "retry"})
        elif ev["principal"] in admin_principals:
            rows.append({**ev, "verdict": "admin_probe"})
        else:
            rows.append({**ev, "verdict": "unexplained"})
    since = min((e["at"] for e in events), default=None)
    orphans = [c.get("seq") for c in mine
               if int(c.get("seq", 0)) not in used and (since is None or int(c.get("created_at", 0)) >= since - window)]
    counts: dict[str, int] = {}
    by_principal: dict[str, int] = {}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
        by_principal[r["principal"]] = by_principal.get(r["principal"], 0) + 1
    if counts.get("unexplained"):
        verdict = "violation"
    elif not events and mine:
        verdict = "logs_missing"             # 체크포인트는 있는데 서명 기록이 하나도 없다 = 로그가 꺼져 있다
    elif counts.get("denied") or counts.get("admin_probe") or counts.get("retry") or orphans:
        verdict = "warning"
    else:
        verdict = "ok"
    return {"verdict": verdict, "counts": counts, "by_principal": by_principal,
            "checkpoint_without_log": orphans,
            "unexplained": [r for r in rows if r["verdict"] == "unexplained"][:50],
            "denied": [r for r in rows if r["verdict"] == "denied"][:50],
            "events": len(events), "checkpoints": len(mine)}
