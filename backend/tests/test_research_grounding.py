"""/generate 조사 연결(PR5) — 조사된 장소만·조사된 사실만. 네트워크·실제 모델 없음."""
import json
import os
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from app import gemini as ai
from app import main
from app.research import grounding, service
from app.research.cache import ResearchCache

KEY = "JP_1850147"
GUIDE = {"wikivoyage": {"title": "Tokyo", "revid": 1, "sections": {}, "listings": [
    {"type": "see", "name": "Senso-ji", "lat": None, "lon": None, "content": "Tokyo's oldest temple. See http://x.y now.",
     "page": "Tokyo", "section": "See", "url": "", "wikidata": "", "alt": ""},
    {"type": "eat", "name": "Sushi Dai", "lat": None, "lon": None, "content": "Famous sushi breakfast.", "page": "Tokyo",
     "section": "Eat", "url": "", "wikidata": "", "alt": ""}]}}
EXTRA = {"places": [{"id": "wvde:JP_1850147:0", "name": "Ueno Park", "kind": "attraction", "desc_en": "Großer Park.", "desc_lang": "de",
                     "sources": [{"provider": "wikivoyage", "url": "https://de.wikivoyage.org/wiki/Tokio"}]}]}
ENV = {"RESEARCH_ENABLED": "1"}


def cache_with_data():
    c = ResearchCache(use_firestore=False)
    c.put("research_cities", KEY, "guide", GUIDE, 3600, [])
    c.put("research_cities", KEY, "places_extra", EXTRA, 3600, [])
    return c


class GroundTest(unittest.TestCase):
    def test_filters_unknown_research_places_and_keeps_user_places(self):
        places = [{"name": "Senso-ji"}, {"name": "sushi dai"}, {"name": "Ueno Park"}, {"name": "Fake Tower"},
                  {"name": "My Friend's Cafe", "user": True}]
        g = grounding.ground(KEY, places, cache_with_data())
        self.assertEqual(g["status"], "ok")
        self.assertEqual([p["name"] for p in g["places"]], ["Senso-ji", "sushi dai", "Ueno Park", "My Friend's Cafe"])
        self.assertEqual(g["filtered"], ["Fake Tower"])                                       # 422 대신 걸러 냄
        self.assertEqual(g["grounded"], 2)                                                     # 독일어 설명은 영어 프롬프트에 안 넣음
        facts = json.loads(g["clause"].split("\n", 3)[-1])
        self.assertEqual([f["name"] for f in facts], ["Senso-ji", "sushi dai"])
        self.assertNotIn("http", facts[0]["facts"])
        self.assertNotIn("<", facts[0]["facts"])
        self.assertIn("Never invent opening hours, prices", g["clause"])

    def test_miss_and_off_keep_the_old_behaviour(self):
        places = [{"name": "Anything"}]
        self.assertEqual(grounding.ground(None, places, cache_with_data())["status"], "off")
        miss = grounding.ground("JP_999", places, ResearchCache(use_firestore=False))
        self.assertEqual((miss["status"], miss["places"], miss["clause"]), ("miss", places, ""))
        self.assertEqual(grounding.ground("../x", places, cache_with_data())["status"], "miss")

    def test_drop_unrequested_sentences(self):
        pack = {"sentences": [{"en": "a", "place": "Senso-ji"}, {"en": "b", "place": "Invented Diner"}, {"en": "c"}]}
        self.assertEqual(grounding.drop_unrequested(pack, ["Senso-ji"]), ["Invented Diner"])
        self.assertEqual([s["en"] for s in pack["sentences"]], ["a", "c"])
        only_bad = {"sentences": [{"en": "x", "place": "Nope"}]}
        self.assertEqual((grounding.drop_unrequested(only_bad, ["Senso-ji"]), len(only_bad["sentences"])), ([], 1))   # 다 빼지는 않는다


@mock.patch.dict(os.environ, ENV)
class GenerateEndpointTest(unittest.TestCase):
    def setUp(self):
        self.c = TestClient(main.app)
        self.p = mock.patch.object(service, "CACHE", cache_with_data())
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def body(self, **over):
        b = {"category_id": "attraction" if "attraction" in main.list_categories() else "restaurant", "city": "Tokyo",
             "places": [{"name": "Sushi Dai", "place_type": "restaurant"}, {"name": "Fake Tower", "place_type": "restaurant"}],
             "research_key": KEY}
        b.update(over)
        return b

    def test_mock_path_reports_filtering(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            r = self.c.post("/generate", json=self.body(category_id="restaurant"))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["facts"]["research"], {"status": "ok", "filtered": ["Fake Tower"], "grounded": 1})

    def test_prompt_gets_researched_facts_and_unrequested_sentences_are_dropped(self):
        cfg = main.load_category("restaurant")
        good = main.mock_pack(cfg, main.GenerateRequest(category_id="restaurant", city="Tokyo"))
        extra = dict(good["sentences"][0], place="Invented Diner")
        pack = {**good, "sentences": good["sentences"] + [extra]}
        seen = {}

        def fake_generate_text(client, model, prompt, **kw):
            seen["prompt"] = prompt
            return json.dumps(pack)

        def fake_run(what, fn):
            return ai.Result(value=fn(None, "fake-model", 1), attempts=1, model="fake-model", failures=[])
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "k"}), mock.patch.object(ai, "generate_text", fake_generate_text), \
                mock.patch.object(ai, "run", fake_run):
            r = self.c.post("/generate", json=self.body(category_id="restaurant"))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("RESEARCHED_PLACES", seen["prompt"])
        self.assertIn("Famous sushi breakfast.", seen["prompt"])
        self.assertNotIn("Fake Tower", seen["prompt"])                                         # 걸러진 장소는 프롬프트에 없음
        out = r.json()
        self.assertFalse(any(s.get("place") == "Invented Diner" for s in out["pack"]["sentences"]))
        self.assertIn("place_not_in_request", [i["code"] for i in out["issues"]])

    def test_research_off_or_bad_key(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "", "RESEARCH_ENABLED": "0"}):
            r = self.c.post("/generate", json=self.body(category_id="restaurant"))
        self.assertEqual(r.json()["facts"]["research"]["status"], "off")
        self.assertEqual(self.c.post("/generate", json=self.body(category_id="restaurant", research_key="../etc")).status_code, 422)


if __name__ == "__main__":
    unittest.main()
