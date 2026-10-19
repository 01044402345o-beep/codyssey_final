"""서버가 Firestore 에 쓰는 체인 문서를 opsarchive 가 그대로 검증할 수 있는가(구현 간 계약).

입력(fixtures/server_chain_documents.json)은 서버 코드가 만든 문서다(make_server_chain_fixture.py).
목록 읽기(gcp.Firestore.list)와 똑같이 해석하고(`decode_fields` + `_id`), 체인 검사를 돌린다.

10/19 실제 Firestore 에서 발견: 문서 전체(`_id`·아카이브 메타 포함)로 digest 를 계산해 실제 항목이
전부 digest_mismatch → anchor 가 chain_broken 으로 거부했다. 순수 매니페스트만 쓰는 test_chain 은
이 차이를 못 잡는다.
"""

from __future__ import annotations

import json
import os
import unittest

from opsarchive import chain, gcp

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "server_chain_documents.json")


def read_like_firestore_list() -> tuple[list[dict], dict]:
    with open(FIXTURE, encoding="utf-8") as f:
        data = json.load(f)
    items = []
    for doc in data["documents"]:
        item = gcp.decode_fields(doc["fields"])
        item["_id"] = doc["name"].rsplit("/", 1)[-1]          # gcp.Firestore.list 와 같다
        items.append(item)
    return items, gcp.decode_fields(data["head"])


class ServerChainContractTest(unittest.TestCase):
    def test_server_documents_form_an_intact_chain(self):
        items, head = read_like_firestore_list()
        result = chain.check_chain(items)
        self.assertEqual(result["problems"], [])                # digest_mismatch 없음
        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], 3)                    # 아카이브 1 + 시도 1 + 결과 1
        self.assertEqual(result["head"], head["digest"])        # 서버가 옮긴 머리와 같다

    def test_archive_metadata_and_list_id_are_not_hashed(self):
        items, _ = read_like_firestore_list()
        archive = next(i for i in items if "kind" not in i)
        self.assertIn("ledger", archive)                        # 메타가 섞여 있는 실제 모양이다
        self.assertIn("_id", archive)
        self.assertEqual(chain.manifest_digest(archive), archive["digest"])

    def test_tampering_an_entry_is_still_detected(self):
        items, _ = read_like_firestore_list()
        entry = next(i for i in items if i.get("kind") == "outcome")
        entry["outcome"] = "failed"                             # digest 대상 필드를 바꾸면 잡혀야 한다
        result = chain.check_chain(items)
        self.assertIn("digest_mismatch", [p["issue"] for p in result["problems"]])

    def test_challenge_is_found_in_server_entries(self):
        items, _ = read_like_firestore_list()
        entries = [i for i in items if "kind" in i]
        hits = chain.find_challenge(entries, "ab" * 16)
        self.assertEqual([h["kind"] for h in hits], ["attempt", "outcome"])


if __name__ == "__main__":
    unittest.main()
