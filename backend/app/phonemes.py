"""음소 단위 비교 — 1단계: 텍스트 → 음소(CMUdict) · 음소열 정렬(대치·삭제·삽입) · 음소 오류율(PER).

목표 문장(target)과 받아쓴 문장(heard)을 각각 사전 발음으로 바꾼 뒤 음소 단위로 맞춰 본다.
같은 입력이면 항상 같은 결과다(모델 없음, 외부 호출 없음).

이 단계의 한계 — 결과에 basis="transcript" 로 표시한다:
  heard 는 받아쓰기(STT) 결과라서, 받아쓰기가 이미 단어로 고쳐 적은 발음 차이는 보이지 않는다.
  예) 'seat' 를 [siːt] 대신 [sɪt] 로 말해도 받아쓰기가 'seat' 로 적으면 여기서는 차이가 없다.
  실제 소리에서 음소를 찾는 층(음성 → 음소 인식기)은 이 모듈의 compare_phones() 에 그대로 꽂는다.

사전에 없는 단어(고유명사·숫자·신조어)는 음소를 지어내지 않는다. status="unknown" 으로 두고 PER 에서 뺀다.
"""
from __future__ import annotations

import gzip
import hashlib
import itertools
import re
import threading
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from .speech_compare import words

LEXICON_PATH = Path(__file__).resolve().parent / "lexicon" / "cmudict.dict.gz"
LEXICON_SHA256 = "81917843c7f44ce2b094ac63873c2c7a4cf802040792c455ba3ca406891c3d22"   # 압축 푼 내용(lexicon/README.md)

VOWELS = frozenset("AA AE AH AO AW AY EH ER EY IH IY OW OY UH UW".split())
CONSONANTS = frozenset("B CH D DH F G HH JH K L M N NG P R S SH T TH V W Y Z ZH".split())
PHONES = VOWELS | CONSONANTS

# 화면 표시와, 국제음성기호(IPA)를 내는 음소 인식기 결과를 맞출 때 쓴다(미국 영어 기준, 강세 표시 없음).
ARPABET_IPA = {
    "AA": "ɑ", "AE": "æ", "AH": "ʌ", "AO": "ɔ", "AW": "aʊ", "AY": "aɪ", "EH": "ɛ", "ER": "ɝ", "EY": "eɪ",
    "IH": "ɪ", "IY": "i", "OW": "oʊ", "OY": "ɔɪ", "UH": "ʊ", "UW": "u",
    "B": "b", "CH": "tʃ", "D": "d", "DH": "ð", "F": "f", "G": "ɡ", "HH": "h", "JH": "dʒ", "K": "k", "L": "l",
    "M": "m", "N": "n", "NG": "ŋ", "P": "p", "R": "ɹ", "S": "s", "SH": "ʃ", "T": "t", "TH": "θ", "V": "v",
    "W": "w", "Y": "j", "Z": "z", "ZH": "ʒ",
}

_MAX_VARIANT_COMBOS = 64   # 한 구간에서 발음 변이 조합을 이보다 많이 보지 않는다(긴 구간은 첫 발음으로)

_lock = threading.Lock()
# 단어 → "S IY T|S IH T" (변이를 | 로 이은 문자열 하나). 음소마다 객체를 만들면 13만 단어에 70MB 넘게 든다.
_lexicon: dict[str, str] | None = None


class LexiconError(RuntimeError):
    pass


