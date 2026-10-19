"""해시체인과 관리자 체크포인트 — "누락"을 가시화하는 앱 밖 앵커.

왜 필요한가
- 앱이 봉인한 아카이브가 **서로 연결**되어 있지 않으면, 침해된 앱이 아카이브를 지우거나
  생략해도 관리자는 알 수 없다. 그래서 앱은 매니페스트에 `prev_digest` 를 넣어 체인을 만들고,
  관리자는 **앱 밖(로컬/저장소)** 에서 체크포인트를 서명해 앵커한다.
- 체인 자체는 앱이 만들므로 완전한 증명이 아니다(앱이 체인을 통째로 다시 쓸 수 있다).
  그래서 관리자 체크포인트는 **한 번 서명된 (count, head) 를 되돌릴 수 없게** 만든다 —
  나중에 개수가 줄거나 head 가 바뀌면 검증이 실패한다.

정직한 한계(문서 §9 와 같다)
- 앱을 장악한 공격자가 **처음부터** 체인을 만들지 않으면 탐지되지 않는다(사전 커밋먼트가 없다).
- 관리자가 주기적으로 앵커하지 않으면 그 사이 구간은 여전히 사각지대다.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from . import container as C

MANIFEST_SCHEMA = "SEAL-SIG-v1"
CHECKPOINT_SCHEMA = "SEAL-CHECKPOINT-v1"
DOMAIN_MANIFEST = b"EVIDENCE-SEAL/v1/manifest"
DOMAIN_CHECKPOINT = b"EVIDENCE-SEAL/v1/checkpoint"


class ChainError(Exception):
    """code: bad_manifest | bad_checkpoint | bad_signature | no_chain | broken"""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


# ------------------------------------------------------------------ 매니페스트(앱이 만든다)

# digest 에 들어가는 필드 — 서버(backend/app/evidence.py)가 digest 를 계산할 때 쓰는 것과 같아야 한다.
# Firestore 에서 읽은 문서에는 그 밖의 필드가 섞여 있다: 아카이브는 메타(expire_at·key_id·commit·ledger…),
# 그리고 목록 읽기(gcp.Firestore.list)가 붙이는 `_id`. 문서 전체로 계산하면 실제 데이터가 전부
# digest_mismatch 가 되고 anchor 가 chain_broken 으로 거부한다(10/19 실제 Firestore 로 확인).
ARCHIVE_FIELDS = ("schema", "archive_id", "created_at", "ciphertext_sha256", "size", "chunks",
                  "recipient_key_id", "trigger", "seq", "prev_digest")
ENTRY_FIELDS = ("schema", "created_at", "recipient_key_id", "seq", "prev_digest",
                "kind", "challenge", "uid_hash", "trigger", "outcome", "archive_id", "note")


def manifest_body(document: dict[str, Any]) -> dict[str, Any]:
    """digest 대상 필드만 고른다. 시도·결과 항목은 `kind` 가 있다(아카이브 매니페스트에는 없다)."""
    fields = ENTRY_FIELDS if "kind" in document else ARCHIVE_FIELDS
    return {k: document[k] for k in fields if k in document}


def manifest_digest(manifest: dict[str, Any]) -> str:
    """매니페스트의 digest — `prev_digest` 를 포함해 계산하므로 체인이 된다."""
    return hashlib.sha256(DOMAIN_MANIFEST + C.canonical_json(manifest_body(manifest))).hexdigest()


def build_manifest(*, archive_id: str, created_at: int, ciphertext_sha256: str, size: int,
                   chunks: int, recipient_key_id: str, seq: int, prev_digest: str,
                   trigger: str = "") -> dict[str, Any]:
    """앱이 저장하는 매니페스트. **서명하지 않는다** — 서명은 관리자 체크포인트의 몫이다."""
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "archive_id": archive_id,
        "created_at": int(created_at),
        "ciphertext_sha256": ciphertext_sha256,
        "size": int(size),
        "chunks": int(chunks),
        "recipient_key_id": recipient_key_id,
        "trigger": trigger,
        "seq": int(seq),
        "prev_digest": prev_digest,
    }
    manifest["digest"] = manifest_digest(manifest)
    return manifest


def check_chain(metas: list[dict[str, Any]]) -> dict[str, Any]:
    """매니페스트들을 seq 순으로 이어 **연속성**을 검사한다.

    돌려주는 값: {"ok", "head", "count", "problems": [...], "forks": [[ids...]]}
    - digest 불일치·prev 불일치·seq 중복은 문제로 보고한다.
    - 갈래(같은 prev 를 가리키는 형제)는 **문제는 아니지만** 순서를 증명할 수 없다고 표시한다.
    """
    problems: list[dict[str, Any]] = []
    ordered = sorted(metas, key=lambda m: (int(m.get("seq", 0)), str(m.get("archive_id", ""))))
    by_digest: dict[str, dict[str, Any]] = {}
    for manifest in ordered:
        expected = manifest_digest(manifest)
        if manifest.get("digest") != expected:
            problems.append({"archive_id": manifest.get("archive_id"), "issue": "digest_mismatch"})
        by_digest[str(manifest.get("digest", ""))] = manifest

    seen_prev: dict[str, int] = {}
    forks: list[list[str]] = []
    for index, manifest in enumerate(ordered):
        prev = str(manifest.get("prev_digest", ""))
        if prev:
            seen_prev[prev] = seen_prev.get(prev, 0) + 1
        if index == 0:
            continue
        previous = ordered[index - 1]
        if prev != str(previous.get("digest", "")):
            problems.append({"archive_id": manifest.get("archive_id"), "issue": "prev_mismatch",
                             "expected": previous.get("digest", ""), "found": prev})
    for prev, hits in seen_prev.items():
        if hits > 1:
            kids = [str(m.get("archive_id")) for m in ordered if str(m.get("prev_digest", "")) == prev]
            forks.append(kids)

    head = str(ordered[-1].get("digest", "")) if ordered else ""
    return {"ok": not problems, "head": head, "count": len(ordered), "problems": problems,
            "forks": forks, "max_seq": int(ordered[-1].get("seq", 0) or 0) if ordered else 0}


# ------------------------------------------------------------------ 체크포인트(관리자가 서명한다)

def checkpoint_body(*, seq: int, count: int, head_digest: str, archive_ids: list[str],
                    created_at: int, entry_ids: list[str] | None = None,
                    head_seq: int | None = None) -> dict[str, Any]:
    """서명 대상 본문. `archive_ids_sha256` 로 **어떤 아카이브를 봤는지**를 압축해 담는다.

    `entry_ids`(시도·결과 체인 항목)를 주면 그 집합 해시도 담고, `head_seq` 로 **앵커 범위**를 남긴다 —
    나중에 "이 챌린지가 앵커 범위 안에 있었는가"를 판정하는 근거가 된다.
    """
    ids = sorted(archive_ids)
    body = {
        "schema": CHECKPOINT_SCHEMA,
        "seq": int(seq),
        "count": int(count),
        "head_digest": head_digest,
        "archive_ids_sha256": hashlib.sha256(C.canonical_json(ids)).hexdigest(),
        "created_at": int(created_at),
    }
    if entry_ids is not None:
        body["entry_ids_sha256"] = hashlib.sha256(
            C.canonical_json(sorted(str(x) for x in entry_ids))).hexdigest()
    if head_seq is not None:
        body["head_seq"] = int(head_seq)
    return body


def find_challenge(entries: list[dict[str, Any]], challenge: str) -> list[dict[str, Any]]:
    """이 챌린지를 가진 체인 항목들(보통 시도 1개 + 결과 1개)."""
    want = (challenge or "").strip().lower()
    if not want:
        return []
    return [e for e in entries if str(e.get("challenge", "")).lower() == want]


def challenge_report(entries: list[dict[str, Any]], challenge: str,
                     checkpoint: dict[str, Any]) -> dict[str, Any]:
    """영수증 대조: 이 챌린지가 체인에 있는가, 그리고 그 항목이 **앵커 범위 안**인가.

    verdict
    - `anchored`: 앵커 범위 안에 있다 → 시도가 있었다는 주장이 뒷받침된다.
    - `after_anchor`: 앵커 이후 구간이다 → 아직 증명되지 않은 구간(다음 앵커에서 확정된다).
    - `missing_from_chain`: 체인에 없다 → **누락 의심**. 단 "그 요청이 앵커 이전이었다"는 것은
      사용자 기기의 기록(`at`)으로 확인해야 한다(우리는 요청 시각을 모른다).
    - `anchor_has_no_head_seq`: 옛 체크포인트라 앵커 범위를 알 수 없다.
    """
    hits = find_challenge(entries, challenge)
    anchored_seq = checkpoint.get("head_seq") if isinstance(checkpoint, dict) else None
    report = {
        "challenge": challenge,
        "found": bool(hits),
        "entries": [{"seq": e.get("seq"), "kind": e.get("kind"), "outcome": e.get("outcome"),
                     "digest": e.get("digest"), "created_at": e.get("created_at")} for e in hits],
        "anchored_seq": anchored_seq,
        "anchored": None,
        "verdict": "",
        "note": "",
    }
    if anchored_seq is None:
        report["verdict"] = "anchor_has_no_head_seq"
        report["note"] = "체크포인트에 head_seq 가 없다(구버전) — 관리자가 다시 anchor 해야 범위를 알 수 있다"
        return report
    if not hits:
        report["anchored"] = False
        report["verdict"] = "missing_from_chain"
        report["note"] = "사용자 기기의 요청 시각이 앵커 이전이라면 누락 의심이다"
        return report
    top = max(int(e.get("seq", 0) or 0) for e in hits)
    report["anchored"] = top <= int(anchored_seq)
    report["verdict"] = "anchored" if report["anchored"] else "after_anchor"
    if not report["anchored"]:
        report["note"] = "앵커 이후 구간 — 다음 anchor 에서 확정된다"
    return report


def checkpoint_message(body: dict[str, Any]) -> bytes:
    return DOMAIN_CHECKPOINT + C.canonical_json(body)


def sign_checkpoint(seed: bytes, body: dict[str, Any]) -> dict[str, Any]:
    """본문에 서명을 붙여 저장 가능한 체크포인트로 만든다."""
    signature = C.sign_message(seed, checkpoint_message(body))
    return {**body, "signature": signature.hex(),
            "signing_key_id": C.key_id(C.sign_public(seed)).hex()}


def verify_checkpoint(checkpoint: dict[str, Any], signing_public: bytes) -> dict[str, Any]:
    """서명과 본문 다이제스트를 검증한다(받은 그대로를 신뢰하지 않는다)."""
    body = {k: v for k, v in checkpoint.items() if k not in ("signature", "signing_key_id")}
    try:
        signature = bytes.fromhex(str(checkpoint.get("signature", "")))
    except ValueError as exc:
        raise ChainError("bad_checkpoint") from exc
    ok = C.verify_signature(signing_public, checkpoint_message(body), signature)
    ids_digest_ok = checkpoint.get("archive_ids_sha256") == body["archive_ids_sha256"]
    return {"ok": bool(ok and ids_digest_ok), "signature_ok": bool(ok),
            "key_id_matches": checkpoint.get("signing_key_id") == C.key_id(signing_public).hex()}


def verify_chain(checkpoints: list[dict], signing_public: bytes,
                 metas: list[dict[str, Any]]) -> dict[str, Any]:
    """체크포인트 시퀀스를 검증한다.

    1) 각 체크포인트의 서명·본문 정합
    2) `seq` 가 1씩 증가하고 `count` 가 **줄지 않는지**(롤백 탐지)
    3) 각 체크포인트의 head/count 가 그 시점 매니페스트와 맞는지(가능한 범위에서)
    4) 마지막 체크포인트 이후의 매니페스트를 **미앵커 구간**으로 보고
    """
    problems: list[dict[str, Any]] = []
    fingerprints = [c.get("archive_ids_sha256") for c in checkpoints]
    for index, checkpoint in enumerate(sorted(checkpoints, key=lambda c: int(c.get("seq", 0)))):
        result = verify_checkpoint(checkpoint, signing_public)
        if not result["ok"]:
            problems.append({"seq": checkpoint.get("seq"), "issue": "bad_signature",
                             "signature_ok": result["signature_ok"]})
        if index == 0:
            continue
        previous = sorted(checkpoints, key=lambda c: int(c.get("seq", 0)))[index - 1]
        if int(checkpoint.get("seq", 0)) != int(previous.get("seq", 0)) + 1:
            problems.append({"seq": checkpoint.get("seq"), "issue": "seq_gap"})
        if int(checkpoint.get("count", 0)) < int(previous.get("count", 0)):
            problems.append({"seq": checkpoint.get("seq"), "issue": "count_rollback",
                             "previous": previous.get("count"), "found": checkpoint.get("count")})
    anchored_count = int(max((c.get("count", 0) for c in checkpoints), default=0))
    chain = check_chain(metas)
    unanchored = max(0, chain["count"] - anchored_count)
    return {"ok": not problems, "problems": problems, "anchored_count": anchored_count,
            "chain_count": chain["count"], "unanchored": unanchored,
            "chain_ok": chain["ok"], "chain_problems": chain["problems"], "forks": chain["forks"],
            "distinct_anchor_sets": len(set(fingerprints))}


def omission_check(metas: list[dict[str, Any]], checkpoint: dict[str, Any]) -> dict[str, Any]:
    """체크포인트가 주장하는 아카이브 집합과 지금 저장소의 집합을 대조한다.

    체크포인트에는 집합의 해시만 있으므로 **개별 비교는 못 하고** 개수·집합 해시로 본다.
    개별 대조는 로컬에 체크포인트와 함께 저장한 목록(`anchors/<seq>.json`)이 있을 때만 가능하다.
    """
    ids = sorted(str(m.get("archive_id", "")) for m in metas)
    digest = hashlib.sha256(C.canonical_json(ids)).hexdigest()
    return {"count_matches": len(ids) == int(checkpoint.get("count", -1)),
            "set_matches": digest == checkpoint.get("archive_ids_sha256"),
            "found": len(ids), "expected": int(checkpoint.get("count", -1))}


def load_archive_ids(path: str) -> list[str]:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return [str(x) for x in (data.get("archive_ids") or [])]
