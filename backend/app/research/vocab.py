"""장소 어휘 추출 — 조사된 장소마다 문장에 쓸 '그 장소다운' 영어 낱말(대표 음식·볼거리·장소 종류)을 뽑는다.

AI 호출 없이 코드로(결정적·무료), 그리고 LLM 추출(extract.py)이 낸 낱말을 검증해 보탠다.
- 출처: 장소 이름 + 영어 설명(위키보이지·위키백과 원문, desc_lang 이 en 이거나 비었을 때만), OSM cuisine 태그, TourAPI 신분류.
- 규칙 1 — 사전: 여행 어휘 사전(DISHES·FEATURES·TYPES)의 낱말이 원문에 낱말 경계로 있으면.
- 규칙 2 — 패턴: "specializes in X", "famous for (its) X", "known for X", "serves X", "try the X", "houses a X" …
  X 는 원문 그대로의 1~3 낱말(라틴 문자·발음 기호 포함, 숫자·기호 없음), 앞의 꾸밈말(delicious·famous…)은 뗀다.
- 규칙 3 — 태그: OSM cuisine(sushi;ramen), TourAPI 중분류(FD01 Korean food …)는 매핑표로.
- 불변식(테스트로 고정): 낱말은 원문(이름·설명·태그) 안에 있거나 매핑표에서 나온다, 1~4 낱말·40자 이하, 꺾쇠·중괄호·URL·숫자 없음.
- 한 장소 최대 MAX_TERMS 개: 구체적인 것(음식·볼거리) → 종류 순. 출처(src)를 함께 남긴다.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional

MAX_TERMS = 4
MAX_CHARS = 40

DISHES = (
    "sushi", "sashimi", "ramen", "udon", "soba", "tempura", "yakitori", "okonomiyaki", "takoyaki", "tonkatsu", "kaiseki",
    "wagyu", "yakiniku", "gyoza", "onigiri", "kakinoha-zushi", "matcha", "mochi", "taiyaki", "bento", "shabu-shabu",
    "bibimbap", "bulgogi", "kimchi", "tteokbokki", "naengmyeon", "galbi", "samgyeopsal", "japchae", "makchang",
    "yukhoe", "kalguksu", "mandu", "hotteok", "korean barbecue", "fried chicken", "whelk soup",
    "pho", "banh mi", "cao lầu", "mì quảng", "white rose dumplings", "spring rolls", "dim sum", "dumplings", "noodles",
    "pizza", "pasta", "gelato", "risotto", "focaccia", "espresso", "cappuccino", "croissant", "baguette", "crêpes",
    "paella", "tapas", "churros", "ceviche", "cuy", "alpaca", "lomo saltado", "empanadas", "tacos", "chocolate",
    "pretzel", "schneeballen", "bratwurst", "schnitzel", "sausages", "beer", "wine", "cider", "cocktails",
    "bagels", "burgers", "hamburger", "hot dogs", "cheesecake", "pastrami", "steak", "seafood", "oysters", "lobster",
    "curry", "kebab", "falafel", "stews", "soup", "barbecue", "coffee", "tea", "cakes", "pastries", "ice cream",
    "banana fritters", "brunch", "breakfast", "set menu", "tasting menu", "chifa", "wonton", "mentaiko", "monja",
    "kakinohazushi", "tekka-don", "bánh xèo", "bánh mì", "pho bo", "tuna", "salad bar", "buffet", "bread", "pie",
    "hot pot", "fish and chips", "dumpling", "gukbap", "bingsu", "makgeolli", "soju", "sake", "dango", "kushikatsu",
)
FEATURES = (
    "Great Buddha", "giant Buddha", "Buddha statue", "statue", "pagoda", "torii", "main hall", "five-storied pagoda",
    "cherry blossoms", "autumn leaves", "night view", "observation deck", "panoramic views", "skyline", "spire", "dome",
    "frescoes", "mosaics", "stained glass", "cloister", "crypt", "bell tower", "city wall", "town walls", "ramparts",
    "exhibits", "exhibitions", "collection", "ceramics", "textiles", "paintings", "sculptures", "artifacts",
    "telescopes", "planetarium", "aquarium", "deer", "lanterns", "gardens", "garden", "pond", "waterfall", "hot spring",
    "Kabuki", "Noh", "Bunraku", "puppet theatre", "tea ceremony", "workshops", "guided tours", "audio guide", "boat tour",
    "river cruise", "fireworks", "light show", "night market", "street food", "souvenirs", "christmas market",
    "ruins", "terraces", "cave churches", "cave dwellings", "Sassi", "Inca walls", "stone walls", "murals", "graffiti",
    "rooftop", "beach", "harbor", "harbour", "pier", "viewpoint", "lookout",
)
TYPES = (
    "temple", "shrine", "museum", "gallery", "castle", "palace", "park", "market", "cathedral", "church", "basilica",
    "chapel", "monastery", "mosque", "tower", "bridge", "gate", "square", "theatre", "theater", "zoo", "hall",
    "assembly hall", "fortress", "fort", "mall", "library", "observatory", "station", "street", "district", "old town",
    "lake", "island", "mountain", "hill", "stadium", "arena", "memorial", "monument", "cemetery", "ruins",
    "restaurant", "café", "cafe", "bakery", "bar", "pub", "brewery", "teahouse", "izakaya", "food stall", "stall",
    "moat", "village", "old house", "house", "convent", "pizzeria", "trattoria", "osteria", "tavern", "inn", "diner",
    "festival", "golf course", "studio", "film set", "sanctuary", "fountain", "exhibition centre", "farm", "sea wall",
)
# 다른 언어 이름의 종류 낱말(독일어·이탈리아어·스페인어·일본어 로마자) → 영어 종류
FOREIGN_TYPES = (
    (r"kirche|münster", "church"), (r"\bdom\b|kathedrale|duomo|catedral", "cathedral"),
    (r"schloss|burg\b|castello", "castle"), (r"museo|museum", "museum"), (r"chiesa|iglesia|basilica", "church"),
    (r"palazzo|palacio", "palace"), (r"piazza|plaza|platz", "square"),
    (r"jinja|jingū|jingu|taisha|-gū\b", "shrine"), (r"-dera\b|-ji\b|-in\b", "temple"),
    (r"-en\b|teien", "garden"),
    (r"weinstube|wirtshaus|gasthaus|gasthof|trattoria|osteria|taberna", "tavern"), (r"mercado|mercato|markt", "market"),
)
# "Japanese cuisine", "Indian food" 처럼 나라 + 음식
_CUISINE_RE = re.compile(r"(?<![A-Za-z])((?:Japanese|Korean|Chinese|Indian|Italian|Vietnamese|Peruvian|French|German|Mexican|"
                         r"Thai|Spanish|American|Turkish|Greek|Vegan|Vegetarian)\s+(?:food|cuisine|dishes))(?![A-Za-z])", re.I)
# 패턴 뒤 1~3 낱말을 원문 그대로 잡는다
_WORD = r"[A-Za-zÀ-ỹ][A-Za-zÀ-ỹ'’\-]*"
_PATTERNS = (
    r"speciali[sz](?:e|es|ed|ing)\s+in\s+", r"famous\s+for\s+(?:its\s+|their\s+|the\s+)?", r"known\s+for\s+(?:its\s+|their\s+|the\s+)?",
    r"\bserv(?:e|es|ed|ing)\s+(?:up\s+)?", r"\btry\s+(?:the\s+|their\s+|some\s+)?", r"\bspecialty\s+(?:is|are)\s+(?:the\s+)?",
    r"\bhouses\s+(?:a|an|the)\s+", r"\bfeatures\s+(?:a|an|the)\s+",
)
_FLUFF = {"delicious", "tasty", "fresh", "freshly", "great", "good", "excellent", "famous", "best", "local", "authentic",
          "homemade", "traditional", "classic", "amazing", "wonderful", "nice", "very", "really", "also", "some", "many",
          "a", "an", "the", "its", "their", "various", "different", "all", "kinds", "of", "both", "super", "probably",
          "pretty", "quite", "most", "inexpensive", "cheap", "huge", "small", "big", "large", "lovely", "real", "true"}
_STOP = {"and", "or", "with", "in", "at", "for", "to", "from", "by", "on", "is", "are", "was", "were", "but", "as", "that",
         "which", "who", "it", "this", "they", "you", "your", "here", "there", "than", "more", "most", "if", "be",
         "people", "food", "place", "places", "visitors", "customers", "price", "prices", "dishes", "menu", "things"}
CUISINE_MAP = {"japanese": "Japanese food", "korean": "Korean food", "chinese": "Chinese food", "italian": "Italian food",
               "vietnamese": "Vietnamese food", "peruvian": "Peruvian food", "german": "German food", "french": "French food",
               "mexican": "Mexican food", "thai": "Thai food", "indian": "Indian food", "american": "American food",
               "coffee_shop": "coffee", "regional": "local dishes", "noodle": "noodles", "seafood": "seafood"}
TOURAPI_MAP = {"FD01": ("Korean food", "dish"), "FD020100": ("Chinese food", "dish"), "FD020200": ("Japanese food", "dish"),
               "FD020300": ("Western food", "dish"), "FD03": ("snacks", "dish"), "FD04": ("drinks", "dish"),
               "FD05": ("coffee", "dish"), "HS": ("historic site", "type"), "NA": ("nature", "type"),
               "VE": ("cultural venue", "type"), "EX": ("experience", "type")}
_BAD = re.compile(r"[<>{}\[\]@0-9]|https?:|www\.")


def _lex_re(words: Iterable[str]) -> re.Pattern:
    alts = sorted(set(words), key=len, reverse=True)
    return re.compile(r"(?<![A-Za-zÀ-ỹ])(" + "|".join(re.escape(w) for w in alts) + r")(?![A-Za-zÀ-ỹ])", re.I)


_DISH_RE, _FEAT_RE, _TYPE_RE = _lex_re(DISHES), _lex_re(FEATURES), _lex_re(TYPES)
_CANON = {w.casefold(): w for w in DISHES + FEATURES + TYPES}


def canon(t: str) -> str:
    return _CANON.get(t.casefold(), t)


def name_type(name: str) -> str:
    """이름의 머리 명사 종류: 'X of Y' 면 of 앞, 그 안에서 마지막 종류 낱말(Market Square → square, Museum of Art → museum)."""
    head = re.split(r"\s+(?:of|de|del|di|della)\s+", name or "", maxsplit=1, flags=re.I)[0]
    found = [m.group(1) for m in _TYPE_RE.finditer(head)]
    if found:
        return canon(found[-1]).lower()
    low = (name or "").casefold()
    return next((en for pat, en in FOREIGN_TYPES if re.search(pat, low)), "")
_PAT_RE = re.compile("(?:" + "|".join(_PATTERNS) + r")(" + _WORD + r"(?:\s+" + _WORD + r"){0,3})", re.I)


def ok_term(t: str) -> bool:
    t = (t or "").strip()
    return bool(t) and len(t) <= MAX_CHARS and len(t.split()) <= 4 and not _BAD.search(t) and bool(re.search(r"[A-Za-zÀ-ỹ]", t))


def _source(p: dict) -> str:
    desc = p.get("desc_en") or ""
    english = (p.get("desc_lang") or "en") == "en"
    return " ".join(x for x in (p.get("name") or "", desc if english else "") if x)


def _trim(phrase: str) -> str:
    words = re.findall(_WORD, phrase)
    while words and (words[0].lower() in _FLUFF or (words[0].lower().endswith("ly") and len(words) > 1)):
        words = words[1:]
    out = []
    for w in words:
        if w.lower() in _STOP or (out and w.lower() in _FLUFF):
            break
        out.append(w)
        if len(out) == 3:
            break
    return " ".join(out)


def _add(out: list, seen: set, en: str, kind: str, src: str) -> None:
    en = re.sub(r"\s+", " ", en or "").strip(" -'’")
    key = en.casefold()
    if not ok_term(en) or key in seen or any(key in s or s in key for s in seen if len(s) > 3 and len(key) > 3):
        return
    seen.add(key)
    out.append({"en": en, "kind": kind, "src": src})


def for_place(p: dict, llm_terms: Optional[list] = None) -> list[dict]:
    """→ [{en, kind: dish|feature|type, src: llm|pattern|lexicon|cuisine|category}] (최대 MAX_TERMS)."""
    text = _source(p)
    low = text.casefold()
    food = p.get("kind") in ("restaurant", "cafe")
    specific, generic, seen = [], [], set()
    for t in llm_terms or []:                                  # LLM 낱말: 원문에 그대로 있을 때만
        if isinstance(t, str) and ok_term(t) and t.strip().casefold() in low:
            _add(specific, seen, t.strip(), "dish" if food else "feature", "llm")
    for m in _PAT_RE.finditer(text):
        phrase = _trim(m.group(1))
        if phrase and phrase.casefold() not in {n.casefold() for n in (p.get("name") or "",)}:
            _add(specific, seen, phrase, "dish" if food else "feature", "pattern")
    if food:
        for m in _CUISINE_RE.finditer(text):
            _add(specific, seen, m.group(1), "dish", "pattern")
    for m in (_DISH_RE if food else _FEAT_RE).finditer(text):
        _add(specific, seen, canon(m.group(1)), "dish" if food else "feature", "lexicon")
    if food:
        for c in re.split(r"[;,]\s*", (p.get("cuisine") or "").lower()):
            if c in CUISINE_MAP:
                _add(specific, seen, CUISINE_MAP[c], "dish", "cuisine")
            elif c and _DISH_RE.fullmatch(c):
                _add(specific, seen, c, "dish", "cuisine")
    cat = str(p.get("category") or "")
    for code in (cat, cat[:4], cat[:2]):
        if code in TOURAPI_MAP:
            en, kind = TOURAPI_MAP[code]
            _add(specific if kind == "dish" else generic, seen, en, kind, "category")
            break
    nt = name_type(p.get("name") or "")                      # 종류는 이름의 머리 명사 먼저(…Temple, Museum of …)
    if nt:
        _add(generic, seen, nt, "type", "lexicon")
    if not nt:
        for m in _TYPE_RE.finditer(text):
            _add(generic, seen, canon(m.group(1)).lower(), "type", "lexicon")
            break
    return (specific[:MAX_TERMS - 1] + generic[:1] + specific[MAX_TERMS - 1:])[:MAX_TERMS]


def for_places(places: list[dict]) -> list[dict]:
    """보고서 장소들에 vocab 을 단다(LLM 낱말은 장소의 vocab_llm 에서)."""
    return [{**p, "vocab": for_place(p, p.get("vocab_llm"))} for p in places]
