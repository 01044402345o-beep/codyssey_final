"""카테고리 계약의 금지어·키워드·예시 문장 — 정상 문장을 막지 않고, 시연(목업)에서 복습이 버려지지 않는지.

실행: cd backend && python -m unittest discover -s tests -t .

- 금지어(negative_case_patterns.terms)는 소문자 부분일치라 정상 질문을 잡기 쉽다(§6-2).
- required_keywords 는 철자 하나만 있으면 자연스러운 문장이 block 된다(§6-1 2).
- 키 없는 시연은 good_examples 를 그대로 돌려주므로, 예시가 없는 상황을 복습하면 결과가 버려진다(§6-1 5).
(docs/ops/CATEGORY_CONTRACT.md §6-1, §6-2)
"""
import json
import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CONTRACT = BACKEND.parent / "agent_contract"
CATEGORY_DIR = CONTRACT / "categories"
sys.path.insert(0, str(BACKEND))
from app.validators import check_weak_coverage, has_blocking, validate_pack, validate_sentence  # noqa: E402

CATEGORIES = ("attraction", "lodging", "restaurant", "transport")


def load(stem: str) -> dict:
    return json.loads((CATEGORY_DIR / f"{stem}.json").read_text(encoding="utf-8"))


def schema() -> dict:
    return json.loads((CONTRACT / "schema.json").read_text(encoding="utf-8"))


def sentence(cfg: dict, sid: str, en: str) -> dict:
    return {"situation_id": sid, "situation": "x", "en": en, "ko": "x",
            "place_type": cfg["place_types"][0]}


def term_issues(cfg: dict, sid: str, en: str) -> list:
    issues = validate_sentence(sentence(cfg, sid, en), cfg, cfg["negative_case_patterns"])
    return [i for i in issues if i["code"] in ("forbidden_topic", "not_polite")]


# (카테고리, situation_id, 정상 문장) — 예전 금지어가 잡던 문장
LEGIT = (
    ("attraction", "ask_discount", "Can children under six enter without a ticket?"),   # without a ticket
    ("attraction", "see_feature", "Am I allowed to touch the exhibits?"),               # touch the exhibits
    ("attraction", "ask_hours", "Is the museum open right now?"),                       # right now
    ("attraction", "souvenir_shop", "Do you sell gimmel pendants here?"),               # gimme
    ("restaurant", "order_menu", "Can I get drunken noodles, please?"),                 # get drunk
    ("restaurant", "pay_check", "Could you give me the bill, please?"),                 # give me the
    ("restaurant", "ask_wait", "Is there a table free right now?"),                     # right now
    ("lodging", "order_room_service", "Can I get drunken noodles, please?"),            # get drunk
    ("lodging", "ask_breakfast", "Is breakfast being served right now?"),               # right now
    ("transport", "security_check", "Where is the fast lane to skip security lines?"),  # skip security
    ("transport", "check_baggage", "Should I move it to the overhead bin?"),            # move it
    ("transport", "buy_ticket", "Can kids ride without a ticket?"),                     # ride without a ticket
)

# (카테고리, situation_id, 막아야 하는 문장, 기대 코드)
STILL_CAUGHT = (
    ("lodging", "check_in", "Let's grab a beer.", "forbidden_topic"),
    ("lodging", "check_in", "Let's have a drink at the bar.", "forbidden_topic"),
    ("lodging", "check_in", "Where can I get drunk tonight?", "forbidden_topic"),
    ("restaurant", "ask_recommend", "Let's get drunk tonight.", "forbidden_topic"),
    ("attraction", "buy_ticket", "How can I sneak in without a ticket?", "forbidden_topic"),
    ("attraction", "see_feature", "Let's touch the exhibits anyway.", "forbidden_topic"),
    ("transport", "security_check", "Can I skip the security check?", "forbidden_topic"),
    ("transport", "buy_ticket", "How do I dodge the fare?", "forbidden_topic"),
    ("transport", "find_gate", "Gimme my boarding pass.", "not_polite"),
    ("transport", "find_gate", "Move it!", "not_polite"),
    ("attraction", "find_entrance", "Show me the exit right now.", "not_polite"),
)

