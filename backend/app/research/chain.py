"""장소 소스 대체 체인 + 소스별 쿨다운(복구) — 위키보이지에 장소가 모자란 도시를 다른 소스로 채운다.

    위키보이지(1순위, nodes.city_guide) → 모자라면 RESEARCH_PLACE_CHAIN 순서대로 → 종류별 목표(caps + 여유)를 채우면 멈춤

- 모자람은 종류별로 센다(관광지 / 식당·카페). 이미 채운 종류는 다음 소스에 묻지 않는다.
- 실패 분류(Airports_near_me map-chain 과 같은 4가지):
    exhaust      401·403·한도(capped)        → 긴 쿨다운(6시간). 키·정책 문제라 곧 낫지 않는다
    rate_limited 429                          → 쿨다운 5분, 이번 요청은 다음 소스로
    transient    5xx·시간 초과·연결 실패        → 쿨다운 1분, 다음 소스로
    nodata       정상인데 결과 없음             → 다음 소스로(쿨다운 없음)
  연속 실패 5번이면 회로를 연다(쿨다운 4배). 성공하면 쿨다운·연속 실패를 지운다(자동 복구).
- 쿨다운 중인 소스는 건너뛴다. 단 체인의 모든 소스가 쿨다운이면 가장 빨리 풀리는 하나는 시도한다(gemini.attempt_order 와 같은 규칙).
- 상태는 프로세스 메모리다(재시작하면 모두 건강한 상태로 시작한다 — 실패하면 다시 배운다).
"""
from __future__ import annotations

import re
import threading
import time
import unicodedata
from typing import Any, Callable, Optional

from . import config, verify

FOOD = ("restaurant", "cafe")
COOLDOWN_S = {"exhaust": 6 * 3600, "rate_limited": 300, "transient": 60}
CIRCUIT_AFTER = 5
CIRCUIT_FACTOR = 4
SAME_PLACE_M = 150

# 결과를 저장하면 안 되는 실시간 소스(Google 약관). 캐시된 대체 결과가 있어도 모자라면 이것만 다시 묻는다.
LIVE_ONLY = frozenset({"google"})

# 어댑터: (deps, tc, want{"attraction": n, "food": n}) -> SourceResult(data = 장소 목록, report.places_from 과 같은 모양)
Adapter = Callable[[Any, dict, dict], dict]
ADAPTERS: dict[str, Adapter] = {}


# ------------------------------------------------------------------ 소스 건강 상태
class Health:
    def __init__(self, now: Callable[[], float] = time.time) -> None:
        self._now = now
        self._lock = threading.Lock()
        self._s: dict[str, dict] = {}

    def _get(self, name: str) -> dict:
        return self._s.setdefault(name, {"until": 0.0, "streak": 0, "last_error": "", "last_ok": 0, "circuit": False})

    def cooling(self, name: str) -> float:
        """남은 쿨다운(초). 0 이면 건강."""
        with self._lock:
            return max(0.0, self._get(name)["until"] - self._now())

    def note(self, name: str, outcome: str, reason: str = "") -> None:
        with self._lock:
            s = self._get(name)
            if outcome in ("ok", "nodata"):
                if outcome == "ok":
                    s["last_ok"] = int(self._now())
                s.update(until=0.0, streak=0, circuit=False)
                return
            if outcome not in COOLDOWN_S:
                return
            s["streak"] += 1
            s["last_error"] = (reason or outcome)[:40]
            s["circuit"] = s["streak"] >= CIRCUIT_AFTER
            s["until"] = self._now() + COOLDOWN_S[outcome] * (CIRCUIT_FACTOR if s["circuit"] else 1)

    def order(self, names: list[str]) -> list[str]:
        """쿨다운 중인 소스는 뺀다. 전부 쿨다운이면 가장 빨리 풀리는 하나만 남긴다."""
        live = [n for n in names if self.cooling(n) <= 0]
        if live or not names:
            return live
        return [min(names, key=self.cooling)]

    def snapshot(self) -> dict:
        now = self._now()
        with self._lock:
            return {n: {"cooldown_s": max(0, int(s["until"] - now)), "streak": s["streak"], "circuit": s["circuit"],
                        "last_error": s["last_error"], "last_ok": s["last_ok"]} for n, s in self._s.items()}

    def reset(self) -> None:
        with self._lock:
            self._s.clear()


HEALTH = Health()


def classify(r: dict) -> str:
    """SourceResult → ok | nodata | disabled | exhaust | rate_limited | transient."""
    st, reason = r.get("status"), str(r.get("reason") or "")
    if st == "ok":
        return "ok" if r.get("data") else "nodata"
    if st == "empty":
        return "nodata"
    if st == "disabled":
        return "disabled"
    if st == "capped" or reason in ("http_401", "http_403"):
        return "exhaust"
    if st == "rate_limited":
        return "rate_limited"
    return "transient"


# ------------------------------------------------------------------ 모자람·합치기
def want(places: list[dict], caps: dict) -> dict:
    """종류별로 더 필요한 수(목표 = caps + RESEARCH_PLACE_MIN_EXTRA)."""
    extra = config.place_min_extra()
    attr = sum(1 for p in places if p.get("kind") == "attraction")
    food = sum(1 for p in places if p.get("kind") in FOOD)
    return {"attraction": max(0, int(caps.get("attr", 0)) + extra - attr) if caps.get("attr", 0) else 0,
            "food": max(0, int(caps.get("rest", 0)) + extra - food) if caps.get("rest", 0) else 0}


