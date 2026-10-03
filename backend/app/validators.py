"""검증 규칙.

카테고리 설정의 negative_case_patterns 를 그대로 실행한다.

두 가지 용도:
  1) /generate 응답이 규칙을 지켰는지 검사 — severity=block 이면 재생성
  2) 각 카테고리의 negative_cases 가 실제로 걸러지는지 자체 점검

severity
  block — 응답을 쓸 수 없음. 재생성한다. (스키마 위반, 금칙, 카테고리 불일치, 취약 표현 미반영)
  warn  — 쓸 수는 있으나 품질 문제. 3주차 비교 실험의 측정값.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any

WORD_RE = re.compile(r"[A-Za-z']+")

try:  # 배포 환경에 없을 수도 있으므로 선택적으로
    import jsonschema
except ImportError:  # pragma: no cover
    jsonschema = None  # type: ignore[assignment]


def _words(text: str) -> int:
    return len(WORD_RE.findall(text or ""))


# 코드가 실제로 구현한 검사만 여기에 있다.
# negative_case_patterns 에 이 목록에 없는 type/match 를 적으면 조용히 무시되므로,
# 아래 check_pattern_declarations 가 경고를 띄운다.
KNOWN_PATTERN_TYPES = {"situation_in_config", "word_count", "duplicate_en"}
KNOWN_PATTERN_MATCH = {"substring"}


def check_pattern_declarations(patterns: dict[str, Any]) -> list[dict[str, Any]]:
    """설정에 적힌 type/match 가 코드에 구현돼 있는지 확인한다.

    이게 없으면 '규칙을 추가했다고 믿는데 실제로는 무시되는' 상태가 조용히 생긴다.
    새 규칙이 필요하면 이슈로 요청해야 한다.
    """
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
    sentence: dict[str, Any],
    cfg: dict[str, Any],
    patterns: dict[str, Any],
    seen_en: set[str] | None = None,
) -> list[dict[str, Any]]:
    """문장 1개를 검사해 문제 목록을 돌려준다."""
    issues: list[dict[str, Any]] = []

    # 1) 상황 id 가 이 카테고리 설정에 있는가 (= 장소/카테고리 불일치 탐지)
    valid_ids = {s["situation_id"] for s in cfg.get("situations", [])}
    sid = sentence.get("situation_id")
    if sid not in valid_ids:
        issues.append({
            "severity": (patterns.get("place_mismatch") or {}).get("severity", "block"),
            "code": "situation_not_in_config",
            "detail": f"situation_id={sid!r} is not in category {cfg.get('category_id')!r}",
        })

    en = sentence.get("en") or ""
    low = en.lower()

    # 2) 금칙 (부분일치)
    for code in ("forbidden_topic", "not_polite"):
        p = patterns.get(code) or {}
        for term in p.get("terms", []):
            if term.lower() in low:
                issues.append({
                    "severity": p.get("severity", "warn"),
                    "code": code,
                    "detail": f"{term!r} in: {en}",
                })

    # 3) 길이
    p = patterns.get("too_long") or {}
    if "max" in p and _words(en) > p["max"]:
        issues.append({
            "severity": p.get("severity", "warn"),
            "code": "too_long",
            "detail": f"{_words(en)} words > max {p['max']}",
        })

    # 4) 팩 안 중복
    if seen_en is not None:
        if low in seen_en:
            issues.append({
                "severity": (patterns.get("duplicate") or {}).get("severity", "warn"),
                "code": "duplicate_en",
                "detail": en,
            })
        seen_en.add(low)

    return issues


def validate_schema(pack: dict[str, Any], schema: dict[str, Any] | None) -> list[dict[str, Any]]:
    """schema.json 으로 구조를 실제 검사한다. (필드 누락·타입 오류)"""
    if not schema or jsonschema is None:
        return []
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


def validate_pack(
    pack: dict[str, Any],
    cfg: dict[str, Any],
    weak_expressions: list[str] | None = None,
    schema: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """생성 결과 1건 전체를 검사한다."""
    patterns = cfg.get("negative_case_patterns", {})
    rules = cfg.get("rules", {})
    issues: list[dict[str, Any]] = []

    # 0) 스키마 구조
    issues.extend(validate_schema(pack, schema))

    # 0-1) 설정 오류 — 코드가 모르는 type/match 가 적혀 있으면 알린다
    issues.extend(check_pattern_declarations(patterns))

    if pack.get("category_id") != cfg.get("category_id"):
        issues.append({
            "severity": "block",
            "code": "category_mismatch",
            "detail": f"expected {cfg.get('category_id')!r}, got {pack.get('category_id')!r}",
        })

    sentences = pack.get("sentences") or []
    if not sentences:
        issues.append({"severity": "block", "code": "empty_pack", "detail": "sentences is empty"})

    # 1) 문장 단위 규칙
    seen: set[str] = set()
    for i, sentence in enumerate(sentences):
        for issue in validate_sentence(sentence, cfg, patterns, seen):
            issue["index"] = i
            issues.append(issue)

    # 2) 취약 표현 반영 (Long-term Memory 를 코드로 보장)
    requested = list(weak_expressions or [])
    if requested:
        covered: set[str] = set()
        for s in sentences:
            covered.update(s.get("targets_weak") or [])
        for w in requested:
            if w not in covered:
                issues.append({
                    "severity": "block",
                    "code": "weak_not_covered",
                    "detail": f"weak_expression {w!r} not targeted by any sentence",
                })

    # 3) 상황 커버리지 — 3주차 측정값
    counts = Counter(s.get("situation_id") for s in sentences)
    need = int(rules.get("min_sentences_per_situation", 1) or 1)
    missing = [
        sit["situation_id"]
        for sit in cfg.get("situations", [])
        if counts.get(sit["situation_id"], 0) < need
    ]
    if missing:
        issues.append({
            "severity": "warn",
            "code": "missing_situation",
            "detail": f"{len(missing)}/{len(cfg.get('situations', []))} situations below min {need}: {missing}",
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