# (카테고리, situation_id, 다른 철자로 쓴 자연스러운 문장)
KEYWORD_VARIANTS = (
    ("lodging", "check_in", "Where is the check-in desk?"),
    ("lodging", "check_in", "Is the checkin counter on this floor?"),
    ("lodging", "check_in", "I'm checking in for two nights."),
    ("lodging", "check_out", "What time is check-out?"),
    ("lodging", "check_out", "Is checkout at noon?"),
    ("lodging", "request_amenity", "Could I have an extra pillow, please?"),
    ("lodging", "request_amenity", "Could I get another blanket, please?"),
    ("lodging", "request_amenity", "Could you bring me a toothbrush?"),
    ("lodging", "request_amenity", "Are the amenities in the bathroom?"),
    ("lodging", "leave_luggage", "Can I leave my bags here until noon?"),
    ("restaurant", "request_side", "Could we have some more water, please?"),
    ("restaurant", "request_side", "Could I have extra sauce, please?"),
    ("restaurant", "allergy_notice", "I have food allergies."),
    ("restaurant", "pay_check", "Can I pay by card?"),
    ("transport", "flight_delay", "Has my flight been canceled?"),
    ("transport", "flight_delay", "Is my flight on time?"),
    ("transport", "transfer_route", "Where do I go for my connection?"),
    ("transport", "transfer_route", "I have a short layover here."),
    ("transport", "ask_platform", "Which track does the train leave from?"),
    ("attraction", "ask_hours", "What are your opening hours?"),
    ("attraction", "ask_hours", "What is the closing time?"),
    ("attraction", "guided_tour", "Is there a tour in English?"),
    ("attraction", "guided_tour", "What time is the next tour?"),
)


class ContractTermsTest(unittest.TestCase):
    def test_정상_문장은_금지어에_걸리지_않는다(self):
        for stem, sid, en in LEGIT:
            with self.subTest(category=stem, en=en):
                self.assertEqual(term_issues(load(stem), sid, en), [])

    def test_막아야_할_문장은_여전히_걸린다(self):
        for stem, sid, en, code in STILL_CAUGHT:
            with self.subTest(category=stem, en=en):
                codes = {i["code"] for i in term_issues(load(stem), sid, en)}
                self.assertIn(code, codes)

    def test_negative_cases_는_모두_걸린다(self):
        for stem in CATEGORIES:
            cfg = load(stem)
            for case in cfg["negative_cases"]:
                with self.subTest(category=stem, case=case["case_id"]):
                    seen = set()
                    if case["expect"] == "duplicate_en":
                        seen.add(case["sentence"]["en"].lower())
                    codes = {i["code"] for i in validate_sentence(
                        case["sentence"], cfg, cfg["negative_case_patterns"], seen)}
                    self.assertIn(case["expect"], codes)

    def test_키워드_다른_철자도_복습으로_인정된다(self):
        for stem, sid, en in KEYWORD_VARIANTS:
            with self.subTest(category=stem, en=en):
                cfg = load(stem)
                issues = check_weak_coverage([sentence(cfg, sid, en)], [sid], cfg)
                self.assertEqual(issues, [])

    def test_tourist_는_가이드_투어로_인정되지_않는다(self):
        cfg = load("attraction")
        issues = check_weak_coverage(
            [sentence(cfg, "guided_tour", "Is this the tourist information desk?")], ["guided_tour"], cfg)
        self.assertEqual([i["code"] for i in issues], ["weak_content_mismatch"])

    def test_모든_상황에_예시_문장이_있다(self):
        for stem in CATEGORIES:
            cfg = load(stem)
            have = {g["situation_id"] for g in cfg["good_examples"]}
            for s in cfg["situations"]:
                with self.subTest(category=stem, situation=s["situation_id"]):
                    self.assertIn(s["situation_id"], have)

    def test_예시_place_type_은_그_카테고리의_장소_종류다(self):
        for stem in CATEGORIES:
            cfg = load(stem)
            for g in cfg["good_examples"]:
                with self.subTest(category=stem, en=g["en"]):
                    self.assertIn(g["place_type"], cfg["place_types"])

    def test_목업_시연에서_어떤_상황을_복습해도_block_이_없다(self):
        # main.mock_pack 과 같은 방식: good_examples 에서 place 를 빼고 그대로 돌려준다.
        sch = schema()
        for stem in CATEGORIES:
            cfg = load(stem)
            default_type = cfg["place_types"][0]
            sentences = []
            for ex in cfg["good_examples"]:
                s = dict(ex)
                s.pop("place", None)
                s.setdefault("place_type", default_type)
                sentences.append(s)
            pack = {"category_id": stem, "city": "Example City", "sentences": sentences}
            for sit in cfg["situations"]:
                sid = sit["situation_id"]
                with self.subTest(category=stem, weak=sid):
                    issues = validate_pack(pack, cfg, [sid], sch)
                    self.assertFalse(has_blocking(issues), [i for i in issues if i["severity"] == "block"])


if __name__ == "__main__":
    unittest.main()
