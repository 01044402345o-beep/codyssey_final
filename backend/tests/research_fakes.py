"""조사 테스트용 가짜 — 네트워크 없이 소스별 응답을 흉내 낸다(호스트·경로로 고른다)."""
import json
import urllib.parse

TOKYO_WT = """{{pagebanner|Tokyo banner.jpg}}
'''Tokyo''' is the capital of [[Japan]].
==Districts==
{{Regionlist
| region1name=[[Tokyo/Chiyoda|Chiyoda]]
| region1description=Palace.
| region2name=[[Tokyo/Chuo|Chuo]]
| region3name=[[Tokyo/Minato|Minato]]
}}
==Talk==
Few people speak English, so learn ''arigatou''.
==Get in==
* {{go| name=[[Haneda Airport]] | alt={{IATA|HND}} | lat=35.55 | long=139.78 | content=Main airport, {{km|14}} south.}}
==Get around==
Trains are punctual. Buy a Suica card at the station.
==See==
* {{see| name=Tokyo Tower | url=https://www.tokyotower.co.jp/ | lat=35.6586 | long=139.7454 | wikidata=Q131478
| content=Iconic [[tower]] with <b>views</b>. See [https://example.com more].}}
==Eat==
Tipping is not customary and may cause confusion. Always carry cash.
==Stay safe==
Tokyo is very safe.
"""
CHIYODA_WT = """==See==
* {{see| name=Imperial Palace | lat=35.6825 | long=139.7521 | content=Home of the Emperor.}}
* {{see| name=Far Away Shrine | lat=36.9 | long=140.9 | content=Not in Tokyo.}}
* {{do| name=Kitanomaru Park | lat=35.691 | long=139.750 | content=Cherry blossoms in spring.}}
==Eat==
* {{eat| name=Sushi Dai | lat=35.665 | long=139.770 | content=Famous sushi breakfast.}}
==Drink==
* {{drink| name=Blue Bottle Coffee | lat=35.67 | long=139.76 | content=Third-wave coffee.}}
* {{drink| name=Bar Night <script> | content=bad name}}
"""
CHUO_WT = """==Eat==
* {{listing| type=eat | name=Tsukiji Outer Market | lat=35.6655 | long=139.7707 | content=Seafood stalls.}}
"""
OSAKA_WT = """==See==
* {{see| name=Osaka Castle | lat=34.6873 | long=135.5259 | content=Famous castle.}}
* {{eat| name=Dotonbori Stalls | lat=34.6687 | long=135.5013 | content=Street food.}}
==Get around==
Use the subway.
"""


def wiki_pages(titles):
    pages = []
    for t in titles:
        text = {"Tokyo": TOKYO_WT, "Tokyo/Chiyoda": CHIYODA_WT, "Tokyo/Chuo": CHUO_WT, "Osaka": OSAKA_WT}.get(t)
        if text is None:
            pages.append({"title": t, "missing": True})
        else:
            pages.append({"title": t, "revisions": [{"revid": 1000 + len(t), "slots": {"main": {"content": text}}}]})
    return {"query": {"pages": pages}}


def sparql(query):
    if "P1566" in query:
        if '"1850147"' in query:
            return {"results": {"bindings": [{"item": {"value": "http://www.wikidata.org/entity/Q1490"},
                                               "wv": {"value": "https://en.wikivoyage.org/wiki/Tokyo_(prefecture)"}}]}}
        if '"1853909"' in query:
            return {"results": {"bindings": [{"item": {"value": "http://www.wikidata.org/entity/Q35765"},
                                               "wv": {"value": "https://en.wikivoyage.org/wiki/Osaka"}}]}}
        return {"results": {"bindings": []}}
    if '"JP"' in query:
        return {"results": {"bindings": [{"country": {"value": "http://www.wikidata.org/entity/Q17"},
                                           "currency": {"value": "JPY"}, "emergency": {"value": "110|119|<x>"},
                                           "drive": {"value": "left"}, "plugs": {"value": "Type A|Type B"},
                                           "voltage": {"value": "100"}, "langs": {"value": "Japanese"}}]}}
    return {"results": {"bindings": []}}


