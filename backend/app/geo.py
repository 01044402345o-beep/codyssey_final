"""국가·도시 목록 — geo-refresh 워크플로우가 Firestore 에 쌓은 GeoNames 데이터를 화면 선택 목록으로 내보낸다.

데이터: geo_countries/{ISO2} · geo_cities/{ISO2}_{nnn}(gzip JSON 행, 인구 내림차순) — docs/ops/GEO_REFRESH.md.
읽기는 백엔드 서비스 계정(firebase_admin)으로 한다. 클라이언트 규칙은 바꾸지 않는다(그 경로는 전부 거부).

- 국가 목록은 한 번 읽어 메모리에 둔다(6시간). 도시는 나라마다 **첫 샤드(인구 상위)** 만 읽어 상위 N 곳을 둔다
  — 선택 목록에 필요한 건 사람이 고를 만한 도시이고, 마을 수백만 곳을 메모리에 올리면 작은 서버가 버티지 못한다.
- 검색: 영문·ASCII·한국어 이름의 앞부분 일치를 먼저, 그다음 포함 일치. 같은 순위면 인구가 많은 곳부터.
- 한국어 도시명 끝의 ' 시'(띄어 쓴 행정 접미사)는 뺀다('뉴욕 시' → '뉴욕'). '서울특별시' 처럼 붙여 쓴 이름은 그대로.
- 출처 표기(CC BY 4.0)를 응답에 싣는다.
"""
from __future__ import annotations

import base64
import gzip
import json
import re
import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Optional

from . import firebase_admin

TTL = 6 * 3600
MAX_CITIES_PER_COUNTRY = 20_000     # 첫 샤드 중 인구 상위만(메모리 상한)
MAX_COUNTRIES_CACHED = 8
ATTRIBUTION = "GeoNames (https://www.geonames.org), CC BY 4.0"
ISO2 = re.compile(r"^[A-Z]{2}$")


class GeoError(RuntimeError):
    def __init__(self, status: int, code: str) -> None:
        super().__init__(code)
        self.status, self.code = status, code


Fetch = Callable[[str], dict]


def _fields(doc: dict) -> dict:
    return doc.get("fields") or {}


def _plain(v: dict) -> Any:
    if "mapValue" in v:
        return {k: _plain(x) for k, x in (v["mapValue"].get("fields") or {}).items()}
    if "integerValue" in v:
        return int(v["integerValue"])
    for key in ("stringValue", "doubleValue", "booleanValue", "bytesValue"):
        if key in v:
            return v[key]
    return None


def _default_fetch(subpath: str) -> dict:
    try:
        admin = firebase_admin.get_admin()
    except firebase_admin.AdminError as exc:
        raise GeoError(503, "geo_unavailable") from exc
    try:
        return admin.firestore("GET", subpath) or {}
    except firebase_admin.AdminError as exc:
        raise GeoError(503, "geo_unavailable") from exc


def ko_label(name: str) -> str:
    """'뉴욕 시' → '뉴욕'. 띄어 쓴 ' 시' 만 뺀다('서울특별시'·'시애틀' 은 그대로)."""
    return re.sub(r"\s+시$", "", (name or "").strip())


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").casefold())


class GeoStore:
    def __init__(self, fetch: Optional[Fetch] = None, now: Callable[[], float] = time.time) -> None:
        self._fetch = fetch or _default_fetch
        self._now = now
        self._lock = threading.Lock()
        self._countries: Optional[tuple[float, list[dict]]] = None
        self._cities: "OrderedDict[str, tuple[float, list[dict]]]" = OrderedDict()

    # -------------------------------------------------------------- 국가
    def countries(self) -> list[dict]:
        with self._lock:
            if self._countries and self._now() - self._countries[0] < TTL:
                return self._countries[1]
        docs, token = [], ""
        while True:
            page = self._fetch("geo_countries?pageSize=300" + ("&pageToken=" + token if token else ""))
            docs += page.get("documents") or []
            token = page.get("nextPageToken") or ""
            if not token:
                break
        out = []
        for d in docs:
            f = {k: _plain(v) for k, v in _fields(d).items()}
            if not f.get("iso2") or not f.get("city_count"):
                continue                                   # 도시가 없는 무인도·폐지 코드(BV·HM·AN·CS)는 고를 일이 없다
            out.append({"iso2": f["iso2"], "name": f.get("name") or "", "ko": f.get("ko") or "",
                        "capital": f.get("capital") or "", "population": int(f.get("population") or 0),
                        "continent": f.get("continent") or "", "shards": int(f.get("shards") or 0),
                        "admin1": f.get("admin1") or {}})
        if not out:
            raise GeoError(503, "geo_empty")
        out.sort(key=lambda c: (c["ko"] or c["name"]))
        with self._lock:
            self._countries = (self._now(), out)
        return out

    def country(self, iso2: str) -> dict:
        for c in self.countries():
            if c["iso2"] == iso2:
                return c
        raise GeoError(404, "unknown_country")

    # -------------------------------------------------------------- 도시
    def _load_cities(self, iso2: str) -> list[dict]:
        with self._lock:
            hit = self._cities.get(iso2)
            if hit and self._now() - hit[0] < TTL:
                self._cities.move_to_end(iso2)
                return hit[1]
        meta = self.country(iso2)
        if not meta["shards"]:
            return []
        doc = self._fetch("geo_cities/%s_000" % iso2)
        raw = _plain(_fields(doc).get("data") or {})
        if not raw:
            raise GeoError(503, "geo_empty")
        rows = json.loads(gzip.decompress(base64.b64decode(raw)))[:MAX_CITIES_PER_COUNTRY]
        admin1 = meta["admin1"]
        cities = []
        for r in rows:       # [geonameid, name, asciiname, ko, admin1, population, lat, lon, fcode]
            ko = ko_label(r[3])
            cities.append({"id": r[0], "name": r[1], "ko": ko, "label": ko or r[1], "region": admin1.get(r[4], ""),
                           "population": r[5], "capital": r[8] == "PPLC",
                           "_k": (_norm(r[1]), _norm(r[2]), _norm(ko))})
        with self._lock:
            self._cities[iso2] = (self._now(), cities)
            self._cities.move_to_end(iso2)
            while len(self._cities) > MAX_COUNTRIES_CACHED:
                self._cities.popitem(last=False)
        return cities

    def cities(self, iso2: str, q: str = "", limit: int = 20) -> list[dict]:
        iso2 = (iso2 or "").strip().upper()
        if not ISO2.match(iso2):
            raise GeoError(400, "bad_country")
        limit = max(1, min(int(limit or 20), 50))
        rows = self._load_cities(iso2)
        needle = _norm(q)[:60]
        if not needle:
            picked = rows[:limit]                          # 인구 상위
        else:
            first, second = [], []
            for c in rows:
                keys = c["_k"]
                if any(k.startswith(needle) for k in keys if k):
                    first.append(c)
                elif any(needle in k for k in keys if k):
                    second.append(c)
                if len(first) >= limit:
                    break
            picked = (first + second)[:limit]              # 행이 이미 인구순이라 각 묶음 안에서도 인구순
        return [{k: v for k, v in c.items() if not k.startswith("_")} for c in picked]


STORE = GeoStore()


def countries_payload() -> dict:
    return {"countries": [{k: v for k, v in c.items() if k not in ("admin1", "shards")} for c in STORE.countries()],
            "attribution": ATTRIBUTION}


def cities_payload(country: str, q: str, limit: int) -> dict:
    return {"country": (country or "").strip().upper(), "cities": STORE.cities(country, q, limit),
            "attribution": ATTRIBUTION}
