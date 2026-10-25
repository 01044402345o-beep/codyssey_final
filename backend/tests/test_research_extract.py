"""조사 LLM 추출(PR3) — 여행 조건 순위·한국어 요약·인용 검증. 네트워크·실제 모델 없음(가짜 모델)."""
import datetime as dt
import json
import os
import re
import threading
import time
import unittest
from unittest import mock

from app.research import extract, graph, identity, net, nodes, report
from app.research.cache import ResearchCache
from tests.research_fakes import FakeServer, FakeStore, trip

ENV = {"RESEARCH_ENABLED": "1", "RESEARCH_SOURCES": "", "RESEARCH_LLM": "1", "RESEARCH_PLACE_CHAIN": "none"}
TODAY = dt.date(2026, 10, 25)


def section(prompt, name):
    m = re.search(rf"^{name}: (.*)$", prompt, re.M)
    return json.loads(m.group(1))


def good_llm(calls=None):
    """가짜 모델: 도쿄면 공원을 1위로(3월 벚꽃), 엉터리 항목도 섞는다 — 검증기가 걸러야 한다."""
    def llm(prompt):
        if calls is not None:
            calls.append(prompt)
        places = {p["name"]: p["id"] for p in section(prompt, "PLACES")}
        out = {"places": [], "practical": []}
        if "Kitanomaru Park" in places:
            out["places"] = [
                {"id": places["Kitanomaru Park"], "summary_ko": "봄에 벚꽃이 피는 공원이에요.", "why_ko": "3월 말 벚꽃 시기"},  # 3 은 원문에 없다 → 이유만 버림
                {"id": "wv:JP_1850147:999", "summary_ko": "없는 장소예요.", "why_ko": ""},                              # 모르는 id
                {"id": places["Sushi Dai"], "summary_ko": "아침 초밥으로 유명한 가게예요. https://evil.example", "why_ko": ""},  # URL
                {"id": places["Blue Bottle Coffee"], "summary_ko": "Imperial Palace 옆 카페예요.", "why_ko": ""},          # 다른 후보 이름
                {"id": places["Imperial Palace"], "summary_ko": "일왕이 사는 궁이에요.", "why_ko": "첫날 가볍게 둘러보기 좋아요"},
                {"id": places["Imperial Palace"], "summary_ko": "중복이에요.", "why_ko": ""},                           # 중복
                {"id": places["Sushi Dai"], "summary_ko": "아침 초밥 30분 대기로 유명해요.", "why_ko": ""},              # 숫자 지어내기
            ]
            out["practical"] = [
                {"topic": "tipping", "summary_ko": "팁을 주는 문화가 아니에요. 현금을 챙기세요.",
                 "quote_en": "Tipping is not customary  and may cause confusion.", "situations": ["tip_split", "taxi_ride"]},
                {"topic": "transport_local", "summary_ko": "지하철은 24시간 다녀요.",
                 "quote_en": "Trains run all night long in Tokyo city.", "situations": []},                         # 원문에 없는 인용
                {"topic": "transport_local", "summary_ko": "기차가 정확해요. 역에서 스이카 카드를 사세요.",
                 "quote_en": "Trains are punctual. Buy a Suica card at the station.", "situations": ["buy_ticket", "check_in"]},
            ]
        elif "Osaka Castle" in places:
            out["places"] = [{"id": places["Dotonbori Stalls"], "summary_ko": "길거리 음식 노점이에요.", "why_ko": "저녁 산책 겸"}]
        return out
    return llm


