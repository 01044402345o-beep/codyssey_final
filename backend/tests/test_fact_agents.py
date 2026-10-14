"""사실 에이전트. 네트워크 없이 상태만 본다.  실행: cd backend && python -m unittest tests.test_fact_agents"""
from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from app import main
from app.agents import facts


def _http_raising(url, headers, timeout):  # noqa: ANN001
    raise AssertionError(f"http called: {url}")


class Facts(unittest.TestCase):
    def test_missing_kakao_key_does_not_call_out(self):
        with mock.patch.dict(os.environ, {"KAKAO_REST_API_KEY": ""}, clear=False):
            out = facts.collect_facts(
                category_id="restaurant", city="서울",
                places=[{"name": "산모퉁이", "place_type": "restaurant"}],
                situation_ids=["allergy_notice", "takeout", "order_menu"],
                http=_http_raising,
            )
        self.assertEqual(out["places"]["status"], "unavailable")
        self.assertEqual(out["places"]["reason"], "KAKAO_REST_API_KEY 없음")
        self.assertEqual(out["places"]["items"], [])
        self.assertEqual(out["situations"]["status"], "unavailable")
        self.assertEqual(out["situations"]["reason"], "좌표 없음")

    def test_other_categories_do_not_call_kakao(self):
        with mock.patch.dict(os.environ, {"KAKAO_REST_API_KEY": "kakao-secret"}, clear=False):
            out = facts.collect_facts(
                category_id="transport", city="서울",
                places=[{"name": "서울역", "place_type": "train_station"}],
                situation_ids=["buy_ticket"],
                http=_http_raising,
            )
        self.assertEqual(out["places"]["status"], "unavailable")
        self.assertEqual(out["places"]["reason"], "식당·카페만 조회한다")
        self.assertEqual(out["situations"]["reason"], "이 카테고리에 조회할 상황 사실이 없다")
        self.assertNotIn("kakao-secret", str(out))

    def test_kakao_hit_is_verified_and_osm_reads_tags(self):
        seen: list[tuple[str, dict]] = []

        def http(url, headers, timeout):  # noqa: ANN001
            seen.append((url, headers))
            if "dapi.kakao.com" in url:
                self.assertEqual(headers["Authorization"], "KakaoAK kakao-secret")
                return 200, {"documents": [{
                    "place_name": "산모퉁이",
                    "road_address_name": "서울 종로구",
                    "x": "126.97",
                    "y": "37.57",
                    "place_url": "http://place.map.kakao.com/1",
                }, {
                    "place_name": "출처없음",
                    "x": "126.1",
                    "y": "37.1",
                    "place_url": "",
                }]}
            self.assertIn("overpass-api.de", url)
            self.assertNotIn("Authorization", headers)
            return 200, {"elements": [{
                "type": "node",
                "id": 9,
                "tags": {
                    "amenity": "restaurant",
                    "diet:vegetarian": "yes",
                    "takeaway": "only",
                    "wifi:password": "do-not-keep",
                    "internet_access": "wlan",
                },
            }]}

        with mock.patch.dict(os.environ, {"KAKAO_REST_API_KEY": "kakao-secret"}, clear=False):
            out = facts.collect_facts(
                category_id="restaurant", city="서울",
                places=[{"name": "산모퉁이", "place_type": "restaurant"}],
                situation_ids=["allergy_notice", "takeout", "ask_wifi", "order_menu"],
                http=http,
            )
        self.assertEqual(out["places"]["status"], "verified")
        self.assertEqual(len(out["places"]["items"]), 1)
        place = out["places"]["items"][0]
        self.assertEqual(place["lat"], 37.57)
        self.assertEqual(place["lon"], 126.97)
        self.assertEqual(place["source_url"], "http://place.map.kakao.com/1")
        ids = {item["situation_id"] for item in out["situations"]["items"]}
        self.assertEqual(ids, {"allergy_notice", "takeout", "ask_wifi"})
        self.assertNotIn("do-not-keep", str(out))
        wifi = next(item for item in out["situations"]["items"] if item["situation_id"] == "ask_wifi")
        self.assertEqual(wifi["value"]["internet_access"], "wlan")
        self.assertTrue(all(item["source_url"].startswith("https://www.openstreetmap.org/")
                            for item in out["situations"]["items"]))
        self.assertEqual(len(seen), 2)
        self.assertTrue(all("maps.googleapis.com" not in url and "places.googleapis.com" not in url
                            for url, _ in seen))

    def test_zero_results_are_not_a_silent_success(self):
        def http(url, headers, timeout):  # noqa: ANN001
            return 200, {"documents": []}

        with mock.patch.dict(os.environ, {"KAKAO_REST_API_KEY": "k"}, clear=False):
            out = facts.collect_facts(
                category_id="restaurant", city="서울", places=[],
                situation_ids=["takeout"], http=http,
            )
        self.assertEqual(out["places"]["status"], "unavailable")
        self.assertEqual(out["places"]["reason"], "검색 결과 0건")
        self.assertEqual(out["situations"]["reason"], "좌표 없음")

    def test_kakao_http_error_is_failed_and_hides_the_key(self):
        def http(url, headers, timeout):  # noqa: ANN001
            raise RuntimeError("boom kakao-secret leaked")

        with mock.patch.dict(os.environ, {"KAKAO_REST_API_KEY": "kakao-secret"}, clear=False):
            out = facts.collect_facts(
                category_id="restaurant", city="서울", places=[],
                situation_ids=["takeout"], http=http,
            )
        self.assertEqual(out["places"]["status"], "failed")
        self.assertNotIn("kakao-secret", out["places"]["reason"])

    def test_osm_http_error_is_failed(self):
        def http(url, headers, timeout):  # noqa: ANN001
            if "dapi.kakao.com" in url:
                return 200, {"documents": [{
                    "place_name": "산모퉁이", "x": "126.9", "y": "37.5",
                    "place_url": "http://place.map.kakao.com/1",
                }]}
            return 429, {}

        with mock.patch.dict(os.environ, {"KAKAO_REST_API_KEY": "k"}, clear=False):
            out = facts.collect_facts(
                category_id="restaurant", city="서울", places=[],
                situation_ids=["takeout"], http=http,
            )
        self.assertEqual(out["places"]["status"], "verified")
        self.assertEqual(out["situations"]["status"], "failed")
        self.assertEqual(out["situations"]["reason"], "osm http 429")

    def test_google_key_is_not_a_kakao_fallback(self):
        source = Path(facts.__file__).read_text(encoding="utf-8")
        self.assertNotIn("maps.googleapis.com", source)
        self.assertNotIn("places.googleapis.com", source)
        self.assertNotIn("GOOGLE_MAPS_API_KEY", source)
        with mock.patch.dict(os.environ, {
            "GOOGLE_MAPS_API_KEY": "google-secret",
            "KAKAO_REST_API_KEY": "",
        }, clear=False):
            out = facts.collect_facts(
                category_id="restaurant", city="서울", places=[],
                situation_ids=["takeout"], http=_http_raising,
            )
        self.assertEqual(out["places"]["reason"], "KAKAO_REST_API_KEY 없음")
        self.assertNotIn("google-secret", str(out))

    def test_prompt_marks_unverified_items_as_not_facts(self):
        cfg = main.load_category("restaurant")
        req = main.GenerateRequest(category_id="restaurant", city="서울")
        text = main.build_prompt(cfg, req, {
            "places": {"status": "unavailable", "reason": "검색 결과 0건", "items": []},
            "situations": {"status": "unavailable", "reason": "좌표 없음", "items": []},
        })
        self.assertIn("VERIFIED_FACTS:", text)
        self.assertIn("Only items with status verified are facts.", text)
        self.assertIn("검색 결과 0건", text)


class GenerateKeepsSentencePath(unittest.TestCase):
    def setUp(self):
        main._hits.clear()
        self.env = mock.patch.dict(os.environ, {}, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)
        os.environ.pop("GEMINI_API_KEY", None)
        os.environ.pop("KAKAO_REST_API_KEY", None)
        self.http = TestClient(main.app)

    def test_sample_generate_reports_facts_without_calling_out(self):
        with mock.patch("app.main.collect_facts", wraps=facts.collect_facts) as called:
            res = self.http.post("/generate", json={
                "category_id": "restaurant", "city": "서울",
                "places": [{"name": "산모퉁이", "place_type": "restaurant"}],
            })
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertTrue(body["mock"])
        self.assertEqual(body["attempts"], 0)
        self.assertEqual(body["facts"]["places"]["status"], "unavailable")
        self.assertEqual(body["facts"]["places"]["reason"], "KAKAO_REST_API_KEY 없음")
        called.assert_called()

    def test_health_lists_fact_agents_without_google_places(self):
        health = self.http.get("/health").json()
        self.assertEqual(health["fact_agents"]["google_places"], False)
        self.assertEqual(health["fact_agents"]["osm"], "no-key")
        self.assertIs(health["fact_agents"]["kakao"], False)
