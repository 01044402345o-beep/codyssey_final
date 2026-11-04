"""음소별 평가 — 목표 음소열을 실제 소리에 강제정렬한 뒤, 음소마다 '목표 음소가 얼마나 우세했는지'(GOP)를 잰다.

GOP = 구간 프레임 평균 P(목표 음소) / max_v P(v) (0~1). 1 이면 그 구간에서 목표 음소가 가장 유력했다.
heard_as = 그 구간에서 목표 음소를 가장 많이 이긴 다른 기호('θ 가 s 로 들렸다'의 근거).

이 값은 '음소 단위 오류 위치와 유형'이지 사람 평가와 맞춘 발음 점수가 아니다(보정하지 않았다).
"""
from __future__ import annotations

import os
from typing import Any

import numpy as np

from . import g2p
from .align import forced_align
from .inventory import tip_for

WEAK_GOP = float(os.getenv("PHONEME_WEAK_GOP", "0.45"))
MISSING_GOP = float(os.getenv("PHONEME_MISSING_GOP", "0.18"))
MAX_TOKENS = 80
MODEL_NAME = "wav2vec2-lv-60-espeak-cv-ft (int8 onnx, c69750f5)"

# 같은 소리를 사전(CMUdict)과 모델(espeak)이 다르게 적는 짝. 이 기호로 들리면 틀린 게 아니다.
# 실측(합성음 'a window seat', 'here for')에서 정확히 말해도 ə→ɐ, ɔɹ→ɜː, ɹ→ɚ 로 잡혀 오탐이 났다.
# t·d → ɾ 는 미국 영어의 탄설음(water, city)이라 정상 발음이다.
EQUIVALENT: dict[str, frozenset[str]] = {
    "ə": frozenset({"ɐ", "ᵻ", "ɪ", "ʌ"}),
    "ʌ": frozenset({"ɐ", "ə"}),
    "ɚ": frozenset({"ɜː", "ɜ", "ə", "ɐ"}),
    "ɹ": frozenset({"ɚ", "ɜː"}),
    "ɔ": frozenset({"ɔː", "ɜː", "ɚ", "oː"}),
    "ɑ": frozenset({"ɑː"}),
    "iː": frozenset({"i"}),
    "uː": frozenset({"u"}),
    "t": frozenset({"ɾ"}),
    "d": frozenset({"ɾ"}),
}


def _competing(probs: np.ndarray, frames: np.ndarray, target: int, vocab: list[str]) -> str | None:
    if frames.size == 0:
        return None
    mean = probs[frames].mean(axis=0)
    mean[target] = -1.0
    mean[0] = -1.0                       # 공백(<pad>)은 '다른 소리'가 아니다
    alt = int(np.argmax(mean))
    sym = vocab[alt] if alt < len(vocab) else ""
    if not sym or len(sym) > 4 or sym.startswith("<"):
        return None
    return sym


def greedy(logp: np.ndarray, vocab: list[str], blank: int = 0) -> list[str]:
    """정렬 없이 들린 음소열(프레임 argmax → 연속 중복·공백 제거). 참고용."""
    ids = logp.argmax(axis=1)
    out, prev = [], -1
    for i in ids:
        if i != prev and i != blank and i < len(vocab) and not vocab[i].startswith("<"):
            out.append(vocab[i])
        prev = i
    return out


def evaluate(target: str, logp: np.ndarray, vocab: list[str], index: dict[str, int],
             duration_ms: int | None = None) -> dict[str, Any]:
    tokens = g2p.tokenize(target)
    if not tokens:
        return {"status": "empty_target"}
    known = [(t, index[t.ipa]) for t in tokens if t.ipa in index]
    unknown = [t.ipa for t in tokens if t.ipa not in index]
    ids = [i for _, i in known]
    spans = forced_align(logp, ids) if ids else []
    if ids and not spans:
        return {"status": "unaligned", "reason": "no_path"}     # 소리가 목표 음소 수보다 짧다
    probs = np.exp(logp).astype(np.float32)
    T = int(logp.shape[0])
    ms_per_frame = (duration_ms / T) if duration_ms and T else 20.0

    rows: list[dict[str, Any]] = []
    ok = weak = missing = 0
    worst: dict[str, Any] | None = None
    for (tok, tid), (s, e) in zip(known, spans):
        frames = np.arange(s, e + 1) if e >= s else np.array([], dtype=int)
        if frames.size == 0:
            gop = 0.0
        else:
            gop = float(np.mean(probs[frames, tid] / np.maximum(probs[frames].max(axis=1), 1e-6)))
        status = "missing" if frames.size == 0 or gop < MISSING_GOP else ("weak" if gop < WEAK_GOP else "ok")
        alt = _competing(probs, frames, tid, vocab) if status != "ok" else None
        variant = alt if alt and alt in EQUIVALENT.get(tok.ipa, ()) else None
        if variant:
            status = "ok"
        ok += status == "ok"
        weak += status == "weak"
        missing += status == "missing"
        row: dict[str, Any] = {
            "ipa": tok.ipa, "arpabet": tok.arpabet, "word": tok.word, "word_index": tok.word_index,
            "start_ms": int(round(s * ms_per_frame)) if frames.size else None,
            "end_ms": int(round((e + 1) * ms_per_frame)) if frames.size else None,
            "gop": round(gop, 3), "status": status,
        }
        if tok.fallback:
            row["fallback"] = True
        if variant:
            row["variant"] = variant            # 같은 소리의 다른 표기로 들림(오류 아님)
        if status != "ok":
            if alt:
                row["heard_as"] = alt
            # 근사 발음(사전에 없는 단어)의 음소는 '틀렸다'고 짚지 않는다 — 목표 자체가 추정이다
            if not tok.fallback and (worst is None or gop < worst["gop"]):
                worst = dict(row)
        rows.append(row)

    total = ok + weak + missing
    hit, nwords, fallback_words = g2p.coverage(target)
    focus = None
    if worst is not None:
        label, tip = tip_for(worst["ipa"])
        focus = {"ipa": worst["ipa"], "label": label, "tip": tip, "word": worst["word"],
                 "gop": worst["gop"], "heard_as": worst.get("heard_as")}
    return {
        "status": "ok",
        "basis": "acoustic",
        "model": MODEL_NAME,
        "inventory": f"espeak-ipa/{len(vocab)}",
        "frames": T,
        "ms_per_frame": round(ms_per_frame, 2),
        "phoneme_accuracy": round(100.0 * ok / total, 1) if total else None,
        "counts": {"ok": ok, "weak": weak, "missing": missing, "unknown": len(unknown)},
        "lexicon": {"hits": hit, "words": nwords, "fallback_words": fallback_words},
        "heard": greedy(logp, vocab),
        "phonemes": rows[:MAX_TOKENS],
        "weak": [r for r in rows if r["status"] != "ok"][:5],
        "focus": focus,
    }
