"""해시체인과 체크포인트 — 연속성·롤백·서명·누락 대조를 실제로 검증한다.

실행: `tools/opsarchive` 에서 `$env:PYTHONPATH="."; python -m unittest discover -s tests -t .`
"""

from __future__ import annotations

import os
import tempfile
import unittest

from opsarchive import chain, container as C


def manifest(seq: int, prev: str, archive_id: str = "") -> dict:
    body = {
        "schema": chain.MANIFEST_SCHEMA,
        "archive_id": archive_id or ("aid%d" % seq),
        "created_at": 1000 + seq,
        "ciphertext_sha256": "a" * 64,
        "size": 10,
        "chunks": 1,
        "recipient_key_id": "kid",
        "trigger": "erase_failed",
        "seq": seq,
        "prev_digest": prev,
    }
    body["digest"] = chain.manifest_digest(body)
    return body


def chain_of(count: int) -> list[dict]:
    out, prev = [], ""
    for seq in range(1, count + 1):
        item = manifest(seq, prev)
        out.append(item)
        prev = item["digest"]
    return out


class ChainTest(unittest.TestCase):
    def test_digest_binds_prev(self):
        first = manifest(1, "")
        second = manifest(2, first["digest"])
        self.assertEqual(second["prev_digest"], first["digest"])
        self.assertNotEqual(chain.manifest_digest(dict(second, prev_digest="x")), second["digest"])

    def test_intact_chain_passes(self):
        result = chain.check_chain(chain_of(3))
        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], 3)
        self.assertEqual(result["head"], chain_of(3)[-1]["digest"])

    def test_gap_is_reported(self):
        items = chain_of(3)
        result = chain.check_chain([items[0], items[2]])          # 가운데가 없다
        self.assertFalse(result["ok"])
        self.assertIn("prev_mismatch", [p["issue"] for p in result["problems"]])

    def test_tampered_manifest_is_reported(self):
        items = chain_of(2)
        items[0]["size"] = 999                                    # digest 계산 뒤 값을 바꿨다
        result = chain.check_chain(items)
        self.assertFalse(result["ok"])
        self.assertIn("digest_mismatch", [p["issue"] for p in result["problems"]])

    def test_fork_is_reported_but_not_fatal(self):
        items = chain_of(2)
        sibling = manifest(2, items[0]["digest"], archive_id="aid-fork")   # 같은 부모를 가리키는 형제
        result = chain.check_chain(items + [sibling])
        self.assertEqual([sorted(kids) for kids in result["forks"]], [sorted(["aid2", "aid-fork"])])


class CheckpointTest(unittest.TestCase):
    def setUp(self):
        self.seed, self.public = C.sign_keypair()
        self.metas = chain_of(3)
        ids = [m["archive_id"] for m in self.metas]
        body = chain.checkpoint_body(seq=1, count=3, head_digest=self.metas[-1]["digest"],
                                     archive_ids=ids, created_at=1234)
        self.checkpoint = chain.sign_checkpoint(self.seed, body)

    def test_signature_verifies(self):
        result = chain.verify_checkpoint(self.checkpoint, self.public)
        self.assertTrue(result["ok"])
        self.assertTrue(result["key_id_matches"])

    def test_wrong_key_fails(self):
        _, other = C.sign_keypair()
        self.assertFalse(chain.verify_checkpoint(self.checkpoint, other)["signature_ok"])

    def test_tampered_count_fails(self):
        broken = dict(self.checkpoint, count=99)
        self.assertFalse(chain.verify_checkpoint(broken, self.public)["ok"])

    def test_rollback_of_count_is_reported(self):
        later = chain.sign_checkpoint(self.seed, chain.checkpoint_body(
            seq=2, count=1, head_digest=self.metas[0]["digest"],
            archive_ids=[self.metas[0]["archive_id"]], created_at=1235))
        result = chain.verify_chain([self.checkpoint, later], self.public, self.metas)
        self.assertFalse(result["ok"])
        self.assertIn("count_rollback", [p["issue"] for p in result["problems"]])

    def test_unanchored_tail_is_reported(self):
        result = chain.verify_chain([self.checkpoint], self.public, chain_of(5))
        self.assertEqual(result["anchored_count"], 3)
        self.assertEqual(result["unanchored"], 2)

    def test_omission_check_detects_a_missing_archive(self):
        present = [m for m in self.metas if m["archive_id"] != "aid2"]     # 하나 사라졌다
        result = chain.omission_check(present, self.checkpoint)
        self.assertFalse(result["count_matches"])
        self.assertFalse(result["set_matches"])
        self.assertEqual(result["found"], 2)

    def test_omission_check_passes_when_set_matches(self):
        result = chain.omission_check(self.metas, self.checkpoint)
        self.assertTrue(result["count_matches"])
        self.assertTrue(result["set_matches"])


class AnchorRoundTripTest(unittest.TestCase):
    """anchor 가 만든 파일을 verify 가 읽는 왕복(네트워크 없이 로컬 파일만)."""

    def test_checkpoint_files_round_trip(self):
        seed, public = C.sign_keypair()
        metas = chain_of(2)
        directory = tempfile.mkdtemp(prefix="opsarchive-anchor-")
        body = chain.checkpoint_body(seq=1, count=2, head_digest=metas[-1]["digest"],
                                     archive_ids=[m["archive_id"] for m in metas], created_at=1)
        signed = chain.sign_checkpoint(seed, body)
        path = os.path.join(directory, "1.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(C.canonical_json(signed).decode())
        import json
        with open(path, encoding="utf-8") as fh:
            loaded = json.load(fh)
        self.assertTrue(chain.verify_checkpoint(loaded, public)["ok"])
        self.assertTrue(chain.omission_check(metas, loaded)["set_matches"])


if __name__ == "__main__":
    unittest.main()
