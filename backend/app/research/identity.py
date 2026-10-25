"""여행 입력 → 조사할 나라·도시(정체성)와 날짜별 역할.

도시: GeoNames id(gid) → 이름 일치 → 미해결(이름만으로 조사, 좌표 없음).
날짜 역할: 첫 도시 시작일 = 도착, 마지막 도시 종료일 = 출국, 도시 사이 경계일 = 이동(나라가 바뀌면 국경 이동).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re
from typing import Any, Optional

from ..geo import GeoError, ko_label

ROLE_ARRIVAL, ROLE_STAY, ROLE_OUT, ROLE_IN, ROLE_DEPART = "arrival", "stay", "transfer_out", "transfer_in", "departure"


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", (s or "").casefold())


def city_key(iso2: str, gid: Optional[int], name: str) -> str:
    """캐시 키. 해석된 도시는 ISO2_gid, 아니면 ISO2_n<이름 해시>(gid 키와 절대 섞이지 않는다)."""
    cc = iso2 if re.fullmatch(r"[A-Z]{2}", iso2 or "") else "XX"
    if gid:
        return f"{cc}_{gid}"
    return f"{cc}_n" + hashlib.sha1(_norm(ko_label(name)).encode("utf-8")).hexdigest()[:12]


def _country(store: Any, raw: dict) -> dict:
    name, iso2 = str(raw.get("name") or "").strip(), str(raw.get("iso2") or "").strip().upper()
    meta = None
    try:
        if re.fullmatch(r"[A-Z]{2}", iso2):
            meta = store.country(iso2)
        if meta is None:
            meta = store.country_by_name(name)
    except GeoError as exc:
        # 국가 목록(Firestore)을 못 읽어도 화면이 보낸 ISO2 는 믿는다 — 나라 조사(통화·권고)는 ISO2 만 있으면 된다.
        # 모르는 코드(404)는 버린다.
        meta = {"iso2": iso2, "name": name, "ko": ""} if exc.status != 404 and re.fullmatch(r"[A-Z]{2}", iso2) else None
    if not meta:
        return {"name": name, "iso2": "", "name_en": name, "ko": "", "resolved": False}
    return {"name": name, "iso2": meta["iso2"], "name_en": meta.get("name") or name, "ko": meta.get("ko") or "",
            "resolved": True}


def _city(store: Any, raw: dict, country: dict) -> dict:
    name = str(raw.get("name") or "").strip()
    gid = raw.get("gid") if type(raw.get("gid")) is int else None
    iso2 = country["iso2"]
    found = None
    try:
        if iso2 and gid:
            found = store.city_by_id(iso2, gid)
        if iso2 and not found:
            found = store.match_city(iso2, name)
    except GeoError:
        found = None
    if found:
        return {"key": city_key(iso2, found["gid"], name), "iso2": iso2, "gid": found["gid"], "name": found["name"],
                "ascii": found["ascii"], "ko": found["ko"] or (name if not name.isascii() else ""), "input": name,
                "lat": found["lat"], "lon": found["lon"], "population": found["population"],
                "region": found["region"], "country_name": country["name_en"], "resolved": True}
    return {"key": city_key(iso2, None, name), "iso2": iso2, "gid": None, "name": name,
            "ascii": name if name.isascii() else "", "ko": "" if name.isascii() else name, "input": name,
            "lat": None, "lon": None, "population": 0, "region": "", "country_name": country["name_en"],
            "resolved": False}


def _dates(start: str, end: str) -> list[str]:
    s, e = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    out, d = [], s
    while d <= e and len(out) < 60:
        out.append(d.isoformat())
        d += dt.timedelta(days=1)
    return out


def resolve(store: Any, req: dict) -> dict:
    """req = {countries: [{name, iso2?}], cities: [{name, gid?, ci, start, end, attr, rest}]} → {countries, cities}."""
    countries = [_country(store, c) for c in req.get("countries") or []]
    cities = []
    raw_cities = req.get("cities") or []
    for i, c in enumerate(raw_cities):
        ci = min(max(int(c.get("ci") or 0), 0), max(0, len(countries) - 1))
        ref = _city(store, c, countries[ci] if countries else {"iso2": "", "name_en": ""})
        dates = _dates(c["start"], c["end"])
        nxt = raw_cities[i + 1] if i + 1 < len(raw_cities) else None
        roles = []
        for d in dates:
            if i == 0 and d == c["start"]:
                role = ROLE_ARRIVAL
            elif nxt is None and d == c["end"]:
                role = ROLE_DEPART
            elif i > 0 and d == c["start"]:
                role = ROLE_IN
            elif nxt is not None and d == c["end"]:
                role = ROLE_OUT
            else:
                role = ROLE_STAY
            roles.append({"date": d, "role": role})
        cross = nxt is not None and int(nxt.get("ci") or 0) != ci
        cities.append({"idx": i, "ref": ref, "ci": ci, "start": c["start"], "end": c["end"],
                       "nights": max(0, len(dates) - 1), "caps": {"attr": int(c.get("attr", 2)), "rest": int(c.get("rest", 2))},
                       "roles": roles, "cross_border_next": cross})
    return {"countries": countries, "cities": cities}
