"""사실 에이전트. 네트워크 없이 상태만 본다.  실행: cd backend && python -m unittest tests.test_fact_agents"""
from __future__ import annotations

import inspect
import os
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from app import main
from app.agents import facts


def _http_raising(url, headers, timeout):  # noqa: ANN001
    raise AssertionError(f"http called: {url}")


def _kakao_doc(name, x="126.97", y="37.57", url="http://place.map.kakao.com/1"):
    return {"place_name": name, "road_address_name": "서울 종로구", "x": x, "y": y, "place_url": url}


class AllergyIsNotDiet(unittest.TestCase):
    """allergy_notice 를 diet:* 로 채우지 않는다. diet:vegetarian=yes 는 채식 메뉴가 있다는
    뜻이고 알레르기 안전과 다른 주장인데, verified 로 올라가면 프롬프트가 사실로 취급한다."""

    def test_allergy_notice_is_not_an_osm_situation(self):
        self.assertNotIn("allergy_notice", facts.OSM_SITUATIONS)

    def test_diet_tags_produce_no_allergy_fact(self):
        def http(url, headers, timeout):  # noqa: ANN001
            if "dapi.kakao.com" in url:
                return 200, {"documents": [_kakao_doc("산모퉁이")]}
            return 200, {"elements": [{
                "type": "node", "id": 9,
                "tags": {"amenity": "restaurant", "diet:vegetarian": "yes",
                         "takeaway": "only", "internet_access": "wlan"},
            }]}

        with mock.patch.dict(os.environ, {"KAKAO_REST_API_KEY": "k"}, clear=False):
            located = facts._kakao_places("서울", [{"name": "산모퉁이", "place_type": "restaurant"}], http, 5.0)
            out = facts._osm_facts(["allergy_notice", "takeout", "ask_wifi", "order_menu"], located, http, 8.0)
        ids = {i["situation_id"] for i in out["items"]}
        self.assertNotIn("allergy_notice", ids)
        self.assertEqual(ids, {"takeout", "ask_wifi"})
        self.assertNotIn("diet", str(out))


class RequestedPlaceMustMatch(unittest.TestCase):
    """요청한 장소와 이름이 맞는 응답만 사실로 올린다."""

    def test_unmatched_documents_are_dropped(self):
        def http(url, headers, timeout):  # noqa: ANN001
            return 200, {"documents": [
                _kakao_doc("다른가게"), _kakao_doc("또다른가게"), _kakao_doc("산모퉁이"),
            ]}

        with mock.patch.dict(os.environ, {"KAKAO_REST_API_KEY": "k"}, clear=False):
            out = facts._kakao_places("서울", [{"name": "산모퉁이", "place_type": "restaurant"}], http, 5.0)
        self.assertEqual(out["status"], "verified")
        self.assertEqual([i["name"] for i in out["items"]], ["산모퉁이"])
        self.assertIn("2건", out["reason"])

    def test_no_match_is_unavailable_not_a_wrong_place(self):
        def http(url, headers, timeout):  # noqa: ANN001
            return 200, {"documents": [_kakao_doc("다른가게"), _kakao_doc("또다른가게")]}

        with mock.patch.dict(os.environ, {"KAKAO_REST_API_KEY": "k"}, clear=False):
            out = facts._kakao_places("서울", [{"name": "Joe's Pizza", "place_type": "restaurant"}], http, 5.0)
        self.assertEqual(out["status"], "unavailable")
        self.assertEqual(out["items"], [])

    def test_no_requested_name_means_no_verdict(self):
        with mock.patch.dict(os.environ, {"KAKAO_REST_API_KEY": "k"}, clear=False):
            out = facts._kakao_places("서울", [], _http_raising, 5.0)
        self.assertEqual(out["status"], "unavailable")
        self.assertIn("대조", out["reason"])

    def test_same_place_normalizes_case_and_punctuation(self):
        self.assertTrue(facts._same_place("Joe's Pizza", "JOES  PIZZA"))
        self.assertTrue(facts._same_place("Joe's Pizza", "Joe's Pizza Greenwich Village"))
        self.assertFalse(facts._same_place("Joe's Pizza", "Ess-a-Bagel"))
        self.assertFalse(facts._same_place("Joe's Pizza", "Pizza"))
        self.assertFalse(facts._same_place("Joe's Pizza", "Not Joe's Pizza"))
        self.assertFalse(facts._same_place("Joe's Pizza", "Joe's Famous Pizza"))
        self.assertFalse(facts._same_place("Pizza", "Joe's Pizza"))
        self.assertFalse(facts._same_place("Bagel", "Ess-a-Bagel"))
        self.assertFalse(facts._same_place("", "아무가게"))
        self.assertFalse(facts._same_place("A", "아무가게"))   # 한 글자 조각은 오탐이 된다


