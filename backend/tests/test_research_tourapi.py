"""한국관광공사 TourAPI(한국 도시 대체 장소 소스) — 네트워크 없음(가짜 서버). 키 값은 가짜다."""
import datetime as dt
import json
import os
import unittest
import urllib.parse
from unittest import mock

from app.research import chain, graph, identity, net, nodes
from app.research.cache import ResearchCache
from app.research.sources import tourapi
from tests.research_fakes import FakeServer, FakeStore

ENV = {"RESEARCH_ENABLED": "1", "RESEARCH_SOURCES": "", "RESEARCH_LLM": "0", "RESEARCH_PLACE_CHAIN": "tourapi",
       "TOURAPI_SERVICE_KEY": "fake/key+with=chars", "TOURAPI_SERVICE": ""}
TODAY = dt.date(2026, 10, 25)
GUNSAN = {"key": "KR_1842025", "iso2": "KR", "lat": 35.9786, "lon": 126.7114, "population": 264091}


def http(srv):
    return net.SafeHttp(transport=srv, sleep=lambda s: None)


@mock.patch.dict(os.environ, ENV)
class TourApiSourceTest(unittest.TestCase):
    def test_location_search_kinds_and_request(self):
        srv = FakeServer()
        h = http(srv)
        r = tourapi.fetch(h, GUNSAN, "KR_1842025", {"attraction": 2, "food": 2})
        self.assertEqual(r["status"], "ok")
        got = [(p["name"], p["kind"], p["provider"]) for p in r["data"]]
        self.assertEqual(got, [("Gunsan Modern History Museum", "attraction", "tourapi"), ("Lee Sung Dang", "restaurant", "tourapi"),
                               ("Cafe Gyeongamdong", "cafe", "tourapi")])                    # 숙박·잘못된 id 는 버림
        museum = r["data"][0]
        self.assertEqual((museum["id"], museum["desc_en"], museum["lat"]),
                         ("kto:KR_1842025:126508", "Address: 240, Haemang-ro, Gunsan-si.", 35.989))
        self.assertNotIn("firstimage", json.dumps(museum))                                  # 사진은 쓰지 않는다(공공누리 3유형)
        self.assertEqual(museum["sources"][0]["url"], "https://www.data.go.kr/data/15101753/openapi.do")
        url = urllib.parse.urlparse(srv.tour[0])
        q = urllib.parse.parse_qs(url.query)
        self.assertEqual(url.path, "/B551011/EngService2/locationBasedList2")
        self.assertEqual((q["mapX"][0], q["mapY"][0], q["radius"][0], q["arrange"][0], q["_type"][0], q["MobileOS"][0]),
                         ("126.711400", "35.978600", "6000", "E", "json", "ETC"))
        self.assertEqual(q["serviceKey"][0], "fake/key+with=chars")                         # Decoding 키는 인코딩해 보낸다
        self.assertFalse(any("fake" in c for c in h.calls))                                  # 진단용 URL 기록엔 키가 없다

    def test_encoded_key_is_sent_as_is_and_korean_service_option(self):
        srv = FakeServer()
        with mock.patch.dict(os.environ, {"TOURAPI_SERVICE_KEY": "abc%2Bdef%3D%3D", "TOURAPI_SERVICE": "KorService2"}):
            tourapi.fetch(http(srv), GUNSAN, "k", {"attraction": 1})
        self.assertIn("serviceKey=abc%2Bdef%3D%3D&", srv.tour[0])
        self.assertIn("/KorService2/", srv.tour[0])

    def test_error_codes(self):
        cases = [({"response": {"header": {"resultCode": "22", "resultMsg": "LIMITED"}}}, "capped"),
                 ({"response": {"header": {"resultCode": "23"}}}, "rate_limited"),
                 ({"response": {"header": {"resultCode": "30"}}}, "unavailable"),
                 (b"<OpenAPI_ServiceResponse><cmmMsgHeader><errMsg>SERVICE ERROR</errMsg>"
                  b"<returnAuthMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR</returnAuthMsg><returnReasonCode>30</returnReasonCode>"
                  b"</cmmMsgHeader></OpenAPI_ServiceResponse>", "unavailable")]
        for body, status in cases:
            srv = FakeServer()
            srv.tour_body = body
            r = tourapi.fetch(http(srv), GUNSAN, "k", {"food": 1})
            self.assertEqual(r["status"], status, body)
        srv = FakeServer()
        srv.tour_body = {"response": {"header": {"resultCode": "30"}}}
        self.assertEqual(chain.classify(tourapi.fetch(http(srv), GUNSAN, "k", {"food": 1})), "exhaust")   # 키 문제 → 6시간
        srv.tour_body = {"response": {"header": {"resultCode": "0000"}, "body": {"items": "", "totalCount": 0}}}
        self.assertEqual(tourapi.fetch(http(srv), GUNSAN, "k", {"food": 1})["status"], "empty")          # 결과 없음 = items ""

    def test_korea_only_and_key_required(self):
        srv = FakeServer()
        self.assertEqual(tourapi.fetch(http(srv), {**GUNSAN, "iso2": "JP"}, "k", {"food": 1})["reason"], "not_korea")
        self.assertEqual(srv.tour, [])
        with mock.patch.dict(os.environ, {"TOURAPI_SERVICE_KEY": ""}):
            self.assertFalse(tourapi.available())
            self.assertNotIn("tourapi", chain.active())
        self.assertIn("tourapi", chain.active())


@mock.patch.dict(os.environ, ENV)
class TourApiGraphTest(unittest.TestCase):
    def test_gunsan_filled_by_tourapi_and_cached(self):
        with mock.patch.object(chain, "HEALTH", chain.Health()):
            srv = FakeServer()
            cache = ResearchCache(use_firestore=False)
            d = nodes.Deps(http=http(srv), cache=cache, store=FakeStore(), today=TODAY, llm_on=False)
            req = {"countries": [{"name": "대한민국", "iso2": "KR"}],
                   "cities": [{"name": "군산", "gid": 1842025, "ci": 0, "start": "2027-03-20", "end": "2027-03-22", "attr": 1, "rest": 1}]}
            rep = graph.run(d, identity.resolve(FakeStore(), req))
            gunsan = rep["cities"][0]
            self.assertEqual([p["name"] for p in gunsan["places"]],
                             ["Gunsan Modern History Museum", "Lee Sung Dang", "Cafe Gyeongamdong"])
            self.assertEqual(gunsan["place_status"], "ok")
            self.assertIn("tourapi", {a["provider"] for a in rep["attributions"]})
            px = cache.get("research_cities", "KR_1842025", "places_extra")
            self.assertIn("Lee Sung Dang", json.dumps(px["data"]))                         # 저장 가능한 소스라 캐시에 남는다
            self.assertNotIn("fake/key", json.dumps(px, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
