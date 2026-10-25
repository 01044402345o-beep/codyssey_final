"""조사 에이전트 부품 — 파서·HTTP·소스·캐시·정체성. 네트워크 없음.  실행: cd backend && python -m unittest discover -s tests -t ."""
import base64
import datetime as dt
import gzip
import json
import os
import unittest
from unittest import mock

from app.research import cache as rcache
from app.research import identity, net
from app.research import wikivoyage_parse as wp
from app.research.sources import frankfurter, openmeteo, wikidata, wikivoyage
from tests.research_fakes import CHIYODA_WT, TOKYO_WT, FakeServer, FakeStore, trip

ENV = {"RESEARCH_ENABLED": "1", "RESEARCH_SOURCES": ""}


def http(server=None):
    return net.SafeHttp(transport=server or FakeServer(), sleep=lambda s: None)


class ParseTest(unittest.TestCase):
    def test_listings_clean_nested_templates_links_and_bad_values(self):
        ls = wp.listings(TOKYO_WT, "Tokyo")
        go = next(x for x in ls if x["type"] == "go")
        self.assertEqual((go["name"], go["alt"], go["content"]), ("Haneda Airport", "HND", "Main airport, 14 km south."))
        tower = next(x for x in ls if x["type"] == "see")
        self.assertEqual((tower["lat"], tower["lon"], tower["wikidata"], tower["section"]), (35.6586, 139.7454, "Q131478", "See"))
        self.assertEqual(tower["content"], "Iconic tower with views. See more.")          # HTML·링크·URL 제거
        self.assertEqual(tower["url"], "https://www.tokyotower.co.jp/")
        eat = wp.listings("* {{listing| type=eat | name=X | url=javascript:alert(1) | lat=abc}}")[0]
        self.assertEqual((eat["type"], eat["url"], eat["lat"]), ("eat", "", None))      # type=eat · 위험한 url · 숫자 아님
        self.assertEqual(wp.listings("{{see| alt=no name}}"), [])

    def test_sections_districts_prose(self):
        titles = [t for t, _ in wp.sections(TOKYO_WT)]
        self.assertEqual(titles[:4], ["", "Districts", "Talk", "Get in"])
        self.assertEqual(wp.districts(TOKYO_WT, "Tokyo"), ["Tokyo/Chiyoda", "Tokyo/Chuo"])
        self.assertEqual(wp.districts(TOKYO_WT, "Tokyo", limit=3)[-1], "Tokyo/Minato")
        body = dict(wp.sections(TOKYO_WT))["Get in"]
        self.assertEqual(wp.prose(body), "")                                          # 템플릿 블록만 있는 섹션
        self.assertIn("arigatou", wp.prose(dict(wp.sections(TOKYO_WT))["Talk"]))

    def test_clean_strips_control_chars_and_caps(self):
        self.assertEqual(wp.clean("a\x00b <script>x</script> http://evil.example/p c"), "a b x c")
        out = wp.clean("word " * 200, 30)
        self.assertTrue(out.endswith("…") and len(out) <= 31)


