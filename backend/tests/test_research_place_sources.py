"""대체 장소 소스(Wikidata 주변 명소 + 위키백과 설명, OSM Overpass)와 이름만 있는 도시 보강 — 네트워크 없음."""
import datetime as dt
import os
import unittest
import urllib.parse
from unittest import mock

from app.research import chain, graph, identity, net, nodes
from app.research.cache import ResearchCache
from app.research.sources import overpass, wikidata, wikidata_places
from tests.research_fakes import FakeServer, FakeStore, trip

ENV = {"RESEARCH_ENABLED": "1", "RESEARCH_SOURCES": "", "RESEARCH_LLM": "0", "RESEARCH_PLACE_CHAIN": "wikidata_places,google"}
TODAY = dt.date(2026, 10, 25)
NARA = {"lat": 34.685, "lon": 135.805, "population": 367353}


def http(srv):
    return net.SafeHttp(transport=srv, sleep=lambda s: None)


@mock.patch.dict(os.environ, ENV)
class WikidataPlacesTest(unittest.TestCase):
    def test_nearby_attractions_with_wikipedia_descriptions(self):
        srv = FakeServer()
        r = wikidata_places.fetch(http(srv), NARA, "JP_1855612")
        self.assertEqual(r["status"], "ok")
        names = [p["name"] for p in r["data"]]
        self.assertEqual(names, ["Tōdai-ji", "Nara Park", "나라 국립 박물관"])          # 중복·50km 밖·주입 이름은 버림, 인지도 순
        todai = r["data"][0]
        self.assertEqual((todai["id"], todai["kind"], todai["wikidata"], todai["provider"]),
                         ("wd:JP_1855612:Q186148", "attraction", "Q186148", "wikidata"))
        self.assertEqual(todai["desc_en"], "Tōdai-ji is a Buddhist temple complex. It houses a giant Buddha.")  # 리다이렉트 뒤 설명
        self.assertEqual(r["data"][1]["desc_en"], "park in Nara")                                # 위키백과 설명 없으면 짧은 설명
        self.assertEqual([s["provider"] for s in todai["sources"]], ["wikidata", "wikipedia"])
        self.assertEqual(todai["homepage"], "https://www.todaiji.or.jp/")
        q = urllib.parse.parse_qs(urllib.parse.urlparse(srv.calls[0]).query)["query"][0]
        self.assertIn('Point(135.80500 34.68500)', q)
        self.assertIn('"6.0"', q)                                                                 # 인구 20만+ → 반경 6km

    def test_no_coords_rate_limit_and_switch(self):
        self.assertEqual(wikidata_places.fetch(http(FakeServer()), {"lat": None, "lon": None}, "JP_n1")["reason"], "no_coords")
        self.assertEqual(wikidata_places.fetch(http(FakeServer(fail={"query.wikidata.org": 429})), NARA, "k")["status"], "rate_limited")
        with mock.patch.dict(os.environ, {"RESEARCH_SOURCES": "wikivoyage"}):
            self.assertEqual(wikidata_places.fetch(http(FakeServer()), NARA, "k")["status"], "disabled")

    def test_adapter_skips_when_attractions_are_not_needed(self):
        srv = FakeServer()
        deps = type("D", (), {"http": http(srv)})()
        tc = {"ref": {**NARA, "key": "JP_1855612"}}
        self.assertEqual(wikidata_places.adapter(deps, tc, {"attraction": 0, "food": 3})["reason"], "not_needed")
        self.assertEqual(srv.calls, [])


@mock.patch.dict(os.environ, ENV)
class OverpassTest(unittest.TestCase):
    def test_parse_rank_and_describe(self):
        srv = FakeServer()
        r = overpass.fetch(http(srv), NARA, "JP_1855612", {"attraction": 2, "food": 2})
        self.assertEqual(r["status"], "ok")
        got = [(p["name"], p["kind"]) for p in r["data"]]
        self.assertEqual(got[0], ("Kakinoha Sushi", "restaurant"))                               # 영어 이름·wikidata·영업시간 → 앞
        self.assertIn(("Nara Museum", "attraction"), got)
        self.assertIn(("Plain Cafe", "cafe"), got)
        self.assertEqual(len(got), 3)                                                            # 이름 없음·주입 이름 버림
        k = r["data"][0]
        self.assertEqual(k["desc_en"], "Cuisine: sushi, japanese. Opening hours (OpenStreetMap): 10:00-19:00.")
        self.assertEqual((k["name_local"], k["wikidata"], k["sources"][0]["url"]),
                         ("柿の葉寿司", "Q55", "https://www.openstreetmap.org/node/2"))
        self.assertEqual(k["sources"][0]["license"], "ODbL 1.0")

    def test_asks_only_needed_kinds_and_reports_outage(self):
        seen = []

        def srv(method, url, body, headers, timeout):
            seen.append(urllib.parse.parse_qs(body.decode())["data"][0])
            return 502, b"", {}
        r = overpass.fetch(http(srv), NARA, "k", {"attraction": 0, "food": 3})
        self.assertEqual(r["status"], "unavailable")
        self.assertIn('"amenity"', seen[0])
        self.assertNotIn('"tourism"', seen[0])

    def test_off_by_default_in_chain(self):
        with mock.patch.dict(os.environ, {"RESEARCH_PLACE_CHAIN": ""}):
            self.assertNotIn("overpass", chain.active())                                     # 공용 서버 정책·포화(10/26) → 기본 끔
        with mock.patch.dict(os.environ, {"RESEARCH_PLACE_CHAIN": "wikidata_places,overpass"}):
            self.assertEqual(chain.active(), ["wikidata_places", "overpass"])


