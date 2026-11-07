"""카테고리 계약 문서가 실제 JSON 과 어긋나지 않는지.

실행: cd backend && python -m unittest discover -s tests -t .

agent_contract/categories/ 에 카테고리를 추가하거나 이름(category)을 바꿨는데
agent_contract/README.md 담당 표를 안 고치면 여기서 깨진다.
"""
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CATEGORY_DIR = ROOT / "agent_contract" / "categories"
CONTRACT_README = ROOT / "agent_contract" / "README.md"


class ContractReadmeTest(unittest.TestCase):
    def test_every_category_listed_in_contract_readme(self):
        text = CONTRACT_README.read_text(encoding="utf-8")
        paths = sorted(CATEGORY_DIR.glob("*.json"))
        self.assertTrue(paths, "카테고리 파일이 하나도 없습니다.")
        for path in paths:
            cfg = json.loads(path.read_text(encoding="utf-8"))
            with self.subTest(file=path.name):
                self.assertIn(f"`{cfg['category_id']}`", text,
                              f"{CONTRACT_README.name} 담당 표에 category_id 가 없습니다.")
                self.assertIn(cfg["category"], text,
                              f"{CONTRACT_README.name} 담당 표에 카테고리 이름이 없습니다.")


if __name__ == "__main__":
    unittest.main()
