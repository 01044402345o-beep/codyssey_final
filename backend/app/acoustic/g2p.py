"""텍스트 → 음소(IPA). 사전은 app/lexicon/cmudict.dict.gz(BSD 계열, 해시 확인)를 그대로 쓴다.

app/phonemes.py 와 같은 사전이지만 여기서는 강세 숫자를 남긴다 — 강세 없는 AH 는 슈와(ə)라서
음성 인식기(espeak IPA)와 맞추려면 강세가 필요하다.

사전에 없는 단어는 철자 규칙으로 근사한다(GPL 도구를 쓰지 않으려고 이 파일에 직접 쓴 규칙).
근사한 단어는 Token.fallback=True 로 표시하고, 결과에도 몇 단어가 근사였는지 밝힌다.
"""
from __future__ import annotations

import gzip
import hashlib
import re
import threading
from dataclasses import dataclass

from ..phonemes import LEXICON_PATH, LEXICON_SHA256, LexiconError
from ..speech_compare import words as _words
from .inventory import ARPABET_TO_IPA, SCHWA

_lock = threading.Lock()
_lex: dict[str, list[str]] | None = None


def _load() -> dict[str, list[str]]:
    """단어 → 첫 발음(강세 숫자 포함 ARPAbet)."""
    global _lex
    if _lex is None:
        with _lock:
            if _lex is None:
                raw = gzip.decompress(LEXICON_PATH.read_bytes())
                if hashlib.sha256(raw).hexdigest() != LEXICON_SHA256:
                    raise LexiconError("cmudict hash mismatch")
                lex: dict[str, list[str]] = {}
                for line in raw.decode("utf-8").splitlines():
                    line = line.split("#", 1)[0].strip()
                    if not line:
                        continue
                    head, *phones = line.split()
                    if "(" in head or not phones:      # word(2) 같은 변이형은 첫 발음만 쓴다
                        continue
                    lex.setdefault(head.lower(), phones)
                _lex = lex
    return _lex


# 규칙 기반 폴백: 철자 → 음소(근사). 사전에 없는 고유명사·신조어만 지나간다.
_DIGRAPHS = [
    ("tion", ["SH", "AH0", "N"]), ("sion", ["ZH", "AH0", "N"]),
    ("ough", ["AO1"]), ("augh", ["AO1"]), ("eigh", ["EY1"]),
    ("tch", ["CH"]), ("dge", ["JH"]), ("sch", ["S", "K"]),
    ("th", ["TH"]), ("sh", ["SH"]), ("ch", ["CH"]), ("ph", ["F"]),
    ("wh", ["W"]), ("ck", ["K"]), ("ng", ["NG"]), ("qu", ["K", "W"]),
    ("ee", ["IY1"]), ("ea", ["IY1"]), ("oo", ["UW1"]), ("ou", ["AW1"]),
    ("ow", ["OW1"]), ("ai", ["EY1"]), ("ay", ["EY1"]), ("oa", ["OW1"]),
    ("oi", ["OY1"]), ("oy", ["OY1"]), ("au", ["AO1"]), ("ie", ["IY1"]),
    ("ar", ["AA1", "R"]), ("or", ["AO1", "R"]), ("er", ["ER0"]), ("ir", ["ER0"]),
    ("ur", ["ER0"]),
]
_SINGLES = {
    "a": ["AE1"], "b": ["B"], "c": ["K"], "d": ["D"], "e": ["EH1"], "f": ["F"],
    "g": ["G"], "h": ["HH"], "i": ["IH1"], "j": ["JH"], "k": ["K"], "l": ["L"],
    "m": ["M"], "n": ["N"], "o": ["AA1"], "p": ["P"], "q": ["K"], "r": ["R"],
    "s": ["S"], "t": ["T"], "u": ["AH1"], "v": ["V"], "w": ["W"], "x": ["K", "S"],
    "y": ["Y"], "z": ["Z"],
}
_SILENT_E = re.compile(r"[^aeiou]e$")


def _lts(word: str) -> list[str]:
    w = re.sub(r"[^a-z]", "", word.lower())
    out: list[str] = []
    i = 0
    long_vowel = bool(_SILENT_E.search(w))
    while i < len(w):
        for src, phones in _DIGRAPHS:
            if w.startswith(src, i):
                out.extend(phones)
                i += len(src)
                break
        else:
            ch = w[i]
            if ch == "c" and i + 1 < len(w) and w[i + 1] in "eiy":
                out.append("S")
            elif ch == "g" and i + 1 < len(w) and w[i + 1] in "eiy":
                out.append("JH")
            elif ch == "y" and i == len(w) - 1 and len(w) > 2:
                out.append("IY0")
            elif ch == "e" and i == len(w) - 1 and len(w) > 2:
                pass                                   # 묵음 e
            elif ch in "aeiou" and long_vowel:
                out.append({"a": "EY1", "e": "IY1", "i": "AY1", "o": "OW1", "u": "UW1"}[ch])
                long_vowel = False
            else:
                out.extend(_SINGLES.get(ch, []))
            i += 1
    return out or ["AH0"]


def _to_ipa(p: str) -> tuple[str, int]:
    stress = int(p[-1]) if p and p[-1].isdigit() else 0
    base = p.rstrip("012").upper()
    if base == "AH" and stress == 0:
        return SCHWA, stress
    return ARPABET_TO_IPA.get(base, ""), stress


_HYPHENED = re.compile(r"[A-Za-z]+(?:-[A-Za-z]+)+")


def words(text: str) -> list[str]:
    """app.phonemes.tokens 와 같은 규칙: 'Wi-Fi' 는 붙인 형태가 사전에 있을 때만 한 단어."""
    lex = _load()
    return _words(_HYPHENED.sub(lambda m: m.group(0).replace("-", "") if m.group(0).replace("-", "").lower() in lex
                                else m.group(0), text or ""))


@dataclass(frozen=True)
class Token:
    ipa: str
    arpabet: str
    word: str
    word_index: int
    stress: int
    fallback: bool


def tokenize(text: str) -> list[Token]:
    """문장 → 음소 토큰. 사전에 없으면 규칙 폴백(fallback=True)."""
    lex = _load()
    out: list[Token] = []
    for wi, w in enumerate(words(text)):
        phones = lex.get(w)
        fb = phones is None
        for p in (phones or _lts(w)):
            ipa, stress = _to_ipa(p)
            if ipa:
                out.append(Token(ipa=ipa, arpabet=p.rstrip("012").upper(), word=w, word_index=wi, stress=stress, fallback=fb))
    return out


def coverage(text: str) -> tuple[int, int, list[str]]:
    """(사전에 있던 단어 수, 전체 단어 수, 근사한 단어들)."""
    lex = _load()
    ws = words(text)
    miss = [w for w in ws if w not in lex]
    return len(ws) - len(miss), len(ws), miss
