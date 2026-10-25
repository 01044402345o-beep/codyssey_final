"""조사 그래프(LangGraph)·잡·엔드포인트 — 네트워크 없음(가짜 서버·가짜 GeoStore·메모리 캐시)."""
import datetime as dt
import os
import time
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from app import main
from app.research import graph, identity, jobs, net, nodes, service
from app.research.cache import ResearchCache
from tests.research_fakes import FakeServer, FakeStore, trip

ENV = {"RESEARCH_ENABLED": "1", "RESEARCH_SOURCES": "", "RESEARCH_MAX_JOBS": "1", "RESEARCH_LLM": "0", "RESEARCH_PLACE_CHAIN": "none"}  # LLM 추출은 test_research_extract
TODAY = dt.date(2026, 10, 25)


def wait(job_id, timeout=10):
    t = time.time()
    while time.time() - t < timeout:
        got = service.poll(job_id)
        if got and got["status"] != "running":
            return got
        time.sleep(0.02)
    raise AssertionError("job did not finish")


@mock.patch.dict(os.environ, ENV)
class GraphTest(unittest.TestCase):
    def setUp(self):
        self.srv = FakeServer()
        self.http = net.SafeHttp(transport=self.srv, sleep=lambda s: None)
        self.cache = ResearchCache(use_firestore=False)
        self.deps = nodes.Deps(http=self.http, cache=self.cache, store=FakeStore(), today=TODAY)

    def run_trip(self, req=None):
        resolved = identity.resolve(FakeStore(), req or trip())
        return graph.run(self.deps, resolved)

    def test_fan_out_researches_each_city_and_country_with_sources(self):
        rep = self.run_trip()
        self.assertEqual((rep["schema"], rep["quality"]), ("research.v1", "full"))
        tokyo, osaka = rep["cities"]
        names = [p["name"] for p in tokyo["places"]]
        self.assertIn("Imperial Palace", names)
        self.assertIn("Tsukiji Outer Market", names)                               # 구역 문서(listing type=eat)
        self.assertNotIn("Far Away Shrine", names)                                # 도시에서 50km 밖 → 버림
        self.assertNotIn("Haneda Airport", names)                                 # go 는 장소가 아니다
        self.assertFalse(any("<" in n for n in names))                            # 주입 흔적 이름 → 버림
        kinds = {p["name"]: p["kind"] for p in tokyo["places"]}
        self.assertEqual((kinds["Blue Bottle Coffee"], kinds["Sushi Dai"], kinds["Kitanomaru Park"]),
                         ("cafe", "restaurant", "attraction"))
        palace = next(p for p in tokyo["places"] if p["name"] == "Imperial Palace")
        self.assertEqual((palace["area"], palace["sources"][0]["url"]), ("Chiyoda", "https://en.wikivoyage.org/wiki/Tokyo/Chiyoda"))
        self.assertIsInstance(palace["area"], str)
        topics = [x["topic"] for x in tokyo["practical"]]
        self.assertIn("tipping", topics)
        self.assertEqual(tokyo["climate"]["kind"], "normals")
        self.assertEqual([d["role"] for d in tokyo["days"]][0], "arrival")
        self.assertEqual(tokyo["days"][0]["topics"], ["transport_airport", "transport_local"])
        self.assertEqual(osaka["places"][0]["name"], "Osaka Castle")
        jp = rep["countries"]["JP"]
        self.assertEqual((jp["currency"]["code"], jp["currency"]["krw_per_unit"], jp["emergency"]), ("JPY", 8.43, ["110", "119"]))
        self.assertIsNone(jp["advisory"])                                       # 영국 FCDO 권고는 쓰지 않는다
        self.assertFalse(any("gov.uk" in c for c in self.srv.calls))
        self.assertEqual({a["provider"] for a in rep["attributions"]},
                         {"wikivoyage", "wikidata", "openmeteo", "frankfurter", "geonames"})

    def test_second_run_is_served_from_cache_without_http(self):
        self.run_trip()
        n = len(self.srv.calls)
        resolved = identity.resolve(FakeStore(), trip())
        plan = nodes.plan(self.deps, resolved)
        self.assertTrue(nodes.all_fresh(plan))
        rep = graph.from_cache(resolved, plan)
        self.assertEqual(len(self.srv.calls), n)                                  # 외부 호출 0회
        self.assertEqual(rep["quality"], "full")
        self.assertEqual(len(rep["cities"][0]["places"]), len(self.run_trip()["cities"][0]["places"]))

    def test_one_city_failing_does_not_sink_the_others(self):
        self.srv.fail = {"titles=Osaka": 503}
        rep = self.run_trip()
        self.assertEqual([c["status"] for c in rep["cities"]], ["ok", "empty"])
        self.assertEqual(rep["quality"], "reduced")
        self.assertIsNotNone(rep["cities"][1]["climate"])                         # 날씨는 따로 받았다

    def test_plain_runner_gives_the_same_report_and_is_the_fallback(self):
        def strip(rep):
            return {**rep, "generated_at": 0}
        resolved = identity.resolve(FakeStore(), trip())
        via_graph = graph.run_graph(self.deps, resolved)
        fresh = nodes.Deps(http=self.http, cache=ResearchCache(use_firestore=False), store=FakeStore(), today=TODAY)
        self.assertEqual(strip(graph.run_plain(fresh, resolved)), strip(via_graph))     # 같은 노드, 같은 결과
        with mock.patch.dict(os.environ, {"RESEARCH_USE_GRAPH": "0"}), mock.patch.object(graph, "run_graph") as g:
            graph.run(self.deps, resolved)
            g.assert_not_called()
        with mock.patch.object(graph, "build", side_effect=ImportError("no langgraph")):
            rep = graph.run(nodes.Deps(http=self.http, cache=ResearchCache(use_firestore=False), store=FakeStore(), today=TODAY), resolved)
        self.assertEqual(rep["quality"], "full")                                   # 그래프가 죽어도 plain 으로

    def test_every_source_down_still_returns_a_report(self):
        self.srv.fail = {"https://": 503}
        rep = self.run_trip()
        self.assertEqual(rep["quality"], "failed")
        self.assertEqual(rep["cities"][0]["places"], [])


