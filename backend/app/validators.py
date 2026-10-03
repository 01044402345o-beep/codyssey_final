"""검증 규칙.

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


# 코드가 실제로 구현한 검사만 여기에 있다.
# negative_case_patterns 에 이 목록에 없는 type/match 를 적으면 조용히 무시되므로,
# 아래 check_pattern_declarations 가 경고를 띄운다.
KNOWN_PATTERN_TYPES = {"situation_in_config", "word_count", "duplicate_en"}
KNOWN_PATTERN_MATCH = {"substring"}


def _words(text: str) -> int:
    return len(WORD_RE.findall(text or ""))


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
    sentence: Any,
    cfg: dict[str, Any],
    patterns: dict[str, Any],
    seen_en: set[str] | None = None,
) -> list[dict[str, Any]]:
    """문장 1개를 검사해 문제 목록을 돌려준다.

    어떤 타입이 들어와도 예외를 내지 않는다. 타입이 틀리면 그것 자체를 block 으로 보고한다.
    """
    # 0) 문장이 dict 가 아니면 이후 .get 호출이 전부 터진다. 여기서 끊는다.
    if not isinstance(sentence, dict):
        return [{
            "severity": "block",
            "code": "sentence_not_object",
            "detail": f"expected object, got {type(sentence).__name__}",
        }]

    issues: list[dict[str, Any]] = []

    # 1) en 은 반드시 문자열이어야 한다 (숫자·null 이면 이후 검사가 무의미)
    raw_en = sentence.get("en")
    if not isinstance(raw_en, str) or not raw_en.strip():
        issues.append({
            "severity": "block",
            "code": "en_not_string",
            "detail": f"en must be a non-empty string, got {type(raw_en).__name__}",
        })
        return issues

    # 2) 상황 id 가 이 카테고리 설정에 있는가 (= 장소/카테고리 불일치 탐지)
    valid_ids = {s.get("situation_id") for s in cfg.get("situations", []) if isinstance(s, dict)}
    sid = sentence.get("situation_id")
    if sid not in valid_ids:
        issues.append({
            "severity": (patterns.get("place_mismatch") or {}).get("severity", "block"),
            "code": "situation_not_in_config",
            "detail": f"situation_id={sid!r} is not in category {cfg.get('category_id')!r}",
        })

    low = raw_en.lower()

    # 3) 금칙 (부분일치)
    for code in ("forbidden_topic", "not_polite"):
        p = patterns.get(code) or {}
        for term in p.get("terms", []):
            if isinstance(term, str) and term.lower() in low:
                issues.append({
                    "severity": p.get("severity", "warn"),
                    "code": code,
                    "detail": f"{term!r} in: {raw_en}",
                })

    # 4) 길이
    p = patterns.get("too_long") or {}
    if isinstance(p.get("max"), int) and _words(raw_en) > p["max"]:
        issues.append({
            "severity": p.get("severity", "warn"),
            "code": "too_long",
            "detail": f"{_words(raw_en)} words > max {p['max']}",
        })

    # 5) 팩 안 중복
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
        # 검사기가 없으면 '검증했다'고 말할 수 없다. 조용히 넘어가지 않는다.
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
    weak_map: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """취약 표현이 '정말로' 반영됐는지 확인한다.

    태그(targets_weak)만 보고 판단하지 않는다. 태그는 자기가 붙였다고 주장하는 것일 뿐이고,
    실제 반영 여부는 그 취약점이 속한 상황의 문장이 생성됐는지(=카드로 배정되는지)로 확인한다.
    keywords 가 정의돼 있으면 그 단어가 실제로 문장에 들어갔는지까지 본다.
    """
    issues: list[dict[str, Any]] = []
    if not requested:
        return issues

    mapping = (weak_map or {}).get("mapping") or {}

    for wid in requested:
        spec = mapping.get(wid)
        if not isinstance(spec, dict):
            # 레지스트리에 없으면 '반영됐다'고 말할 근거가 없다. 설정 공백으로 알린다.
            issues.append({
                "severity": "warn",
                "code": "weak_unmapped",
                "detail": f"weak id {wid!r} is not in agent_contract/weak_expressions.json — 반영 여부를 판단할 수 없습니다.",
            })
            continue

        sat = spec.get("situation_id")
        kws = [k.lower() for k in (spec.get("keywords") or []) if isinstance(k, str)]

        in_situation = [
            s for s in sentences
            if isinstance(s, dict) and s.get("situation_id") == sat
        ]
        if not in_situation:
            issues.append({
                "severity": "block",
                "code": "weak_not_covered",
                "detail": (
                    f"{wid} ({spec.get('label', '')}) 은 상황 {sat!r} 에서 연습되어야 하는데 "
                    f"그 상황의 문장이 없습니다."
                ),
            })
            continue

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
                        f"{wid} 은 상황 {sat!r} 에 배정됐지만 {kws} 중 어떤 단어도 "
                        f"문장에 없습니다. 태그만 붙은 상태입니다."
                    ),
                })

    return issues


def validate_pack(
    pack: Any,
    cfg: dict[str, Any],
    weak_expressions: list[str] | None = None,
    schema: dict[str, Any] | None = None,
    weak_map: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """생성 결과 1건 전체를 검사한다. 어떤 입력에도 예외를 내지 않는다."""
    patterns = cfg.get("negative_case_patterns", {})
    rules = cfg.get("rules", {})
    issues: list[dict[str, Any]] = []

    if not isinstance(pack, dict):
        return [{
            "severity": "block",
            "code": "pack_not_object",
            "detail": f"expected object, got {type(pack).__name__}",
        }]

    # 0) 스키마 구조. block 이면 이후 검사는 타입 전제가 깨지므로 여기서 멈춘다.
    issues.extend(validate_schema(pack, schema))
    if any(i["severity"] == "block" for i in issues):
        return issues

    # 0-1) 설정 오류 — 코드가 모르는 type/match 가 적혀 있으면 알린다
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

    # 1) 문장 단위 규칙
    seen: set[str] = set()
    for i, sentence in enumerate(sentences):
        for issue in validate_sentence(sentence, cfg, patterns, seen):
            issue["index"] = i
            issues.append(issue)

    # 2) 취약 표현 반영 — 태그가 아니라 상황·내용으로 확인한다 (Long-term Memory)
    issues.extend(check_weak_coverage(sentences, list(weak_expressions or []), weak_map))

    # 3) 상황 커버리지 — 3주차 측정값
    counts = Counter(
        s.get("situation_id") for s in sentences if isinstance(s, dict)
    )
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


# ------------------------------------------------------------------ 음성 평가

def validate_speak_result(data: Any) -> tuple[dict[str, Any], bool, str]:
    """음성 평가 응답을 정규화하고 쓸 수 있는지 판단한다.

    반환: (정규화된 결과, 쓸 수 있는가, 못 쓰는 이유)
    점수가 숫자로 안 나와도 heard/fix_one 이 있으면 쓸 수 있다 (초기 제품은 점수보다
    '들린 내용 + 고칠 한 가지 + 다시 말하기'가 신뢰할 만하다).
    """
    if not isinstance(data, dict):
        return (
            {"score": None, "heard": "", "issues": [], "fix_one": "", "tip": ""},
            False,
            "평가 결과 형식이 올바르지 않습니다.",
        )

    # 점수는 있으면 0~100 숫자여야 한다. 아니면 버리되, 버렸다는 사실을 남긴다.
    raw_score = data.get("score")
    score_discarded = False
    if raw_score is None:
        score = None
    elif isinstance(raw_score, bool) or not isinstance(raw_score, (int, float)):
        score, score_discarded = None, True
    elif not (0 <= float(raw_score) <= 100):
        score, score_discarded = None, True
    else:
        score = float(raw_score)

    heard = data.get("heard") if isinstance(data.get("heard"), str) else ""
    fix_one = data.get("fix_one") if isinstance(data.get("fix_one"), str) else ""
    tip = data.get("tip") if isinstance(data.get("tip"), str) else ""

    clean: list[dict[str, str]] = []
    raw_issues = data.get("issues")
    if isinstance(raw_issues, list):
        for it in raw_issues:
            if isinstance(it, dict) and isinstance(it.get("word"), str):
                clean.append({
                    "word": it["word"],
                    "note": it.get("note") if isinstance(it.get("note"), str) else "",
                })

    norm = {"score": score, "heard": heard, "issues": clean, "fix_one": fix_one, "tip": tip}
    if score_discarded:
        norm["score_discarded"] = True

    if not heard.strip() and score is None:
        return norm, False, "음성이 인식되지 않았습니다. 다시 녹음해 주세요."

    if score is None and not fix_one.strip() and not tip.strip() and not clean:
        return norm, False, "채점 결과를 해석하지 못했습니다. 다시 시도해 주세요."

    return norm, True, ""
