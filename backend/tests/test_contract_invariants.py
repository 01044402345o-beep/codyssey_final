"""카테고리 계약의 불변식 — 네 파일 모두 전체 점검을 통과하고, 상황 id 가 바뀌지 않는지.

실행: cd backend && python -m unittest discover -s tests -t .

CI 의 scripts/test_validate_category.py 는 restaurant 한 파일로만 check_config 를 돌린다.
여기서는 네 파일 전부를 돌리고, 상황 id 목록을 고정해 이름이 바뀌면 바로 깨지게 한다.
(docs/ops/CATEGORY_CONTRACT.md §6-5, §7)
"""
import json
import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATEGORY_DIR = BACKEND.parent / "agent_contract" / "categories"
sys.path.insert(0, str(BACKEND / "scripts"))
from validate_category import check_config  # noqa: E402

# situation_id 는 복습 목록·문장 배정의 키다. 바꾸면 사용자 기록이 끊긴다.
# 상황을 일부러 추가·삭제했다면 이 표도 같은 PR 에서 고친다.
SITUATION_IDS = {
    "attraction": ("buy_ticket", "ask_hours", "find_entrance", "guided_tour", "photo_request",
                   "ask_way", "see_feature", "bag_storage", "ask_discount", "souvenir_shop"),
    "lodging": ("check_in", "leave_luggage", "room_upgrade", "ask_breakfast", "ask_wifi",
                "early_late_check", "request_amenity", "order_room_service", "room_complaint", "check_out"),
    "restaurant": ("reserve_table", "ask_wait", "order_menu", "ask_recommend", "allergy_notice",
                   "request_side", "ask_ingredient", "takeout", "pay_check", "tip_split"),
    "transport": ("airport_checkin", "check_baggage", "security_check", "find_gate", "flight_delay",
                  "transfer_route", "buy_ticket", "ask_platform", "public_transport_route", "taxi_ride"),
}


def load(stem: str) -> dict:
    return json.loads((CATEGORY_DIR / f"{stem}.json").read_text(encoding="utf-8"))


class ContractInvariantsTest(unittest.TestCase):
    def test_카테고리는_네_개다(self):
        self.assertEqual(sorted(p.stem for p in CATEGORY_DIR.glob("*.json")), sorted(SITUATION_IDS))

    def test_네_파일_모두_전체_점검을_통과한다(self):
        for stem in SITUATION_IDS:
            with self.subTest(category=stem):
                errors, _ = check_config(load(stem), stem)
                self.assertEqual(errors, [])

    def test_파일_이름과_category_id_가_같다(self):
        for stem in SITUATION_IDS:
            with self.subTest(category=stem):
                self.assertEqual(load(stem)["category_id"], stem)

    def test_상황_id_는_바뀌지_않는다(self):
        for stem, expected in SITUATION_IDS.items():
            with self.subTest(category=stem):
                got = tuple(s["situation_id"] for s in load(stem)["situations"])
                self.assertEqual(got, expected)


if __name__ == "__main__":
    unittest.main()