class VerifyTest(unittest.TestCase):
    def test_verifier_keeps_only_grounded_items(self):
        cands = [{"id": "a", "name": "Tokyo Tower", "kind": "attraction", "desc": "Iconic tower, 333 m tall."},
                 {"id": "b", "name": "Sushi Dai", "kind": "restaurant", "desc": "Famous sushi breakfast."}]
        docs = [{"topic": "tipping", "text": "Tipping is not customary. A 10% service charge is added at hotels.",
                 "allowed_situations": ["tip_split"]}]
        raw = {"places": [{"id": "a", "summary_ko": "높이 333m 의 전망 타워예요.", "why_ko": ""},
                          {"id": "b", "summary_ko": "Famous sushi.", "why_ko": ""},                                  # 한글 없음
                          {"id": "b", "summary_ko": "<b>초밥</b>", "why_ko": ""}],
               "practical": [{"topic": "tipping", "summary_ko": "호텔은 봉사료 10% 가 붙어요.",
                              "quote_en": "A 10% service charge is added at hotels.", "situations": ["tip_split", "x"]}]}
        data, dropped = extract.verify_output(raw, cands, docs, 5)
        self.assertEqual([p["id"] for p in data["places"]], ["a"])
        self.assertEqual(dropped, 2)
        self.assertEqual(data["practical"][0]["situations"], ["tip_split"])
        bad = {"practical": [{"topic": "tipping", "summary_ko": "봉사료 15% 가 붙어요.",
                              "quote_en": "A 10% service charge is added at hotels.", "situations": []}]}
        self.assertEqual(extract.verify_output(bad, cands, docs, 5)[0]["practical"], [])           # 숫자가 인용과 다름

    def test_section_name_depends_on_month_and_length_only(self):
        tc = {"start": "2027-03-20", "nights": 3}
        self.assertEqual(extract.section_name(tc), "extract_m03_m")
        self.assertEqual(extract.section_name({"start": "2027-12-01", "nights": 1}), "extract_m12_s")

    def test_apply_puts_ranked_first_and_keeps_the_rest(self):
        places = [{"id": "a", "name": "A"}, {"id": "b", "name": "B"}, {"id": "c", "name": "C"}]
        out = extract.apply_places(places, {"places": [{"id": "c", "summary_ko": "씨", "why_ko": ""}]})
        self.assertEqual([p["id"] for p in out], ["c", "a", "b"])
        self.assertEqual((out[0]["rank"], out[0]["summary_ko"]), (1, "씨"))
        self.assertNotIn("rank", out[1])
        self.assertEqual(extract.apply_places(places, None), places)


