"""카테고리 설정 파일 1개를 PR 전에 점검한다.  팀원이 `agent_contract/categories/<id>.json` 을 만든 뒤 실행한다.

  python backend/scripts/validate_category.py agent_contract/categories/transport.json

오류(ERROR)가 하나라도 있으면 종료코드 1. 경고(WARN)는 확인만 하면 된다.
서버가 실제로 쓰는 검증기(backend/app/validators.py)를 그대로 쓰므로, 여기서 통과하면 서버에서도 읽힌다.
의미(문장이 자연스러운지, 상황이 실제로 쓸모 있는지)는 검사하지 못한다. 그건 사람이 검수한다.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.validators import SCHEMA_CHECKER_AVAILABLE, check_pattern_declarations, validate_pack, validate_sentence  # noqa: E402

ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")
RULE_KEYS = ("min_sentences_per_situation", "max_sentences_per_situation", "max_words_per_sentence", "min_sentences_per_category")
SCHEMA_PATH = BACKEND.parent / "agent_contract" / "schema.json"
IGNORED_PACK_WARN = {"missing_situation", "below_min_sentences"}  # good_examples 는 일부 상황만 보여줘도 된다


def check_config(cfg: Any, stem: str) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warns: list[str] = []
    if not isinstance(cfg, dict):
        return ["최상위가 JSON 객체({ ... })가 아닙니다."], warns

    # 1) 필수 키
    for k in ("category_id", "category", "owner", "place_types", "rules", "situations", "system_prompt", "good_examples", "negative_cases", "negative_case_patterns"):
        if k not in cfg:
            errors.append(f"필수 항목 `{k}` 이(가) 없습니다.")
    if errors:
        return errors, warns

    cid = cfg["category_id"]
    if not isinstance(cid, str) or not ID_RE.match(cid):
        errors.append("`category_id` 는 영문 소문자·숫자·밑줄(예: transport)이어야 합니다.")
    elif cid != stem:
        errors.append(f"`category_id`({cid!r}) 가 파일 이름({stem!r}.json) 과 다릅니다.")
    if not isinstance(cfg["place_types"], list) or not cfg["place_types"] or not all(isinstance(x, str) and x for x in cfg["place_types"]):
        errors.append("`place_types` 는 비어 있지 않은 문자열 목록이어야 합니다. (예: [\"airport\", \"station\"])")

    # 2) rules
    rules = cfg["rules"]
    if not isinstance(rules, dict):
        errors.append("`rules` 는 객체여야 합니다.")
        rules = {}
    for k in RULE_KEYS:
        if not isinstance(rules.get(k), int) or isinstance(rules.get(k), bool) or rules[k] < 1:
            errors.append(f"`rules.{k}` 는 1 이상의 정수여야 합니다.")

    # 3) situations
    sits = cfg["situations"]
    ids: list[str] = []
    if not isinstance(sits, list) or not sits:
        errors.append("`situations` 는 비어 있지 않은 목록이어야 합니다.")
        sits = []
    for i, s in enumerate(sits):
        if not isinstance(s, dict):
            errors.append(f"situations[{i}] 가 객체가 아닙니다.")
            continue
        sid = s.get("situation_id")
        if not isinstance(sid, str) or not ID_RE.match(sid):
            errors.append(f"situations[{i}].situation_id 는 영문 소문자·숫자·밑줄이어야 합니다. (지금: {sid!r})")
            continue
        ids.append(sid)
        if not isinstance(s.get("situation"), str) or not s["situation"].strip():
            errors.append(f"situations[{i}] ({sid}) 에 한국어 설명 `situation` 이 없습니다.")
        kws = s.get("required_keywords")
        if kws is not None and (not isinstance(kws, list) or not all(isinstance(x, str) and x.strip() for x in kws)):
            errors.append(f"situations[{i}] ({sid}).required_keywords 는 문자열 목록이어야 합니다. (선택 항목)")
    dup = sorted({x for x in ids if ids.count(x) > 1})
    if dup:
        errors.append(f"situation_id 가 중복됩니다: {dup}")
    if ids and not 8 <= len(ids) <= 12:
        warns.append(f"상황이 {len(ids)}개입니다. 안내는 10개 내외입니다.")

    # 4) 프롬프트 플레이스홀더
    prompt = cfg["system_prompt"]
    if not isinstance(prompt, str) or not prompt.strip():
        errors.append("`system_prompt` 가 비어 있습니다.")
    else:
        unknown = sorted({m for m in PLACEHOLDER.findall(prompt) if m not in rules})
        if unknown:
            errors.append(f"`system_prompt` 의 {{{', '.join(unknown)}}} 는 rules 에 없는 키라 치환되지 않습니다. rules 키 이름을 그대로 쓰세요.")

    if errors:
        return errors, warns  # 이후 검사는 위 구조가 맞아야 의미가 있다

    patterns = cfg["negative_case_patterns"] if isinstance(cfg["negative_case_patterns"], dict) else {}
    if not isinstance(cfg["negative_case_patterns"], dict):
        errors.append("`negative_case_patterns` 는 객체여야 합니다.")
    for w in check_pattern_declarations(patterns):
        warns.append(w["detail"])

    # 5) good_examples
    goods = cfg["good_examples"]
    if not isinstance(goods, list) or len(goods) < 3:
        errors.append("`good_examples` 는 3개 이상이어야 합니다.")
        goods = [g for g in goods if isinstance(g, dict)] if isinstance(goods, list) else []
    if goods:
        try:
            schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            schema = None
            errors.append("agent_contract/schema.json 을 읽을 수 없어 구조 검사를 못 했습니다.")
        pack = {"category_id": cid, "city": "Example City", "sentences": goods}
        for issue in validate_pack(pack, cfg, [], schema):
            if issue["code"] in IGNORED_PACK_WARN:
                continue
            where = f" (good_examples[{issue['index']}])" if "index" in issue else ""
            (errors if issue["severity"] == "block" else warns).append(f"good_examples 점검 [{issue['code']}]{where}: {issue['detail']}")

    # 6) negative_cases — 실제로 걸러지는지
    negs = cfg["negative_cases"]
    if not isinstance(negs, list) or len(negs) < 5:
        errors.append("`negative_cases` 는 5개 이상이어야 합니다. (금칙·장소불일치·중복·길이·말투)")
        negs = [n for n in negs if isinstance(n, dict)] if isinstance(negs, list) else []
    for n in negs:
        name = n.get("case_id", "?")
        if not isinstance(n.get("sentence"), dict) or not isinstance(n.get("expect"), str):
            errors.append(f"negative_cases[{name}] 에 `sentence`(객체)와 `expect`(문자열)가 필요합니다.")
            continue
        seen: set[str] = set()
        if n["expect"] == "duplicate_en":
            seen.add(str(n["sentence"].get("en") or "").lower())
        codes = {i["code"] for i in validate_sentence(n["sentence"], cfg, patterns, seen)}
        if n["expect"] not in codes:
            errors.append(f"negative_cases[{name}] 이(가) 걸러지지 않습니다. expect={n['expect']!r}, 실제={sorted(codes)}")
    return errors, warns


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("사용법: python backend/scripts/validate_category.py agent_contract/categories/<id>.json")
        return 2
    path = Path(argv[1])
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except OSError as e:
        print(f"[ERROR] 파일을 읽을 수 없습니다: {e}")
        return 1
    except ValueError as e:
        print(f"[ERROR] JSON 문법 오류: {e}  (쉼표·따옴표·괄호를 확인하세요)")
        return 1
    errors, warns = check_config(cfg, path.stem)
    if not SCHEMA_CHECKER_AVAILABLE:
        errors.append("jsonschema 가 설치돼 있지 않아 구조 검사가 꺼져 있습니다. `pip install -r backend/requirements.txt` 후 다시 실행하세요.")
    for w in warns:
        print(f"[WARN]  {w}")
    for e in errors:
        print(f"[ERROR] {e}")
    print(f"\n{path.name}: 오류 {len(errors)}개, 경고 {len(warns)}개" + (" — PR 해도 됩니다." if not errors else " — 오류를 고친 뒤 다시 실행하세요."))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
