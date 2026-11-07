"""계약 rules 를 검증기·점검 스크립트·프롬프트가 실제로 지키는지 (docs/ops/CATEGORY_CONTRACT.md §6-3).

실행: cd backend && python -m unittest discover -s tests -t .

새 검사는 모두 warn 이다. 생성 실패율(block)을 바꾸지 않는다.
"""
import copy
import json
import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATEGORY_DIR = BACKEND.parent / "agent_contract" / "categories"
SCHEMA = json.loads((BACKEND.parent / "agent_contract" / "schema.json").read_text(encoding="utf-8"))
sys.path.insert(0, str(BACKEND / "scripts"))
from validate_category import check_config  # noqa: E402

from app import main  # noqa: E402
from app.validators import has_blocking, max_words_limit, validate_pack, validate_sentence  # noqa: E402


def load(stem: str) -> dict:
    return json.loads((CATEGORY_DIR / f"{stem}.json").read_text(encoding="utf-8"))


def codes(issues):
    return [i["code"] for i in issues]


def sent(cfg, en="Could I see the menu, please?", **kw):
    first = cfg["situations"][0]
    s = {"situation_id": first["situation_id"], "situation": first["situation"], "en": en, "ko": "메뉴 볼 수 있을까요?",
         "place_type": cfg["place_types"][0]}
    s.update(kw)
    return s


class MaxSentencesPerSituationTest(unittest.TestCase):
    def setUp(self):
        self.cfg = load("restaurant")
        self.most = self.cfg["rules"]["max_sentences_per_situation"]

    def pack(self, n):
        return {"category_id": "restaurant", "city": "X",
                "sentences": [sent(self.cfg, en=f"Could I order dish number {i}, please?") for i in range(n)]}

    def test_over_max_is_warn(self):
        issues = validate_pack(self.pack(self.most + 1), self.cfg, [], SCHEMA)
        hit = [i for i in issues if i["code"] == "too_many_in_situation"]
        self.assertEqual(len(hit), 1)
        self.assertEqual(hit[0]["severity"], "warn")
        self.assertFalse(has_blocking(issues))

    def test_at_max_is_silent(self):
        issues = validate_pack(self.pack(self.most), self.cfg, [], SCHEMA)
        self.assertNotIn("schema_invalid", codes(issues))   # 검사가 실제로 돌았는지 (스키마에서 멈추지 않았는지)
        self.assertNotIn("too_many_in_situation", codes(issues))

    def test_missing_rule_disables_check(self):
        cfg = copy.deepcopy(self.cfg)
        del cfg["rules"]["max_sentences_per_situation"]
        self.assertNotIn("too_many_in_situation", codes(validate_pack(self.pack(self.most + 3), cfg, [], SCHEMA)))


class MaxWordsTest(unittest.TestCase):
    LONG = " ".join(["word"] * 16)

    def setUp(self):
        self.cfg = load("restaurant")

    def test_falls_back_to_rules_when_pattern_has_no_max(self):
        cfg = copy.deepcopy(self.cfg)
        del cfg["negative_case_patterns"]["too_long"]["max"]
        cfg["rules"]["max_words_per_sentence"] = 15
        self.assertEqual(max_words_limit(cfg), 15)
        self.assertIn("too_long", codes(validate_sentence(sent(cfg, en=self.LONG), cfg, cfg["negative_case_patterns"])))

    def test_pattern_max_wins_when_set(self):
        cfg = copy.deepcopy(self.cfg)
        cfg["negative_case_patterns"]["too_long"]["max"] = 20
        cfg["rules"]["max_words_per_sentence"] = 10
        self.assertEqual(max_words_limit(cfg), 20)
        self.assertNotIn("too_long", codes(validate_sentence(sent(cfg, en=self.LONG), cfg, cfg["negative_case_patterns"])))

    def test_no_limit_anywhere_is_silent(self):
        cfg = copy.deepcopy(self.cfg)
        del cfg["negative_case_patterns"]["too_long"]
        del cfg["rules"]["max_words_per_sentence"]
        self.assertIsNone(max_words_limit(cfg))
        self.assertNotIn("too_long", codes(validate_sentence(sent(cfg, en=self.LONG), cfg, cfg["negative_case_patterns"])))

    def test_check_config_errors_when_values_differ(self):
        cfg = copy.deepcopy(self.cfg)
        cfg["negative_case_patterns"]["too_long"]["max"] = cfg["rules"]["max_words_per_sentence"] + 1
        errors, _ = check_config(cfg, "restaurant")
        self.assertTrue(any("too_long.max" in e for e in errors), errors)

    def test_check_config_ok_when_equal(self):
        errors, _ = check_config(self.cfg, "restaurant")
        self.assertFalse(any("too_long.max" in e for e in errors), errors)


