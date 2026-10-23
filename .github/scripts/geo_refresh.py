"""전세계 국가·도시명 주간 수집 → 회귀 검사 → Firestore 저장 (geo-refresh 워크플로우).

소스(2026-10-24 다중 에이전트 리서치·회귀 조사로 결정, docs/ops/GEO_REFRESH.md):
  - 본 소스: GeoNames 덤프(download.geonames.org/export/dump, CC BY 4.0, 키·한도 없음, 매일 갱신)
      countryInfo.txt · admin1CodesASCII.txt · allCountries.zip(feature class P = 사람이 사는 곳 전부) ·
      alternateNamesV2.zip(isolanguage=ko → 한국어 이름)
  - 교차 검증(저장하지 않음): dr5hn countries.json(ODbL) · CountriesNow /api/v0.1/countries
저장: Firestore geo_meta/current · geo_countries/{ISO2} · geo_cities/{ISO2}_{nnn}(gzip 바이트 샤드).
  문서 1MiB 상한·중첩 배열 불가 → 국가별로 인구 내림차순 정렬해 gzip JSON 샤드로 나눈다.
  해시가 바뀐 문서만 쓰고, 사라진 샤드는 지우고, geo_meta/current 를 마지막에 쓴다(멱등 — 실패하면 재실행).
회귀 검사가 실패하면 아무것도 쓰지 않는다.

표준 라이브러리만 쓴다. 네트워크는 opener 로 바꿔 끼울 수 있다(테스트).
사용: python3 geo_refresh.py run --work DIR [--dry-run]   (Firestore 토큰은 환경변수 GCP_ACCESS_TOKEN)
"""
from __future__ import annotations

import argparse
import base64
import csv
import gzip
import hashlib
import io
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
import zipfile
from typing import Any, Callable, Iterable, Optional

DUMP = "https://download.geonames.org/export/dump/"
FILES = ("countryInfo.txt", "admin1CodesASCII.txt", "allCountries.zip", "alternateNamesV2.zip")
DR5HN = "https://raw.githubusercontent.com/dr5hn/countries-states-cities-database/master/json/countries.json"
COUNTRIESNOW = "https://countriesnow.space/api/v0.1/countries"
UA = "codyssey-geo-refresh/1.0 (+https://github.com/01044402345o-beep/codyssey_final)"
ATTRIBUTION = ("GeoNames (https://www.geonames.org), CC BY 4.0. 변경: 사람이 사는 곳(feature class P, "
               "역사적·버려진·파괴된·도시 내 구역 제외)만 골라 한국어 이름을 붙이고 국가별로 나눠 변환함.")
# 사람이 사는 곳 중 '도시명' 으로 보기 어려운 것: 역사적·버려진·파괴된 곳, 도시 안의 구역.
EXCLUDE_CODES = frozenset({"PPLH", "PPLQ", "PPLW", "PPLCH", "PPLX"})
SHARD_MAX = 800_000          # gzip 바이트. Firestore 문서 1MiB 안에 다른 필드·여유를 남긴다
RAW_CHUNK = 3_000_000        # 샤드 하나로 시도할 JSON 원문 크기(압축 전)
COMMIT_MAX_BYTES = 8_000_000  # documents:commit 요청 한 번(10MiB 상한 아래)
COMMIT_MAX_WRITES = 450      # 500건 상한 아래

# 회귀 검사 기준(이전 스냅샷 대비)
MAX_TOTAL_DROP = 0.02        # 전체 도시 수 2% 넘게 줄면 실패
MAX_COUNTRY_DROP = 0.05      # 국가별 5% 넘게 줄면 실패 …
MIN_COUNTRY_DROP_ABS = 50    # … 단 50곳 이상 줄었을 때만(작은 나라의 흔들림은 무시)
MAX_KO_RATIO_DROP = 0.02     # 한국어 이름이 붙은 비율이 2%p 넘게 줄면 실패


class GeoError(RuntimeError):
    pass


Opener = Callable[..., Any]


# ------------------------------------------------------------------ 다운로드

def _request(url: str, *, method: str = "GET", data: bytes | None = None, headers: dict | None = None):
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("User-Agent", UA)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    return req