def enough(places: list[dict], caps: dict) -> bool:
    """여유 없이 일정이 정한 수만큼은 있는가(보고서 place_status)."""
    attr = sum(1 for p in places if p.get("kind") == "attraction")
    food = sum(1 for p in places if p.get("kind") in FOOD)
    return attr >= int(caps.get("attr", 0)) and food >= int(caps.get("rest", 0))


def short(w: dict) -> bool:
    return any(v > 0 for v in w.values())


def _norm_name(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").casefold()
    return re.sub(r"[\W_]+", "", s)


def _same(a: dict, b: dict) -> bool:
    if a.get("wikidata") and a.get("wikidata") == b.get("wikidata"):
        return True
    if _norm_name(a.get("name", "")) != _norm_name(b.get("name", "")):
        return False
    if None in (a.get("lat"), a.get("lon"), b.get("lat"), b.get("lon")):
        return True
    return verify.km(a["lat"], a["lon"], b["lat"], b["lon"]) * 1000 <= SAME_PLACE_M


def merge(primary: list[dict], extra: list[dict]) -> list[dict]:
    """앞 소스(우선순위 높은 것)를 남기고, 뒤 소스의 같은 장소는 빈 설명·홈페이지·wikidata 만 채우고 출처를 합친다."""
    out = [dict(p) for p in primary]
    for e in extra:
        hit = next((p for p in out if _same(p, e)), None)
        if hit is None:
            out.append(dict(e))
            continue
        for k in ("desc_en", "desc_ko", "homepage", "wikidata"):
            if not hit.get(k) and e.get(k):
                hit[k] = e[k]
        seen = {s.get("url") for s in hit.get("sources") or []}
        hit["sources"] = list(hit.get("sources") or []) + [s for s in e.get("sources") or [] if s.get("url") not in seen]
    return out


# ------------------------------------------------------------------ 실행
def active(adapters: Optional[dict[str, Adapter]] = None) -> list[str]:
    """지금 쓸 수 있는 대체 소스(순서대로). 어댑터가 있고, RESEARCH_PLACE_CHAIN·RESEARCH_SOURCES 가 막지 않은 것."""
    adapters = ADAPTERS if adapters is None else adapters
    def allowed(n: str) -> bool:
        base = n.split("_", 1)[0]                     # wikidata_places → wikidata (RESEARCH_SOURCES 로 끈 소스는 체인에서도 끔)
        return base not in config.ALL_SOURCES or config.source_on(base)
    def ready(n: str) -> bool:                        # 키가 필요한 소스는 adapter.available() 로 설정 여부를 알린다
        check = getattr(adapters[n], "available", None)
        return check() if callable(check) else True
    return [n for n in config.place_chain() if n in adapters and allowed(n) and ready(n)]


def run(deps: Any, tc: dict, have: list[dict], health: Optional[Health] = None,
        adapters: Optional[dict[str, Adapter]] = None, only: Optional[frozenset] = None) -> dict:
    """→ {places: 대체 소스에서 새로 얻은 장소(have 와 겹치지 않음), by_source: {name: {status, outcome, count}}, outage: bool}.
    예외를 올리지 않는다. 마감(RESEARCH_SOFT_DEADLINE_S)이 지나면 지금까지 얻은 것으로 끝낸다."""
    health = health or HEALTH
    adapters = ADAPTERS if adapters is None else adapters
    names = [n for n in active(adapters) if only is None or n in only]
    got: list[dict] = []
    by_source: dict[str, dict] = {}
    w = want(have, tc["caps"])
    for name in health.order(names):
        if not short(w):
            break
        if deps.past_deadline():
            by_source[name] = {"status": "skipped", "outcome": "deadline", "count": 0}
            break
        try:
            r = adapters[name](deps, tc, dict(w))
        except Exception as exc:  # noqa: BLE001 — 어댑터 버그도 장애처럼 다음 소스로
            r = {"status": "unavailable", "reason": type(exc).__name__, "data": None}
        outcome = classify(r)
        health.note(name, outcome, str(r.get("reason") or ""))
        fresh = [p for p in (r.get("data") or []) if isinstance(p, dict)] if outcome == "ok" else []
        before = len(got)
        got = merge(got, [p for p in fresh if not any(_same(p, h) for h in have)])
        by_source[name] = {"status": r.get("status"), "outcome": outcome, "count": len(got) - before,
                           "reason": str(r.get("reason") or "")[:40]}
        w = want(have + got, tc["caps"])
    for name in names:
        if name not in by_source and health.cooling(name) > 0:
            by_source[name] = {"status": "skipped", "outcome": "cooldown", "count": 0}
    outage = any(v["outcome"] in ("exhaust", "rate_limited", "transient", "cooldown") for v in by_source.values())
    return {"places": got, "by_source": by_source, "outage": outage}


def keep_last_good(new: dict, old: Optional[dict]) -> tuple[dict, bool]:
    """대량 감소 가드(flight-sync 의 mass-delete guard): 새 결과가 기존의 절반 미만이고 그 원인이 장애면
    기존(만료된 것이라도)을 그대로 쓴다. → (쓸 결과, 기존을 썼는가)."""
    if not old:
        return new, False
    old_n, new_n = len(old.get("places") or []), len(new.get("places") or [])
    if new.get("outage") and new_n * 2 < old_n:
        return old, True
    return new, False
