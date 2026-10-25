"""조사 결과 캐시 — Firestore(서비스 계정, 규칙을 거치지 않는다). 설정이 없으면 프로세스 메모리.

research_cities/{ISO2}_{gid|n<sha1-12>}/sections/{guide|climate_MMDD_N}
research_countries/{ISO2}/sections/{facts|advisory|fx}
섹션 문서: data(gzip JSON → bytes) · fetched_at · valid_until · expire_at(TTL 정책용) · schema · sources(JSON 문자열).
같은 도시를 고른 다음 사용자는 바로 받는다. 오래된 섹션(valid_until 지남·schema 다름)은 없는 것으로 본다.
Firestore 문서 상한(1MiB) 때문에 900KB 넘는 데이터는 쓰지 않는다.
"""
from __future__ import annotations

import base64
import datetime as dt
import gzip
import json
import logging
import re
import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Optional

SCHEMA = 1
MAX_BYTES = 900 * 1024
COLLECTIONS = ("research_cities", "research_countries")
KEY = re.compile(r"^[A-Z]{2}(_(\d{1,10}|n[0-9a-f]{12}))?$")
SECTION = re.compile(r"^[a-z0-9_]{1,40}$")
log = logging.getLogger("app.research")

Fetch = Callable[[str, str, Optional[dict]], dict]


def _default_fetch() -> Optional[Fetch]:
    from .. import firebase_admin
    if not firebase_admin.configured():
        return None
    try:
        admin = firebase_admin.get_admin()
    except firebase_admin.AdminError:
        return None
    return lambda method, subpath, body=None: admin.firestore(method, subpath, body)


class ResearchCache:
    def __init__(self, fetch: Optional[Fetch] = None, now: Callable[[], float] = time.time, memory_max: int = 64,
                 use_firestore: Optional[bool] = None) -> None:
        self._fetch = fetch
        self._auto = fetch is None and use_firestore is not False
        self._now = now
        self._mem: "OrderedDict[str, tuple[float, dict]]" = OrderedDict()   # 메모리 캐시(설정 없을 때의 본 저장소, 있을 때는 읽기 완충)
        self._mem_max = memory_max
        self._lock = threading.Lock()

    def _store(self) -> Optional[Fetch]:
        if self._fetch is None and self._auto:
            return _default_fetch()
        return self._fetch

    @staticmethod
    def _path(collection: str, key: str, section: str) -> str:
        if collection not in COLLECTIONS or not KEY.match(key or "") or not SECTION.match(section or ""):
            raise ValueError("bad cache path")
        return f"{collection}/{key}/sections/{section}"

    def get(self, collection: str, key: str, section: str) -> Optional[dict]:
        path = self._path(collection, key, section)
        now = self._now()
        with self._lock:
            hit = self._mem.get(path)
            if hit and hit[1]["valid_until"] > now:
                self._mem.move_to_end(path)
                return hit[1]
        store = self._store()
        if store is None:
            return None
        try:
            doc = store("GET", path, None) or {}
        except Exception as exc:  # noqa: BLE001 — 캐시를 못 읽으면 새로 조사한다(조사는 계속된다)
            log.warning("research cache read failed %s", type(exc).__name__)
            return None
        entry = self._decode(doc)
        if not entry or entry["valid_until"] <= now or entry["schema"] != SCHEMA:
            return None
        self._remember(path, entry)
        return entry

    def put(self, collection: str, key: str, section: str, data: Any, ttl_s: int, sources: list[dict]) -> bool:
        path = self._path(collection, key, section)
        now = int(self._now())
        raw = gzip.compress(json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        if len(raw) > MAX_BYTES:
            log.warning("research cache too large %s %d", path, len(raw))
            return False
        srcs = [{k: s.get(k, "") for k in ("provider", "url", "license", "attribution", "status")} for s in sources]
        entry = {"data": data, "fetched_at": now, "valid_until": now + int(ttl_s), "schema": SCHEMA, "sources": srcs}
        self._remember(path, entry)
        store = self._store()
        if store is None:
            return True
        expire = dt.datetime.fromtimestamp(now + int(ttl_s), dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        body = {"fields": {
            "data": {"bytesValue": base64.b64encode(raw).decode("ascii")},
            "fetched_at": {"integerValue": str(now)}, "valid_until": {"integerValue": str(now + int(ttl_s))},
            "expire_at": {"timestampValue": expire}, "schema": {"integerValue": str(SCHEMA)},
            "sources": {"stringValue": json.dumps(srcs, ensure_ascii=False)},
        }}
        try:
            store("PATCH", path, body)
            return True
        except Exception as exc:  # noqa: BLE001 — 쓰기 실패는 이번 결과를 버리지 않는다(다음 사용자가 다시 조사할 뿐)
            log.warning("research cache write failed %s", type(exc).__name__)
            return False

    def _remember(self, path: str, entry: dict) -> None:
        with self._lock:
            self._mem[path] = (self._now(), entry)
            self._mem.move_to_end(path)
            while len(self._mem) > self._mem_max:
                self._mem.popitem(last=False)

    @staticmethod
    def _decode(doc: dict) -> Optional[dict]:
        f = (doc or {}).get("fields") or {}
        try:
            raw = base64.b64decode((f.get("data") or {}).get("bytesValue") or "")
            data = json.loads(gzip.decompress(raw).decode("utf-8"))
            return {"data": data, "fetched_at": int((f.get("fetched_at") or {}).get("integerValue") or 0),
                    "valid_until": int((f.get("valid_until") or {}).get("integerValue") or 0),
                    "schema": int((f.get("schema") or {}).get("integerValue") or 0),
                    "sources": json.loads((f.get("sources") or {}).get("stringValue") or "[]")}
        except (ValueError, OSError, TypeError, EOFError):
            return None
