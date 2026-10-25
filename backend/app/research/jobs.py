"""조사 잡 — POST 가 잡을 시작하고, 화면이 GET 으로 진행·결과를 받는다(Render 무료 단일 인스턴스 기준).

- 같은 요청(도시·날짜·caps 가 같음)이 이미 돌고 있으면 그 잡을 같이 본다(single-flight).
- IP 당 동시 1잡, 전역 RESEARCH_MAX_JOBS(기본 1). 넘으면 Busy → 503.
- 잡은 끝난 뒤 15분 보관, 최대 50개. 서버가 재시작되면 잃는다 — 화면은 404 면 다시 요청하고, 끝난 도시는 캐시에 있다.
- 화면이 기다리기를 멈춰도 잡은 끝까지 돌아 캐시를 데운다.
"""
from __future__ import annotations

import contextvars
import logging
import secrets
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Optional

from . import config

KEEP_S = 15 * 60
MAX_KEEP = 50
log = logging.getLogger("app.research")


class Busy(RuntimeError):
    """조사 잡 상한."""


class JobStore:
    def __init__(self, now: Callable[[], float] = time.time) -> None:
        self._now = now
        self._lock = threading.Lock()
        self._jobs: "OrderedDict[str, dict]" = OrderedDict()
        self._by_key: dict[str, str] = {}
        self._pool: Optional[ThreadPoolExecutor] = None
        self._pool_size = 0

    def _executor(self) -> ThreadPoolExecutor:
        size = config.max_jobs()
        if self._pool is None or self._pool_size != size:
            self._pool = ThreadPoolExecutor(max_workers=size, thread_name_prefix="research")
            self._pool_size = size
        return self._pool

    def _gc(self) -> None:
        now = self._now()
        for jid in [j for j, v in self._jobs.items() if v["status"] != "running" and now - v["ended"] > KEEP_S]:
            self._drop(jid)
        while len(self._jobs) > MAX_KEEP:
            jid = next((j for j, v in self._jobs.items() if v["status"] != "running"), None)
            if jid is None:
                break
            self._drop(jid)

    def _drop(self, jid: str) -> None:
        job = self._jobs.pop(jid, None)
        if job and self._by_key.get(job["key"]) == jid:
            self._by_key.pop(job["key"], None)

    def start(self, key: str, ip: str, work: Callable[[Callable[[dict], None]], dict]) -> "tuple[str, bool]":
        """(job_id, 이미 돌던 잡인가). work(on_progress) -> report."""
        with self._lock:
            self._gc()
            jid = self._by_key.get(key)
            if jid and self._jobs.get(jid, {}).get("status") == "running":
                return jid, True
            running = [v for v in self._jobs.values() if v["status"] == "running"]
            if len(running) >= config.max_jobs() or (ip and any(v["ip"] == ip for v in running)):
                raise Busy("research_busy")
            jid = secrets.token_urlsafe(16)
            job = {"id": jid, "key": key, "ip": ip, "status": "running", "progress": [], "report": None,
                   "reason": "", "started": self._now(), "ended": 0.0}
            self._jobs[jid] = job
            self._by_key[key] = jid

        def progress(ev: dict) -> None:
            with self._lock:
                if len(job["progress"]) < 200:
                    job["progress"].append(ev)

        def run() -> None:
            try:
                rep = work(progress)
                status, reason = "done", ""
            except Exception as exc:  # noqa: BLE001 — 잡 실패는 화면이 예시로 돌아가게 상태만 남긴다
                log.warning("research job failed %s", type(exc).__name__)
                rep, status, reason = None, "failed", "research_error"
            with self._lock:
                job.update(status=status, report=rep, reason=reason, ended=self._now())

        ctx = contextvars.copy_context()
        self._executor().submit(ctx.run, run)
        return jid, False

    def get(self, jid: str) -> Optional[dict]:
        with self._lock:
            job = self._jobs.get(jid)
            if not job:
                return None
            return {"status": job["status"], "progress": list(job["progress"][-30:]),
                    **({"report": job["report"]} if job["report"] else {}),
                    **({"reason": job["reason"]} if job["reason"] else {})}

    def active(self) -> int:
        with self._lock:
            return sum(1 for v in self._jobs.values() if v["status"] == "running")


JOBS = JobStore()
