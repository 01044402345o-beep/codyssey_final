"""국가·도시 목록 — geo-refresh 워크플로우가 Firestore 에 쌓은 GeoNames 데이터를 화면 선택 목록으로 내보낸다.

데이터: geo_countries/{ISO2} · geo_cities/{ISO2}_{nnn}(gzip JSON 행, 인구 내림차순) — docs/ops/GEO_REFRESH.md.
읽기는 백엔드 서비스 계정(firebase_admin)으로 한다. 클라이언트 규칙은 바꾸지 않는다(그 경로는 전부 거부).

- 국가 목록은 한 번 읽어 메모리에 둔다(6시간). 도시 검색은 나라마다 **첫 샤드(인구 상위)** 에서 한다
  — 마을 수백만 곳을 한꺼번에 메모리에 올리면 작은 서버가 버티지 못한다.
- 빈 칸(검색어 없음)은 **생략 없는 전체 목록**을 쪽(offset·limit)으로 준다: 샤드를 차례로 읽어 이어 붙이고,
  전체 개수는 그 나라의 city_count(geo-refresh 가 센 전부)다. 읽은 샤드는 몇 개만 캐시한다(MAX_SHARDS_CACHED).
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
MAX_CITY_LIMIT = MAX_CITIES_PER_COUNTRY   # 한 나라의 도시를 한 번에 다 줄 수 있는 상한
MAX_COUNTRIES_CACHED = 8
MAX_SHARDS_CACHED = 6               # 빈 칸 목록을 넘겨 볼 때 읽은 샤드(원본 행) 캐시 — 샤드 하나 ≈ 행 2만
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
        self._shards: "OrderedDict[tuple[str, int], tuple[float, list[list]]]" = OrderedDict()
        self._shard_len: dict[tuple[str, int], tuple[float, int]] = {}   # 샤드 행 수 — 앞 샤드를 다시 읽지 않고 건너뛴다

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
                        "city_count": int(f.get("city_count") or 0),
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

    def country_by_name(self, name: str) -> Optional[dict]:
        """적힌 나라 이름(한국어·영문·ISO2)으로 목록의 나라를 찾는다. 못 찾으면 None(자유 입력)."""
        k = _norm(name)
        if not k:
            return None
        for c in self.countries():
            if k in (_norm(c["iso2"]), _norm(c["ko"]), _norm(c["name"])):
                return c
        return None

    # -------------------------------------------------------------- 도시 정체성(조사 단계)
    def _identity(self, iso2: str, c: dict) -> dict:
        lat, lon = c["_ll"]
        return {"gid": c["id"], "iso2": iso2, "name": c["name"], "ascii": c["_ascii"], "ko": c["ko"],
                "region": c["region"], "population": c["population"], "lat": lat, "lon": lon}

    def city_by_id(self, iso2: str, gid: int, max_shards: int = 3) -> Optional[dict]:
        """GeoNames id 로 도시를 찾는다(좌표 포함). 첫 샤드(인구 상위)부터 최대 max_shards 개까지만 본다."""
        iso2 = (iso2 or "").strip().upper()
        if not ISO2.match(iso2) or type(gid) is not int or gid <= 0:
            return None
        try:
            meta = self.country(iso2)
        except GeoError:
            return None
        for c in self._load_cities(iso2):
            if c["id"] == gid:
                return self._identity(iso2, c)
        for k in range(1, min(meta["shards"], max_shards)):
            for r in self._shard_raw(iso2, k):
                if r[0] == gid:
                    c = self._city(meta["admin1"], r)
                    c["_ll"], c["_ascii"] = (r[6], r[7]), r[2]
                    return self._identity(iso2, c)
        return None

    def match_city(self, iso2: str, name: str) -> Optional[dict]:
        """이름(영문·ASCII·한국어, 띄어쓰기 무시)이 정확히 같은 도시 중 인구가 가장 많은 곳. 없으면 None."""
        iso2, k = (iso2 or "").strip().upper(), _norm(ko_label(name))
        if not ISO2.match(iso2) or not k:
            return None
        try:
            rows = self._load_cities(iso2)                 # 인구 내림차순이라 처음 맞는 것이 가장 큰 도시
        except GeoError:
            return None
        for c in rows:
            if k in c["_k"]:
                return self._identity(iso2, c)
        return None

    # -------------------------------------------------------------- 도시
    @staticmethod
    def _city(admin1: dict, r: list) -> dict:
        # r = [geonameid, name, asciiname, ko, admin1, population, lat, lon, fcode]
        ko = ko_label(r[3])
        return {"id": r[0], "name": r[1], "ko": ko, "label": ko or r[1], "region": admin1.get(r[4], ""),
                "population": r[5], "capital": r[8] == "PPLC"}

    def _shard_raw(self, iso2: str, k: int) -> list[list]:
        key = (iso2, k)
        with self._lock:
            hit = self._shards.get(key)
            if hit and self._now() - hit[0] < TTL:
                self._shards.move_to_end(key)
                return hit[1]
        doc = self._fetch("geo_cities/%s_%03d" % (iso2, k))
        raw = _plain(_fields(doc).get("data") or {})
        if not raw:
            raise GeoError(503, "geo_empty")
        rows = json.loads(gzip.decompress(base64.b64decode(raw)))
        with self._lock:
            self._shards[key] = (self._now(), rows)
            self._shards.move_to_end(key)
            self._shard_len[key] = (self._now(), len(rows))
            while len(self._shards) > MAX_SHARDS_CACHED:
                self._shards.popitem(last=False)
        return rows

    def _shard_count(self, iso2: str, k: int) -> int:
        with self._lock:
            hit = self._shard_len.get((iso2, k))
            if hit and self._now() - hit[0] < TTL:
                return hit[1]
        return len(self._shard_raw(iso2, k))

    def browse(self, iso2: str, offset: int = 0, limit: int = 500) -> tuple[list[dict], int]:
        """빈 칸 목록: 인구순 전체를 offset 부터 limit 줄. (줄, 전체 개수) — 생략 없이 끝까지 넘길 수 있다."""
        meta = self.country(iso2)
        limit = max(1, min(int(limit or 1), MAX_CITY_LIMIT))
        offset = max(0, int(offset or 0))
        out: list[dict] = []
        pos = offset
        for k in range(meta["shards"]):
            if len(out) >= limit:
                break
            n = self._shard_count(iso2, k)
            if pos >= n:
                pos -= n
                continue
            rows = self._shard_raw(iso2, k)
            out += [self._city(meta["admin1"], r) for r in rows[pos:pos + limit - len(out)]]
            pos = 0
        return out, max(meta["city_count"], offset + len(out))

    def _load_cities(self, iso2: str) -> list[dict]:
        with self._lock:
            hit = self._cities.get(iso2)
            if hit and self._now() - hit[0] < TTL:
                self._cities.move_to_end(iso2)
                return hit[1]
        meta = self.country(iso2)
        if not meta["shards"]:
            return []
        rows = self._shard_raw(iso2, 0)[:MAX_CITIES_PER_COUNTRY]
        admin1 = meta["admin1"]
        cities = []
        for r in rows:
            c = self._city(admin1, r)
            c["_k"] = (_norm(r[1]), _norm(r[2]), _norm(c["ko"]))
            c["_ll"] = (r[6], r[7])                        # 좌표·ASCII 이름은 응답에 안 나간다('_' 키는 걷어 낸다) — 조사 단계가 쓴다
            c["_ascii"] = r[2]
            cities.append(c)
        with self._lock:
            self._cities[iso2] = (self._now(), cities)
            self._cities.move_to_end(iso2)
            while len(self._cities) > MAX_COUNTRIES_CACHED:
                self._cities.popitem(last=False)
        return cities

    def cities_page(self, iso2: str, q: str = "", limit: int = 20, offset: int = 0) -> tuple[list[dict], int]:
        """(고른 목록, 조건에 맞는 전체 개수). 목록이 잘렸는지 화면이 알 수 있어야 한다.
        검색어가 없으면 browse — 첫 샤드만이 아니라 그 나라 전체를 쪽으로 준다."""
        iso2 = (iso2 or "").strip().upper()
        if not ISO2.match(iso2):
            raise GeoError(400, "bad_country")
        limit = max(1, min(int(limit or 20), MAX_CITY_LIMIT))
        needle = _norm(q)[:60]
        if not needle:
            return self.browse(iso2, offset, limit)
        first, second = [], []
        for c in self._load_cities(iso2):
            keys = c["_k"]
            if any(k.startswith(needle) for k in keys if k):
                first.append(c)
            elif any(needle in k for k in keys if k):
                second.append(c)
        matched = first + second                                     # 행이 이미 인구순이라 각 묶음 안에서도 인구순
        offset = max(0, int(offset or 0))
        return [{k: v for k, v in c.items() if not k.startswith("_")} for c in matched[offset:offset + limit]], len(matched)

    def cities(self, iso2: str, q: str = "", limit: int = 20) -> list[dict]:
        iso2 = (iso2 or "").strip().upper()
        if not ISO2.match(iso2):
            raise GeoError(400, "bad_country")
        limit = max(1, min(int(limit or 20), MAX_CITY_LIMIT))
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
    return {"countries": [{k: v for k, v in c.items() if k not in ("admin1", "shards", "city_count")} for c in STORE.countries()],
            "attribution": ATTRIBUTION}


def cities_payload(country: str, q: str, limit: int, offset: int = 0) -> dict:
    picked, total = STORE.cities_page(country, q, limit, offset)
    return {"country": (country or "").strip().upper(), "cities": picked, "total": total,
            "attribution": ATTRIBUTION}
