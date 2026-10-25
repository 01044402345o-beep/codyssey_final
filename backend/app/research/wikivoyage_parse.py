"""위키보이지 위키텍스트 파서 — listing 템플릿·섹션·구역(하위 문서)을 코드로 뽑는다(LLM 없음).

listing 템플릿: {{see|eat|do|drink|buy|sleep|go|listing | name= | alt= | url= | lat= | long= | wikidata= | content= ...}}
(위키보이지 Template:Listing), 지도 표시 {{marker}}. 다른 언어판: de·ja {{vCard}}, fr {{voir}}…(nom·latitude),
es {{listado}}…(nombre·latitud), it 은 en 과 같은 템플릿에 nome·descrizione. 장소는 여기서만 나온다 — 모델이 장소를 지어낼 수 없다.
본문은 데이터다: 위키 문법·HTML·URL 을 걷어내고 길이를 자른다(프롬프트 주입 대비, 후속 LLM 단계에 그대로 쓴다).
"""
from __future__ import annotations

import re
from typing import Optional

LISTING_TYPES = ("see", "do", "eat", "drink", "buy", "sleep", "go", "listing")
MAX_CONTENT = 300
MAX_SECTION = 4000


def _templates(text: str) -> list[tuple[int, int, str]]:
    """맨 바깥 {{…}} 템플릿의 (시작, 끝, 안쪽 본문). 중첩은 짝을 맞춘다."""
    out, depth, start, i, n = [], 0, -1, 0, len(text)
    while i < n - 1:
        pair = text[i:i + 2]
        if pair == "{{":
            if depth == 0:
                start = i
            depth += 1
            i += 2
            continue
        if pair == "}}" and depth:
            depth -= 1
            i += 2
            if depth == 0 and start >= 0:
                out.append((start, i, text[start + 2:i - 2]))
                start = -1
            continue
        i += 1
    return out


def _split_params(body: str) -> list[str]:
    """맨 바깥의 | 로만 나눈다([[a|b]]·{{x|y}} 안의 | 는 그대로)."""
    parts, buf, depth_t, depth_l, i = [], [], 0, 0, 0
    while i < len(body):
        two = body[i:i + 2]
        if two in ("{{", "}}", "[[", "]]"):
            if two == "{{":
                depth_t += 1
            elif two == "}}":
                depth_t = max(0, depth_t - 1)
            elif two == "[[":
                depth_l += 1
            else:
                depth_l = max(0, depth_l - 1)
            buf.append(two)
            i += 2
            continue
        ch = body[i]
        if ch == "|" and depth_t == 0 and depth_l == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    parts.append("".join(buf))
    return parts


def _inline_template(m: re.Match) -> str:
    inner = m.group(1)
    bits = [b.strip() for b in inner.split("|")]
    name = bits[0].lower()
    if name in ("km", "mi", "m", "ft") and len(bits) > 1:
        return f"{bits[1]} {name}"
    if name in ("iata", "icao") and len(bits) > 1:
        return bits[1]
    if name in ("convert",) and len(bits) > 2:
        return f"{bits[1]} {bits[2]}"
    if name in ("lang", "lang-ja", "nowrap") and len(bits) > 1:
        return bits[-1]
    return ""


def clean(text: str, cap: int = MAX_CONTENT) -> str:
    """위키 문법·HTML·URL 을 걷어낸 평문. 제어 문자도 지운다."""
    t = text or ""
    t = re.sub(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>", " ", t, flags=re.S | re.I)
    t = re.sub(r"<!--.*?-->", " ", t, flags=re.S)
    for _ in range(3):                                         # 안쪽 템플릿부터 몇 겹
        t = re.sub(r"\{\{([^{}]*)\}\}", _inline_template, t)
    t = re.sub(r"\[\[(?:File|Image):[^\]]*\]\]", " ", t, flags=re.I)
    t = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", t)   # [[a|b]] → b, [[a]] → a
    t = re.sub(r"\[(?:https?:)?//\S+\s+([^\]]*)\]", r"\1", t)  # [url 글] → 글
    t = re.sub(r"\[(?:https?:)?//\S+\]", " ", t)
    t = re.sub(r"https?://\S+", " ", t)
    t = re.sub(r"<[^>]+>", " ", t)
    t = t.replace("'''", "").replace("''", "")
    t = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r" ([.,;:!?)])", r"\1", t)
    if len(t) > cap:
        cut = t[:cap].rsplit(" ", 1)[0]
        t = (cut or t[:cap]).rstrip(",;: ") + "…"
    return t