class NetTest(unittest.TestCase):
    def test_only_allowlisted_https_hosts(self):
        srv = FakeServer()
        h = http(srv)
        for url in ("http://en.wikivoyage.org/w/api.php", "https://evil.example/x", "https://user:pw@en.wikivoyage.org/",
                    "https://en.wikivoyage.org:8443/x", "file:///etc/passwd", "https://169.254.169.254/latest"):
            self.assertEqual(h.request("GET", url).error, "host_not_allowed", url)
        self.assertEqual(srv.calls, [])

    def test_retry_once_on_5xx_and_short_429_then_give_up(self):
        seq = [(503, b"", {}), (200, b'{"ok":1}', {})]
        h = net.SafeHttp(transport=lambda *a: seq.pop(0), sleep=lambda s: None)
        self.assertEqual(h.get_json("https://api.frankfurter.dev/v2/rates")[1], {"ok": 1})
        slept = []
        seq2 = [(429, b"", {"retry-after": "2"}), (429, b"", {"retry-after": "2"})]
        h2 = net.SafeHttp(transport=lambda *a: seq2.pop(0), sleep=slept.append)
        res = h2.request("GET", "https://api.frankfurter.dev/x")
        self.assertEqual((res.status, net.status_of(res), slept), (429, "rate_limited", [2.0]))
        seq3 = [(429, b"", {"retry-after": "120"})]
        self.assertEqual(net.SafeHttp(transport=lambda *a: seq3.pop(0), sleep=slept.append)
                         .request("GET", "https://api.frankfurter.dev/x").status, 429)   # 긴 Retry-After 는 기다리지 않는다

    def test_size_cap_timeout_and_redaction(self):
        big = net.SafeHttp(transport=lambda *a: (200, b"x" * (net.MAX_BYTES + 1), {}), sleep=lambda s: None)
        self.assertEqual(big.request("GET", "https://api.frankfurter.dev/x").error, "too_large")

        def boom(*a):
            raise TimeoutError()
        self.assertEqual(net.SafeHttp(transport=boom, sleep=lambda s: None).request("GET", "https://api.frankfurter.dev/x").error, "timeout")
        self.assertEqual(net.redact("https://api.geoapify.com/v2/places?apiKey=SECRET&x=1"), "https://api.geoapify.com/v2/places?apiKey=***&x=1")

    def test_allowlist_has_exactly_the_hosts_we_call(self):
        self.assertEqual(net.ALLOWED_HOSTS, frozenset({
            "en.wikivoyage.org", "query.wikidata.org", "ko.wikipedia.org", "en.wikipedia.org", "www.wikidata.org",
            "api.open-meteo.com", "archive-api.open-meteo.com", "api.frankfurter.dev",
            "api.geoapify.com", "api.tavily.com", "places.googleapis.com", "overpass-api.de"}))

    def test_user_agent_names_app_and_contact(self):
        seen = {}
        net.SafeHttp(transport=lambda m, u, b, h, t: (seen.update(h), (200, b"{}", {}))[1]).request("GET", "https://api.frankfurter.dev/x")
        self.assertTrue(seen["User-Agent"].startswith("MADI-TravelEnglish/1.0 (https://"))
        with mock.patch.dict(os.environ, {"WIKIMEDIA_CONTACT": "ops(at)x.dev\r\nX: y"}):
            self.assertNotIn("\n", net.config.user_agent())