@mock.patch.dict(os.environ, ENV)
class ExtractGraphTest(unittest.TestCase):
    def setUp(self):
        self.srv = FakeServer()
        self.cache = ResearchCache(use_firestore=False)
        self.calls = []

    def deps(self, llm=None, llm_on=None):
        return nodes.Deps(http=net.SafeHttp(transport=self.srv, sleep=lambda s: None), cache=self.cache, store=FakeStore(),
                          today=TODAY, llm=llm, llm_on=llm_on)

    def run_trip(self, deps):
        return graph.run(deps, identity.resolve(FakeStore(), trip()))

    def test_ranked_korean_places_and_quoted_practical(self):
        rep = self.run_trip(self.deps(good_llm(self.calls)))
        tokyo, osaka = rep["cities"]
        self.assertEqual(tokyo["extract"]["status"], "ok")
        first, second = tokyo["places"][:2]
        self.assertEqual((first["name"], first["rank"], first["summary_ko"], first["why_ko"]),
                         ("Kitanomaru Park", 1, "봄에 벚꽃이 피는 공원이에요.", ""))
        self.assertEqual((second["name"], second["why_ko"]), ("Imperial Palace", "첫날 가볍게 둘러보기 좋아요"))
        self.assertEqual(second["sources"][0]["url"], "https://en.wikivoyage.org/wiki/Tokyo/Chiyoda")  # 출처는 코드가 붙인 그대로
        sushi = next(p for p in tokyo["places"] if p["name"] == "Sushi Dai")
        self.assertNotIn("summary_ko", sushi)                                                       # URL·숫자 지어낸 요약은 버림
        self.assertEqual(len(tokyo["places"]), 7)                                                   # 고르지 않은 장소도 뒤에 남는다
        tip = next(p for p in tokyo["practical"] if p["topic"] == "tipping")
        self.assertEqual((tip["quote_en"], tip["situations"]), ("Tipping is not customary and may cause confusion.", ["tip_split"]))
        self.assertIn("text_en", tip)                                                               # 원문 발췌는 그대로
        local = next(p for p in tokyo["practical"] if p["topic"] == "transport_local")
        self.assertEqual((local["summary_ko"], local["situations"]), ("기차가 정확해요. 역에서 스이카 카드를 사세요.", ["buy_ticket"]))
        self.assertEqual(osaka["places"][0]["name"], "Dotonbori Stalls")
        # 프롬프트: 여행 조건이 들어가고, 외부 문서 속 URL·HTML 은 들어가지 않는다. 사용자 정보도 없다.
        tokyo_prompt = next(p for p in self.calls if "Kitanomaru Park" in p)
        t = section(tokyo_prompt, "TRIP")
        self.assertEqual((t["month"], t["nights"], t["arrives_here_from_abroad"], t["wanted_attractions"]), (3, 3, True, 2))
        self.assertEqual(t["weather"]["kind"], "normals")
        body = tokyo_prompt.split("TRIP:", 1)[1]
        self.assertNotIn("http", body)
        self.assertNotIn("<b>", body)
        self.assertIn("buy_ticket", json.dumps(section(tokyo_prompt, "DOCUMENTS")))

    def test_cached_extract_is_reused_without_model_call(self):
        self.run_trip(self.deps(good_llm(self.calls)))
        n = len(self.calls)
        d = self.deps(good_llm(self.calls))
        resolved = identity.resolve(FakeStore(), trip())
        plan = nodes.plan(d, resolved)
        self.assertTrue(nodes.all_fresh(plan))
        rep = graph.from_cache(resolved, plan)
        self.assertEqual(len(self.calls), n)
        self.assertEqual(rep["cities"][0]["places"][0]["summary_ko"], "봄에 벚꽃이 피는 공원이에요.")

    def test_changed_wikivoyage_revision_reruns_extract(self):
        self.run_trip(self.deps(good_llm(self.calls)))
        resolved = identity.resolve(FakeStore(), trip())
        tc = resolved["cities"][0]
        old = self.cache.get("research_cities", tc["ref"]["key"], extract.section_name(tc))
        self.cache.put("research_cities", tc["ref"]["key"], extract.section_name(tc), {**old["data"], "revid": 1}, 3600, [])
        plan = nodes.plan(self.deps(good_llm()), resolved)
        self.assertEqual(plan["cities"][0]["need"], ["extract"])
        self.assertEqual(plan["cities"][1]["need"], [])

    def test_model_failure_keeps_listing_report_and_caches_nothing(self):
        def boom(prompt):
            raise RuntimeError("model down")
        rep = self.run_trip(self.deps(boom))
        tokyo = rep["cities"][0]
        self.assertEqual((rep["quality"], tokyo["extract"]["status"]), ("full", "failed"))
        self.assertFalse(any("summary_ko" in p for p in tokyo["places"]))
        tc = identity.resolve(FakeStore(), trip())["cities"][0]
        self.assertIsNone(self.cache.get("research_cities", tc["ref"]["key"], extract.section_name(tc)))

    def test_slow_model_hits_soft_deadline_but_still_warms_cache(self):
        inner = good_llm()

        def slow(prompt):
            time.sleep(1.6)
            return inner(prompt)
        d = self.deps(slow)
        d.started = time.monotonic() - 9.7                       # 소프트 마감(최소 10초)까지 0.3초 → 1초만 기다린다
        with mock.patch.dict(os.environ, {"RESEARCH_SOFT_DEADLINE_S": "10"}):
            rep = self.run_trip(d)
        self.assertEqual(rep["cities"][0]["extract"]["status"], "deadline")
        self.assertFalse(any("summary_ko" in p for p in rep["cities"][0]["places"]))      # 보고서는 listing 그대로 바로 나간다
        tc = identity.resolve(FakeStore(), trip())["cities"][0]
        for _ in range(60):
            if self.cache.get("research_cities", tc["ref"]["key"], extract.section_name(tc)):
                break
            time.sleep(0.05)
        self.assertIsNotNone(self.cache.get("research_cities", tc["ref"]["key"], extract.section_name(tc)))

    def test_output_without_any_grounded_place_is_a_failure(self):
        rep = self.run_trip(self.deps(lambda p: {"places": [{"id": "nope", "summary_ko": "가짜", "why_ko": ""}]}))
        self.assertEqual(rep["cities"][0]["extract"]["status"], "failed")

    def test_disabled_llm_needs_no_extract(self):
        d = self.deps(llm_on=False)
        rep = self.run_trip(d)
        self.assertEqual(rep["cities"][0]["extract"]["status"], "disabled")
        plan = nodes.plan(self.deps(llm_on=False), identity.resolve(FakeStore(), trip()))
        self.assertTrue(nodes.all_fresh(plan))

    def test_no_gemini_key_means_disabled(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "", "GEMINI_API_KEYS": "", "GEMINI_API_KEY_FALLBACK": ""}), \
                mock.patch("app.gemini.api_keys", return_value=[]):
            self.assertFalse(self.deps().use_llm())
        with mock.patch.dict(os.environ, {"RESEARCH_LLM": "0"}):
            self.assertFalse(self.deps().use_llm())

    def test_plain_runner_gives_the_same_report(self):
        a = self.run_trip(self.deps(good_llm()))
        self.cache = ResearchCache(use_firestore=False)
        with mock.patch.dict(os.environ, {"RESEARCH_USE_GRAPH": "0"}):
            b = self.run_trip(self.deps(good_llm()))
        strip = lambda r: [[(p["name"], p.get("summary_ko")) for p in c["places"]] for c in r["cities"]]
        self.assertEqual(strip(a), strip(b))

    def test_llm_concurrency_cap(self):
        live, peak, lock = [0], [0], threading.Lock()
        inner = good_llm()

        def slow(prompt):
            with lock:
                live[0] += 1
                peak[0] = max(peak[0], live[0])
            time.sleep(0.05)
            with lock:
                live[0] -= 1
            return inner(prompt)
        with mock.patch.dict(os.environ, {"RESEARCH_LLM_CONCURRENCY": "1"}), mock.patch.object(extract, "_sem", None):
            self.run_trip(self.deps(slow))
        self.assertEqual(peak[0], 1)


