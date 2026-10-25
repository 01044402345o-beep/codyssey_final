"""다른 언어판 위키보이지(de·it·fr·es·ja·zh) 파서·좌표 복구·대체 소스 — 네트워크 없음(가짜 서버)."""
import datetime as dt
import os
import unittest
from unittest import mock

from app.research import chain, graph, identity, net, nodes
from app.research import wikivoyage_parse as wp
from app.research.cache import ResearchCache
from app.research.sources import wikivoyage, wikivoyage_intl
from tests.research_fakes import FakeServer, FakeStore, trip

ENV = {"RESEARCH_ENABLED": "1", "RESEARCH_SOURCES": "", "RESEARCH_LLM": "0", "RESEARCH_PLACE_CHAIN": "wikivoyage_intl"}
TODAY = dt.date(2026, 10, 25)


def http(srv):
    return net.SafeHttp(transport=srv, sleep=lambda s: None)


class ParserTest(unittest.TestCase):
    def kinds(self, text, lang):
        return [(l["type"], l["name"], l["lat"], l["content"]) for l in wp.listings(text, "P", lang)]

    def test_each_edition_template_and_params(self):
        de = "==Küche==\n* {{vCard| name = Zur Höll | lat = 49.37 | long = 10.17 | description = Alt.}}\n" \
             "* {{vCard| type = museum | name = Burg | lat = 49.38 | long = 10.18 }}"
        self.assertEqual(self.kinds(de, "de"), [("eat", "Zur Höll", 49.37, "Alt."), ("see", "Burg", 49.38, "")])   # 섹션·type
        fr = "==Voir==\n* {{voir | nom=Château | latitude=45.89 | longitude=6.12 | description=Beau.}}"
        self.assertEqual(self.kinds(fr, "fr"), [("see", "Château", 45.89, "Beau.")])
        es = "* {{listado | tipo=comer | nombre=La Bodega | latitud=-13.5 | longitud=-71.9 | descripción=Buena.}}"
        self.assertEqual(self.kinds(es, "es"), [("eat", "La Bodega", -13.5, "Buena.")])
        it = "* {{see | nome=Sassi | lat=40.66 | long=16.61 | descrizione=Rupestri.}}"
        self.assertEqual(self.kinds(it, "it"), [("see", "Sassi", 40.66, "Rupestri.")])
        ja = "==食べる==\n* {{vCard|name=飛騨牛 まるあき|lat=36.14|long=137.25}}"
        self.assertEqual(self.kinds(ja, "ja"), [("eat", "飛騨牛 まるあき", 36.14, "")])
        self.assertEqual(self.kinds(de, "en"), [])                                         # 언어판에 없는 템플릿은 무시

    def test_english_marker_is_read_and_deduped_against_listing(self):
        en = "==See==\n* {{marker|type=see|name=Plönlein|lat=49.374|long=10.179}}\n" \
             "* {{see|name=Rathaus|lat=49.377|long=10.179|content=Town hall.}}\n* {{marker|type=see|name=Rathaus|lat=49.377|long=10.179}}"
        ls = wikivoyage.dedupe(wp.listings(en, "Rothenburg", "en"))
        self.assertEqual([(l["name"], l["marker"]) for l in ls], [("Plönlein", True), ("Rathaus", False)])


@mock.patch.dict(os.environ, ENV)
class CoordRepairAndSourceTest(unittest.TestCase):
    def test_repair_coords_from_wikidata(self):
        srv = FakeServer()
        ls = [{"name": "Museum", "wikidata": "Q500001", "lat": None, "lon": None}, {"name": "X", "wikidata": "", "lat": None, "lon": None}]
        self.assertEqual(wikivoyage.repair_coords(http(srv), ls), 1)
        self.assertEqual((ls[0]["lat"], ls[0]["coord_src"], ls[1]["lat"]), (34.6851, "wikidata", None))
        self.assertEqual(wikivoyage.repair_coords(http(FakeServer(fail={"www.wikidata.org": 503})),
                                                  [{"name": "M", "wikidata": "Q500001", "lat": None, "lon": None}]), 0)

    def test_edition_order_by_country(self):
        avail = {"de": "A", "ja": "B", "it": "C", "zh": "D"}
        self.assertEqual(wikivoyage_intl.order("JP", avail), ["de", "ja", "it", "zh"])
        self.assertEqual(wikivoyage_intl.order("IT", avail), ["it", "de", "ja", "zh"])
        self.assertEqual(wikivoyage_intl.order("KR", {}), [])

    def test_adapter_reads_german_then_stops_when_filled(self):
        srv = FakeServer()
        deps = type("D", (), {"http": http(srv)})()
        tc = {"ref": {"key": "JP_1855612", "qid": "Q169134", "iso2": "JP", "lat": 34.685, "lon": 135.805}}
        r = wikivoyage_intl.adapter(deps, tc, {"attraction": 2, "food": 2})
        self.assertEqual(r["status"], "ok")
        got = [(p["name"], p["kind"], p["desc_lang"]) for p in r["data"]]
        self.assertIn(("Tōdai-ji", "attraction", "de"), got)
        self.assertIn(("Nationalmuseum Nara", "attraction", "de"), got)                   # 좌표는 Wikidata 로 복구
        self.assertIn(("Kamameshi Shizuka", "restaurant", "de"), got)
        self.assertIn(("Rokumei Kaffee", "cafe", "de"), got)
        museum = next(p for p in r["data"] if p["name"] == "Nationalmuseum Nara")
        self.assertEqual((museum["lat"], museum["id"].split(":")[0]), (34.6851, "wvde"))
        self.assertEqual(museum["sources"][0]["url"], "https://de.wikivoyage.org/wiki/Nara")
        self.assertFalse(any("ja.wikivoyage.org" in c for c in srv.calls))                  # 채웠으니 2번째 판은 안 읽음

    def test_adapter_without_qid_or_editions(self):
        deps = type("D", (), {"http": http(FakeServer())})()
        self.assertEqual(wikivoyage_intl.adapter(deps, {"ref": {"qid": ""}}, {"attraction": 1})["reason"], "no_qid")
        self.assertEqual(wikivoyage_intl.adapter(deps, {"ref": {"qid": "Q1", "iso2": "KR"}}, {"attraction": 1})["reason"],
                         "no_other_edition")


@mock.patch.dict(os.environ, ENV)
class IntlChainGraphTest(unittest.TestCase):
    def test_nara_without_english_article_gets_german_listings(self):
        health = chain.Health()
        with mock.patch.object(chain, "HEALTH", health):
            srv = FakeServer()
            d = nodes.Deps(http=http(srv), cache=ResearchCache(use_firestore=False), store=FakeStore(), today=TODAY, llm_on=False)
            req = trip(cities=[{"name": "나라", "gid": 1855612, "ci": 0, "start": "2027-03-20", "end": "2027-03-22", "attr": 2, "rest": 2}])
            rep = graph.run(d, identity.resolve(FakeStore(), req))
        nara = rep["cities"][0]
        names = [p["name"] for p in nara["places"]]
        self.assertEqual(names.count("Tōdai-ji"), 1)
        self.assertIn("Kamameshi Shizuka", names)
        self.assertEqual((nara["place_status"], nara["chain"]["wikivoyage_intl"]["outcome"]), ("ok", "ok"))
        self.assertTrue(any(s["url"].startswith("https://de.wikivoyage.org/") for p in nara["places"] for s in p["sources"]))


if __name__ == "__main__":
    unittest.main()