@mock.patch.dict(os.environ, ENV)
class SourcesTest(unittest.TestCase):
    def test_wikidata_bridge_and_country_facts_filter_values(self):
        b = wikidata.city_bridge(http(), 1850147)
        self.assertEqual(b["data"], {"qid": "Q1490", "wikivoyage": "Tokyo (prefecture)"})
        self.assertEqual(wikidata.city_bridge(http(), 999)["status"], "empty")
        f = wikidata.country_facts(http(), "JP")["data"]
        self.assertEqual((f["currency"], f["emergency"], f["voltage"], f["driving_side"]), ("JPY", ["110", "119"], "100", "left"))
        self.assertEqual(wikidata.country_facts(http(), "jp")["status"], "empty")       # ISO2 형식 아님 → 질의 안 함
        # 통화: 본토(지역 한정·끝난 진술 제외) → 보정 표 → 아무 통화
        self.assertEqual(wikidata.pick_currency("FR", "EUR", "EUR|XPF"), "EUR")
        self.assertEqual(wikidata.pick_currency("NL", "", "AWG|EUR|USD"), "EUR")
        self.assertEqual(wikidata.pick_currency("CZ", "203|CZK", "CZK"), "CZK")
        self.assertEqual(wikidata.pick_currency("XX", "", "<x>|ABC"), "ABC")
        self.assertEqual(wikidata.pick_currency("XX", "", ""), "")

    def test_wikivoyage_picks_richer_article_and_reads_two_districts(self):
        srv = FakeServer()
        r = wikivoyage.fetch(http(srv), ["Tokyo (prefecture)", "Tokyo"])
        d = r["data"]
        self.assertEqual((r["status"], d["title"], d["pages"]), ("ok", "Tokyo", ["Tokyo", "Tokyo/Chiyoda", "Tokyo/Chuo"]))
        self.assertIn("Imperial Palace", [x["name"] for x in d["listings"]])
        self.assertEqual(set(d["sections"]), {"Talk", "Get around", "Eat", "Stay safe"})
        self.assertEqual(len(srv.calls), 2)                                           # 본문 + 구역 2개를 한 번에
        same = wikivoyage.fetch(http(), ["Tokyo"], known_revid=1005)
        self.assertTrue(same["data"]["unchanged"])
        self.assertEqual(wikivoyage.fetch(http(), ["Nowhere"])["status"], "empty")
        self.assertEqual(wikivoyage.fetch(http(FakeServer(fail={"wikivoyage": 429})), ["Tokyo"])["status"], "rate_limited")

    def test_openmeteo_forecast_soon_normals_otherwise_with_new_year_wrap(self):
        today = dt.date(2026, 10, 25)
        fc = openmeteo.climate(http(), 35.6, 139.7, "2026-10-28", "2026-10-31", today)["data"]
        self.assertEqual((fc["kind"], fc["tmax_avg"], fc["wet_days_pct"]), ("forecast", 20.0, 100))
        srv = FakeServer()
        nm = openmeteo.climate(http(srv), 35.6, 139.7, "2026-12-30", "2027-01-02", today)["data"]
        self.assertEqual((nm["kind"], nm["days"]), ("normals", 20))                   # 4일 × 5해, 연말을 넘는 창
        self.assertIn("start_date=2021-01-01", srv.calls[0])
        self.assertEqual(openmeteo.climate(http(), None, None, "2027-01-01", "2027-01-02", today)["status"], "empty")

    def test_frankfurter_rate_and_unsupported_currency(self):
        self.assertEqual(frankfurter.krw_rate(http(), "JPY")["data"], {"currency": "JPY", "krw_per_unit": 8.43, "as_of": "2026-10-25"})
        self.assertEqual(frankfurter.krw_rate(http(), "XYZ")["status"], "empty")
        self.assertEqual(frankfurter.krw_rate(http(), "KRW")["reason"], "same_currency")

    def test_sources_can_be_switched_off(self):
        srv = FakeServer()
        with mock.patch.dict(os.environ, {"RESEARCH_SOURCES": "wikidata"}):
            self.assertEqual(wikivoyage.fetch(http(srv), ["Tokyo"])["status"], "disabled")
            self.assertEqual(openmeteo.climate(http(srv), 35.6, 139.7, "2027-03-20", "2027-03-22")["status"], "disabled")
        self.assertEqual(srv.calls, [])


class FakeFirestore:
    def __init__(self):
        self.docs, self.calls = {}, []

    def __call__(self, method, path, body=None):
        self.calls.append((method, path))
        if method == "PATCH":
            self.docs[path] = body
            return body
        return self.docs.get(path, {})


