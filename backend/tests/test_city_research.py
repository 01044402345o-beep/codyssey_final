"""도시 브리프(백업 경로, agents/city_research) — 네트워크 없이 계약만 검증한다(소스는 스텁).

다른 에이전트의 스크립트형 테스트(18개 검사)를 unittest 로 옮겼다. 실행: cd backend && python -m unittest discover -s tests -t .
"""
import os
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from app import main
from app.agents import city_research as cr

KO = {"extract": "뉴욕은 미국 뉴욕주 남부의 항구 도시다. 세계 금융의 중심지 가운데 하나다.",
      "title": "뉴욕", "description": "미국 뉴욕주의 도시", "coordinates": {"lat": 40.7128, "lon": -74.0060},
      "content_urls": {"desktop": {"page": "https://ko.wikipedia.org/wiki/뉴욕"}}}
EN = {"extract": "New York City is the most populous city in the United States. It is a global financial hub.",
      "title": "New York City", "coordinates": {"lat": 40.7128, "lon": -74.0060},
      "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/New_York_City"}}}
WV = {"query": {"pages": {"24468": {"title": "New York City",
      "extract": "New York City is a huge city. Understand The city has five boroughs. Get in By air. Eat Bagels are everywhere.",
      "coordinates": [{"lat": 40.7128, "lon": -74.006}]}}}}
WD = {"search": [{"id": "Q60"}], "entities": {"Q60": {"claims": {
      "P1082": [{"mainsnak": {"datavalue": {"value": {"amount": "+8804190"}}}}],
      "P625": [{"mainsnak": {"datavalue": {"value": {"latitude": 40.7128, "longitude": -74.006}}}}]}}}}


def make(ko=KO, en=EN, wv=WV, wd=WD, calls=None):
    def fetch(url):
        if calls is not None:
            calls.append(url)
        if "wikidata.org" in url:
            return wd
        if "wikivoyage.org" in url:
            return wv
        if "ko.wikipedia.org" in url:
            return ko
        if "en.wikipedia.org" in url:
            return en
        raise AssertionError("unexpected url " + url)
    return fetch


