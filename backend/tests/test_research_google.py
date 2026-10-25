"""대체 장소 소스 ③ Google Places 실시간 보충 — 저장하지 않음·캐시 위 실시간·한도·키 없으면 체인에서 빠짐. 네트워크 없음."""
import datetime as dt
import json
import os
import time
import unittest
from unittest import mock

from app.agents import itinerary
from app.research import chain, graph, identity, net, nodes, service
from app.research.cache import ResearchCache
from app.research.sources import google_places
from tests.research_fakes import FakeServer, FakeStore, trip

ENV = {"RESEARCH_ENABLED": "1", "RESEARCH_SOURCES": "", "RESEARCH_LLM": "0", "RESEARCH_PLACE_CHAIN": "wikidata_places,google",
       "GOOGLE_MAPS_API_KEY": "test-key-not-real", "ITINERARY_DAILY_CAP": "50"}
TODAY = dt.date(2026, 10, 25)
NARA_REQ = trip(cities=[{"name": "나라", "gid": 1855612, "ci": 0, "start": "2027-03-20", "end": "2027-03-22", "attr": 2, "rest": 2}])


def http(srv):
    return net.SafeHttp(transport=srv, sleep=lambda s: None)


@mock.patch.dict(os.environ, ENV)
class GoogleSourceTest(unittest.TestCase):
    def setUp(self):
        itinerary.reset_daily_cap()

    def test_queries_needed_kinds_with_location_bias(self):
        srv = FakeServer()
        ref = {"name": "Nara", "country_name": "Japan", "lat": 34.685, "lon": 135.805, "population": 367353}
        r = google_places.fetch(http(srv), ref, "JP_1855612", {"attraction": 0, "food": 3})
        self.assertEqual(r["status"], "ok")
        self.assertEqual([b["includedType"] for b in srv.google], ["restaurant", "cafe"])            # 관광지는 묻지 않음
        self.assertEqual(srv.google[0]["textQuery"], "Nara Japan restaurant")
        self.assertEqual(srv.google[0]["locationBias"]["circle"],
                         {"center": {"latitude": 34.685, "longitude": 135.805}, "radius": 6000.0})
        names = [(p["name"], p["kind"], p["provider"], p["live"]) for p in r["data"]]
        self.assertEqual(names[0], ("Kamameshi Shizuka", "restaurant", "google", True))
        self.assertEqual(r["data"][2]["kind"], "cafe")
        self.assertEqual(r["data"][0]["sources"][0], {"provider": "google", "url": "https://maps.google.com/?cid=g1",
                                                     "title": "Kamameshi Shizuka", "license": "Google Maps"})

    def test_key_cap_and_errors(self):
        ref = {"name": "Nara", "lat": 34.685, "lon": 135.805, "population": 1}
        with mock.patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": ""}):
            self.assertEqual(google_places.fetch(http(FakeServer()), ref, "k", {"food": 1})["status"], "disabled")
            self.assertFalse(google_places.available())
        with mock.patch.dict(os.environ, {"ITINERARY_DAILY_CAP": "0"}):
            self.assertEqual(google_places.fetch(http(FakeServer()), ref, "k", {"food": 1})["status"], "capped")
        self.assertEqual(google_places.fetch(http(FakeServer(fail={"places.googleapis.com": 429})), ref, "k", {"food": 1})["status"],
                         "rate_limited")
        self.assertEqual(google_places.fetch(http(FakeServer(fail={"places.googleapis.com": 403})), ref, "k", {"food": 1})["reason"],
                         "http_403")
        self.assertEqual(chain.classify(google_places.fetch(http(FakeServer(fail={"places.googleapis.com": 503})), ref, "k",
                                                            {"food": 1})), "transient")

    def test_without_key_the_chain_skips_google(self):
        self.assertIn("google", chain.active())
        with mock.patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": ""}):
            self.assertNotIn("google", chain.active())