class CacheTest(unittest.TestCase):
    def test_round_trip_ttl_schema_and_size_guard(self):
        clock = [1000.0]
        fs = FakeFirestore()
        c = rcache.ResearchCache(fetch=fs, now=lambda: clock[0], memory_max=0)
        self.assertTrue(c.put("research_cities", "JP_1850147", "guide", {"a": "도쿄"}, 60, [{"provider": "wikivoyage", "status": "ok"}]))
        doc = fs.docs["research_cities/JP_1850147/sections/guide"]["fields"]
        self.assertEqual(json.loads(gzip.decompress(base64.b64decode(doc["data"]["bytesValue"]))), {"a": "도쿄"})
        self.assertIn("expire_at", doc)
        self.assertEqual(c.get("research_cities", "JP_1850147", "guide")["data"], {"a": "도쿄"})
        clock[0] += 61
        self.assertIsNone(c.get("research_cities", "JP_1850147", "guide"))            # TTL 지남
        c.put("research_cities", "JP_1850147", "guide", {"a": 1}, 60, [])
        fs.docs["research_cities/JP_1850147/sections/guide"]["fields"]["schema"] = {"integerValue": "0"}
        self.assertIsNone(c.get("research_cities", "JP_1850147", "guide"))            # 스키마가 다르면 없는 것
        big = os.urandom(1_000_000).hex()
        self.assertFalse(c.put("research_cities", "JP_1", "guide", {"x": big}, 60, []))

    def test_paths_are_validated_and_memory_fallback(self):
        c = rcache.ResearchCache(use_firestore=False)
        for bad in (("users", "JP_1", "guide"), ("research_cities", "../users/x", "guide"), ("research_cities", "JP_1", "a/b")):
            with self.assertRaises(ValueError):
                c.get(*bad)
        c.put("research_countries", "JP", "facts", {"currency": "JPY"}, 60, [])
        self.assertEqual(c.get("research_countries", "JP", "facts")["data"]["currency"], "JPY")

    def test_read_or_write_failure_is_not_fatal(self):
        def broken(*a, **k):
            raise RuntimeError("firestore down")
        c = rcache.ResearchCache(fetch=broken, memory_max=0)
        self.assertIsNone(c.get("research_cities", "JP_1", "guide"))
        self.assertFalse(c.put("research_cities", "JP_1", "guide", {}, 60, []))


class IdentityTest(unittest.TestCase):
    def test_resolve_by_gid_then_name_then_unresolved(self):
        req = trip()
        req["countries"].append({"name": "프랑스"})
        req["cities"].append({"name": "Atlantis", "ci": 1, "start": "2027-03-26", "end": "2027-03-28"})
        got = identity.resolve(FakeStore(), req)
        self.assertEqual([c["iso2"] for c in got["countries"]], ["JP", "FR"])         # ISO2 없이 한국어 이름으로
        tokyo, osaka, atl = (c["ref"] for c in got["cities"])
        self.assertEqual((tokyo["key"], tokyo["lat"], tokyo["resolved"]), ("JP_1850147", 35.6895, True))
        self.assertTrue(osaka["resolved"])
        self.assertFalse(atl["resolved"])
        self.assertRegex(atl["key"], r"^FR_n[0-9a-f]{12}$")
        by_name = identity.resolve(FakeStore(), trip(cities=[{"name": "오사카", "ci": 0, "start": "2027-03-23", "end": "2027-03-24"}]))
        self.assertEqual(by_name["cities"][0]["ref"]["key"], "JP_1853909")             # gid 없이 이름으로

    def test_country_iso2_is_trusted_when_geo_store_is_down(self):
        from app.geo import GeoError

        class Down(FakeStore):
            def country(self, iso2):
                raise GeoError(503, "geo_unavailable")

            def city_by_id(self, iso2, gid):
                raise GeoError(503, "geo_unavailable")
        got = identity.resolve(Down(), trip())
        self.assertEqual(got["countries"][0]["iso2"], "JP")                              # 나라 조사는 계속
        self.assertFalse(got["cities"][0]["ref"]["resolved"])                            # 도시는 이름으로
        self.assertEqual(identity.resolve(FakeStore(), trip(countries=[{"name": "x", "iso2": "ZZ"}]))["countries"][0]["iso2"], "")

    def test_day_roles_and_cross_border(self):
        req = trip()
        req["countries"].append({"name": "프랑스", "iso2": "FR"})
        req["cities"].append({"name": "Paris", "ci": 1, "start": "2027-03-26", "end": "2027-03-28"})
        cities = identity.resolve(FakeStore(), req)["cities"]
        self.assertEqual([r["role"] for r in cities[0]["roles"]], ["arrival", "stay", "stay", "transfer_out"])
        self.assertEqual([r["role"] for r in cities[1]["roles"]], ["transfer_in", "stay", "stay", "transfer_out"])
        self.assertEqual([r["role"] for r in cities[2]["roles"]], ["transfer_in", "stay", "departure"])
        self.assertEqual([c["cross_border_next"] for c in cities], [False, True, False])
        self.assertEqual(cities[0]["nights"], 3)


if __name__ == "__main__":
    unittest.main()