def _num(v: str) -> Optional[float]:
    try:
        f = float((v or "").strip())
    except ValueError:
        return None
    return f if f == f else None


def sections(text: str) -> list[tuple[str, str]]:
    """2단계 제목(==X==) 기준 (제목, 본문). 맨 앞(제목 전) 본문은 '' 제목."""
    out, last, title = [], 0, ""
    for m in re.finditer(r"^==\s*([^=\n][^\n]*?)\s*==\s*$", text, flags=re.M):
        out.append((title, text[last:m.start()]))
        title, last = m.group(1).strip(), m.end()
    out.append((title, text[last:]))
    return out


# 언어판마다 listing 템플릿 이름·매개변수가 다르다(10/26 실측: en·it·zh / de·ja / fr / es).
# 템플릿 이름 → 종류. None 이면 type 매개변수(또는 섹션 제목)로 종류를 정한다.
_EN_LIKE = {t: t for t in LISTING_TYPES if t != "listing"} | {"listing": None, "marker": None}
TEMPLATES = {
    "en": _EN_LIKE, "it": _EN_LIKE, "zh": _EN_LIKE,
    "de": {"vcard": None, "marker": None, "marker kopie": None},
    "ja": {"vcard": None, "marker": None},
    "fr": {"voir": "see", "faire": "do", "acheter": "buy", "manger": "eat", "sortir": "drink", "se loger": "sleep",
           "aller": "go", "circuler": "go", "listing": None},
    "es": {**_EN_LIKE, "listado": None, "ver": "see", "hacer": "do", "comprar": "buy", "comer": "eat", "beber": "drink",
           "salir": "drink", "dormir": "sleep"},
}
_KEYS = {"name": ("name", "nome", "nom", "nombre"), "lat": ("lat", "latitude", "latitud"),
         "lon": ("long", "lon", "longitude", "longitud"), "url": ("url", "sito", "web", "site"),
         "content": ("content", "description", "descrizione", "descripción", "descripcion", "contenu"),
         "type": ("type", "tipo"), "alt": ("alt",)}
# type 매개변수 값(영어·독일어 vCard 세부 종류 등) → 종류
_TYPE = {"see": "see", "do": "do", "eat": "eat", "drink": "drink", "buy": "buy", "sleep": "sleep", "go": "go",
         "restaurant": "eat", "imbiss": "eat", "food": "eat", "fastfood": "eat", "cafe": "drink", "café": "drink",
         "coffee": "drink", "bar": "drink", "pub": "drink", "nightlife": "drink", "teahouse": "drink",
         "hotel": "sleep", "hostel": "sleep", "guest house": "sleep", "campsite": "sleep", "ryokan": "sleep",
         "shop": "buy", "market": "buy", "shopping": "buy", "station": "go", "airport": "go", "bus station": "go",
         "museum": "see", "church": "see", "castle": "see", "palace": "see", "temple": "see", "shrine": "see",
         "monument": "see", "sight": "see", "building": "see", "park": "see", "garden": "see", "zoo": "see",
         "tower": "see", "monastery": "see", "mosque": "see", "synagogue": "see", "square": "see", "bridge": "see",
         "gallery": "see", "viewpoint": "see", "landmark": "see", "theater": "do", "theatre": "do", "activity": "do",
         "beach": "do", "spa": "do", "onsen": "do", "sport": "do", "cinema": "do",
         "vedere": "see", "fare": "do", "mangiare": "eat", "bere": "drink", "dormire": "sleep",
         "ver": "see", "hacer": "do", "comer": "eat", "beber": "drink", "dormir": "sleep"}