def _parse(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        head, *phones = line.split()
        word = head.split("(", 1)[0].lower()
        pron = [ph.rstrip("012") for ph in phones]
        if not pron or any(ph not in PHONES for ph in pron):
            continue
        joined = " ".join(pron)
        prev = out.get(word)
        if prev is None:
            out[word] = joined
        elif joined not in prev.split("|"):      # 강세만 다른 변이는 하나로 친다
            out[word] = prev + "|" + joined
    return out


def lexicon() -> dict[str, str]:
    """단어 → 발음 변이 문자열(강세 숫자 제거). 처음 한 번만 읽는다."""
    global _lexicon
    if _lexicon is None:
        with _lock:
            if _lexicon is None:
                raw = gzip.decompress(LEXICON_PATH.read_bytes())
                if hashlib.sha256(raw).hexdigest() != LEXICON_SHA256:
                    raise LexiconError("cmudict hash mismatch")
                _lexicon = _parse(raw.decode("utf-8"))
    return _lexicon


def pronounce(word: str) -> tuple[tuple[str, ...], ...]:
    """사전 발음 변이들(첫 번째가 대표 발음). 없으면 빈 튜플(지어내지 않는다)."""
    entry = lexicon().get((word or "").lower().replace("’", "'"))
    return tuple(tuple(v.split()) for v in entry.split("|")) if entry else ()


_HYPHENED = re.compile(r"[A-Za-z]+(?:-[A-Za-z]+)+")


def tokens(text: str) -> list[str]:
    """speech_compare.words 와 같되, 'Wi-Fi' 처럼 하이픈으로 이은 말은 붙인 형태('wifi')가 사전에 있을 때만 한 단어로 둔다.
    사전에 없으면 하이픈에서 나눈다(words 와 같다). 목표 문장과 받아쓴 문장에 똑같이 적용하므로 'wifi'·'Wi-Fi' 가 같아진다."""
    def join(m: re.Match) -> str:
        joined = m.group(0).replace("-", "")
        return joined if joined.lower() in lexicon() else m.group(0)
    return words(_HYPHENED.sub(join, text or ""))


def to_ipa(phones: list[str] | tuple[str, ...]) -> str:
    return "".join(ARPABET_IPA.get(p, "?") for p in phones)


def _sub_cost(a: str, b: str) -> float:
    if a == b:
        return 0.0
    # 모음끼리·자음끼리 바뀐 것은 대치로, 모음↔자음은 삭제+삽입에 가깝게 본다(정렬 경로만 정한다. 개수 셈은 아래).
    return 1.0 if (a in VOWELS) == (b in VOWELS) else 1.6


def align(ref: list[str] | tuple[str, ...], hyp: list[str] | tuple[str, ...]) -> list[dict[str, Any]]:
    """음소열 정렬. 각 항목 {"op": eq|sub|del|ins, "ref": 음소|None, "hyp": 음소|None, "i": ref 위치|None}.

    비용: 같음 0, 대치 1(모음↔자음 1.6), 삭제·삽입 1. 같은 비용이면 eq/sub → del → ins 순으로 고른다(결정적).
    """
    n, m = len(ref), len(hyp)
    cost = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        cost[i][0] = float(i)
    for j in range(1, m + 1):
        cost[0][j] = float(j)
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost[i][j] = min(cost[i - 1][j - 1] + _sub_cost(ref[i - 1], hyp[j - 1]),
                             cost[i - 1][j] + 1.0, cost[i][j - 1] + 1.0)
    ops: list[dict[str, Any]] = []
    i, j = n, m
    while i or j:
        if i and j and abs(cost[i][j] - (cost[i - 1][j - 1] + _sub_cost(ref[i - 1], hyp[j - 1]))) < 1e-9:
            same = ref[i - 1] == hyp[j - 1]
            ops.append({"op": "eq" if same else "sub", "ref": ref[i - 1], "hyp": hyp[j - 1], "i": i - 1})
            i, j = i - 1, j - 1
        elif i and abs(cost[i][j] - (cost[i - 1][j] + 1.0)) < 1e-9:
            ops.append({"op": "del", "ref": ref[i - 1], "hyp": None, "i": i - 1})
            i -= 1
        else:
            ops.append({"op": "ins", "ref": None, "hyp": hyp[j - 1], "i": None})
            j -= 1
    ops.reverse()
    return ops


def counts(ops: list[dict[str, Any]]) -> dict[str, int]:
    c = {"eq": 0, "sub": 0, "del": 0, "ins": 0}
    for o in ops:
        c[o["op"]] += 1
    return c


def per(ref: list[str] | tuple[str, ...], hyp: list[str] | tuple[str, ...]) -> float | None:
    """음소 오류율 = (대치 + 삭제 + 삽입) / 기준 음소 수. 기준이 비면 None."""
    if not ref:
        return None
    c = counts(align(ref, hyp))
    return (c["sub"] + c["del"] + c["ins"]) / len(ref)


def _distance(ref: tuple[str, ...], hyp: tuple[str, ...]) -> tuple[int, int]:
    c = counts(align(ref, hyp))
    return c["sub"] + c["del"] + c["ins"], c["sub"]


def _best_variants(t_prons: list[tuple[tuple[str, ...], ...]], h_prons: list[tuple[tuple[str, ...], ...]]):
    """구간 안 단어마다 발음 변이를 골라 오류가 가장 적은 조합. 조합이 너무 많으면 첫 발음."""
    combos = 1
    for v in t_prons + h_prons:
        combos *= len(v)
    if combos > _MAX_VARIANT_COMBOS:
        return [v[0] for v in t_prons], [v[0] for v in h_prons]
    best = None
    for tc in itertools.product(*t_prons):
        ref = tuple(p for w in tc for p in w)
        for hc in itertools.product(*h_prons):
            hyp = tuple(p for w in hc for p in w)
            d = _distance(ref, hyp)
            if best is None or d < best[0]:
                best = (d, list(tc), list(hc))
    return best[1], best[2]


def _split_by_word(ops: list[dict[str, Any]], prons: list[tuple[str, ...]]) -> list[list[dict[str, Any]]]:
    """정렬 결과를 목표 단어별로 나눈다. 삽입(ins)은 바로 앞 기준 음소가 속한 단어(맨 앞이면 첫 단어)에 붙인다."""
    owner = [wi for wi, pr in enumerate(prons) for _ in pr]
    per_word: list[list[dict[str, Any]]] = [[] for _ in prons]
    last = 0
    for o in ops:
        if o["i"] is not None:
            last = owner[o["i"]]
        per_word[last].append(o)
    return per_word


def _word_entry(word: str, phones: tuple[str, ...], status: str, ops: list[dict[str, Any]] | None = None,
                heard: str | None = None) -> dict[str, Any]:
    e: dict[str, Any] = {"word": word, "status": status, "phones": list(phones), "ipa": to_ipa(phones)}
    if heard is not None:
        e["heard"] = heard
    if ops is not None:
        e["ops"] = [{"op": o["op"], "ref": o["ref"], "hyp": o["hyp"],
                     "ref_ipa": ARPABET_IPA.get(o["ref"], "") if o["ref"] else "",
                     "hyp_ipa": ARPABET_IPA.get(o["hyp"], "") if o["hyp"] else ""} for o in ops]
    return e


def compare(target: str, heard: str) -> dict[str, Any]:
    """목표 문장과 받아쓴 문장을 음소 단위로 비교한다.

    words[]: 목표 단어마다
      status  ok(같은 단어) · diff(다른 단어로 들림 — ops 에 음소 차이) · missing(말하지 않음) · unknown(사전에 없음)
      phones/ipa: 사전 발음, ops: [{op, ref, hyp}] (diff·missing 만)
    extra[]: 목표에 없는데 들린 단어(사전에 있으면 phones 포함)
    per: 사전에 있는 목표 단어들 기준 음소 오류율(0~). 비교할 음소가 없으면 None
    """
    t, h = tokens(target), tokens(heard)
    out_words: list[dict[str, Any]] = []
    extra: list[dict[str, Any]] = []
    total = {"ref": 0, "sub": 0, "del": 0, "ins": 0}

    def add(c: dict[str, int], n_ref: int) -> None:
        total["ref"] += n_ref
        for k in ("sub", "del", "ins"):
            total[k] += c[k]

    for op, i1, i2, j1, j2 in SequenceMatcher(a=t, b=h, autojunk=False).get_opcodes():
        tw, hw = t[i1:i2], h[j1:j2]
        if op == "equal":
            for w in tw:
                v = pronounce(w)
                if not v:
                    out_words.append(_word_entry(w, (), "unknown"))
                    continue
                out_words.append(_word_entry(w, v[0], "ok"))
                add({"sub": 0, "del": 0, "ins": 0}, len(v[0]))
        elif op == "delete":
            for w in tw:
                v = pronounce(w)
                if not v:
                    out_words.append(_word_entry(w, (), "unknown"))
                    continue
                ops = align(v[0], ())
                out_words.append(_word_entry(w, v[0], "missing", ops))
                add(counts(ops), len(v[0]))
        elif op == "insert":
            for w in hw:
                v = pronounce(w)
                extra.append({"word": w, "phones": list(v[0]) if v else [], "ipa": to_ipa(v[0]) if v else ""})
        else:   # replace: 구간 전체를 음소로 이어 붙여 맞춘 뒤, 차이를 목표 단어별로 나눈다
            t_prons = [pronounce(w) for w in tw]
            h_prons = [pronounce(w) for w in hw]
            if any(not v for v in t_prons) or any(not v for v in h_prons):
                # 한쪽이라도 사전에 없으면 이 구간은 음소로 말하지 않는다(지어내지 않는다)
                for w, v in zip(tw, t_prons):
                    out_words.append(_word_entry(w, v[0] if v else (), "unknown", heard=" ".join(hw)))
                continue
            tc, hc = _best_variants(t_prons, h_prons)
            ref = tuple(p for pr in tc for p in pr)
            hyp = tuple(p for pr in hc for p in pr)
            ops = align(ref, hyp)
            add(counts(ops), len(ref))
            per_word = _split_by_word(ops, tc)
            heard_txt = " ".join(hw)
            for wi, w in enumerate(tw):
                status = "ok" if all(o["op"] == "eq" for o in per_word[wi]) else "diff"
                out_words.append(_word_entry(w, tc[wi], status, per_word[wi], heard=heard_txt))

    errors = total["sub"] + total["del"] + total["ins"]
    return {
        "basis": "transcript",     # 받아쓴 글자에서 나온 음소다 — 실제 소리의 음소가 아니다(모듈 설명 참고)
        "inventory": "arpabet",
        "words": out_words,
        "extra": extra,
        "per": round(errors / total["ref"], 4) if total["ref"] else None,
        "counts": {"ref_phones": total["ref"], "sub": total["sub"], "del": total["del"], "ins": total["ins"]},
        "unknown_words": [w["word"] for w in out_words if w["status"] == "unknown"],
    }


def compare_phones(target: str, heard_phones: list[str]) -> dict[str, Any]:
    """목표 문장과 '실제 소리에서 인식한 음소열'을 비교한다(음성 → 음소 인식기를 붙일 자리).

    heard_phones 는 ARPAbet(강세 없음). 목표 문장의 사전에 없는 단어가 하나라도 있으면 비교하지 않는다
    (그 단어 자리의 음소를 모르면 정렬이 어긋나 엉뚱한 단어에 오류가 붙는다).
    """
    t = tokens(target)
    prons = [pronounce(w) for w in t]
    unknown = [w for w, v in zip(t, prons) if not v]
    hyp = tuple(p for p in heard_phones if p in PHONES)
    if not t or unknown:
        return {"basis": "acoustic", "inventory": "arpabet", "words": [], "per": None,
                "counts": {"ref_phones": 0, "sub": 0, "del": 0, "ins": 0}, "unknown_words": unknown}
    tc, _ = _best_variants(prons, [(hyp,)])
    ref = tuple(p for pr in tc for p in pr)
    ops = align(ref, hyp)
    per_word = _split_by_word(ops, tc)
    c = counts(ops)
    out = []
    for wi, w in enumerate(t):
        st = "ok" if all(o["op"] == "eq" for o in per_word[wi]) else (
            "missing" if all(o["op"] == "del" for o in per_word[wi]) else "diff")
        out.append(_word_entry(w, tc[wi], st, per_word[wi]))
    return {"basis": "acoustic", "inventory": "arpabet", "words": out,
            "per": round((c["sub"] + c["del"] + c["ins"]) / len(ref), 4),
            "counts": {"ref_phones": len(ref), "sub": c["sub"], "del": c["del"], "ins": c["ins"]},
            "unknown_words": []}


def _sig(w: dict[str, Any]) -> tuple:
    return (w["status"], tuple((o["op"], o["ref"], o["hyp"]) for o in w.get("ops") or ()))


def consensus(target: str, heard_a: str, heard_b: str) -> dict[str, Any]:
    """두 받아쓰기(서로 다른 모델 계열)가 **같은 음소 차이**를 낸 단어만 차이로 남긴다.

    speech_compare.compare_consensus 와 같은 원칙이다 — 한쪽 받아쓰기만 다르게 적은 단어는
    그 받아쓰기의 실수일 수 있으므로 status="unsure"(음소 차이 없음)로 둔다.
    per·counts 는 두 쪽이 같은 판정을 낸 단어만 센다.
    """
    a, b = compare(target, heard_a), compare(target, heard_b)
    out: list[dict[str, Any]] = []
    total = {"ref_phones": 0, "sub": 0, "del": 0, "ins": 0}
    for wa, wb in zip(a["words"], b["words"]):
        if "unknown" in (wa["status"], wb["status"]):
            out.append({**{k: wa[k] for k in ("word", "phones", "ipa")}, "status": "unknown"})
            continue
        if _sig(wa) != _sig(wb):
            out.append({**{k: wa[k] for k in ("word", "phones", "ipa")}, "status": "unsure"})
            continue
        out.append(wa)
        total["ref_phones"] += len(wa["phones"])
        for o in wa.get("ops") or ():
            if o["op"] in ("sub", "del", "ins"):
                total[o["op"]] += 1
    errors = total["sub"] + total["del"] + total["ins"]
    return {
        "basis": "transcript",
        "inventory": "arpabet",
        "words": out,
        "per": round(errors / total["ref_phones"], 4) if total["ref_phones"] else None,
        "counts": total,
        "unknown_words": [w["word"] for w in out if w["status"] == "unknown"],
        "unsure_words": [w["word"] for w in out if w["status"] == "unsure"],
    }