@mock.patch.dict(os.environ, ENV)
class ServiceTest(unittest.TestCase):
    def setUp(self):
        self.srv = FakeServer()
        self.kw = dict(http=net.SafeHttp(transport=self.srv, sleep=lambda s: None), cache=ResearchCache(use_firestore=False),
                       store=FakeStore(), today=TODAY)
        jobs.JOBS = service.JOBS = jobs.JobStore()

    def test_disabled_makes_no_calls(self):
        with mock.patch.dict(os.environ, {"RESEARCH_ENABLED": "0"}):
            self.assertEqual(service.submit(trip(), "ip", **self.kw), {"status": "unavailable", "reason": "research_disabled"})
        self.assertEqual(self.srv.calls, [])

    def test_job_then_cached_then_cache_only(self):
        self.assertEqual(service.submit(trip(cache_only=True), "ip", **self.kw), {"status": "miss"})
        r = service.submit(trip(), "ip", **self.kw)
        self.assertEqual(r["status"], "running")
        got = wait(r["job_id"])
        self.assertEqual((got["status"], got["report"]["quality"]), ("done", "full"))
        self.assertTrue(any(e["step"] == "guide" and e["state"] == "done" for e in got["progress"]))
        again = service.submit(trip(), "ip", **self.kw)
        self.assertEqual((again["status"], again["cached"]), ("done", True))

    def test_dates_and_city_limits(self):
        far = trip(cities=[{"name": "도쿄", "gid": 1850147, "ci": 0, "start": "2028-03-20", "end": "2028-03-23"}])
        self.assertEqual(service.submit(far, "ip", **self.kw)["reason"], "bad_dates")
        past = trip(cities=[{"name": "도쿄", "gid": 1850147, "ci": 0, "start": "2026-10-01", "end": "2026-10-03"}])
        self.assertEqual(service.submit(past, "ip", **self.kw)["reason"], "bad_dates")
        with mock.patch.dict(os.environ, {"RESEARCH_MAX_CITIES": "1"}):
            self.assertEqual(service.submit(trip(), "ip", **self.kw)["reason"], "too_many_cities")

    def test_single_flight_and_per_ip_limit(self):
        gate = []

        def slow(on_progress):
            while not gate:
                time.sleep(0.01)
            return {"status": "done"}
        jid, joined = service.JOBS.start("k1", "1.1.1.1", slow)
        self.assertEqual(service.JOBS.start("k1", "2.2.2.2", slow), (jid, True))   # 같은 요청은 같은 잡
        with self.assertRaises(jobs.Busy):
            service.JOBS.start("k2", "3.3.3.3", slow)                              # 전역 1잡
        gate.append(1)
        self.assertEqual(wait(jid)["status"], "done")


@mock.patch.dict(os.environ, ENV)
class EndpointTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        jobs.JOBS = service.JOBS = jobs.JobStore()
        self.srv = FakeServer()
        p1 = mock.patch.object(service, "SafeHttp", lambda: net.SafeHttp(transport=self.srv, sleep=lambda s: None))
        p2 = mock.patch.object(service, "_store", lambda: FakeStore())
        p3 = mock.patch.object(service, "CACHE", ResearchCache(use_firestore=False))
        for p in (p1, p2, p3):
            p.start()
            self.addCleanup(p.stop)

    def body(self):
        today = dt.date.today()
        s, m, e = (today + dt.timedelta(days=60)).isoformat(), (today + dt.timedelta(days=63)).isoformat(), (today + dt.timedelta(days=66)).isoformat()
        return trip(cities=[{"name": "도쿄", "gid": 1850147, "ci": 0, "start": s, "end": m},
                            {"name": "오사카", "gid": 1853909, "ci": 0, "start": m, "end": e}])

    def test_post_202_then_poll_done(self):
        r = self.client.post("/research", json=self.body())
        self.assertEqual(r.status_code, 202, r.text)
        jid = r.json()["job_id"]
        for _ in range(500):
            got = self.client.get(f"/research/{jid}").json()
            if got["status"] != "running":
                break
            time.sleep(0.02)
        self.assertEqual(got["status"], "done")
        self.assertEqual(len(got["report"]["cities"]), 2)
        self.assertEqual(self.client.post("/research", json=self.body()).json()["status"], "done")   # 캐시

    def test_validation_and_unknown_job(self):
        bad = self.body()
        bad["cities"][0]["uid"] = "u1"
        self.assertEqual(self.client.post("/research", json=bad).status_code, 422)          # 모르는 필드
        many = self.body()
        many["cities"] = many["cities"] * 3
        self.assertEqual(self.client.post("/research", json=many).status_code, 422)         # 도시 6곳
        self.assertEqual(self.client.get("/research/not-a-real-job-id-xx").status_code, 404)
        self.assertEqual(self.client.get("/research/..%2F..%2Fhealth").status_code, 404)

    def test_disabled_and_health(self):
        with mock.patch.dict(os.environ, {"RESEARCH_ENABLED": "0"}):
            self.assertEqual(self.client.post("/research", json=self.body()).json()["reason"], "research_disabled")
        h = main.health_detail()["research"]
        self.assertEqual((h["enabled"], h["langgraph"]), (True, True))
        self.assertNotIn("research", main.health_public(main.health_detail()))


if __name__ == "__main__":
    unittest.main()