def daily(start, days, tmax=15.0, tmin=5.0, rain=0.0):
    import datetime as dt
    s = dt.date.fromisoformat(start)
    times = [(s + dt.timedelta(days=i)).isoformat() for i in range(days)]
    return {"daily": {"time": times, "temperature_2m_max": [tmax] * days, "temperature_2m_min": [tmin] * days,
                      "precipitation_sum": [rain] * days}}


class FakeServer:
    """transport(method, url, body, headers, timeout) — 실패를 꽂을 수 있다(fail={host_or_path: status})."""

    def __init__(self, fail=None):
        self.fail = fail or {}
        self.calls = []

    def __call__(self, method, url, body, headers, timeout):
        p = urllib.parse.urlparse(url)
        q = urllib.parse.parse_qs(p.query)
        self.calls.append(url)
        for k, status in self.fail.items():
            if k in url:
                return status, b"", {}
        if p.hostname == "en.wikivoyage.org":
            data = wiki_pages(q["titles"][0].split("|"))
        elif p.hostname == "query.wikidata.org":
            data = sparql(q["query"][0])
        elif p.hostname == "api.open-meteo.com":
            data = daily(q["start_date"][0], 4, 20.0, 10.0, 2.0)
        elif p.hostname == "archive-api.open-meteo.com":
            import datetime as dt
            s, e = dt.date.fromisoformat(q["start_date"][0]), dt.date.fromisoformat(q["end_date"][0])
            data = daily(s.isoformat(), (e - s).days + 1)
        elif p.hostname == "api.frankfurter.dev":
            base = q["base"][0]
            if base == "XYZ":
                return 404, b"", {}
            data = [{"date": "2026-10-25", "base": base, "quote": "KRW", "rate": 8.43}]
        else:
            return 404, b"", {}
        return 200, json.dumps(data).encode(), {}


class FakeStore:
    COUNTRIES = {"JP": {"iso2": "JP", "name": "Japan", "ko": "일본"},
                 "FR": {"iso2": "FR", "name": "France", "ko": "프랑스"}}
    CITIES = {("JP", 1850147): {"gid": 1850147, "name": "Tokyo", "ascii": "Tokyo", "ko": "도쿄", "lat": 35.6895,
                                "lon": 139.6917, "population": 8336599, "region": "Tokyo"},
              ("JP", 1853909): {"gid": 1853909, "name": "Osaka", "ascii": "Osaka", "ko": "오사카", "lat": 34.6937,
                                "lon": 135.5022, "population": 2592413, "region": "Osaka"},
              # 위키보이지 문서가 없는 도시(대체 소스 체인 시험용)
              ("JP", 1855612): {"gid": 1855612, "name": "Nara", "ascii": "Nara", "ko": "나라", "lat": 34.685,
                                "lon": 135.805, "population": 367353, "region": "Nara"}}

    def country(self, iso2):
        from app.geo import GeoError
        if iso2 not in self.COUNTRIES:
            raise GeoError(404, "unknown_country")
        return self.COUNTRIES[iso2]

    def country_by_name(self, name):
        n = (name or "").strip().lower()
        return next((c for c in self.COUNTRIES.values() if n in (c["iso2"].lower(), c["ko"], c["name"].lower())), None)

    def city_by_id(self, iso2, gid):
        return self.CITIES.get((iso2, gid))

    def match_city(self, iso2, name):
        return next((c for (cc, _), c in self.CITIES.items() if cc == iso2 and name in (c["name"], c["ko"])), None)


def trip(**over):
    req = {"countries": [{"name": "일본", "iso2": "JP"}],
           "cities": [{"name": "도쿄", "gid": 1850147, "ci": 0, "start": "2027-03-20", "end": "2027-03-23", "attr": 2, "rest": 2},
                      {"name": "오사카", "gid": 1853909, "ci": 0, "start": "2027-03-23", "end": "2027-03-26", "attr": 2, "rest": 2}],
           "cache_only": False}
    req.update(over)
    return req