class KoreaOnlyScope(unittest.TestCase):
    def test_foreign_city_makes_no_call(self):
        with mock.patch.dict(os.environ, {"KAKAO_REST_API_KEY": "kakao-secret"}, clear=False):
            out = facts._kakao_places("뉴욕", [{"name": "Joe's Pizza", "place_type": "restaurant"}],
                                      _http_raising, 5.0)
        self.assertEqual(out["status"], "unavailable")
        self.assertIn("한국", out["reason"])

    def test_korean_city_is_in_scope(self):
        self.assertTrue(facts._kakao_in_scope("서울"))
        for city in ("뉴욕", "보스턴", "오사카", "런던", "파리", "도쿄", "시드니", "타이베이"):
            self.assertFalse(facts._kakao_in_scope(city), city)


class SourcesAreOff(unittest.TestCase):
    """키를 넣지 않기로 한 결정을 코드로도 막는다."""

    def test_flag_is_false(self):
        self.assertFalse(facts.FACT_SOURCES_READY)

    def test_key_present_still_makes_no_external_call(self):
        with mock.patch.dict(os.environ, {"KAKAO_REST_API_KEY": "kakao-secret"}, clear=False):
            out = facts.collect_facts(
                category_id="restaurant", city="뉴욕",
                places=[{"name": "Joe's Pizza", "place_type": "restaurant"}],
                situation_ids=["takeout", "ask_wifi"], http=_http_raising,
            )
        self.assertEqual(out["places"]["status"], "unavailable")
        self.assertEqual(out["situations"]["status"], "unavailable")
        self.assertNotIn("kakao-secret", str(out))

    def test_collect_facts_does_not_wire_the_provider(self):
        src = inspect.getsource(facts.collect_facts)
        for bad in ("_kakao_places", "_osm_facts", "_default_http"):
            self.assertNotIn(bad, src)


