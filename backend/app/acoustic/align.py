"""CTC 강제정렬 — 프레임별 음소 사후확률에서 '어느 음소가 어디에 있었는지'를 찾는다.

CTC 음소 분류기는 프레임별 확률만 준다. 경계와 음소별 점수를 얻으려면 정렬 계층이 따로 필요하다
(조사 H7 기각 사유). 여기서는 blank 를 포함한 Viterbi 로 목표 음소열을 강제 통과시킨다.
"""
from __future__ import annotations

import numpy as np

NEG = np.float32(-1e30)


def log_softmax(x: np.ndarray) -> np.ndarray:
    x = x.astype(np.float32)
    m = x.max(axis=-1, keepdims=True)
    z = x - m
    return z - np.log(np.exp(z).sum(axis=-1, keepdims=True))


def forced_align(logp: np.ndarray, tokens: list[int], blank: int = 0) -> list[tuple[int, int]]:
    """logp (T,V) · tokens(음소 id 열) → 음소별 (start_frame, end_frame) [포함].

    실패하면(경로 없음) 빈 목록. 프레임을 하나도 못 받은 음소는 (start, start-1) 로 돌려준다.
    """
    T = int(logp.shape[0])
    L = len(tokens)
    if T <= 0 or L == 0:
        return []
    S = 2 * L + 1
    tok = np.full(S, -1, dtype=np.int64)
    tok[1::2] = np.asarray(tokens, dtype=np.int64)
    emit = np.empty((T, S), dtype=np.float32)
    emit[:] = logp[:, np.maximum(tok, 0)]
    emit[:, 0::2] = logp[:, blank][:, None]

    dp = np.full(S, NEG, dtype=np.float32)
    bp = np.zeros((T, S), dtype=np.int8)
    dp[0] = emit[0, 0]
    if S > 1:
        dp[1] = emit[0, 1]
    for t in range(1, T):
        best = dp.copy()
        arg = np.zeros(S, dtype=np.int8)
        step1 = np.full(S, NEG, dtype=np.float32)
        step1[1:] = dp[:-1]
        m1 = step1 > best
        best = np.where(m1, step1, best)
        arg = np.where(m1, np.int8(1), arg)
        if S > 2:
            step2 = np.full(S, NEG, dtype=np.float32)
            step2[2:] = dp[:-2]
            same = tok[2:] == tok[:-2]
            tail = step2[2:]
            tail[same] = NEG
            step2[2:] = tail
            m2 = step2 > best
            best = np.where(m2, step2, best)
            arg = np.where(m2, np.int8(2), arg)
        dp = best + emit[t]
        bp[t] = arg

    end = S - 1 if dp[S - 1] >= dp[S - 2] else S - 2
    if not np.isfinite(dp[end]) or dp[end] <= NEG / 2:
        return []
    state = end
    spans: list[list[int]] = [[-1, -1] for _ in range(S)]
    for t in range(T - 1, -1, -1):
        if spans[state][1] < 0:
            spans[state][1] = t
        spans[state][0] = t
        state -= int(bp[t, state])
    out: list[tuple[int, int]] = []
    for i in range(L):
        s, e = spans[2 * i + 1]
        out.append((s, e) if s >= 0 else (0, -1))
    return out
