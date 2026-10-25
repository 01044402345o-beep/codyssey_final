"""조사 단계 설정. 값은 호출할 때마다 읽는다(임포트 때 고정하지 않는다 — itinerary_enabled 와 같은 규칙).

키 값은 어디에도 내보내지 않는다. /health 에는 '설정됨' 여부만 나간다.
"""
from __future__ import annotations

import os

# 영국 외무부(FCDO) 권고는 쓰지 않는다 — 영국 국적자 기준(영국 대사관 연락처 등)이라 한국 사용자에게는 오정보다(10/25 결정).
# 안전 정보는 외교부 해외안전여행(0404.go.kr) 공공데이터 API 키가 생기면 붙인다.
ALL_SOURCES = ("wikivoyage", "wikidata", "openmeteo", "frankfurter", "geoapify", "google", "tavily")
# 이번 단계(PR1)에 구현된 소스. 나머지는 후속 PR 에서 붙는다.
KEYLESS_SOURCES = ("wikivoyage", "wikidata", "openmeteo", "frankfurter")
DEFAULT_CONTACT = "https://github.com/01044402345o-beep/codyssey_final"


def _int(name: str, default: int, lo: int, hi: int) -> int:
    try:
        v = int((os.getenv(name) or "").strip() or default)
    except ValueError:
        v = default
    return max(lo, min(hi, v))


def research_enabled() -> bool:
    """킬 스위치. 기본 꺼짐 — 꺼져 있으면 외부 호출이 0회다."""
    return (os.getenv("RESEARCH_ENABLED") or "").strip() == "1"


def sources_enabled() -> set[str]:
    raw = os.getenv("RESEARCH_SOURCES")
    if raw is None or not raw.strip():
        return set(ALL_SOURCES)
    return {s.strip().lower() for s in raw.split(",") if s.strip().lower() in ALL_SOURCES}


def source_on(name: str) -> bool:
    return name in sources_enabled()


def use_graph() -> bool:
    """1(기본)이면 LangGraph 로, 0 이면 같은 노드를 스레드로 순서대로 돌린다(같은 결과). 그래프가 실패해도 자동으로 0 경로."""
    return (os.getenv("RESEARCH_USE_GRAPH") or "1").strip() != "0"


def max_jobs() -> int:
    return _int("RESEARCH_MAX_JOBS", 1, 1, 4)


def max_cities() -> int:
    return _int("RESEARCH_MAX_CITIES", 5, 1, 5)


def soft_deadline_s() -> int:
    return _int("RESEARCH_SOFT_DEADLINE_S", 100, 10, 600)


def cache_days() -> int:
    return _int("RESEARCH_CACHE_DAYS", 30, 1, 90)


def volatile_hours() -> int:
    return _int("RESEARCH_VOLATILE_HOURS", 24, 1, 168)


def user_agent() -> str:
    """위키미디어 User-Agent 정책: 앱 이름·연락처를 밝힌다. 없으면 공유 IP 가 익명(10회/분) 취급된다."""
    contact = (os.getenv("WIKIMEDIA_CONTACT") or "").strip() or DEFAULT_CONTACT
    contact = "".join(ch for ch in contact if 32 < ord(ch) < 127 and ch not in "()")[:120] or DEFAULT_CONTACT
    return f"MADI-TravelEnglish/1.0 ({contact}) python-urllib"
