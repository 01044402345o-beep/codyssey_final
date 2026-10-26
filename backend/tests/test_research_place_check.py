"""직접 추가한 장소 확인(POST /place-check) — TourAPI(한국) → Wikidata → Google(저장 안 함), 도시 근처만. 네트워크 없음."""
import os
import unittest
import urllib.parse
from unittest import mock

from fastapi.testclient import TestClient

from app import main
from app.agents import itinerary
from app.research import net, place_check
from app.research.cache import ResearchCache
from tests.research_fakes import FakeServer, FakeStore

ENV = {"RESEARCH_ENABLED": "1", "RESEARCH_SOURCES": "", "TOURAPI_SERVICE_KEY": "", "GOOGLE_MAPS_API_KEY": "",
       "ITINERARY_DAILY_CAP": "50"}
NARA = {"country": {"name": "일본", "iso2": "JP"}, "city": {"name": "나라", "gid": 1855612}}
GUNSAN = {"country": {"name": "대한민국", "iso2": "KR"}, "city": {"name": "군산", "gid": 1842025}}


def run(req, srv=None):
    srv = srv or FakeServer()
    return place_check.check(req, http=net.SafeHttp(transport=srv, sleep=lambda s: None), store=FakeStore(),
                             cache=ResearchCache(use_firestore=False)), srv


@mock.patch.dict(os.environ, ENV)
class PlaceCheckTest(unittest.TestCase):
    def setUp(self):
        place_check.clear()
        itinerary.reset_daily_cap()

    def test_found_on_wikidata_near_the_city(self):
        r, _ = run({**NARA, "place": {"name": "Todaiji", "kind": "attraction"}})
        self.assertEqual((r["status"], r["name"], r["source"]["provider"]), ("found", "Tōdai-ji", "wikidata"))
        self.assertEqual(r["source"]["url"], "https://www.wikidata.org/wiki/Q186148")
        self.assertLess(r["distance_km"], 5)
        again, srv2 = run({**NARA, "place": {"name": "todaiji", "kind": "attraction"}})
        self.assertTrue(again.get("cached"))                                                   # Wikidata 결과는 기억

    def test_same_name_in_another_city_is_not_found(self):
        r, _ = run({**NARA, "place": {"name": "Far Shrine", "kind": "attraction"}})
        self.assertEqual(r["status"], "not_found")                                             # 도시에서 40km 밖

    def test_korea_uses_tourapi_keyword_first(self):
        with mock.patch.dict(os.environ, {"TOURAPI_SERVICE_KEY": "k"}):
            r, srv = run({**GUNSAN, "place": {"name": "근대역사박물관", "kind": "attraction"}})
        self.assertEqual((r["status"], r["source"]["provider"], r["kind"]), ("found", "tourapi", "attraction"))
        u = urllib.parse.urlparse(srv.tour[0])
        self.assertEqual((u.path, urllib.parse.parse_qs(u.query)["keyword"][0]), ("/B551011/EngService2/searchKeyword2", "근대역사박물관"))

    def test_google_is_last_and_never_remembered(self):
        with mock.patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "g"}):
            r, srv = run({**GUNSAN, "place": {"name": "Sandy Coffee", "kind": "cafe"}})
            self.assertEqual((r["status"], r["name"], r["source"]["provider"]), ("found", "Sandy Coffee Naun", "google"))
            self.assertEqual(srv.google[-1]["locationBias"]["circle"]["center"], {"latitude": 35.9786, "longitude": 126.7114})
            r2, srv2 = run({**GUNSAN, "place": {"name": "Sandy Coffee", "kind": "cafe"}})
        self.assertFalse(r2.get("cached"))
        self.assertEqual(len(srv2.google), 1)                                                   # 다시 물었다(저장하지 않음)

    def test_guards(self):
        self.assertEqual(run({**NARA, "place": {"name": "<b>x</b>", "kind": "cafe"}})[0]["status"], "not_found")
        self.assertEqual(run({"country": {"name": "일본", "iso2": "JP"}, "city": {"name": "어디도아님"},
                              "place": {"name": "Cafe", "kind": "cafe"}})[0]["status"], "no_city")
        with mock.patch.dict(os.environ, {"RESEARCH_ENABLED": "0"}):
            self.assertEqual(run({**NARA, "place": {"name": "Todaiji", "kind": "attraction"}})[0]["reason"], "research_disabled")

    def test_endpoint_validates_body(self):
        client = TestClient(main.app)
        with mock.patch.object(place_check, "check", return_value={"status": "not_found"}) as m:
            ok = client.post("/place-check", json={**NARA, "place": {"name": "Todaiji", "kind": "attraction"}})
        self.assertEqual((ok.status_code, ok.json()), (200, {"status": "not_found"}))
        self.assertEqual(m.call_args[0][0]["place"]["name"], "Todaiji")
        bad = client.post("/place-check", json={**NARA, "place": {"name": "x", "kind": "hotel"}, "uid": "u1"})
        self.assertEqual(bad.status_code, 422)                                                # 모르는 종류·사용자 정보 거부


if __name__ == "__main__":
    unittest.main()
