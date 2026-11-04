"""실제 소리 음소 분석의 단계별 대체 — main(/speak-check)이 이것 하나만 부른다.

  1) 음소 노드(PC, remote) — 목록 순서, 실패하면 다음 노드, 죽은 노드는 쉬게 했다가 되돌린다(무료)
  2) 노드가 모두 실패했거나 노드 설정이 없으면 클라우드 발음 평가(cloud: Azure → Speechace, 하루 상한, 유료)
  3) 그것도 안 되면 결과 없음(unavailable) — 화면은 받아쓴 글자 기준(#211)·단어 쪽만으로 내려간다

Hugging Face 등 클라우드에 띄운 같은 모델의 노드는 1)의 목록 맨 뒤에 넣는다(backend/phoneme-node/Dockerfile).
예외를 던지지 않는다.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from . import cloud, remote


def configured() -> bool:
    return remote.configured() or cloud.configured()


def timeout() -> float:
    """main 이 기다릴 상한 — 노드 예산 + 클라우드 예산."""
    return (remote.budget() if remote.configured() else 0.0) + (cloud.budget() if cloud.configured() else 0.0)


def analyze(samples: np.ndarray, target: str) -> dict[str, Any]:
    node = remote.analyze(samples, target) if remote.configured() else None
    if node is not None and node.get("status") == "ok":
        return node
    if cloud.configured():
        out = cloud.analyze(samples, target)
        if out.get("status") == "ok":
            out["fallback_from"] = (node or {}).get("reason") or "no_nodes"     # 왜 클라우드로 왔나(진단)
            return out
        if node is None:
            return out
        node = {**node, "cloud": {"reason": out.get("reason")}}
    return node or {"status": "disabled", "reason": "not_configured"}


def status() -> dict[str, Any]:
    return {**remote.status(), "cloud": cloud.status()}