class GeminiPathTest(unittest.TestCase):
    def test_uses_shared_runner_under_research_budget(self):
        from app import gemini as ai
        seen = {}

        def fake_run(what, fn):
            seen["what"], seen["client"] = what, ai._client.get()
            return ai.Result(value=fn(object(), "gemini-x", 1), attempts=1, model="gemini-x", failures=[])
        llm_text = json.dumps({"places": [{"id": "wv:k:0", "summary_ko": "전망 타워예요.", "why_ko": ""}]}, ensure_ascii=False)
        tc = {"ref": {"name": "Tokyo", "country_name": "Japan", "key": "k"}, "start": "2027-03-20", "end": "2027-03-23",
              "nights": 3, "roles": [], "caps": {"attr": 2, "rest": 2}}
        places = [{"id": "wv:k:0", "name": "Tokyo Tower", "kind": "attraction", "desc_en": "Iconic tower."}]
        with mock.patch.object(ai, "run", fake_run), mock.patch.object(ai, "generate_text", return_value="```json\n" + llm_text + "\n```"):
            r = extract.run(tc, places, [], None)
        self.assertEqual((r["status"], seen["what"], seen["client"]), ("ok", "research_extract", "research"))
        self.assertEqual(r["data"]["places"][0]["summary_ko"], "전망 타워예요.")

    def test_busy_slot_is_reported_not_raised(self):
        from app import gemini as ai

        def busy(what, fn):
            raise ai.Busy("busy")
        tc = {"ref": {"name": "T", "country_name": "", "key": "k"}, "start": "2027-03-20", "end": "2027-03-21",
              "nights": 1, "roles": [], "caps": {"attr": 1, "rest": 1}}
        with mock.patch.object(ai, "run", busy):
            r = extract.run(tc, [{"id": "a", "name": "A", "kind": "attraction", "desc_en": ""}], [], None)
        self.assertEqual(r["status"], "busy")


if __name__ == "__main__":
    unittest.main()