@mock.patch.dict(os.environ, ENV)
class GoogleLiveGraphTest(unittest.TestCase):
    def setUp(self):
        itinerary.reset_daily_cap()
        self.health = chain.Health()
        self.p = mock.patch.object(chain, "HEALTH", self.health)
        self.p.start()
        self.srv = FakeServer()
        self.cache = ResearchCache(use_firestore=False)

    def tearDown(self):
        self.p.stop()

    def deps(self, llm=None, llm_on=False):
        return nodes.Deps(http=http(self.srv), cache=self.cache, store=FakeStore(), today=TODAY, llm=llm, llm_on=llm_on)

    def test_google_fills_food_but_is_never_cached(self):
        rep = graph.run(self.deps(), identity.resolve(FakeStore(), NARA_REQ))
        nara = rep["cities"][0]
        kinds = {p["name"]: p["sources"][0]["provider"] for p in nara["places"]}
        self.assertEqual(kinds["Tōdai-ji"], "wikidata")
        self.assertEqual(kinds["Kamameshi Shizuka"], "google")
        self.assertEqual(nara["place_status"], "ok")                                               # 식당까지 채움
        self.assertEqual(nara["chain"]["google"]["outcome"], "ok")
        key = identity.resolve(FakeStore(), NARA_REQ)["cities"][0]["ref"]["key"]
        stored = json.dumps(self.cache.get("research_cities", key, "places_extra")["data"], ensure_ascii=False)
        self.assertIn("Tōdai-ji", stored)
        self.assertNotIn("Kamameshi", stored)                                                     # Google 결과는 저장 안 함
        self.assertNotIn("maps.google.com", stored)

    def test_cached_report_tops_up_live_and_cache_only_restore_needs_no_network(self):
        graph.run(self.deps(), identity.resolve(FakeStore(), NARA_REQ))
        resolved = identity.resolve(FakeStore(), NARA_REQ)
        plan = nodes.plan(self.deps(), resolved)
        self.assertEqual(plan["cities"][0]["need"], ["live"])                                   # 캐시 + 실시간만 다시
        self.assertFalse(nodes.all_fresh(plan))
        self.assertTrue(nodes.all_fresh(plan, ignore=("live",)))
        n_wikidata = sum("query.wikidata.org" in c for c in self.srv.calls)
        n_google = len(self.srv.google)
        rep = graph.run(self.deps(), resolved, plan)
        self.assertEqual(sum("query.wikidata.org" in c for c in self.srv.calls), n_wikidata)      # 캐시된 소스는 다시 안 부름
        self.assertGreater(len(self.srv.google), n_google)
        self.assertIn("Kamameshi Shizuka", [p["name"] for p in rep["cities"][0]["places"]])
        # 저장된 여행 복원(cache_only): 실시간 보충만 빠졌으면 캐시로 바로 답한다(외부 호출 0)
        before = len(self.srv.calls)
        out = service.submit({**NARA_REQ, "cache_only": True}, "1.2.3.4", http=http(self.srv), cache=self.cache,
                             store=FakeStore(), today=TODAY)
        self.assertEqual((out["status"], len(self.srv.calls)), ("done", before))
        self.assertNotIn("Kamameshi Shizuka", [p["name"] for p in out["report"]["cities"][0]["places"]])

    def test_google_places_stay_out_of_llm_extract(self):
        prompts = []

        def llm(prompt):
            prompts.append(prompt)
            return {"places": [{"id": "wd:JP_1855612:Q186148", "summary_ko": "큰 불상이 있는 절이에요.", "why_ko": ""}], "practical": []}
        rep = graph.run(self.deps(llm=llm, llm_on=True), identity.resolve(FakeStore(), NARA_REQ))
        self.assertTrue(prompts)
        self.assertNotIn("Kamameshi", prompts[0])
        self.assertIn("Tōdai-ji", prompts[0])
        self.assertEqual(rep["cities"][0]["places"][0]["summary_ko"], "큰 불상이 있는 절이에요.")

    def test_no_key_city_is_served_from_cache(self):
        with mock.patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": ""}):
            graph.run(self.deps(), identity.resolve(FakeStore(), NARA_REQ))
            plan = nodes.plan(self.deps(), identity.resolve(FakeStore(), NARA_REQ))
            self.assertTrue(nodes.all_fresh(plan))                                                # 키 없으면 '실시간 필요' 아님
        self.assertEqual(self.srv.google, [])


if __name__ == "__main__":
    unittest.main()
