"""validate_category 테스트.  실행: python backend/scripts/test_validate_category.py"""
import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_category import check_config  # noqa: E402

BASE = json.loads((Path(__file__).resolve().parents[2] / "agent_contract" / "categories" / "restaurant.json").read_text(encoding="utf-8"))


def mutate(fn):
    cfg = copy.deepcopy(BASE)
    fn(cfg)
    return check_config(cfg, "restaurant")


class T(unittest.TestCase):
    def test_restaurant_passes(self):
        errors, _ = check_config(copy.deepcopy(BASE), "restaurant")
        self.assertEqual(errors, [])

    def test_missing_and_mismatch(self):
        self.assertTrue(any("category_id" in e for e in check_config(copy.deepcopy(BASE), "transport")[0]))
        self.assertTrue(any("`owner`" in e for e in mutate(lambda c: c.pop("owner"))[0]))

    def test_situations(self):
        e, _ = mutate(lambda c: c["situations"].append({"situation_id": "order_menu", "situation": "중복"}))
        self.assertTrue(any("중복" in x for x in e))
        e, _ = mutate(lambda c: c["situations"][0].update(situation_id="Bad-Id"))
        self.assertTrue(any("situation_id" in x for x in e))

    def test_placeholder(self):
        e, _ = mutate(lambda c: c.update(system_prompt=c["system_prompt"] + " {min}"))
        self.assertTrue(any("{min}" in x for x in e))

    def test_good_example_problems(self):
        e, _ = mutate(lambda c: c["good_examples"][0].update(situation_id="not_in_config"))
        self.assertTrue(any("situation_not_in_config" in x for x in e))
        e, _ = mutate(lambda c: c["good_examples"][0].pop("ko"))
        self.assertTrue(any("schema_invalid" in x for x in e))
        e, _ = mutate(lambda c: c.update(good_examples=c["good_examples"][:2]))
        self.assertTrue(any("3개 이상" in x for x in e))

    def test_negative_case_must_fire(self):
        e, _ = mutate(lambda c: c["negative_cases"][0]["sentence"].update(en="Nice weather today."))
        self.assertTrue(any("걸러지지 않습니다" in x for x in e))
        e, _ = mutate(lambda c: c.update(negative_cases=c["negative_cases"][:3]))
        self.assertTrue(any("5개 이상" in x for x in e))

    def test_unknown_pattern_type_warns(self):
        _, w = mutate(lambda c: c["negative_case_patterns"].update(x={"severity": "warn", "type": "regex"}))
        self.assertTrue(any("regex" in x for x in w))

    def test_not_an_object(self):
        self.assertTrue(check_config([], "x")[0])


if __name__ == "__main__":
    unittest.main()
