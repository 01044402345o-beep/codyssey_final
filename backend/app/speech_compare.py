"""말하기 판정은 코드가 한다 — 받아쓴 문장(heard)과 목표 문장(target)을 단어 단위로 비교한다.

AI 는 목표 문장을 모른 채 받아쓰기만 하고(app/main.py TRANSCRIBE_PROMPT), 점수·빠진 단어·다른 단어는
여기서 결정한다. 같은 입력이면 항상 같은 결과다.

점수의 뜻: '목표 문장을 단어 단위로 맞게 말했는가'(0~100). 발음의 질(억양·강세·음소)은 재지 않는다.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

_WORD = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)*")

# 받아쓰기 모델이 '말 없음'을 글자로 적는 경우. 들린 문장으로 인정하지 않는다.
_PLACEHOLDER = re.compile(
    # 학습자가 실제로 말할 수 있는 단어(none, nothing 등)는 넣지 않는다.
    r"^\W*(?:silence|silent|no speech|no audio|no voice|inaudible|unintelligible|no_speech|"
    r"\[[^\]]*\]|\([^)]*\))\W*$",
    re.IGNORECASE,
)


def words(text: str) -> list[str]:
    """소문자 단어 목록. 구두점은 버리고 축약(I'd, don't)은 한 단어로 둔다."""
    return _WORD.findall((text or "").lower().replace("’", "'"))


def is_placeholder(text: str) -> bool:
    """빈 문자열, 영문자 없는 문자열('...'), '[silence]'·'(no speech)' 같은 표기면 True."""
    t = (text or "").strip()
    if not t or not re.search(r"[A-Za-z]", t):
        return True
    return bool(_PLACEHOLDER.match(t))


def compare(target: str, heard: str) -> dict[str, Any]:
    """target 과 heard 를 단어 단위로 맞춰 본다.

    score   = 100 × 2M / (T + H)  (M: 같은 자리에서 맞은 단어 수, T·H: 각 단어 수)
              빠뜨린 단어와 덧붙인 단어를 똑같이 깎는다.
    missing = 목표에는 있는데 말하지 않은 단어
    extra   = 목표에 없는데 말한 단어
    replaced= [목표 단어들, 대신 말한 단어들] 쌍
    """
    t, h = words(target), words(heard)
    if not t:
        return {"score": None, "missing": [], "extra": [], "replaced": [], "target_words": 0, "heard_words": len(h)}
    sm = SequenceMatcher(a=t, b=h, autojunk=False)
    matched = sum(b.size for b in sm.get_matching_blocks())
    missing: list[str] = []
    extra: list[str] = []
    replaced: list[list[str]] = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "delete":
            missing.extend(t[i1:i2])
        elif op == "insert":
            extra.extend(h[j1:j2])
        elif op == "replace":
            replaced.append([" ".join(t[i1:i2]), " ".join(h[j1:j2])])
    score = round(100 * 2 * matched / (len(t) + len(h))) if (t or h) else 0
    return {
        "score": score,
        "missing": missing,
        "extra": extra,
        "replaced": replaced,
        "target_words": len(t),
        "heard_words": len(h),
    }


def template_feedback(diff: dict[str, Any]) -> tuple[str, str]:
    """피드백 AI 호출이 끝내 실패했을 때의 대체 문구 (사실만 말한다)."""
    if diff.get("replaced"):
        want, said = diff["replaced"][0]
        fix = f"'{want}' 대신 '{said}'(으)로 들렸어요. '{want}'를 또렷하게 다시 말해 보세요."
    elif diff.get("missing"):
        fix = f"'{' '.join(diff['missing'][:3])}'이(가) 들리지 않았어요. 빠뜨리지 말고 다시 말해 보세요."
    elif diff.get("extra"):
        fix = f"목표 문장에 없는 '{' '.join(diff['extra'][:3])}'이(가) 들렸어요."
    else:
        fix = "목표 문장의 단어를 모두 말했어요."
    return fix, "듣기 버튼으로 원어민 발음을 들은 뒤 따라 말해 보세요."


# ---------------------------------------------------------------- 전사 환각 필터
# seongbin45/transcribe_app core/engines/local_whisper.py 에서 가져왔다. transcribe_app 은 이 필터를
# 로컬 엔진에만 적용했지만(커밋 교차검증으로 확인), 여기서는 모든 STT 공급자 결과에 적용한다.

# Whisper 가 무음·저에너지 구간에서 지어내는 것으로 잘 알려진 문구(유튜브 자막 학습 영향).
# transcribe_app 목록 그대로. "Thank you." 처럼 학습 문장일 수 있는 짧은 말은 넣지 않는다.
HALLUCINATION_PHRASES = {
    "시청해주셔서 감사합니다",
    "구독과 좋아요 부탁드립니다",
    "구독과 좋아요",
    "다음 영상에서 만나요",
    "많은 시청 부탁드립니다",
    "구독 좋아요 알림설정",
    "thank you for watching",
    "please subscribe",
    "don't forget to subscribe",
    "like and subscribe",
    "see you in the next video",
}
NO_SPEECH_PROB_THRESHOLD = 0.85        # transcribe_app: 모델 스스로 '거의 무음'이라고 본 세그먼트
WHISPER_NO_SPEECH_THRESHOLD = 0.6      # openai/whisper 기본 규칙: no_speech_prob > 0.6
WHISPER_LOGPROB_THRESHOLD = -1.0       #   그리고 avg_logprob < -1.0 이면 무음으로 본다


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def hallucination_reason(text: str, no_speech_prob: Any = None, avg_logprob: Any = None) -> str | None:
    """버릴 이유. 값이 없는 신호(공급자가 안 준 필드)는 그 규칙만 건너뛴다."""
    normalized = (text or "").strip().strip(".!?~ ").lower()
    if normalized in HALLUCINATION_PHRASES:
        return "known_phrase"
    nsp, lp = _num(no_speech_prob), _num(avg_logprob)
    if nsp is not None and nsp > NO_SPEECH_PROB_THRESHOLD:
        return "no_speech_prob"
    if nsp is not None and lp is not None and nsp > WHISPER_NO_SPEECH_THRESHOLD and lp < WHISPER_LOGPROB_THRESHOLD:
        return "no_speech_and_low_logprob"
    return None


def filter_segments(text: str, segments: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """(남은 텍스트, 버린 세그먼트 목록). 세그먼트가 없으면 전체 텍스트에 문구 규칙만 적용한다."""
    dropped: list[dict[str, Any]] = []
    if not segments:
        reason = hallucination_reason(text)
        if reason:
            return "", [{"text": text, "reason": reason}]
        return (text or "").strip(), []
    kept: list[str] = []
    for seg in segments:
        t = str(seg.get("text") or "").strip()
        reason = hallucination_reason(t, seg.get("no_speech_prob"), seg.get("avg_logprob"))
        if reason:
            dropped.append({"text": t, "reason": reason,
                            "no_speech_prob": _num(seg.get("no_speech_prob")),
                            "avg_logprob": _num(seg.get("avg_logprob"))})
        elif t:
            kept.append(t)
    return " ".join(kept).strip(), dropped