def download(name: str, work: str, opener: Opener = urllib.request.urlopen) -> dict:
    """덤프 파일 하나를 work 에 받고 {name, bytes, sha256, last_modified} 를 돌려준다(스트리밍)."""
    path = os.path.join(work, name)
    digest = hashlib.sha256()
    size = 0
    with opener(_request(DUMP + name), timeout=120) as res, open(path, "wb") as out:
        last_modified = res.headers.get("Last-Modified", "") if getattr(res, "headers", None) else ""
        while True:
            chunk = res.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
            digest.update(chunk)
            size += len(chunk)
    if size == 0:
        raise GeoError("empty_download:" + name)
    return {"name": name, "bytes": size, "sha256": digest.hexdigest(), "last_modified": last_modified}


def _tsv(lines: Iterable[str]) -> Iterable[list[str]]:
    for line in lines:
        if not line or line.startswith("#"):
            continue
        yield line.rstrip("\n").split("\t")


def _zip_lines(path: str, member: str) -> Iterable[str]:
    with zipfile.ZipFile(path) as zf, zf.open(member) as raw:
        for line in io.TextIOWrapper(raw, encoding="utf-8", newline="\n"):
            yield line


# ------------------------------------------------------------------ 파싱

def parse_countries(lines: Iterable[str]) -> dict:
    """countryInfo.txt → {ISO2: {...}}. 컬럼은 readme 순서."""
    out = {}
    for row in _tsv(lines):
        if len(row) < 17 or len(row[0]) != 2:
            continue
        out[row[0]] = {"iso2": row[0], "iso3": row[1], "name": row[4], "capital": row[5],
                       "population": int(row[7] or 0), "continent": row[8], "geonameid": int(row[16] or 0),
                       "ko": "", "admin1": {}}
    return out


def parse_admin1(lines: Iterable[str], countries: dict) -> None:
    """admin1CodesASCII.txt(`KR.11\\tSeoul\\tSeoul\\t1835847`) → countries[cc]['admin1'][code] = name."""
    for row in _tsv(lines):
        if len(row) < 2 or "." not in row[0]:
            continue
        cc, code = row[0].split(".", 1)
        if cc in countries:
            countries[cc]["admin1"][code] = row[1]


def parse_ko_names(lines: Iterable[str]) -> dict:
    """alternateNamesV2.txt 에서 한국어 이름 {geonameid: 이름}. preferred 가 있으면 우선, 역사적·구어 이름 제외.

    컬럼: id, geonameid, isolanguage, name, isPreferred, isShort, isColloquial, isHistoric, from, to
    """
    best: dict[int, tuple[int, str]] = {}
    for row in _tsv(lines):
        if len(row) < 4 or row[2] != "ko":
            continue
        if len(row) > 7 and (row[6] == "1" or row[7] == "1"):
            continue
        try:
            gid = int(row[1])
        except ValueError:
            continue
        rank = (2 if len(row) > 4 and row[4] == "1" else 0) + (1 if len(row) > 5 and row[5] != "1" else 0)
        if gid not in best or rank > best[gid][0]:
            best[gid] = (rank, row[3])
    return {gid: name for gid, (_rank, name) in best.items()}


def split_places(lines: Iterable[str], countries: dict, ko: dict, tmp: str) -> dict:
    """allCountries 를 한 줄씩 읽어 사람이 사는 곳만 국가별 임시 파일(JSON Lines)로 나눈다. 국가별 개수를 돌려준다.

    전체(수백만 행)를 메모리에 올리지 않는다. 한 행: [geonameid, name, asciiname, ko, admin1, population, lat, lon, fcode]
    """
    os.makedirs(tmp, exist_ok=True)
    handles: dict[str, Any] = {}
    counts: dict[str, int] = {}
    try:
        for row in _tsv(lines):
            if len(row) < 15 or row[6] != "P" or row[7] in EXCLUDE_CODES:
                continue
            cc = row[8]
            if cc not in countries:
                continue
            try:
                gid = int(row[0])
                rec = [gid, row[1], row[2], ko.get(gid, ""), row[10], int(row[14] or 0),
                       round(float(row[4]), 5), round(float(row[5]), 5), row[7]]
            except ValueError:
                continue                                    # 숫자 칸이 깨진 행은 건너뛴다(검사에서 개수로 드러난다)
            fh = handles.get(cc)
            if fh is None:
                fh = handles[cc] = open(os.path.join(tmp, cc + ".jsonl"), "a", encoding="utf-8")
            fh.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")
            counts[cc] = counts.get(cc, 0) + 1
    finally:
        for fh in handles.values():
            fh.close()
    return counts


# ------------------------------------------------------------------ 샤딩