@mock.patch.dict(os.environ, ENV)
class UnresolvedCityTest(unittest.TestCase):
    def deps(self, srv):
        return nodes.Deps(http=http(srv), cache=ResearchCache(use_firestore=False), store=FakeStore(), today=TODAY, llm_on=False)

    def test_name_only_city_gets_coords_once(self):
        srv = FakeServer()
        d = self.deps(srv)
        req = trip(cities=[{"name": "가마쿠라", "ci": 0, "start": "2027-03-20", "end": "2027-03-22", "attr": 2, "rest": 2}])
        resolved = identity.resolve(FakeStore(), req)
        self.assertIsNone(resolved["cities"][0]["ref"]["lat"])
        nodes.enrich_unresolved(d, resolved)
        ref = resolved["cities"][0]["ref"]
        self.assertEqual((round(ref["lat"], 3), ref["name"], ref["ascii"], ref["wv_title"], ref["resolved"]),
                         (35.319, "Kamakura", "Kamakura", "Kamakura", False))
        self.assertTrue(ref["key"].startswith("JP_n"))                                          # gid 키와 섞지 않는다
        n = len(srv.calls)
        again = identity.resolve(FakeStore(), req)
        nodes.enrich_unresolved(d, again)
        self.assertEqual((len(srv.calls), again["cities"][0]["ref"]["name"]), (n, "Kamakura"))   # 두 번째는 캐시
        self.assertIsNotNone(d.cache.get("research_countries", "JP", "facts"))                    # 나라 사실도 캐시(뒤 단계가 재사용)

    def test_cache_only_mode_reports_pending_without_network(self):
        srv = FakeServer()
        d = self.deps(srv)
        req = trip(cities=[{"name": "가마쿠라", "ci": 0, "start": "2027-03-20", "end": "2027-03-22", "attr": 2, "rest": 2}])
        resolved = identity.resolve(FakeStore(), req)
        self.assertEqual(nodes.enrich_unresolved(d, resolved, network=False), [resolved["cities"][0]["ref"]["key"]])
        self.assertEqual(srv.calls, [])

    def test_submit_looks_up_inside_the_job(self):
        from app.research import service
        import threading
        srv, on_main = FakeServer(), []

        def transport(*a):
            on_main.append(threading.current_thread() is threading.main_thread())
            return srv(*a)
        req = trip(cities=[{"name": "가마쿠라", "ci": 0, "start": "2027-03-20", "end": "2027-03-22", "attr": 2, "rest": 2}])
        with mock.patch.dict(os.environ, {"RESEARCH_PLACE_CHAIN": "none"}):
            out = service.submit(req, "1.2.3.4", http=http(transport), cache=ResearchCache(use_firestore=False), store=FakeStore(),
                                 today=TODAY)
            self.assertEqual(out["status"], "running")
            import time
            for _ in range(200):
                got = service.poll(out["job_id"])
                if got and got["status"] != "running":
                    break
                time.sleep(0.02)
        self.assertTrue(on_main and not any(on_main))                                             # 조회는 모두 잡 스레드에서(POST 를 늦추지 않음)
        city = got["report"]["cities"][0]
        self.assertEqual((city["name"], city["wikivoyage"]["title"]), ("Kamakura", ""))          # 가짜 위키보이지엔 문서 없음
        self.assertIsNotNone(city["climate"])                                                     # 좌표가 생겨 날씨까지 조사

    def test_unsafe_name_is_not_queried(self):
        srv = FakeServer()
        self.assertEqual(wikidata.city_by_name(http(srv), "Q17", 'x" } DROP')["reason"], "bad_input")
        self.assertEqual(wikidata.city_by_name(http(srv), "JP", "가마쿠라")["reason"], "bad_input")         # 나라 id 형식
        self.assertEqual(srv.calls, [])


@mock.patch.dict(os.environ, ENV)
class DefaultChainGraphTest(unittest.TestCase):
    def setUp(self):
        self.health = chain.Health()
        self.p = mock.patch.object(chain, "HEALTH", self.health)
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def test_nara_without_wikivoyage_gets_wikidata_places_and_credits(self):
        srv = FakeServer()
        d = nodes.Deps(http=http(srv), cache=ResearchCache(use_firestore=False), store=FakeStore(), today=TODAY, llm_on=False)
        req = trip(cities=[{"name": "나라", "gid": 1855612, "ci": 0, "start": "2027-03-20", "end": "2027-03-22", "attr": 2, "rest": 2}])
        rep = graph.run(d, identity.resolve(FakeStore(), req))
        nara = rep["cities"][0]
        self.assertEqual([p["name"] for p in nara["places"]], ["Tōdai-ji", "Nara Park", "나라 국립 박물관"])
        self.assertEqual((nara["place_status"], nara["chain"]["wikidata_places"]["outcome"]), ("thin", "ok"))  # 식당은 아직 0
        self.assertFalse(any("overpass-api.de" in c for c in srv.calls))
        self.assertTrue({"wikidata", "wikipedia"} <= {a["provider"] for a in rep["attributions"]})


if __name__ == "__main__":
    unittest.main()