class ToneRequiredTest(unittest.TestCase):
    def test_missing_tone_is_error(self):
        cfg = load("restaurant")
        del cfg["rules"]["tone"]
        errors, _ = check_config(cfg, "restaurant")
        self.assertTrue(any("rules.tone" in e for e in errors), errors)

    def test_present_tone_passes(self):
        errors, _ = check_config(load("restaurant"), "restaurant")
        self.assertEqual(errors, [])


class PlaceTypeTest(unittest.TestCase):
    def setUp(self):
        self.cfg = load("restaurant")
        self.patterns = self.cfg["negative_case_patterns"]

    def test_foreign_place_type_is_warn(self):
        issues = validate_sentence(sent(self.cfg, place_type="hotel"), self.cfg, self.patterns)
        hit = [i for i in issues if i["code"] == "place_type_not_in_category"]
        self.assertEqual(len(hit), 1)
        self.assertEqual(hit[0]["severity"], "warn")
        self.assertFalse(has_blocking(issues))

    def test_allowed_place_type_is_silent(self):
        for pt in self.cfg["place_types"] + [" Restaurant "]:
            with self.subTest(pt=pt):
                self.assertNotIn("place_type_not_in_category",
                                 codes(validate_sentence(sent(self.cfg, place_type=pt), self.cfg, self.patterns)))

    def test_missing_place_type_is_silent(self):
        s = sent(self.cfg)
        del s["place_type"]
        self.assertNotIn("place_type_not_in_category", codes(validate_sentence(s, self.cfg, self.patterns)))


class GoodExamplesStillCleanTest(unittest.TestCase):
    def test_no_block_and_no_new_warn_on_good_examples(self):
        for p in sorted(CATEGORY_DIR.glob("*.json")):
            with self.subTest(category=p.stem):
                cfg = load(p.stem)
                pack = {"category_id": cfg["category_id"], "city": "X", "sentences": cfg["good_examples"]}
                issues = validate_pack(pack, cfg, [], SCHEMA)
                self.assertFalse(has_blocking(issues), issues)
                new = {"too_many_in_situation", "place_type_not_in_category"} & set(codes(issues))
                self.assertEqual(new, set(), issues)


class PromptTest(unittest.TestCase):
    def payload(self, cfg):
        req = main.GenerateRequest(category_id=cfg["category_id"])
        text = main.build_prompt(cfg, req)
        return json.loads(text.split("INPUT:\n", 1)[1].split("\n\nOUTPUT JSON SCHEMA", 1)[0])

    def test_payload_carries_contract_place_types(self):
        for p in sorted(CATEGORY_DIR.glob("*.json")):
            with self.subTest(category=p.stem):
                cfg = load(p.stem)
                self.assertEqual(self.payload(cfg)["place_types"], cfg["place_types"])

    def test_unresolved_placeholder_logs_warning(self):
        cfg = load("restaurant")
        cfg["system_prompt"] += " Keep it under {not_a_rule} words."
        with self.assertLogs("app.prompt", level="WARNING") as cm:
            text = main.build_prompt(cfg, main.GenerateRequest(category_id="restaurant"))
        self.assertIn("not_a_rule", cm.output[0])
        self.assertIn("{not_a_rule}", text)   # 동작은 그대로: 치환하지 않고 남긴다

    def test_resolved_placeholders_do_not_log(self):
        cfg = load("restaurant")
        with self.assertNoLogs("app.prompt", level="WARNING"):
            main.build_prompt(cfg, main.GenerateRequest(category_id="restaurant"))


if __name__ == "__main__":
    unittest.main()