# 섹션 제목 낱말 → 종류(type 이 없거나 모를 때)
_SECTION = (("sehensw", "see"), ("見る", "see"), ("voir", "see"), ("vedere", "see"), ("ver", "see"), ("景点", "see"),
            ("观光", "see"), ("see", "see"), ("aktivit", "do"), ("する", "do"), ("faire", "do"), ("fare", "do"),
            ("hacer", "do"), ("do", "do"), ("küche", "eat"), ("essen", "eat"), ("食べる", "eat"), ("manger", "eat"),
            ("mangiare", "eat"), ("comer", "eat"), ("餐", "eat"), ("吃", "eat"), ("eat", "eat"), ("nachtleben", "drink"),
            ("飲む", "drink"), ("sortir", "drink"), ("boire", "drink"), ("bere", "drink"), ("beber", "drink"),
            ("drink", "drink"), ("unterkunft", "sleep"), ("泊まる", "sleep"), ("loger", "sleep"), ("alloggiare", "sleep"),
            ("dormir", "sleep"), ("住", "sleep"), ("sleep", "sleep"), ("einkauf", "buy"), ("買う", "buy"),
            ("acheter", "buy"), ("comprare", "buy"), ("comprar", "buy"), ("buy", "buy"), ("anreise", "go"),
            ("mobilit", "go"), ("get in", "go"), ("get around", "go"))


def _kind_of(tmpl_kind: Optional[str], params: dict, section: str) -> str:
    if tmpl_kind:
        return tmpl_kind
    t = next((params[k] for k in _KEYS["type"] if params.get(k)), "").strip().lower()
    if t in _TYPE:
        return _TYPE[t]
    low = section.casefold()
    for word, kind in _SECTION:
        if word in low:
            return kind
    return "listing"


def _first(params: dict, key: str) -> str:
    return next((params[k] for k in _KEYS[key] if params.get(k)), "")


def listings(text: str, page: str = "", lang: str = "en") -> list[dict]:
    """listing 템플릿 → [{type, name, alt, lat, lon, url, wikidata, content, section, page, marker}]. 이름 없는 것은 버린다.
    lang 에 따라 템플릿·매개변수 이름을 맞춘다. 지도 표시(marker)는 설명이 없어 marker=True 로 표시한다."""
    table = TEMPLATES.get(lang, TEMPLATES["en"])
    out = []
    for title, body in sections(text):
        for _s, _e, inner in _templates(body):
            parts = _split_params(inner)
            tname = re.sub(r"\s+", " ", parts[0].strip().lower())
            if tname not in table:
                continue
            params: dict[str, str] = {}
            for p in parts[1:]:
                if "=" in p:
                    k, v = p.split("=", 1)
                    params[k.strip().lower()] = v.strip()
            kind = _kind_of(table[tname], params, title)
            if kind not in LISTING_TYPES:
                kind = "listing"
            name = clean(_first(params, "name"), 120)
            if not name:
                continue
            url = _first(params, "url").strip()
            wd = (params.get("wikidata") or "").strip()
            out.append({
                "type": kind, "name": name, "alt": clean(params.get("alt", ""), 80),
                "lat": _num(_first(params, "lat")), "lon": _num(_first(params, "lon")),
                "url": url if re.fullmatch(r"https?://[^\s<>\"'{}|\\^`]{3,290}", url) and "@" not in url.split("/")[2] else "",
                "wikidata": wd if re.fullmatch(r"Q\d{1,12}", wd) else "",
                "content": clean(_first(params, "content"), MAX_CONTENT),
                "section": title, "page": page, "marker": tname.startswith("marker"),
                "subtype": next((params[k] for k in _KEYS["type"] if params.get(k)), "").strip().lower()[:30],
            })
    return out


def districts(text: str, title: str, limit: int = 2) -> list[str]:
    """{{Regionlist}} 의 regionNname 에 걸린 '<문서>/<구역>' 하위 문서 제목(순서대로 최대 limit)."""
    out: list[str] = []
    for _s, _e, inner in _templates(text):
        parts = _split_params(inner)
        if parts[0].strip().lower() != "regionlist":
            continue
        for p in parts[1:]:
            k, _, v = p.partition("=")
            if not re.fullmatch(r"\s*region\d+name\s*", k):
                continue
            m = re.search(r"\[\[([^\]|]+)", v)
            if m and m.group(1).strip().startswith(title + "/") and m.group(1).strip() not in out:
                out.append(m.group(1).strip())
            if len(out) >= limit:
                return out
    return out


def prose(body: str, cap: int = MAX_SECTION) -> str:
    """섹션 본문의 평문(템플릿 블록·하위 제목·목록 기호 제거)."""
    t = body
    for s, e, _inner in reversed(_templates(t)):
        t = t[:s] + " " + t[e:]
    t = re.sub(r"^=+[^=\n]+=+\s*$", " ", t, flags=re.M)
    t = re.sub(r"^[*#:;]+\s*", "", t, flags=re.M)
    return clean(t, cap)
