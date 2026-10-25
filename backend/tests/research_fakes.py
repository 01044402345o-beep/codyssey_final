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


def _b(**kw):
    return {k: {"value": v} for k, v in kw.items()}


NARA_AROUND = [
    _b(item="http://www.wikidata.org/entity/Q186148", loc="Point(135.8398 34.6890)", en="Tōdai-ji", ko="도다이지",
       desc="Buddhist temple in Nara, Japan", site="https://www.todaiji.or.jp/", wp="https://en.wikipedia.org/wiki/T%C5%8Ddai-ji", links="90"),
    _b(item="http://www.wikidata.org/entity/Q186148", loc="Point(135.8398 34.6890)", en="Tōdai-ji", links="90"),   # 같은 항목(종류 2개)
    _b(item="http://www.wikidata.org/entity/Q1062513", loc="Point(135.8430 34.6851)", en="Nara Park", desc="park in Nara",
       wp="https://en.wikipedia.org/wiki/Nara_Park", links="40"),
    _b(item="http://www.wikidata.org/entity/Q999001", loc="Point(139.70 35.68)", en="Far Shrine", links="30"),      # 50km 밖
    _b(item="http://www.wikidata.org/entity/Q999002", loc="Point(135.80 34.68)", en="<script>x", links="20"),       # 주입 이름
    _b(item="http://www.wikidata.org/entity/Q999003", loc="Point(135.81 34.69)", ko="나라 국립 박물관", links="10"),     # 영어 라벨 없음 → 한국어
]


def sparql(query):
    if "wikibase:around" in query:
        return {"results": {"bindings": NARA_AROUND if "Point(135.805" in query else []}}
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


def _claim(pid, value):
    return {pid: [{"mainsnak": {"datavalue": {"value": value}}}]}


def wikidata_api(q):
    """wbsearchentities / wbgetentities — '가마쿠라' 검색: 첫 결과는 동명 항목(다른 나라), 둘째가 일본의 가마쿠라시."""
    action = q["action"][0]
    if action == "wbsearchentities":
        return {"search": [{"id": "Q900001"}, {"id": "Q200267"}] if q["search"][0] == "가마쿠라" else []}
    ents = {"Q900001": {"claims": {**_claim("P17", {"id": "Q30"}), **_claim("P625", {"latitude": 40.0, "longitude": -75.0})}},
            "Q200267": {"labels": {"en": {"value": "Kamakura"}}, "sitelinks": {"enwikivoyage": {"title": "Kamakura"}},
                        "claims": {**_claim("P17", {"id": "Q17"}), **_claim("P625", {"latitude": 35.3192, "longitude": 139.5466}),
                                   **_claim("P1082", {"amount": "+172302"})}}}
    return {"entities": {i: ents[i] for i in q["ids"][0].split("|") if i in ents}}


OVERPASS = {"elements": [
    {"type": "node", "id": 1, "lat": 34.684, "lon": 135.806, "tags": {"amenity": "cafe", "name": "Plain Cafe"}},
    {"type": "node", "id": 2, "lat": 34.685, "lon": 135.807, "tags": {"amenity": "restaurant", "name": "柿の葉寿司", "name:en": "Kakinoha Sushi",
                                                                      "cuisine": "sushi;japanese", "opening_hours": "10:00-19:00",
                                                                      "website": "https://kakinoha.example/", "wikidata": "Q55"}},
    {"type": "way", "id": 3, "center": {"lat": 34.686, "lon": 135.808}, "tags": {"tourism": "museum", "name": "Nara Museum"}},
    {"type": "node", "id": 4, "lat": 34.684, "lon": 135.806, "tags": {"amenity": "cafe", "name": "Bad <b>"}},
    {"type": "node", "id": 5, "lat": 34.684, "lon": 135.806, "tags": {"amenity": "cafe"}},                              # 이름 없음
]}


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
        elif p.hostname == "www.wikidata.org":
            data = wikidata_api(q)
        elif p.hostname == "en.wikipedia.org":
            titles = q.get("titles", [""])[0].split("|")
            data = {"query": {"redirects": [{"from": "Tōdai-ji", "to": "Tōdai-ji (temple)"}] if "Tōdai-ji" in titles else [],
                              "pages": [{"title": "Tōdai-ji (temple)", "extract": "Tōdai-ji is a Buddhist temple complex. It houses a giant Buddha."}]
                              if "Tōdai-ji" in titles else []}}
        elif p.hostname == "overpass-api.de":
            data = OVERPASS
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
