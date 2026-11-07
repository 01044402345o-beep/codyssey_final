"""검증 규칙.

두 가지 용도:
  1) /generate 응답이 규칙을 지켰는지 검사 — severity=block 이면 재생성
  2) 각 카테고리의 negative_cases 가 실제로 걸러지는지 자체 점검

severity
  block — 응답을 쓸 수 없음. 재생성한다.
  warn  — 쓸 수는 있으나 품질 문제. 3주차 비교 실험의 측정값.

어떤 입력이 와도 예외를 내지 않는다. 검증기 버그가 요청 전체를 죽이면 안 된다.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any

WORD_RE = re.compile(r"[A-Za-z']+")

# 자리표시자. 앱(app.js slotText)이 펼칠 수 있는 것만 허용한다.
PLACEHOLDER_RE = re.compile(r"\[([A-Za-z_][A-Za-z0-9_]*)\]")
ALLOWED_PLACEHOLDERS = frozenset({"name", "destination"})
# 자리표시자 앞 한정사. 화면이 [your destination] 으로 펼치므로 'your [destination]' 는
# 'your [your destination]' 이 되어 표시와 음성이 둘 다 망가진다.
DETERMINER_BEFORE_SLOT = re.compile(r"\b(?:your|my|the|a|an|his|her|their|our)\s+\[", re.IGNORECASE)

try:  # 배포 환경에 없을 수도 있으므로 선택적으로
    import jsonschema
except ImportError:  # pragma: no cover
    jsonschema = None  # type: ignore[assignment]

SCHEMA_CHECKER_AVAILABLE = jsonschema is not None


# 코드가 실제로 구현한 검사만 여기에 있다.
# negative_case_patterns 에 이 목록에 없는 type/match 를 적으면 조용히 무시되므로,
# check_pattern_declarations 가 경고를 띄운다.
KNOWN_PATTERN_TYPES = {"situation_in_config", "word_count", "duplicate_en"}
KNOWN_PATTERN_MATCH = {"substring"}


def _words(text: str) -> int:
    return len(WORD_RE.findall(text or ""))


def _positive_int(v: Any) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else None


def max_words_limit(cfg: dict[str, Any], patterns: dict[str, Any] | None = None) -> int | None:
    """문장 길이 상한. negative_case_patterns.too_long.max 가 있으면 그 값, 없으면 rules.max_words_per_sentence.

    두 값이 모두 있는데 다르면 scripts/validate_category.py 가 ERROR 로 막는다.
    """
    if patterns is None:
        patterns = cfg.get("negative_case_patterns") or {}
    p = patterns.get("too_long") if isinstance(patterns, dict) else None
    from_pattern = _positive_int(p.get("max")) if isinstance(p, dict) else None
    if from_pattern is not None:
        return from_pattern
    rules = cfg.get("rules") if isinstance(cfg.get("rules"), dict) else {}
    return _positive_int(rules.get("max_words_per_sentence"))


def check_pattern_declarations(patterns: dict[str, Any]) -> list[dict[str, Any]]:
    """설정에 적힌 type/match 가 코드에 구현돼 있는지 확인한다."""
    issues: list[dict[str, Any]] = []
    for name, p in (patterns or {}).items():
        if not isinstance(p, dict):
            continue
        t = p.get("type")
        if t is not None and t not in KNOWN_PATTERN_TYPES:
            issues.append({
                "severity": "warn",
                "code": "unknown_pattern_type",
                "detail": (
                    f"negative_case_patterns[{name!r}].type={t!r} 는 구현돼 있지 않아 무시됩니다. "
                    f"구현된 type: {sorted(KNOWN_PATTERN_TYPES)}"
                ),
            })
        m = p.get("match")
        if m is not None and m not in KNOWN_PATTERN_MATCH:
            issues.append({
                "severity": "warn",
                "code": "unknown_pattern_match",
                "detail": (
                    f"negative_case_patterns[{name!r}].match={m!r} 는 구현돼 있지 않아 무시됩니다. "
                    f"구현된 match: {sorted(KNOWN_PATTERN_MATCH)}"
                ),
            })
    return issues


def validate_sentence(
    sentence: Any,
    cfg: dict[str, Any],
    patterns: dict[str, Any],
    seen_en: set[str] | None = None,
) -> list[dict[str, Any]]:
    """문장 1개를 검사한다. 어떤 타입이 들어와도 예외를 내지 않는다."""
    if not isinstance(sentence, dict):
        return [{
            "severity": "block",
            "code": "sentence_not_object",
            "detail": f"expected object, got {type(sentence).__name__}",
        }]

    issues: list[dict[str, Any]] = []

    raw_en = sentence.get("en")
    if not isinstance(raw_en, str) or not raw_en.strip():
        issues.append({
            "severity": "block",
            "code": "en_not_string",
            "detail": f"en must be a non-empty string, got {type(raw_en).__name__}",
        })
        return issues

    valid_ids = {s.get("situation_id") for s in cfg.get("situations", []) if isinstance(s, dict)}
    sid = sentence.get("situation_id")
    if sid not in valid_ids:
        # 이름은 place_mismatch 지만 실제로는 '상황 id 가 계약에 없음'(situation_not_in_config)의
        # severity 를 정한다. 장소 검사가 아니다. 생성된 place_type 검사는 아래 place_type_not_in_category(warn).
        # 이름을 바꾸면 네 계약 JSON 과 negative_cases 의 expect 가 함께 바뀌어야 해서 그대로 둔다.
        issues.append({
            "severity": (patterns.get("place_mismatch") or {}).get("severity", "block"),
            "code": "situation_not_in_config",
            "detail": f"situation_id={sid!r} is not in category {cfg.get('category_id')!r}",
        })

    # 생성된 문장의 장소 종류. 요청 쪽은 main.check_place_types 가 422 로 막지만 출력은 여기서만 본다.
    # 실패율을 바꾸지 않도록 warn 으로만 기록한다.
    pt = sentence.get("place_type")
    allowed_pt = {str(t).strip().lower() for t in (cfg.get("place_types") or []) if isinstance(t, str)}
    if isinstance(pt, str) and pt.strip() and allowed_pt and pt.strip().lower() not in allowed_pt:
        issues.append({
            "severity": "warn",
            "code": "place_type_not_in_category",
            "detail": f"place_type={pt!r} 는 카테고리 {cfg.get('category_id')!r} 의 place_types {sorted(allowed_pt)} 에 없습니다.",
        })

    low = raw_en.lower()

    # 자리표시자 검사. 화면과 음성이 같은 문자열을 쓰므로 생성 단계에서 막는다.
    for name in PLACEHOLDER_RE.findall(raw_en):
        if name not in ALLOWED_PLACEHOLDERS:
            issues.append({
                "severity": "block",
                "code": "unknown_placeholder",
                "detail": (
                    f"[{name}] 은 앱이 펼칠 수 없는 자리표시자입니다 (표시·음성이 깨집니다). "
                    f"허용: {sorted(ALLOWED_PLACEHOLDERS)}"
                ),
            })
    if DETERMINER_BEFORE_SLOT.search(raw_en):
        issues.append({
            "severity": "block",
            "code": "determiner_before_placeholder",
            "detail": f"자리표시자 앞에 한정사가 있습니다: {raw_en}",
        })

    for code in ("forbidden_topic", "not_polite"):
        p = patterns.get(code) or {}
        for term in p.get("terms", []):
            if isinstance(term, str) and term.lower() in low:
                issues.append({
                    "severity": p.get("severity", "warn"),
                    "code": code,
                    "detail": f"{term!r} in: {raw_en}",
                })

    p = patterns.get("too_long") or {}
    limit = max_words_limit(cfg, patterns)
    if limit is not None and _words(raw_en) > limit:
        issues.append({
            "severity": p.get("severity", "warn"),
            "code": "too_long",
            "detail": f"{_words(raw_en)} words > max {limit}",
        })

    if seen_en is not None:
        if low in seen_en:
            issues.append({
                "severity": (patterns.get("duplicate") or {}).get("severity", "warn"),
                "code": "duplicate_en",
                "detail": raw_en,
            })
        seen_en.add(low)

    return issues


def validate_schema(pack: Any, schema: dict[str, Any] | None) -> list[dict[str, Any]]:
    """schema.json 으로 구조를 실제 검사한다. (필드 누락·타입 오류)"""
    if not schema:
        return []
    if jsonschema is None:
        return [{
            "severity": "warn",
            "code": "schema_checker_missing",
            "detail": "jsonschema 가 설치되지 않아 구조 검사를 건너뛰었습니다. requirements.txt 를 확인하세요.",
        }]
    try:
        jsonschema.validate(instance=pack, schema=schema)
        return []
    except jsonschema.ValidationError as exc:  # type: ignore[union-attr]
        path = "/".join(str(p) for p in exc.absolute_path) or "(root)"
        return [{
            "severity": "block",
            "code": "schema_invalid",
            "detail": f"{path}: {exc.message[:200]}",
        }]


def check_weak_coverage(
    sentences: list[Any],
    requested: list[str],
    cfg: dict[str, Any],
) -> list[dict[str, Any]]:
    """취약 표현이 '정말로' 반영됐는지 확인한다.

    weak id 는 그 표현을 연습해야 하는 **situation_id 와 같은 값**을 쓴다.
    (예: 알레르기 취약 → weak id 'allergy_notice' = 식당의 알레르기 상황)

    이렇게 하면 별도 매핑 파일이 필요 없고, 담당자들이 만드는 파일 구조도 그대로다.
    태그(targets_weak)만 보고 판단하지 않는다 — 태그는 자기 주장일 뿐이고,
    실제 판단은 '그 상황의 문장이 생성됐는가'로 한다.
    """
    issues: list[dict[str, Any]] = []
    if not requested:
        return issues

    situations = [s for s in cfg.get("situations", []) if isinstance(s, dict)]
    valid_ids = {s.get("situation_id") for s in situations}

    def _kws(sid: Any) -> list[str]:
        for s in situations:
            if s.get("situation_id") == sid:
                return [k.lower() for k in (s.get("required_keywords") or []) if isinstance(k, str)]
        return []

    for wid in requested:
        if not isinstance(wid, str) or wid not in valid_ids:
            issues.append({
                "severity": "warn",
                "code": "weak_unknown_situation",
                "detail": (
                    f"{wid!r} 는 카테고리 {cfg.get('category_id')!r} 의 situation_id 가 아닙니다. "
                    f"weak id 는 situation_id 와 같은 값을 써야 합니다."
                ),
            })
            continue

        in_situation = [
            s for s in sentences
            if isinstance(s, dict) and s.get("situation_id") == wid
        ]
        if not in_situation:
            issues.append({
                "severity": "block",
                "code": "weak_not_covered",
                "detail": f"취약 상황 {wid!r} 의 문장이 생성되지 않았습니다.",
            })
            continue

        kws = _kws(wid)
        if kws:
            hit = any(
                isinstance(s.get("en"), str) and any(k in s["en"].lower() for k in kws)
                for s in in_situation
            )
            if not hit:
                issues.append({
                    "severity": "block",
                    "code": "weak_content_mismatch",
                    "detail": (
                        f"{wid!r} 문장은 있지만 {kws} 중 어떤 단어도 없습니다. "
                        f"상황만 배정하고 내용은 다른 상태입니다."
                    ),
                })

    return issues


def validate_pack(
    pack: Any,
    cfg: dict[str, Any],
    weak_expressions: list[str] | None = None,
    schema: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """생성 결과 1건 전체를 검사한다. 어떤 입력에도 예외를 내지 않는다."""
    if not isinstance(pack, dict):
        return [{
            "severity": "block",
            "code": "pack_not_object",
            "detail": f"expected object, got {type(pack).__name__}",
        }]

    patterns = cfg.get("negative_case_patterns", {})
    rules = cfg.get("rules", {})

    # 0) 스키마 구조. block 이면 이후 검사는 타입 전제가 깨지므로 여기서 멈춘다.
    issues = validate_schema(pack, schema)
    if any(i["severity"] == "block" for i in issues):
        return issues

    issues.extend(check_pattern_declarations(patterns))

    if pack.get("category_id") != cfg.get("category_id"):
        issues.append({
            "severity": "block",
            "code": "category_mismatch",
            "detail": f"expected {cfg.get('category_id')!r}, got {pack.get('category_id')!r}",
        })

    sentences = pack.get("sentences")
    if not isinstance(sentences, list) or not sentences:
        issues.append({
            "severity": "block",
            "code": "empty_pack",
            "detail": "sentences is missing, not a list, or empty",
        })
        return issues

    seen: set[str] = set()
    for i, sentence in enumerate(sentences):
        for issue in validate_sentence(sentence, cfg, patterns, seen):
            issue["index"] = i
            issues.append(issue)

    # 1) targets_weak 와 situation_id 의 구조적 일관성.
    #    태그가 다른 상황을 가리키면 그 태그는 아무 의미가 없다 (커버리지는 situation_id 로 판단).
    for i, s in enumerate(sentences):
        if not isinstance(s, dict):
            continue
        tags = s.get("targets_weak")
        if not isinstance(tags, list):
            continue
        for t in tags:
            if isinstance(t, str) and t != s.get("situation_id"):
                issues.append({
                    "severity": "warn",
                    "code": "weak_tag_mismatch",
                    "detail": (
                        f"targets_weak={t!r} 인데 이 문장의 situation_id={s.get('situation_id')!r} 입니다. "
                        f"태그가 가리키는 상황과 실제 상황이 다릅니다."
                    ),
                    "index": i,
                })

    # 2) 취약 표현 반영 — 태그가 아니라 상황·내용으로 확인 (Long-term Memory)
    issues.extend(check_weak_coverage(sentences, list(weak_expressions or []), cfg))

    # 3) 상황 커버리지 — 3주차 측정값
    counts = Counter(s.get("situation_id") for s in sentences if isinstance(s, dict))
    need = int(rules.get("min_sentences_per_situation", 1) or 1)
    missing = [
        sit["situation_id"]
        for sit in cfg.get("situations", [])
        if isinstance(sit, dict) and counts.get(sit.get("situation_id"), 0) < need
    ]
    if missing:
        issues.append({
            "severity": "warn",
            "code": "missing_situation",
            "detail": f"{len(missing)}/{len(cfg.get('situations', []))} situations below min {need}: {missing}",
        })

    # 3-1) 상황별 최대 문장 수 — warn 만 (생성 실패율을 바꾸지 않는다)
    most = _positive_int(rules.get("max_sentences_per_situation"))
    if most is not None:
        over = sorted(
            (str(sid), n) for sid, n in counts.items() if sid is not None and n > most
        )
        if over:
            issues.append({
                "severity": "warn",
                "code": "too_many_in_situation",
                "detail": f"{len(over)} situations above max {most}: {dict(over)}",
            })

    # 4) 카테고리 최소 문장 수 — 3주차 측정값
    min_total = int(rules.get("min_sentences_per_category", 0) or 0)
    if min_total and len(sentences) < min_total:
        issues.append({
            "severity": "warn",
            "code": "below_min_sentences",
            "detail": f"{len(sentences)} sentences < min {min_total}",
        })

    return issues


def has_blocking(issues: list[dict[str, Any]]) -> bool:
    return any(i.get("severity") == "block" for i in issues)
