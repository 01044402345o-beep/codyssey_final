"""후퇴(복구): 옛 지명 → 지금 도시(P7888 통합됨), 좌표 없는 구역 → 상위 구역(P131), 반경 넓혀 다시 찾기. 네트워크 없음."""
import datetime as dt
import os
import unittest
import urllib.parse
from unittest import mock

from app.research import chain, graph, identity, net, nodes, report
from app.research.cache import ResearchCache
from app.research.sources import tourapi, wikidata
from tests.research_fakes import FakeServer, FakeStore

ENV = {"RESEARCH_ENABLED": "1", "RESEARCH_SOURCES": "", "RESEARCH_LLM": "0", "RESEARCH_PLACE_CHAIN": "fake_near",
       "TOURAPI_SERVICE_KEY": ""}
TODAY = dt.date(2026, 10, 25)


def http(srv):
    return net.SafeHttp(transport=srv, sleep=lambda s: None)


def kr_trip(name, gid=None):
    c = {"name": name, "ci": 0, "start": "2027-03-20", "end": "2027-03-22", "attr": 1, "rest": 1}
    if gid:
        c["gid"] = gid
    return {"countries": [{"name": "대한민국", "iso2": "KR"}], "cities": [c]}


@mock.patch.dict(os.environ, ENV)
class OldNameAndParentTest(unittest.TestCase):
    def test_dissolved_county_follows_merged_into(self):
        r = wikidata.city_by_name(http(FakeServer()), "Q884", "옥구군")
        self.assertEqual(r["status"], "ok")
        self.assertEqual((r["data"]["qid"], r["data"]["name_en"], r["data"]["wikivoyage"]), ("Q42074", "Gunsan", "Gunsan"))
        self.assertEqual(r["data"]["via"], {"kind": "merged", "from": "Q16183663", "label": "Gunsan"})

    def test_new_area_without_coords_uses_current_parent(self):
        r = wikidata.city_by_name(http(FakeServer()), "Q884", "새빛동")
        self.assertEqual((r["data"]["qid"], r["data"]["lat"], r["data"]["via"]["kind"]), ("Q41157", 35.82, "parent"))   # 끝난 소속(Q1)은 무시

    def test_other_country_is_not_followed(self):
        self.assertEqual(wikidata.city_by_name(http(FakeServer()), "Q17", "옥구군")["reason"], "no_item")

    def test_enrich_marks_area_fallback_and_report_shows_it(self):
        srv = FakeServer()
        d = nodes.Deps(http=http(srv), cache=ResearchCache(use_firestore=False), store=FakeStore(), today=TODAY, llm_on=False)
        resolved = identity.resolve(FakeStore(), kr_trip("옥구군"))
        nodes.enrich_unresolved(d, resolved)
        ref = resolved["cities"][0]["ref"]
        self.assertEqual((ref["name"], ref["qid"], ref["area_fallback"]), ("Gunsan", "Q42074", {"kind": "merged", "label": "Gunsan"}))
        rc = report.city_report(resolved["cities"][0], {"guide": {}})
        self.assertEqual(rc["fallback"], {"kind": "merged", "label": "Gunsan"})


@mock.patch.dict(os.environ, ENV)
class WiderRadiusTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.outage = False

        def near(deps, tc, want):
            scale = chain.scale(tc["ref"])
            self.calls.append(scale)
            if self.outage:
                return {"status": "unavailable", "reason": "http_503", "data": None}
            if scale < 2:
                return {"status": "empty", "reason": "no_places", "data": None}
            return {"status": "ok", "data": [{"id": "x:1", "name": "Far Temple", "kind": "attraction", "lat": 36.05, "lon": 126.80,
                                              "area": "", "desc_en": "", "sources": [{"provider": "fake", "url": "https://e.org/1"}]}]}
        self.patches = [mock.patch.object(chain, "HEALTH", chain.Health()), mock.patch.object(chain, "ADAPTERS", {"fake_near": near}),
                        mock.patch.object(chain, "NEARBY", frozenset({"fake_near"}))]
        for p in self.patches:
            p.start()
        self.cache = ResearchCache(use_firestore=False)

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def run_gunsan(self):
        d = nodes.Deps(http=http(FakeServer()), cache=self.cache, store=FakeStore(), today=TODAY, llm_on=False)
        return graph.run(d, identity.resolve(FakeStore(), kr_trip("군산", 1842025)))

    def test_empty_city_retries_with_wider_radius_and_says_so(self):
        rep = self.run_gunsan()
        city = rep["cities"][0]
        self.assertEqual(self.calls, [1.0, 2.5])
        self.assertEqual([p["name"] for p in city["places"]], ["Far Temple"])
        self.assertEqual((city["places"][0]["area_fallback"], city["fallback"]), ("wider", {"kind": "wider", "label": ""}))
        resolved = identity.resolve(FakeStore(), kr_trip("군산", 1842025))
        p = nodes.plan(nodes.Deps(http=http(FakeServer()), cache=self.cache, store=FakeStore(), today=TODAY, llm_on=False), resolved)
        self.assertEqual(graph.from_cache(resolved, p)["cities"][0]["fallback"]["kind"], "wider")     # 캐시에도 남는다

    def test_outage_does_not_widen(self):
        self.outage = True
        rep = self.run_gunsan()
        self.assertEqual(self.calls, [1.0])
        self.assertEqual((rep["cities"][0]["none_reason"], rep["cities"][0]["fallback"]), ("outage", None))

    def test_scale_bounds_and_tourapi_radius(self):
        self.assertEqual((chain.scale({}), chain.scale({"radius_scale": 9}), chain.scale({"radius_scale": "x"})), (1.0, 4.0, 1.0))
        srv = FakeServer()
        with mock.patch.dict(os.environ, {"TOURAPI_SERVICE_KEY": "k"}):
            tourapi.fetch(http(srv), {"iso2": "KR", "lat": 35.9, "lon": 126.7, "population": 264091, "radius_scale": 2.5}, "k",
                          {"food": 1})
        self.assertEqual(urllib.parse.parse_qs(urllib.parse.urlparse(srv.tour[0]).query)["radius"][0], "15000")


if __name__ == "__main__":
    unittest.main()
