"""일정 오케스트레이터. 네트워크 없이 상태만 본다.

실행: cd backend && python -m unittest tests.test_itinerary
"""
from __future__ import annotations

import json
import os
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from fastapi.testclient import TestClient

from app import gemini as ai
from app import main
from app.agents import itinerary
from app.validators import validate_pack

MASK_EXCLUDED = (
    "rating", "userRatingCount", "regularOpeningHours", "priceLevel",
    "currentOpeningHours", "dineIn", "delivery", "reservable",
    "paymentOptions", "parkingOptions", "websiteUri",
)


def _place(pid="p1", name="Joe's Pizza", lat=40.7, lon=-74.0,
           uri="https://maps.google.com/?cid=1", status="OPERATIONAL", **over):
    item = {
        "id": pid,
        "displayName": {"text": name},
        "formattedAddress": "7 Carmine St, New York, NY",
        "location": {"latitude": lat, "longitude": lon},
        "primaryType": "pizza_restaurant",
        "businessStatus": status,
        "googleMapsUri": uri,
    }
    item.update(over)
    return item


def _sentence(pid="p1", name="Joe's Pizza", day=1):
    return {"days": [{"day": day, "blocks": [{
        "time_label": "morning",
        "place_id": pid,
        "sentence_en": f"Could we get a table at {name}, please?",
        "sentence_ko": "",
        "source_url": "https://map.kakao.com/",
        "why": "rated 4.9 and open now",
    }]}]}


_ENV_KEYS = ("ITINERARY_ENABLED", "GOOGLE_MAPS_API_KEY", "GEMINI_API_KEY",
             "KAKAO_REST_API_KEY", "ITINERARY_DAILY_CAP")


