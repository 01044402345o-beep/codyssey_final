"""장소 대체 체인·소스 쿨다운·마지막 정상 캐시(복구) — 네트워크 없음(가짜 어댑터·가짜 서버)."""
import datetime as dt
import os
import unittest
from unittest import mock

from app.research import chain, graph, identity, net, nodes, report
from app.research.cache import ResearchCache
from tests.research_fakes import FakeServer, FakeStore, trip

ENV = {"RESEARCH_ENABLED": "1", "RESEARCH_SOURCES": "", "RESEARCH_LLM": "0", "RESEARCH_PLACE_CHAIN": "fake_a,fake_b",
       "RESEARCH_PLACE_MIN_EXTRA": "2"}
TODAY = dt.date(2026, 10, 25)


def pl(i, kind, name=None, lat=34.69, lon=135.50, **kw):
    return {"id": f"x:{i}", "name": name or f"Place {i}", "kind": kind, "lat": lat, "lon": lon, "area": "", "desc_en": "",
            "sources": [{"provider": "fake", "url": f"https://example.org/{i}", "title": "fake"}], **kw}


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class FakeDeps:
    def __init__(self, late=False):
        self.late = late

    def past_deadline(self):
        return self.late


def adapter(result, calls=None, name=""):
    def run(deps, tc, want):
        if calls is not None:
            calls.append((name, dict(want)))
        if isinstance(result, Exception):
            raise result
        return result
    return run


def ok(places):
    return {"status": "ok", "data": places, "reason": ""}


TC = {"caps": {"attr": 2, "rest": 2}, "ref": {"input": "x"}}


