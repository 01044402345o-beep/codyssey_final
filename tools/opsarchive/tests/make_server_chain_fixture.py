"""서버(backend/app/evidence.py)가 Firestore 에 실제로 쓰는 체인 문서를 고정 파일로 만든다.

opsarchive 의 체인 검사가 **서버가 만든 문서**를 그대로 검증할 수 있는지 보는 계약 테스트
(test_server_chain_contract.py)의 입력이다. 서버의 digest 계산·필드 구성이 바뀌면 다시 만든다:

    cd backend && python ../tools/opsarchive/tests/make_server_chain_fixture.py

결정적으로 만든다(시각·키·아카이브 id 고정) — 다시 만들어도 같은 파일이 나와야 차이가 보인다.
"""
import base64
import json
import os
import sys
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "..", "backend"))
os.environ["EVIDENCE_PUBKEY"] = "x25519:" + base64.urlsafe_b64encode(b"\x07" * 32).decode().rstrip("=")

from app import evidence, firebase_admin  # noqa: E402


class Recorder:
    """Firestore REST 처럼 문서 경로(짝수 마디)만 받고, 쓴 본문을 그대로 모은다."""

    def __init__(self):
        self.docs = {}

    def firestore(self, method, subpath, body=None):
        assert len([p for p in subpath.split("/") if p]) % 2 == 0, subpath
        if method == "PATCH":
            self.docs[subpath] = body
            return {}
        return self.docs.get(subpath, {})


rec = Recorder()
firebase_admin.set_admin(rec)
with mock.patch.object(evidence.time, "time", side_effect=[1792000000, 1792000001, 1792000002, 1792000003]):
    evidence.store(b"sealed-bytes", {"archive_id": "fixture-archive-1", "created_at": 1792000000,
                                     "expire_at": 1799776000, "trigger": "erase_failed",
                                     "key_id": evidence.key_id_hex(), "commit": "0" * 40,
                                     "ledger": [{"step": "tombstone", "ok": True}],
                                     "verification": {}, "truncated": {}, "plain_bytes": 12})
    evidence.record_attempt("ab" * 16, "uid-fixture")
    evidence.record_outcome("ab" * 16, "ok", uid="uid-fixture")

# Firestore list 응답과 같은 모양: {"name": ".../documents/<경로>", "fields": {...}}
root = "projects/demo/databases/(default)/documents/"
documents = [{"name": root + path, "fields": body["fields"]}
             for path, body in sorted(rec.docs.items())
             if path.startswith("evidence_archives/") and "/parts/" not in path
             or path.startswith(evidence.ENTRIES_COLLECTION + "/")]
out = os.path.join(HERE, "fixtures", "server_chain_documents.json")
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "w", encoding="utf-8", newline="\n") as f:
    json.dump({"head": rec.docs["evidence_chain/head"]["fields"], "documents": documents},
              f, ensure_ascii=False, indent=1, sort_keys=True)
    f.write("\n")
print("wrote", out, len(documents), "documents")