class ItineraryTests(unittest.TestCase):
    def setUp(self):
        main._hits.clear()
        itinerary.reset_daily_cap()
        self.http_calls: list[tuple] = []
        self.runs: list[str] = []
        self.gen_config: list[dict] = []
        self._saved = {key: os.environ.get(key) for key in _ENV_KEYS}
        for key in _ENV_KEYS:
            os.environ.pop(key, None)
        self.client = TestClient(main.app)

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        itinerary.reset_daily_cap()
        main._hits.clear()

    def _env(self, **env: str) -> None:
        for key in ("ITINERARY_ENABLED", "GOOGLE_MAPS_API_KEY", "GEMINI_API_KEY",
                    "KAKAO_REST_API_KEY", "ITINERARY_DAILY_CAP"):
            os.environ.pop(key, None)
        os.environ.update(env)

    def _req(self, **kw):
        data = {"city": "뉴욕", "days": 1, "start_date": "2026-10-15",
                "places": [], "itinerary_kinds": ["restaurant"]}
        data.update(kw)
        return SimpleNamespace(**data)

    def _http(self, payload):
        def http(url, body, headers, timeout):  # noqa: ANN001
            self.http_calls.append((url, body, dict(headers), timeout))
            if "dapi.kakao.com" in url:
                raise AssertionError(url)
            return 200, payload
        return http

    def _run(self, payload):
        def run(what, fn):
            self.runs.append(what)

            def generate_text(client, model, contents, **config):  # noqa: ANN001
                self.gen_config.append(config)
                return json.dumps(payload)

            with mock.patch("app.agents.itinerary.ai.generate_text", side_effect=generate_text):
                value = fn(None, "gemini-test", 1)
            return ai.Result(value=value, attempts=1, model="gemini-test", failures=[])
        return run

    def test_flag_off_makes_no_http_and_no_prose(self):
        self._env(ITINERARY_ENABLED="0", GOOGLE_MAPS_API_KEY="g", GEMINI_API_KEY="gem")

        def boom(*_a, **_k):
            raise AssertionError("called")

        out = itinerary.collect_itinerary(self._req(), http=boom, run=boom)
        self.assertEqual(out, {"status": "unavailable", "reason": "itinerary_disabled"})

    def test_missing_google_key_skips_http_and_prose(self):
        self._env(ITINERARY_ENABLED="1", GEMINI_API_KEY="gem")

        def boom(*_a, **_k):
            raise AssertionError("called")

        out = itinerary.collect_itinerary(self._req(), http=boom, run=boom)
        self.assertEqual(out["reason"], "missing_google_key")
        self.assertEqual(self.http_calls, [])
        self.assertEqual(self.runs, [])

    def test_bad_date_does_not_call_out(self):
        self._env(ITINERARY_ENABLED="1", GOOGLE_MAPS_API_KEY="g", GEMINI_API_KEY="gem")

        def boom(*_a, **_k):
            raise AssertionError("called")

        out = itinerary.collect_itinerary(
            self._req(start_date="2026-02-31"), http=boom, run=boom)
        self.assertEqual(out["reason"], "bad_date")

    def test_bad_date_keeps_the_sentence_pack(self):
        self._env(ITINERARY_ENABLED="1", GOOGLE_MAPS_API_KEY="g")
        res = self.client.post("/generate", json={
            "category_id": "restaurant", "city": "뉴욕",
            "start_date": "2026-02-31", "itinerary_kinds": ["restaurant"],
            "places": [{"name": "Joe's Pizza", "place_type": "restaurant"}],
        })
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["itinerary"]["reason"], "bad_date")
        self.assertNotIn("itinerary", body["pack"])
        issues = validate_pack(body["pack"], main.load_category("restaurant"), [], main.load_schema())
        self.assertFalse(any(i["severity"] == "block" for i in issues))

    def test_place_without_coordinates_is_dropped_and_not_reinserted(self):
        self._env(ITINERARY_ENABLED="1", GOOGLE_MAPS_API_KEY="g")
        raw = {"places": [_place(lat=None, lon=None), _place(pid="p2", name="Katz's Delicatessen")]}
        raw["places"][0]["location"] = {}
        out = itinerary.collect_itinerary(
            self._req(), http=self._http(raw), run=self._run(_sentence(pid="p2", name="Katz's Delicatessen")))
        self.assertEqual([p["provider_id"] for p in out["places"]], ["p2"])
        self.assertNotEqual(out["places"], raw["places"])

    def test_zero_coordinates_stay(self):
        self._env(ITINERARY_ENABLED="1", GOOGLE_MAPS_API_KEY="g", GEMINI_API_KEY="gem")
        out = itinerary.collect_itinerary(
            self._req(),
            http=self._http({"places": [_place(lat=0, lon=0)]}),
            run=self._run(_sentence()))
        self.assertEqual(out["places"][0]["lat"], 0)
        self.assertEqual(out["places"][0]["lon"], 0)
        self.assertEqual(out["status"], "verified")

    def test_invented_place_is_stripped_without_a_second_call(self):
        self._env(ITINERARY_ENABLED="1", GOOGLE_MAPS_API_KEY="g", GEMINI_API_KEY="gem")
        invented = _sentence()
        invented["days"][0]["blocks"][0]["place_id"] = "not-in-the-list"
        out = itinerary.collect_itinerary(
            self._req(), http=self._http({"places": [_place()]}), run=self._run(invented))
        self.assertEqual(self.runs, ["itinerary"])
        self.assertEqual(out["reason"], "all_days_empty")
        self.assertEqual(out["days"][0]["blocks"], [])

    def test_block_without_place_id_is_dropped(self):
        self._env(ITINERARY_ENABLED="1", GOOGLE_MAPS_API_KEY="g", GEMINI_API_KEY="gem")
        payload = _sentence()
        del payload["days"][0]["blocks"][0]["place_id"]
        out = itinerary.collect_itinerary(
            self._req(), http=self._http({"places": [_place()]}), run=self._run(payload))
        self.assertEqual(out["days"][0]["blocks"], [])

    def test_kakao_homepage_is_not_verified(self):
        self._env(ITINERARY_ENABLED="1", GOOGLE_MAPS_API_KEY="g")

        def boom(*_a, **_k):
            raise AssertionError("prose")

        out = itinerary.collect_itinerary(
            self._req(),
            http=self._http({"places": [_place(uri="https://map.kakao.com/")]}),
            run=boom)
        self.assertEqual(out["reason"], "no_verified_places")
        self.assertEqual(out["places"], [])
        self.assertEqual(self.runs, [])

    def test_closed_permanently_is_dropped(self):
        self._env(ITINERARY_ENABLED="1", GOOGLE_MAPS_API_KEY="g")
        out = itinerary.collect_itinerary(
            self._req(),
            http=self._http({"places": [_place(status="CLOSED_PERMANENTLY")]}),
            run=lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("prose")))
        self.assertEqual(out["places"], [])

    def test_sentence_must_contain_the_verified_name(self):
        self._env(ITINERARY_ENABLED="1", GOOGLE_MAPS_API_KEY="g", GEMINI_API_KEY="gem")
        payload = _sentence()
        payload["days"][0]["blocks"][0]["sentence_en"] = "Could we get a table, please?"
        out = itinerary.collect_itinerary(
            self._req(), http=self._http({"places": [_place()]}), run=self._run(payload))
        self.assertEqual(out["days"][0]["reason"], "day_empty")

    def test_field_mask_is_pro_only_and_kakao_is_not_called_for_new_york(self):
        self._env(ITINERARY_ENABLED="1", GOOGLE_MAPS_API_KEY="g", GEMINI_API_KEY="gem",
                  KAKAO_REST_API_KEY="kakao")
        out = itinerary.collect_itinerary(
            self._req(city="뉴욕"),
            http=self._http({"places": [_place()]}),
            run=self._run(_sentence()))
        self.assertEqual(out["status"], "verified")
        url, body, headers, timeout = self.http_calls[0]
        self.assertEqual(url, itinerary.SEARCH_URL)
        self.assertNotIn("dapi.kakao.com", url)
        self.assertEqual(headers["X-Goog-FieldMask"], itinerary.FIELD_MASK)
        for name in MASK_EXCLUDED:
            self.assertNotIn(name, headers["X-Goog-FieldMask"])
        parsed = json.loads(body)
        self.assertEqual(parsed["maxResultCount"], 5)
        self.assertNotIn("pageToken", parsed)
        self.assertEqual(parsed["textQuery"], "뉴욕 restaurant")
        self.assertEqual(timeout, 8.0)
        block = out["days"][0]["blocks"][0]
        self.assertEqual(block["source_url"], "https://maps.google.com/?cid=1")
        self.assertNotIn("4.9", block["why"])
        self.assertEqual(self.gen_config[0]["temperature"], 0.2)
        self.assertEqual(self.gen_config[0]["max_output_tokens"], 2048)
        self.assertNotIn("itinerary", out)

    def test_zero_verified_places_do_not_call_prose(self):
        self._env(ITINERARY_ENABLED="1", GOOGLE_MAPS_API_KEY="g", GEMINI_API_KEY="gem")

        def boom(*_a, **_k):
            raise AssertionError("prose")

        out = itinerary.collect_itinerary(
            self._req(), http=self._http({"places": []}), run=boom)
        self.assertEqual(out["reason"], "no_verified_places")
        self.assertEqual(self.runs, [])

    def test_daily_cap_stops_further_place_calls(self):
        self._env(ITINERARY_ENABLED="1", GOOGLE_MAPS_API_KEY="g", ITINERARY_DAILY_CAP="1")
        out = itinerary.collect_itinerary(
            self._req(itinerary_kinds=["restaurant", "cafe"]),
            http=self._http({"places": [_place()]}),
            run=lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no gemini key path")))
        self.assertEqual(len(self.http_calls), 1)
        reasons = [q["reason"] for q in out["queries"]]
        self.assertIn("daily_cap", reasons)

    def test_daily_cap_zero_makes_no_http(self):
        self._env(ITINERARY_ENABLED="1", GOOGLE_MAPS_API_KEY="g", ITINERARY_DAILY_CAP="0")

        def boom(*_a, **_k):
            raise AssertionError("called")

        out = itinerary.collect_itinerary(self._req(), http=boom, run=boom)
        self.assertEqual(out["reason"], "daily_cap")

    def test_health_matrix_follows_the_environment_after_import(self):
        cases = (
            ({}, False, False, False),
            ({"GOOGLE_MAPS_API_KEY": "g"}, False, True, False),
            ({"ITINERARY_ENABLED": "1"}, True, False, False),
            ({"ITINERARY_ENABLED": "1", "GOOGLE_MAPS_API_KEY": "g"}, True, True, True),
        )
        for env, enabled, configured, calling in cases:
            self._env(**env)
            health = self.client.get("/health").json()
            self.assertIs(health["itinerary_enabled"], enabled)
            self.assertIs(health["fact_agents"]["google_places_configured"], configured)
            self.assertIs(health["fact_agents"]["itinerary_calling"], calling)
            self.assertIs(health["fact_agents"]["google_places"], False)
            self.assertIs(health["fact_agents"]["sources_ready"], False)

    def test_flag_off_generate_keeps_a_valid_pack(self):
        self._env(GOOGLE_MAPS_API_KEY="g", GEMINI_API_KEY="")
        res = self.client.post("/generate", json={
            "category_id": "restaurant", "city": "뉴욕",
            "places": [{"name": "Joe's Pizza", "place_type": "restaurant"}],
        })
        body = res.json()
        self.assertEqual(body["itinerary"], {"status": "unavailable", "reason": "itinerary_disabled"})
        self.assertNotIn("itinerary", body["pack"])
        self.assertTrue(body["mock"])
        issues = validate_pack(body["pack"], main.load_category("restaurant"), [], main.load_schema())
        self.assertFalse(any(i["severity"] == "block" for i in issues))

    def test_sentence_and_itinerary_overlap(self):
        order: list[str] = []

        def slow_run(what, fn):  # noqa: ANN001
            order.append("sentence_start")
            time.sleep(0.2)
            order.append("sentence_end")
            pack = {"category_id": "restaurant", "city": "뉴욕", "sentences": []}
            return ai.Result(value=(pack, []), attempts=1, model="m", failures=[])

        def slow_it(req):  # noqa: ANN001
            order.append("it_start")
            time.sleep(0.2)
            order.append("it_end")
            return {"status": "unavailable", "reason": "itinerary_disabled"}

        self._env(GEMINI_API_KEY="gem")
        with mock.patch("app.main.ai.run", side_effect=slow_run), \
                mock.patch("app.main.collect_itinerary", side_effect=slow_it):
            started = time.perf_counter()
            res = self.client.post("/generate", json={"category_id": "restaurant", "city": "뉴욕"})
            elapsed = time.perf_counter() - started
        self.assertEqual(res.status_code, 200)
        self.assertLess(order.index("it_start"), order.index("sentence_end"))
        self.assertLess(order.index("sentence_start"), order.index("it_end"))
        self.assertLess(elapsed, 0.35)
        self.assertEqual(res.json()["itinerary"]["reason"], "itinerary_disabled")


if __name__ == "__main__":
    unittest.main()
