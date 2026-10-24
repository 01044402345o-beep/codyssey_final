"""국가·도시 선택 목록(/geo/*) — Firestore 는 가짜로 바꾼다.  실행: cd backend && python -m unittest discover -s tests -t ."""
import base64
import gzip
import json
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from app import geo, main


def fs(v):
    if isinstance(v, bool):
        return {"booleanValue": v}
    if isinstance(v, int):
        return {"integerValue": str(v)}
    if isinstance(v, dict):
        return {"mapValue": {"fields": {k: fs(x) for k, x in v.items()}}}
    return {"stringValue": v}


def country_doc(iso2, name, ko, city_count, shards=1, admin1=None):
    return {"fields": {k: fs(v) for k, v in {"iso2": iso2, "name": name, "ko": ko, "capital": "", "population": 1,
                                              "continent": "AS", "city_count": city_count, "shards": shards,
                                              "admin1": admin1 or {}}.items()}}


US_ROWS = [  # 인구 내림차순(geo-refresh 가 그렇게 저장한다)
    [5128581, "New York City", "New York City", "뉴욕 시", "NY", 8800000, 40.7, -74.0, "PPL"],
    [5368361, "Los Angeles", "Los Angeles", "로스앤젤레스", "CA", 3800000, 34.0, -118.2, "PPL"],
    [4930956, "Boston", "Boston", "보스턴", "MA", 653833, 42.3, -71.0, "PPLA"],
    [4140963, "Washington", "Washington", "워싱턴", "DC", 690000, 38.9, -77.0, "PPLC"],
    [1, "Boston", "Boston", "", "GA", 1323, 30.7, -83.7, "PPL"],
    [2, "Newark", "Newark", "", "NJ", 300000, 40.7, -74.1, "PPL"],
]


class FakeFirestore:
    def __init__(self):
        self.calls = []
        self.countries = [country_doc("US", "United States", "미국", 6, admin1={"NY": "New York", "MA": "Massachusetts"}),
                          country_doc("AU", "Australia", "오스트레일리아", 3),
                          country_doc("BV", "Bouvet Island", "부베 섬", 0, shards=0)]

    def __call__(self, subpath):
        self.calls.append(subpath)
        if subpath.startswith("geo_countries"):
            return {"documents": self.countries}
        if subpath == "geo_cities/US_000":
            data = base64.b64encode(gzip.compress(json.dumps(US_ROWS).encode())).decode()
            return {"fields": {"data": {"bytesValue": data}}}
        return {}


class GeoStoreTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeFirestore()
        self.clock = [1000.0]
        self.store = geo.GeoStore(fetch=self.fake, now=lambda: self.clock[0])

    def test_countries_sorted_by_korean_and_empty_ones_dropped(self):
        got = self.store.countries()
        self.assertEqual([c["iso2"] for c in got], ["US", "AU"])      # 미국 < 오스트레일리아, BV(도시 0) 제외
        self.assertEqual(got[0]["ko"], "미국")

    def test_countries_cached_until_ttl(self):
        self.store.countries(); self.store.countries()
        self.assertEqual(sum(1 for c in self.fake.calls if c.startswith("geo_countries")), 1)
        self.clock[0] += geo.TTL + 1
        self.store.countries()
        self.assertEqual(sum(1 for c in self.fake.calls if c.startswith("geo_countries")), 2)

    def test_top_cities_without_query_and_korean_label(self):
        got = self.store.cities("US")
        self.assertEqual(got[0]["label"], "뉴욕")                       # '뉴욕 시' → '뉴욕'
        self.assertEqual(got[0]["region"], "New York")
        self.assertEqual([c["name"] for c in got[:3]], ["New York City", "Los Angeles", "Boston"])
        self.assertTrue(got[3]["capital"])
        self.assertNotIn("_k", got[0])

    def test_search_english_korean_prefix_then_contains(self):
        self.assertEqual([c["id"] for c in self.store.cities("US", "bos")], [4930956, 1])     # 인구순
        self.assertEqual(self.store.cities("US", "보스")[0]["id"], 4930956)
        self.assertEqual([c["name"] for c in self.store.cities("US", "new")], ["New York City", "Newark"])
        self.assertEqual(self.store.cities("US", "york")[0]["name"], "New York City")           # 포함 일치
        self.assertEqual(self.store.cities("US", "newyork")[0]["name"], "New York City")        # 띄어쓰기 무시
        self.assertEqual(self.store.cities("US", "zzz"), [])

    def test_cities_read_firestore_once_per_country(self):
        self.store.cities("US", "a"); self.store.cities("US", "b")
        self.assertEqual(self.fake.calls.count("geo_cities/US_000"), 1)

    def test_bad_inputs(self):
        with self.assertRaises(geo.GeoError) as c:
            self.store.cities("U1")
        self.assertEqual(c.exception.status, 400)
        with self.assertRaises(geo.GeoError) as c:
            self.store.cities("ZZ")
        self.assertEqual(c.exception.status, 404)
        self.assertEqual(len(self.store.cities("US", "", limit=999)), len(US_ROWS))   # 상한 50 안에서 전부

    def test_ko_label_only_strips_spaced_suffix(self):
        self.assertEqual(geo.ko_label("오사카 시"), "오사카")
        self.assertEqual(geo.ko_label("서울특별시"), "서울특별시")
        self.assertEqual(geo.ko_label("시애틀"), "시애틀")


class GeoEndpointTest(unittest.TestCase):
    def setUp(self):
        self.http = TestClient(main.app)
        self.store = geo.GeoStore(fetch=FakeFirestore())
        p = mock.patch.object(geo, "STORE", self.store)
        p.start(); self.addCleanup(p.stop)

    def test_countries_endpoint(self):
        r = self.http.get("/geo/countries")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("CC BY 4.0", body["attribution"])
        self.assertNotIn("admin1", body["countries"][0])
        self.assertIn("max-age", r.headers.get("cache-control", ""))

    def test_cities_endpoint(self):
        body = self.http.get("/geo/cities", params={"country": "us", "q": "보스", "limit": 5}).json()
        self.assertEqual((body["country"], body["cities"][0]["label"]), ("US", "보스턴"))

    def test_validation_and_unavailable(self):
        self.assertEqual(self.http.get("/geo/cities", params={"country": "USA"}).status_code, 422)
        self.assertEqual(self.http.get("/geo/cities", params={"country": "ZZ"}).status_code, 404)
        broken = geo.GeoStore(fetch=lambda _p: (_ for _ in ()).throw(geo.GeoError(503, "geo_unavailable")))
        with mock.patch.object(geo, "STORE", broken):
            r = self.http.get("/geo/countries")
        self.assertEqual((r.status_code, r.json()["detail"]), (503, "geo_unavailable"))


if __name__ == "__main__":
    unittest.main()