class ProviderBehavior(unittest.TestCase):
    def test_happy_path_and_tag_filtering(self):
        seen: list[tuple[str, dict]] = []

        def http(url, headers, timeout):  # noqa: ANN001
            seen.append((url, headers))
            if "dapi.kakao.com" in url:
                self.assertEqual(headers["Authorization"], "KakaoAK kakao-secret")
                return 200, {"documents": [_kakao_doc("산모퉁이"), _kakao_doc("출처없음", url="")]}
            self.assertIn("overpass-api.de", url)
            self.assertNotIn("Authorization", headers)
            return 200, {"elements": [{
                "type": "node", "id": 9,
                "tags": {"amenity": "restaurant", "takeaway": "only",
                         "wifi:password": "do-not-keep", "internet_access": "wlan"},
            }]}

        with mock.patch.dict(os.environ, {"KAKAO_REST_API_KEY": "kakao-secret"}, clear=False):
            located = facts._kakao_places("서울", [{"name": "산모퉁이", "place_type": "restaurant"}], http, 5.0)
            out = facts._osm_facts(["takeout", "ask_wifi"], located, http, 8.0)
        self.assertEqual(located["status"], "verified")
        self.assertEqual(len(located["items"]), 1)
        self.assertEqual(located["items"][0]["lat"], 37.57)
        self.assertEqual(located["items"][0]["lon"], 126.97)
        self.assertEqual(located["items"][0]["source_url"], "http://place.map.kakao.com/1")
        self.assertEqual({i["situation_id"] for i in out["items"]}, {"takeout", "ask_wifi"})
        self.assertNotIn("do-not-keep", str({"p": located, "s": out}))
        self.assertEqual(len(seen), 2)
        self.assertTrue(all("maps.googleapis.com" not in u and "places.googleapis.com" not in u for u, _ in seen))

    def test_zero_results_are_not_a_silent_success(self):
        def http(url, headers, timeout):  # noqa: ANN001
            return 200, {"documents": []}

        with mock.patch.dict(os.environ, {"KAKAO_REST_API_KEY": "k"}, clear=False):
            located = facts._kakao_places("서울", [{"name": "산모퉁이"}], http, 5.0)
        self.assertEqual(located["status"], "unavailable")
        self.assertEqual(located["reason"], "검색 결과 0건")

    def test_missing_key_is_unavailable(self):
        with mock.patch.dict(os.environ, {"KAKAO_REST_API_KEY": ""}, clear=False):
            located = facts._kakao_places("서울", [{"name": "산모퉁이"}], _http_raising, 5.0)
        self.assertEqual(located["status"], "unavailable")
        self.assertEqual(located["reason"], "KAKAO_REST_API_KEY 없음")

    def test_http_error_is_failed_and_hides_the_key(self):
        def http(url, headers, timeout):  # noqa: ANN001
            raise RuntimeError("boom kakao-secret leaked")

        with mock.patch.dict(os.environ, {"KAKAO_REST_API_KEY": "kakao-secret"}, clear=False):
            located = facts._kakao_places("서울", [{"name": "산모퉁이"}], http, 5.0)
        self.assertEqual(located["status"], "failed")
        self.assertNotIn("kakao-secret", located["reason"])

    def test_osm_without_coordinates_is_unavailable(self):
        out = facts._osm_facts(["takeout"], {"status": "unavailable", "items": []}, _http_raising, 8.0)
        self.assertEqual(out["status"], "unavailable")
        self.assertEqual(out["reason"], "좌표 없음")

    def test_osm_http_error_is_failed(self):
        out = facts._osm_facts(["takeout"], {"status": "verified", "items": [{"lat": 37.5, "lon": 126.9}]},
                               lambda u, h, t: (429, {}), 8.0)
        self.assertEqual(out["status"], "failed")
        self.assertEqual(out["reason"], "osm http 429")

    def test_google_key_is_not_a_kakao_fallback(self):
        source = Path(facts.__file__).read_text(encoding="utf-8")
        self.assertNotIn("maps.googleapis.com", source)
        self.assertNotIn("places.googleapis.com", source)
        self.assertNotIn("GOOGLE_MAPS_API_KEY", source)
        with mock.patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "google-secret",
                                          "KAKAO_REST_API_KEY": ""}, clear=False):
            out = facts.collect_facts(category_id="restaurant", city="서울", places=[],
                                      situation_ids=["takeout"], http=_http_raising)
        self.assertNotIn("google-secret", str(out))

    def test_prompt_marks_unverified_items_as_not_facts(self):
        cfg = main.load_category("restaurant")
        req = main.GenerateRequest(category_id="restaurant", city="서울")
        text = main.build_prompt(cfg, req, {
            "places": {"status": "unavailable", "reason": "사실 공급원 없음", "items": []},
            "situations": {"status": "unavailable", "reason": "좌표 공급원 없음", "items": []},
        })
        self.assertIn("VERIFIED_FACTS:", text)
        self.assertIn("Only items with status verified are facts.", text)
        self.assertIn("사실 공급원 없음", text)


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
        self.assertIn("한국", body["facts"]["places"]["reason"])
        called.assert_called()

    def test_health_reports_sources_off(self):
        health = main.health_detail()
        self.assertEqual(health["fact_agents"]["google_places"], False)
        self.assertEqual(health["fact_agents"]["osm"], "no-key")
        self.assertIs(health["fact_agents"]["kakao"], False)
        self.assertIs(health["fact_agents"]["sources_ready"], False)