@mock.patch.dict(os.environ, ENV)
class ChainUnitTest(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.health = chain.Health(now=self.clock)

    def test_classify(self):
        self.assertEqual([chain.classify(r) for r in (
            ok([1]), ok([]), {"status": "empty"}, {"status": "disabled"}, {"status": "capped"},
            {"status": "unavailable", "reason": "http_403"}, {"status": "rate_limited"}, {"status": "unavailable", "reason": "timeout"})],
            ["ok", "nodata", "nodata", "disabled", "exhaust", "exhaust", "rate_limited", "transient"])

    def test_cooldown_circuit_and_recovery(self):
        h = self.health
        h.note("a", "transient")
        self.assertEqual(h.cooling("a"), 60)
        self.assertEqual(h.order(["a", "b"]), ["b"])                     # 쿨다운 중이면 건너뜀
        h.note("b", "exhaust", "http_401")
        self.assertEqual(h.order(["a", "b"]), ["a"])                     # 전부 쿨다운 → 가장 빨리 풀리는 하나
        for _ in range(4):
            h.note("a", "transient")
        self.assertTrue(h.snapshot()["a"]["circuit"])
        self.assertEqual(h.cooling("a"), 240)                            # 연속 5번 → 회로 열림(4배)
        self.clock.t += 241
        self.assertEqual(h.order(["a"]), ["a"])                          # 시간이 지나면 다시 시도
        h.note("a", "ok")
        self.assertEqual((h.cooling("a"), h.snapshot()["a"]["streak"], h.snapshot()["a"]["circuit"]), (0, 0, False))
        h.note("c", "nodata")
        self.assertEqual(h.cooling("c"), 0)                              # 결과 없음은 장애가 아니다

    def test_want_enough_and_merge(self):
        have = [pl(1, "attraction"), pl(2, "restaurant")]
        self.assertEqual(chain.want(have, {"attr": 2, "rest": 2}), {"attraction": 3, "food": 3})
        self.assertEqual(chain.want(have, {"attr": 0, "rest": 1}), {"attraction": 0, "food": 2})
        self.assertFalse(chain.enough(have, {"attr": 2, "rest": 1}))
        a = pl(1, "attraction", "Todai-ji", wikidata="Q1")
        same_qid = pl(9, "attraction", "Todaiji Temple", wikidata="Q1", desc_en="Big Buddha.", homepage="https://todaiji.or.jp/")
        near = pl(10, "attraction", "TODAI-JI", lat=34.6901, lon=135.5001)       # 이름 같고 150m 안
        far = pl(11, "attraction", "Todai-ji", lat=34.80, lon=135.50)            # 이름 같지만 12km 밖 → 다른 장소
        out = chain.merge([a], [same_qid, near, far])
        self.assertEqual(len(out), 2)
        self.assertEqual((out[0]["desc_en"], out[0]["homepage"]), ("Big Buddha.", "https://todaiji.or.jp/"))
        self.assertEqual(len(out[0]["sources"]), 3)
        self.assertEqual(a.get("desc_en"), "")                                     # 원본은 건드리지 않는다

    def test_run_stops_when_filled_and_asks_only_missing_kinds(self):
        calls = []
        adapters = {"fake_a": adapter(ok([pl(3, "restaurant"), pl(4, "cafe"), pl(5, "restaurant"), pl(9, "cafe")]), calls, "a"),
                    "fake_b": adapter(ok([pl(6, "attraction")]), calls, "b")}
        have = [pl(1, "attraction"), pl(2, "attraction"), pl(7, "attraction"), pl(8, "attraction")]
        r = chain.run(FakeDeps(), TC, have, self.health, adapters)
        self.assertEqual(calls, [("a", {"attraction": 0, "food": 4})])         # 관광지는 이미 충분 → 식당만 묻는다
        self.assertEqual(len(r["places"]), 4)
        self.assertEqual(r["by_source"]["fake_a"]["outcome"], "ok")
        self.assertNotIn("fake_b", r["by_source"])                               # 다 채웠으니 다음 소스는 묻지 않는다
        self.assertFalse(r["outage"])

    def test_failure_falls_through_and_cools_down(self):
        calls = []
        adapters = {"fake_a": adapter({"status": "rate_limited", "data": None, "reason": "http_429"}, calls, "a"),
                    "fake_b": adapter(ok([pl(3, "attraction"), pl(4, "restaurant")]), calls, "b")}
        r = chain.run(FakeDeps(), TC, [], self.health, adapters)
        self.assertEqual([c[0] for c in calls], ["a", "b"])
        self.assertEqual(len(r["places"]), 2)
        self.assertTrue(r["outage"])
        self.assertEqual(self.health.cooling("fake_a"), 300)
        calls.clear()
        r2 = chain.run(FakeDeps(), TC, [], self.health, adapters)               # 다음 요청: a 는 쿨다운이라 건너뜀
        self.assertEqual([c[0] for c in calls], ["b"])
        self.assertEqual(r2["by_source"]["fake_a"]["outcome"], "cooldown")

    def test_adapter_exception_is_transient_and_deadline_stops(self):
        adapters = {"fake_a": adapter(RuntimeError("bug")), "fake_b": adapter(ok([pl(3, "attraction")]))}
        r = chain.run(FakeDeps(), TC, [], self.health, adapters)
        self.assertEqual(r["by_source"]["fake_a"]["outcome"], "transient")
        late = chain.run(FakeDeps(late=True), TC, [], chain.Health(now=self.clock), adapters)
        self.assertEqual((late["places"], late["by_source"]["fake_a"]["outcome"]), ([], "deadline"))

    def test_chain_order_and_kill_switch(self):
        calls = []
        adapters = {"fake_a": adapter(ok([]), calls, "a"), "fake_b": adapter(ok([]), calls, "b")}
        with mock.patch.dict(os.environ, {"RESEARCH_PLACE_CHAIN": "fake_b,fake_a"}):
            chain.run(FakeDeps(), TC, [], self.health, adapters)
        self.assertEqual([c[0] for c in calls], ["b", "a"])
        with mock.patch.dict(os.environ, {"RESEARCH_PLACE_CHAIN": "none"}):
            self.assertEqual(chain.active(adapters), [])
        with mock.patch.dict(os.environ, {"RESEARCH_PLACE_CHAIN": "wikivoyage,fake_a"}):
            self.assertEqual(chain.active(adapters), ["fake_a"])                # 위키보이지는 늘 1순위라 목록에서 뺀다

    def test_keep_last_good(self):
        old = {"places": [pl(i, "attraction") for i in range(6)]}
        kept, used_old = chain.keep_last_good({"places": [pl(1, "attraction")], "outage": True}, old)
        self.assertTrue(used_old)
        self.assertIs(kept, old)
        self.assertFalse(chain.keep_last_good({"places": [pl(1, "attraction")], "outage": False}, old)[1])   # 정상적으로 줄면 교체
        self.assertFalse(chain.keep_last_good({"places": [], "outage": True}, None)[1])


class CacheStaleTest(unittest.TestCase):
    def test_stale_entry_is_served_only_when_asked(self):
        clock = Clock()
        c = ResearchCache(use_firestore=False, now=clock)
        c.put("research_cities", "JP_1", "places_extra", {"places": [1]}, 10, [])
        self.assertFalse(c.get("research_cities", "JP_1", "places_extra")["stale"])
        clock.t += 11
        self.assertIsNone(c.get("research_cities", "JP_1", "places_extra"))
        got = c.get("research_cities", "JP_1", "places_extra", allow_stale=True)
        self.assertEqual((got["stale"], got["data"]), (True, {"places": [1]}))

    def test_firestore_ttl_keeps_a_grace_period(self):
        docs = {}

        def fetch(method, path, body=None):
            if method == "PATCH":
                docs[path] = body
                return body
            return docs.get(path)
        clock = Clock()
        c = ResearchCache(fetch=fetch, now=clock)
        c.put("research_cities", "JP_1", "guide", {"x": 1}, 100, [])
        f = docs["research_cities/JP_1/sections/guide"]["fields"]
        expire = dt.datetime.fromisoformat(f["expire_at"]["timestampValue"].replace("Z", "+00:00")).timestamp()
        self.assertEqual(int(expire), int(clock.t) + 100 + 30 * 86400)
        fresh = ResearchCache(fetch=fetch, now=lambda: clock.t + 200)                 # 다른 프로세스: 메모리 없음
        self.assertIsNone(fresh.get("research_cities", "JP_1", "guide"))
        self.assertTrue(fresh.get("research_cities", "JP_1", "guide", allow_stale=True)["stale"])


def nara_trip(**over):
    return trip(cities=[{"name": "나라", "gid": 1855612, "ci": 0, "start": "2027-03-20", "end": "2027-03-22", "attr": 2, "rest": 2},
                        {"name": "오사카", "gid": 1853909, "ci": 0, "start": "2027-03-22", "end": "2027-03-24", "attr": 2, "rest": 2}], **over)


@mock.patch.dict(os.environ, ENV)
class ChainGraphTest(unittest.TestCase):
    def setUp(self):
        self.srv = FakeServer()
        self.cache = ResearchCache(use_firestore=False)
        self.calls = []
        self.health = chain.Health()
        self.result = {"fake_a": ok([pl(1, "attraction", "Todai-ji", lat=34.689, lon=135.84),
                                     pl(2, "attraction", "Nara Park", lat=34.685, lon=135.843),
                                     pl(3, "restaurant", "Kakinoha", lat=34.683, lon=135.83),
                                     pl(4, "cafe", "Deer Cafe", lat=34.684, lon=135.82)]),
                       "fake_b": ok([])}
        self.patches = [mock.patch.object(chain, "HEALTH", self.health),
                        mock.patch.object(chain, "ADAPTERS", {n: self._adapter(n) for n in ("fake_a", "fake_b")})]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def _adapter(self, name):
        def run(deps, tc, want):
            self.calls.append((name, tc["ref"]["name"], dict(want)))
            r = self.result[name]
            if isinstance(r, Exception):
                raise r
            return r
        return run

    def deps(self):
        return nodes.Deps(http=net.SafeHttp(transport=self.srv, sleep=lambda s: None), cache=self.cache, store=FakeStore(),
                          today=TODAY, llm_on=False)

    def run_trip(self, req=None):
        return graph.run(self.deps(), identity.resolve(FakeStore(), req or nara_trip()))

    def test_city_without_wikivoyage_is_filled_by_the_chain(self):
        rep = self.run_trip()
        nara, osaka = rep["cities"]
        self.assertEqual([p["name"] for p in nara["places"]], ["Todai-ji", "Nara Park", "Kakinoha", "Deer Cafe"])
        self.assertEqual((nara["place_status"], nara["none_reason"], nara["stale"]), ("ok", "", False))
        self.assertEqual(nara["chain"]["fake_a"], {"status": "ok", "outcome": "ok", "count": 4})
        self.assertEqual(nara["places"][0]["sources"][0]["url"], "https://example.org/1")
        # 오사카: 위키보이지 장소(관광 1·식당 1)가 있어도 목표(2+2)에 모자라 체인이 보탠다 — 겹치는 이름은 없음
        self.assertEqual(osaka["places"][0]["name"], "Osaka Castle")
        self.assertIn(("fake_a", "Osaka", {"attraction": 3, "food": 3}), self.calls)
        self.assertEqual(rep["quality"], "full")

    def test_missing_article_and_extra_places_are_cached(self):
        self.run_trip()
        n_http, n_calls = len(self.srv.calls), len(self.calls)
        resolved = identity.resolve(FakeStore(), nara_trip())
        d = self.deps()
        p = nodes.plan(d, resolved)
        self.assertTrue(nodes.all_fresh(p), p["cities"][0]["need"])          # 문서 없음도 기억 → 캐시만으로 보고서
        rep = graph.from_cache(resolved, p)
        self.assertEqual((len(self.srv.calls), len(self.calls)), (n_http, n_calls))
        self.assertEqual(rep["cities"][0]["places"][1]["name"], "Nara Park")
        guide = self.cache.get("research_cities", resolved["cities"][0]["ref"]["key"], "guide")
        self.assertEqual(guide["data"], {"wikivoyage": None, "reason": "no_article"})

    def test_wikivoyage_outage_is_not_remembered(self):
        self.srv.fail = {"en.wikivoyage.org": 503}
        self.result["fake_a"] = ok([])
        rep = self.run_trip()
        self.assertEqual((rep["cities"][0]["place_status"], rep["cities"][0]["none_reason"]), ("none", "outage"))
        key = identity.resolve(FakeStore(), nara_trip())["cities"][0]["ref"]["key"]
        self.assertIsNone(self.cache.get("research_cities", key, "guide"))

    def test_no_sources_reason_when_everything_is_healthy_but_empty(self):
        self.result["fake_a"] = ok([])
        rep = self.run_trip()
        self.assertEqual((rep["cities"][0]["place_status"], rep["cities"][0]["none_reason"]), ("none", "no_sources"))

    def test_outage_keeps_last_good_places_marked_stale(self):
        self.run_trip()
        key = identity.resolve(FakeStore(), nara_trip())["cities"][0]["ref"]["key"]
        good = self.cache.get("research_cities", key, "places_extra")
        self.cache.put("research_cities", key, "places_extra", good["data"], -1, [])     # 만료시킨다
        self.result["fake_a"] = {"status": "unavailable", "data": None, "reason": "http_503"}
        self.result["fake_b"] = {"status": "unavailable", "data": None, "reason": "timeout"}
        rep = self.run_trip()
        nara = rep["cities"][0]
        self.assertEqual(len(nara["places"]), 4)                                       # 옛 결과 그대로
        self.assertTrue(nara["stale"])
        self.assertEqual(nara["place_status"], "ok")
        still = self.cache.get("research_cities", key, "places_extra", allow_stale=True)
        self.assertTrue(still["stale"])                                                # 덮어쓰지 않았다

    def test_kill_switch_means_wikivoyage_only(self):
        with mock.patch.dict(os.environ, {"RESEARCH_PLACE_CHAIN": "none"}):
            rep = self.run_trip()
        self.assertEqual((self.calls, rep["cities"][0]["places"], rep["cities"][0]["none_reason"]), ([], [], "no_sources"))

    def test_plain_runner_matches_graph(self):
        a = self.run_trip()
        self.cache = ResearchCache(use_firestore=False)
        with mock.patch.dict(os.environ, {"RESEARCH_USE_GRAPH": "0"}):
            b = self.run_trip()
        names = lambda r: [[p["name"] for p in c["places"]] for c in r["cities"]]
        self.assertEqual(names(a), names(b))

    def test_report_status_helpers(self):
        tc = identity.resolve(FakeStore(), nara_trip())["cities"][0]
        thin = report.city_report(tc, {"guide": {}, "extra_places": [pl(1, "attraction", lat=34.685, lon=135.805)]})
        self.assertEqual(thin["place_status"], "thin")
        tc_nocoord = {**tc, "ref": {**tc["ref"], "lat": None, "lon": None}}
        self.assertEqual(report.city_report(tc_nocoord, {"guide": {}})["none_reason"], "no_coords")


if __name__ == "__main__":
    unittest.main()