def _gz(raw: bytes) -> bytes:
    return gzip.compress(raw, compresslevel=9, mtime=0)       # mtime=0 → 같은 내용이면 같은 바이트


def _shard_rows(rows: list) -> list[tuple[bytes, int]]:
    """rows 를 gzip ≤ SHARD_MAX 인 덩어리로 나눈다. [(gzip 바이트, 행 수)]."""
    out: list[tuple[bytes, int]] = []
    start = 0
    while start < len(rows):
        end, size = start, 0
        while end < len(rows) and size < RAW_CHUNK:
            size += len(json.dumps(rows[end], ensure_ascii=False)) + 1
            end += 1
        chunk = rows[start:end]
        while True:
            data = _gz(json.dumps(chunk, ensure_ascii=False, separators=(",", ":")).encode())
            if len(data) <= SHARD_MAX or len(chunk) == 1:
                break
            chunk = chunk[: max(1, len(chunk) // 2)]
        out.append((data, len(chunk)))
        start += len(chunk)
    return out


def build_shards(tmp: str, countries: dict) -> dict:
    """국가별 임시 파일 → {doc_id: {"country", "shard", "count", "data", "hash"}}. 인구 내림차순, 같으면 id 순."""
    shards: dict[str, dict] = {}
    for cc in sorted(countries):
        path = os.path.join(tmp, cc + ".jsonl")
        if not os.path.exists(path):
            countries[cc]["city_count"], countries[cc]["shards"] = 0, 0
            continue
        with open(path, encoding="utf-8") as fh:
            rows = [json.loads(line) for line in fh]
        rows.sort(key=lambda r: (-r[5], r[0]))
        parts = _shard_rows(rows)
        for i, (data, n) in enumerate(parts):
            doc = "%s_%03d" % (cc, i)
            shards[doc] = {"country": cc, "shard": i, "count": n, "data": data,
                           "hash": hashlib.sha256(data).hexdigest()}
        countries[cc]["city_count"], countries[cc]["shards"] = len(rows), len(parts)
    return shards


def country_hash(c: dict) -> str:
    return hashlib.sha256(json.dumps({k: v for k, v in c.items() if k != "hash"}, ensure_ascii=False,
                                     sort_keys=True).encode()).hexdigest()


# ------------------------------------------------------------------ 회귀 검사

def check(countries: dict, shards: dict, prev: Optional[dict], cross: dict) -> dict:
    """실패(errors)가 하나라도 있으면 저장하지 않는다. warnings 는 알리기만 한다."""
    errors: list[str] = []
    warnings: list[str] = []
    total = sum(c.get("city_count", 0) for c in countries.values())
    ko_named = sum(s.get("ko_count", 0) for s in shards.values())
    ko_ratio = round(ko_named / total, 4) if total else 0.0
    if len(countries) < 240:
        errors.append("국가 수가 너무 적음: %d" % len(countries))
    if total < 1_000_000:
        errors.append("도시 수가 너무 적음: %d (덤프가 잘렸을 수 있음)" % total)
    for doc, s in shards.items():
        if len(s["data"]) > SHARD_MAX:
            errors.append("샤드가 너무 큼: %s %d" % (doc, len(s["data"])))
    missing_capital = [cc for cc, c in countries.items() if c.get("capital") and not c.get("capital_found")
                       and c.get("city_count", 0) > 0]
    if missing_capital:
        warnings.append("수도가 도시 목록에 없음: %s" % ", ".join(sorted(missing_capital)[:30]))
    if prev:
        pc = prev.get("counts") or {}
        p_total = int(pc.get("cities") or 0)
        if p_total and total < p_total * (1 - MAX_TOTAL_DROP):
            errors.append("전체 도시 수 급감: %d → %d" % (p_total, total))
        p_countries = prev.get("country_counts") or {}
        gone = sorted(set(p_countries) - set(countries))
        if gone:
            errors.append("사라진 국가: %s" % ", ".join(gone))
        for cc, before in p_countries.items():
            now = countries.get(cc, {}).get("city_count", 0)
            if before - now >= MIN_COUNTRY_DROP_ABS and now < before * (1 - MAX_COUNTRY_DROP):
                errors.append("국가 도시 수 급감: %s %d → %d" % (cc, before, now))
        p_ko = float(pc.get("ko_ratio") or 0)
        if p_ko and ko_ratio < p_ko - MAX_KO_RATIO_DROP:
            errors.append("한국어 이름 비율 급감: %.4f → %.4f" % (p_ko, ko_ratio))
    else:
        warnings.append("이전 스냅샷 없음 — 첫 적재(감소 비교 생략)")
    dr = cross.get("dr5hn")
    if isinstance(dr, set):
        only_ours, only_theirs = sorted(set(countries) - dr), sorted(dr - set(countries))
        if only_ours or only_theirs:
            warnings.append("dr5hn 와 국가 집합 차이 — 우리만: %s / 그쪽만: %s" % (only_ours[:20], only_theirs[:20]))
    elif dr:
        warnings.append("dr5hn 교차 검증 못 함: %s" % dr)
    cn = cross.get("countriesnow")
    if isinstance(cn, dict):
        thin = sorted(cc for cc, n in cn.items() if n > 50 and countries.get(cc, {}).get("city_count", 0) < n)
        if thin:
            warnings.append("CountriesNow 보다 도시가 적은 국가: %s" % ", ".join(thin[:30]))
    elif cn:
        warnings.append("CountriesNow 교차 검증 못 함: %s" % cn)
    return {"ok": not errors, "errors": errors, "warnings": warnings,
            "counts": {"countries": len(countries), "cities": total, "shards": len(shards), "ko_ratio": ko_ratio}}


def cross_sources(opener: Opener = urllib.request.urlopen) -> dict:
    """교차 검증용(쓰지 않는다). 실패해도 회귀 검사를 막지 않는다 — 경고로만 남긴다."""
    out: dict[str, Any] = {}
    try:
        with opener(_request(DR5HN), timeout=60) as res:
            out["dr5hn"] = {c.get("iso2") for c in json.loads(res.read()) if c.get("iso2")}
    except Exception as exc:        # noqa: BLE001
        out["dr5hn"] = type(exc).__name__
    try:
        with opener(_request(COUNTRIESNOW), timeout=60) as res:
            body = json.loads(res.read())
        if body.get("error"):
            raise GeoError("error_flag")
        out["countriesnow"] = {c.get("iso2"): len(set(c.get("cities") or [])) for c in body.get("data") or []
                               if c.get("iso2")}
    except Exception as exc:        # noqa: BLE001
        out["countriesnow"] = type(exc).__name__
    return out


# ------------------------------------------------------------------ Firestore REST

def _fs_value(v: Any) -> dict:
    if v is None:
        return {"nullValue": None}
    if isinstance(v, bool):
        return {"booleanValue": v}
    if isinstance(v, int):
        return {"integerValue": str(v)}
    if isinstance(v, float):
        return {"doubleValue": v}
    if isinstance(v, bytes):
        return {"bytesValue": base64.b64encode(v).decode()}
    if isinstance(v, dict):
        return {"mapValue": {"fields": {str(k): _fs_value(x) for k, x in v.items()}}}
    if isinstance(v, (list, tuple)):
        return {"arrayValue": {"values": [_fs_value(x) for x in v]}}
    return {"stringValue": str(v)}


def _fs_plain(v: dict) -> Any:
    if "mapValue" in v:
        return {k: _fs_plain(x) for k, x in (v["mapValue"].get("fields") or {}).items()}
    if "arrayValue" in v:
        return [_fs_plain(x) for x in v["arrayValue"].get("values") or []]
    if "integerValue" in v:
        return int(v["integerValue"])
    for key in ("stringValue", "doubleValue", "booleanValue"):
        if key in v:
            return v[key]
    return None


class Firestore:
    def __init__(self, project: str, token: str, opener: Opener = urllib.request.urlopen) -> None:
        if not project or "/" in project:
            raise GeoError("bad_project")
        self.root = "projects/%s/databases/(default)/documents" % project
        self.base = "https://firestore.googleapis.com/v1/"
        self.token, self.opener = token, opener

    def _call(self, method: str, path: str, body: Any = None) -> dict:
        data = None if body is None else json.dumps(body).encode()
        req = _request(self.base + path, method=method, data=data,
                       headers={"Authorization": "Bearer " + self.token, "Content-Type": "application/json"})
        try:
            with self.opener(req, timeout=120) as res:
                raw = res.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return {}
            raise GeoError("firestore_http_%d" % exc.code) from exc
        return json.loads(raw) if raw else {}

    def get(self, collection: str, doc: str) -> Optional[dict]:
        got = self._call("GET", "%s/%s/%s" % (self.root, collection, doc))
        return {k: _fs_plain(v) for k, v in (got.get("fields") or {}).items()} if got else None

    def name(self, collection: str, doc: str) -> str:
        return "%s/%s/%s" % (self.root, collection, doc)

    def commit(self, writes: list[dict]) -> int:
        """writes 를 요청 크기·건수 상한에 맞춰 나눠 커밋한다. 커밋 횟수를 돌려준다."""
        batches, cur, size = [], [], 0
        for w in writes:
            n = len(json.dumps(w))
            if cur and (size + n > COMMIT_MAX_BYTES or len(cur) >= COMMIT_MAX_WRITES):
                batches.append(cur)
                cur, size = [], 0
            cur.append(w)
            size += n
        if cur:
            batches.append(cur)
        for batch in batches:
            self._call("POST", self.root.rsplit("/documents", 1)[0] + "/documents:commit", {"writes": batch})
        return len(batches)


def store(fs: Firestore, countries: dict, shards: dict, meta: dict, prev: Optional[dict]) -> dict:
    """바뀐 문서만 쓰고, 사라진 샤드는 지우고, 메타를 마지막에 쓴다."""
    prev_shards = (prev or {}).get("shards") or {}
    prev_countries = (prev or {}).get("country_hashes") or {}
    upd = lambda col, doc, fields: {"update": {"name": fs.name(col, doc),  # noqa: E731
                                               "fields": {k: _fs_value(v) for k, v in fields.items()}}}
    writes = []
    for doc, s in shards.items():
        if prev_shards.get(doc) != s["hash"]:
            writes.append(upd("geo_cities", doc, {k: s[k] for k in ("country", "shard", "count", "data", "hash")}))
    for cc, c in countries.items():
        if prev_countries.get(cc) != c["hash"]:
            writes.append(upd("geo_countries", cc, c))
    deletes = [{"delete": fs.name("geo_cities", doc)} for doc in sorted(set(prev_shards) - set(shards))]
    commits = fs.commit(writes + deletes) if (writes or deletes) else 0
    fs.commit([upd("geo_meta", "current", meta)])           # 마지막 — 여기까지 와야 새 스냅샷
    return {"written": len(writes), "deleted": len(deletes), "commits": commits + 1}


# ------------------------------------------------------------------ 실행

def build(work: str, opener: Opener = urllib.request.urlopen) -> tuple[dict, dict, list[dict]]:
    os.makedirs(work, exist_ok=True)
    sources = [download(name, work, opener) for name in FILES]
    with open(os.path.join(work, "countryInfo.txt"), encoding="utf-8") as fh:
        countries = parse_countries(fh)
    with open(os.path.join(work, "admin1CodesASCII.txt"), encoding="utf-8") as fh:
        parse_admin1(fh, countries)
    ko = parse_ko_names(_zip_lines(os.path.join(work, "alternateNamesV2.zip"), "alternateNamesV2.txt"))
    for c in countries.values():
        c["ko"] = ko.get(c["geonameid"], "")
    tmp = os.path.join(work, "split")
    shutil.rmtree(tmp, ignore_errors=True)
    split_places(_zip_lines(os.path.join(work, "allCountries.zip"), "allCountries.txt"), countries, ko, tmp)
    shards = build_shards(tmp, countries)
    for doc, s in shards.items():                           # 한국어 이름 개수(검사용)·수도 확인
        rows = json.loads(gzip.decompress(s["data"]))
        s["ko_count"] = sum(1 for r in rows if r[3])
        cap = countries[s["country"]].get("capital", "")
        if cap and any(r[1] == cap or r[2] == cap for r in rows):
            countries[s["country"]]["capital_found"] = True
    return countries, shards, sources


def run(work: str, *, dry_run: bool, project: str, token: str, opener: Opener = urllib.request.urlopen) -> dict:
    countries, shards, sources = build(work, opener)
    fs = Firestore(project, token, opener) if token else None
    prev = fs.get("geo_meta", "current") if fs else None
    report = check(countries, shards, prev, cross_sources(opener))
    capital_found = {cc for cc, c in countries.items() if c.pop("capital_found", False)}
    for c in countries.values():
        c["hash"] = country_hash(c)
    report["capitals_found"] = len(capital_found)
    report["sources"] = sources
    if not report["ok"]:
        report["stored"] = "skipped: 회귀 검사 실패"
        return report
    if dry_run or not fs:
        report["stored"] = "skipped: dry-run" if dry_run else "skipped: GCP_ACCESS_TOKEN 없음"
        return report
    meta = {"version": time.strftime("%Y-%m-%d", time.gmtime()), "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "attribution": ATTRIBUTION, "license": "CC BY 4.0", "sources": sources, "counts": report["counts"],
            "country_counts": {cc: c["city_count"] for cc, c in countries.items()},
            "country_hashes": {cc: c["hash"] for cc, c in countries.items()},
            "shards": {doc: s["hash"] for doc, s in shards.items()}}
    report["stored"] = store(fs, countries, shards, meta, prev)
    return report


def summary_markdown(report: dict) -> str:
    c = report.get("counts", {})
    lines = ["## 국가·도시 수집 (geo-refresh)", "",
             "| 항목 | 값 |", "|---|---|",
             "| 결과 | %s |" % ("✅ 통과" if report.get("ok") else "❌ 회귀 검사 실패"),
             "| 국가 | %s |" % c.get("countries"), "| 도시(사람이 사는 곳) | %s |" % c.get("cities"),
             "| 샤드 | %s |" % c.get("shards"), "| 한국어 이름 비율 | %s |" % c.get("ko_ratio"),
             "| 저장 | %s |" % report.get("stored"), ""]
    for title, items in (("실패", report.get("errors") or []), ("경고", report.get("warnings") or [])):
        if items:
            lines += ["### " + title] + ["- " + x for x in items] + [""]
    return "\n".join(lines)


ISSUE_TITLE = "[geo-refresh] 국가·도시 수집 실패"


def report_issue(report_path: str, repo: str, token: str, run_url: str, opener: Opener = urllib.request.urlopen) -> str:
    """실패하면 이슈 하나에 모은다(같은 제목의 열린 이슈가 있으면 댓글). anchor_issue 의 API 호출을 재사용한다."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from anchor_issue import _api      # noqa: E402 — 같은 폴더의 표준 라이브러리 스크립트
    try:
        with open(report_path, encoding="utf-8") as fh:
            report = json.load(fh)
        detail = summary_markdown(report)
    except (OSError, ValueError):
        detail = "리포트를 읽지 못했습니다(다운로드·토큰 단계에서 실패했을 수 있습니다 — 실행 로그를 보세요)."
    body = "실행: %s\n\n%s\n\n- 회귀 검사가 실패했으면 Firestore 에는 아무것도 쓰지 않았습니다." % (run_url, detail)
    import urllib.parse
    q = urllib.parse.quote('repo:%s is:issue is:open in:title "%s"' % (repo, ISSUE_TITLE))
    found = _api("GET", "/search/issues?q=" + q, token, opener=opener) or {}
    items = [i for i in found.get("items") or [] if i.get("title") == ISSUE_TITLE]
    if items:
        _api("POST", "/repos/%s/issues/%d/comments" % (repo, items[0]["number"]), token, {"body": body}, opener)
        return "commented #%d" % items[0]["number"]
    made = _api("POST", "/repos/%s/issues" % repo, token, {"title": ISSUE_TITLE, "body": body}, opener)
    return "opened #%s" % (made or {}).get("number")


def main(argv: Optional[list] = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # Windows 콘솔(cp949)에서도 요약을 찍는다
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--work", required=True)
    r.add_argument("--dry-run", action="store_true")
    r.add_argument("--report", default="geo-report.json")
    i = sub.add_parser("issue", help="실패를 GitHub 이슈로 알린다(Actions 의 if: failure())")
    i.add_argument("report", nargs="?", default="geo-report.json")
    args = ap.parse_args(argv)
    if args.cmd == "issue":
        repo, token = os.environ.get("GITHUB_REPOSITORY", ""), os.environ.get("GH_TOKEN", "")
        if not repo or not token:
            print("::error::GITHUB_REPOSITORY/GH_TOKEN 없음")
            return 1
        run_url = "%s/%s/actions/runs/%s" % (os.environ.get("GITHUB_SERVER_URL", "https://github.com"), repo,
                                             os.environ.get("GITHUB_RUN_ID", ""))
        print(report_issue(args.report, repo, token, run_url))
        return 0
    try:
        report = run(args.work, dry_run=args.dry_run, project=os.environ.get("FIREBASE_PROJECT_ID", ""),
                     token=os.environ.get("GCP_ACCESS_TOKEN", ""))
    except Exception as exc:        # noqa: BLE001 — 값만 남긴다
        report = {"ok": False, "errors": ["%s: %s" % (type(exc).__name__, str(exc)[:200])], "stored": "skipped: 오류"}
    with open(args.report, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    md = summary_markdown(report)
    print(md)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write(md + "\n")
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
