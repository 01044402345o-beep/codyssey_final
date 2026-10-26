"""장소 어휘 추출(research/vocab.py) — 골든 코퍼스(실제 도시 8곳 조사 결과 고정) + 속성 테스트 + 단위 사례.

골든이 깨지면: 규칙을 일부러 바꿨다면 `python scripts/update_research_golden.py` 로 기대값을 갱신하고 diff 를 확인해 커밋한다.
"""
import json
import pathlib
import random
import unittest

from app.research import extract, vocab

GOLDEN = pathlib.Path(__file__).parent / "fixtures" / "research_golden"


def load(city):
    return json.loads((GOLDEN / f"{city}.json").read_text(encoding="utf-8"))["places"]


class GoldenCorpusTest(unittest.TestCase):
    def test_vocab_matches_expected_snapshot(self):
        expected = json.loads((GOLDEN / "expected" / "vocab.json").read_text(encoding="utf-8"))
        diffs = []
        for f in sorted(GOLDEN.glob("*.json")):
            for i, p in enumerate(json.loads(f.read_text(encoding="utf-8"))["places"]):
                key = f"{i:02d} {p['name']}"
                got = [[v["en"], v["kind"], v["src"]] for v in vocab.for_place(p)]
                if expected.get(f.stem, {}).get(key) != got:
                    diffs.append(f"{f.stem}/{key}: {expected.get(f.stem, {}).get(key)} -> {got}")
        self.assertEqual(diffs, [], "\n".join(diffs[:20]) + "\n(의도한 변경이면 scripts/update_research_golden.py)")

    def test_corpus_has_8_cities_and_good_coverage(self):
        files = sorted(p.stem for p in GOLDEN.glob("*.json"))
        self.assertEqual(files, ["cusco", "gunsan", "hoi_an", "matera", "nara", "new_york", "rothenburg", "tokyo"])
        english = [p for f in files for p in load(f) if (p.get("desc_lang") or "en") == "en"]
        covered = sum(1 for p in english if vocab.for_place(p))
        self.assertGreater(covered / len(english), 0.85, f"{covered}/{len(english)}")    # 영어 설명 장소의 85%+ 에 어휘

    def test_known_places(self):
        def terms(city, name):
            p = next(x for x in load(city) if x["name"] == name)
            return [v["en"] for v in vocab.for_place(p)]
        self.assertEqual(terms("nara", "Tōdai-ji")[0], "Great Buddha")
        self.assertIn("okonomiyaki", terms("nara", "Okaru"))
        self.assertIn("tuna", terms("nara", "Maguro Koya"))
        self.assertIn("Kong-namul-gukbap", terms("gunsan", "Ilhaeog"))
        self.assertIn("spire", terms("matera", "Matera Cathedral"))
        self.assertEqual(terms("rothenburg", "Market Square"), ["square"])                 # 이름의 머리 명사
        self.assertEqual(terms("rothenburg", "St. Jakobskirche"), ["church"])              # 독일어 이름 → 종류
        self.assertIn("Japanese cuisine", terms("rothenburg", "Louvre"))
        self.assertIn("Pho Bo", terms("hoi_an", "Phở Tùng"))                               # 꾸밈말(super nice) 떼기


class PropertyTest(unittest.TestCase):
    WORDS = ("temple", "sushi", "Great Buddha", "famous", "for", "its", "delicious", "the", "serves", "known", "spire",
             "museum", "ramen", "and", "with", "Café", "Bánh", "Xèo", "specializes", "in", "try", "houses", "a", "giant",
             "statue", "market", "square", "of", "₩35,000", "<script>", "http://evil.example", "{{x}}", "@user", "12",
             "rooftop", "Japanese", "cuisine", "kirche", "-ji", "‮", "Robert'); DROP", "x" * 60)

    def rand_text(self, rnd, n):
        return " ".join(rnd.choice(self.WORDS) for _ in range(n))

    def test_invariants_on_random_and_hostile_input(self):
        rnd = random.Random(20261026)
        mapped = set(vocab.CUISINE_MAP.values()) | {v[0] for v in vocab.TOURAPI_MAP.values()}
        for _ in range(800):
            p = {"name": self.rand_text(rnd, rnd.randint(1, 4)), "desc_en": self.rand_text(rnd, rnd.randint(0, 25)),
                 "desc_lang": rnd.choice(["en", "", "de"]), "kind": rnd.choice(["attraction", "restaurant", "cafe"]),
                 "cuisine": rnd.choice(["", "sushi;japanese", "evil<script>", "korean"]), "category": rnd.choice(["", "FD050100", "HS010100"])}
            llm = [self.rand_text(rnd, rnd.randint(1, 3)) for _ in range(rnd.randint(0, 3))]
            out = vocab.for_place(p, llm)
            source = (p["name"] + " " + (p["desc_en"] if p["desc_lang"] in ("en", "") else "")).casefold()
            self.assertLessEqual(len(out), vocab.MAX_TERMS)
            keys = [v["en"].casefold() for v in out]
            self.assertEqual(len(keys), len(set(keys)), out)                                 # 중복 없음
            for v in out:
                self.assertTrue(vocab.ok_term(v["en"]), v)                                    # 짧고 숫자·기호·URL 없음
                self.assertIn(v["kind"], ("dish", "feature", "type"))
                self.assertIn(v["src"], ("llm", "pattern", "lexicon", "cuisine", "category"))
                if v["src"] in ("llm", "pattern"):
                    self.assertIn(v["en"].casefold(), source, (v, p))                         # 원문에 그대로 있는 낱말만
                elif v["src"] in ("cuisine", "category"):
                    self.assertTrue(v["en"] in mapped or v["en"].casefold() in p["cuisine"].casefold(), v)
                else:
                    self.assertTrue(v["en"].casefold() in source or v["kind"] == "type", (v, p))

    def test_llm_terms_not_in_text_are_dropped(self):
        p = {"name": "Okaru", "desc_en": "A restaurant specialized in okonomiyaki.", "kind": "restaurant"}
        out = [v["en"] for v in vocab.for_place(p, ["okonomiyaki", "wagyu steak", "Michelin star"])]
        self.assertIn("okonomiyaki", out)
        self.assertNotIn("wagyu steak", out)
        self.assertNotIn("Michelin star", out)

    def test_non_english_description_gives_only_name_type(self):
        p = {"name": "Klostergarten", "desc_en": "Der ehemalige Garten des Klosters. Ein ruhiger Park.", "desc_lang": "de",
             "kind": "attraction"}
        self.assertEqual([v["en"] for v in vocab.for_place(p)], [])
        p2 = {**p, "name": "Heilig-Geist-Kirche"}
        self.assertEqual([v["en"] for v in vocab.for_place(p2)], ["church"])


class ExtractVocabTest(unittest.TestCase):
    def test_llm_vocab_is_verified_against_candidate(self):
        cands = [{"id": "a", "name": "Okaru", "kind": "restaurant", "desc": "A restaurant specialized in okonomiyaki."}]
        raw = {"places": [{"id": "a", "summary_ko": "오코노미야키 전문점이에요.", "why_ko": "",
                           "vocab": ["okonomiyaki", "sushi", "<b>", "restaurant specialized in okonomiyaki and more words"]}]}
        data, _ = extract.verify_output(raw, cands, [], 5)
        self.assertEqual(data["places"][0]["vocab"], ["okonomiyaki"])
        merged = extract.apply_places([{"id": "a", "name": "Okaru"}], data)
        self.assertEqual(merged[0]["vocab_llm"], ["okonomiyaki"])


if __name__ == "__main__":
    unittest.main()