class CityBriefTest(unittest.TestCase):
    def setUp(self):
        cr.clear_cache()

    def test_brief_from_four_sources_with_sources_per_paragraph(self):
        r = cr.research("미국", "뉴욕", "ko", fetch=make())
        self.assertTrue(r["ok"])
        self.assertIn(r["confidence"], ("verified", "partial", "single_source"))
        self.assertEqual(r["sections"][0]["source"], "wikipedia:ko")                    # 한국어 요약을 먼저
        self.assertIn("뉴욕", r["sections"][0]["text"])
        self.assertTrue(any(s["source"].startswith("wikivoyage") for s in r["sections"]))
        self.assertTrue(any(s["kind"] == "facts" and "8,804,190" in s["text"] for s in r["sections"]))
        self.assertLess(abs(r["coords"][0] - 40.7128), 0.01)
        self.assertTrue(all(s["url"] or s["source"] == "llm" for s in r["sections"]))
        self.assertEqual(len(r["sources"]), 4)

    def test_cache_means_no_second_fetch(self):
        cr.research("미국", "뉴욕", "ko", fetch=make())
        calls = []
        r2 = cr.research("미국", "뉴욕", "ko", fetch=make(calls=calls))
        self.assertEqual((r2["cached"], calls), (True, []))

    def test_coordinates_far_apart_are_dropped_with_reason(self):
        bad = dict(KO, coordinates={"lat": 51.5, "lon": -0.12})                          # 런던
        r = cr.research("미국", "뉴욕", "ko", fetch=make(ko=bad))
        self.assertIsNone(r["coords"])
        self.assertTrue(any("어긋" in g for g in r["gaps"]))

    def test_all_sources_dead_is_not_success(self):
        def dead(url):
            raise TimeoutError("boom")
        r = cr.research("미국", "뉴욕", "ko", fetch=dead)
        self.assertEqual((r["ok"], r["confidence"], r["sections"]), (False, "unavailable", []))
        self.assertTrue(r["gaps"])

    def test_single_source_and_homonym_guard_and_input(self):
        r = cr.research("미국", "뉴욕", "ko", fetch=make(en={"extract": "", "title": "New York City"},
                                                    wv={"query": {"pages": {"1": {"missing": ""}}}}, wd={"search": []}))
        self.assertEqual(r["confidence"], "single_source")
        self.assertTrue(r["ok"] and r["sections"])
        cr.clear_cache()
        r6 = cr.research("미국", "뉴욕", "ko", fetch=make(ko={**KO, "title": "뉴욕 (소설)"}))
        self.assertTrue(any("동명이인" in g for g in r6["gaps"]))
        with self.assertRaises(cr.ResearchError):
            cr.research("미국", "  ", "ko", fetch=make())

    def test_disambiguation_page_is_skipped_and_wikidata_title_is_used(self):
        # 한국어 '파리' 는 동음이의 문서 — 위키데이터 항목의 kowiki 제목 '파리 (프랑스)' 로 다시 부른다(괄호가 있어도 믿는다)
        disamb = {"type": "disambiguation", "extract": "파리는 다음을 의미한다. 파리: 곤충.", "title": "파리"}
        paris = {"extract": "파리는 프랑스의 수도이다.", "title": "파리 (프랑스)", "coordinates": {"lat": 48.85, "lon": 2.35},
                 "content_urls": {"desktop": {"page": "https://ko.wikipedia.org/wiki/파리_(프랑스)"}}}
        wd = {"search": [{"id": "Q90"}], "entities": {"Q90": {"claims": {},
              "sitelinks": {"kowiki": {"title": "파리 (프랑스)"}, "enwiki": {"title": "Paris"}}}}}

        def fetch(url):
            if "wikidata.org" in url:
                return wd
            if "ko.wikipedia.org" in url:
                return paris if "%28" in url or "(" in url else disamb
            if "en.wikipedia.org" in url:
                return {**EN, "title": "Paris", "extract": "Paris is the capital of France.", "coordinates": {"lat": 48.85, "lon": 2.35}}
            return {"query": {"pages": {"1": {"missing": ""}}}}
        r = cr.research("프랑스", "파리", "ko", fetch=fetch)
        self.assertEqual(r["sections"][0]["source"], "wikipedia:ko")
        self.assertIn("프랑스의 수도", r["sections"][0]["text"])
        self.assertFalse(any("곤충" in s["text"] for s in r["sections"]))
        self.assertFalse(any("괄호" in g for g in r["gaps"]))

    def test_llm_is_optional_and_failure_keeps_extracts(self):
        r = cr.research("미국", "뉴욕", "ko", fetch=make(), llm=lambda ctx: "뉴욕은 금융의 도시입니다.")
        self.assertEqual(r["sections"][0]["kind"], "brief")
        cr.clear_cache()
        r2 = cr.research("미국", "뉴욕", "ko", fetch=make(), llm=lambda ctx: (_ for _ in ()).throw(RuntimeError("x")))
        self.assertTrue(r2["ok"])
        self.assertNotEqual(r2["sections"][0]["kind"], "brief")

    def test_prompt_facts_only_sourced_items(self):
        p = cr.prompt_facts("미국", "뉴욕", fetch=make())
        self.assertEqual(p["status"], "verified")
        self.assertTrue(all(i["url"] for i in p["items"]))
        cr.clear_cache()
        self.assertEqual(cr.prompt_facts("미국", "뉴욕", fetch=lambda u: (_ for _ in ()).throw(TimeoutError()))["status"], "unavailable")

    def test_http_goes_through_safe_http_allowlist(self):
        from app.research import net
        seen = []
        fake = net.SafeHttp(transport=lambda m, u, b, h, t: (seen.append(u), (200, b'{"extract": ""}', {}))[1], sleep=lambda s: None)
        with mock.patch.object(cr, "_HTTP", fake):
            cr.fetch_wikipedia("ko", "뉴욕")
            with self.assertRaises(cr.ResearchError):
                cr._get_json("https://evil.example/x")                                 # 허용 목록 밖 → 요청 자체를 안 한다
        self.assertEqual(len(seen), 1)
        self.assertTrue(seen[0].startswith("https://ko.wikipedia.org/api/rest_v1/page/summary/"))


class CityBriefEndpointTest(unittest.TestCase):
    def setUp(self):
        cr.clear_cache()
        self.client = TestClient(main.app)

    def test_endpoint_and_kill_switch(self):
        with mock.patch.object(cr, "_get_json", make()):
            r = self.client.get("/city-brief", params={"country": "미국", "city": "뉴욕"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        with mock.patch.dict(os.environ, {"CITY_BRIEF_ENABLED": "0"}):
            self.assertEqual(self.client.get("/city-brief", params={"country": "미국", "city": "뉴욕"}).json(),
                             {"ok": False, "reason": "city_brief_disabled"})
        self.assertEqual(self.client.get("/city-brief", params={"country": "미국", "city": ""}).status_code, 422)

    def test_prompt_injection_is_off_by_default(self):
        self.assertEqual(main.city_brief_prompt("", "뉴욕")["reason"], "city_brief_prompt_off")
        self.assertEqual(main.city_facts_clause(main.city_brief_prompt("", "뉴욕")), "")
        with mock.patch.dict(os.environ, {"CITY_BRIEF_PROMPT": "1"}), mock.patch.object(cr, "_get_json", make()):
            brief = main.city_brief_prompt("", "뉴욕")
        clause = main.city_facts_clause(brief)
        self.assertIn("CITY_CONTEXT", clause)
        self.assertIn("https://ko.wikipedia.org/wiki/", clause)
        self.assertIn("Do not add facts that are not listed here.", clause)


if __name__ == "__main__":
    unittest.main()
