"""제3자 증인 — "앱이 기록을 생략했다"를 **사용자 제시 없이** 드러내는 겹.

사전 커밋먼트(§11)는 사용자가 챌린지를 들고 있어야 작동한다. 그래서 앱 밖에 두 개의 증인을 둔다.

1. **플랫폼 접근 로그 증인** (기본, 무료): 호스팅 플랫폼(Render)의 접근 로그는 **앱이 지울 수 없는**
   관찰자다. `/account/erase` 요청 수와 체인의 `attempt` 항목 수를 비교하면, 앱이 기록을 통째로
   생략한 경우에도 요청 수가 더 많은 것이 드러난다. 사용자가 아무것도 제시하지 않아도 된다.
   - 한계: 로그 보존 기간이 짧다 → 앵커 주기가 곧 관측 주기다. 로그에 **헤더(챌린지)** 는 없으므로
     개별 요청을 챌린지에 연결하지는 못하고 **개수 수준**만 본다.
2. **RFC 3161 TSA 타임스탬프** (선택): 체인 항목의 시각을 제3자가 서명해 준다. 나중에 앱이 체인을
   다시 쓰더라도 **이미 TSA 로 찍힌 시각을 되돌릴 수 없다**(앵커와 함께 저장소에 남긴다).
   - 한계: 브라우저에서 TSA 를 직접 부르면 CORS 로 막힌다. 앱이 중계하면 앱을 믿게 되므로,
     TSA 는 **앱 자신의 발신 시각 보증**(백데이트 방지)으로만 쓴다 — "서버가 그 요청을 받았다"의
     증명은 위 1번(접근 로그)이 담당한다.

이 모듈은 계산만 한다(네트워크 없음): 로그 텍스트 세기와 비교 판정. 그래서 오프라인 테스트가 가능하다.
"""

from __future__ import annotations

import hashlib
from typing import Any


class WitnessError(Exception):
    """code: bad_input"""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def count_requests(log_text: str, path: str = "/account/erase", method: str = "POST") -> int:
    """접근 로그 텍스트에서 이 경로에 대한 요청 줄 수를 센다.

    플랫폼마다 형식이 달라 **줄 단위로 관대하게** 센다(경로가 들어 있고, method 가 적혀 있으면 일치).
    로그에 같은 요청이 두 번(요청/응답) 찍히는 플랫폼도 있어 호출자가 보정값을 줄 수 있다.
    """
    hits = 0
    for line in (log_text or "").splitlines():
        if path not in line:
            continue
        if method and method not in line.upper().replace(path.upper(), ""):
            continue
        hits += 1
    return hits


def compare(observed: int, attempts: int, *, tolerance: int = 0) -> dict[str, Any]:
    """관찰된 요청 수와 체인의 시도 항목 수를 비교한다.

    - `observed > attempts`: **기록 생략 의심**(요청은 왔는데 체인에 시도가 없다).
    - `observed < attempts`: 로그 보존 기간 밖이거나 로그 필터가 좁은 경우가 흔하다(로그 쪽이 약하다).
    - `tolerance`: 플랫폼이 한 요청을 여러 줄로 찍는 경우를 흡수한다.
    """
    observed = int(observed)
    attempts = int(attempts)
    diff = observed - attempts
    verdict = "ok"
    note = ""
    if observed == 0 and attempts > 0:
        verdict = "no_logs_visible"
        note = "로그가 비어 있다(보존 기간 만료·필터 문제일 수 있다) — 로그 쪽을 믿을 수 없다"
    elif diff > tolerance:
        verdict = "missing_attempts"
        note = "요청 로그 수보다 체인 시도 항목이 적다 — 앱이 기록을 생략했을 수 있다"
    elif diff < -tolerance:
        verdict = "stale_logs"
        note = "체인 항목이 로그보다 많다(로그 보존 기간 밖일 가능성) — 앵커 주기를 줄여라"
    return {"verdict": verdict, "ok": verdict == "ok", "observed": observed, "attempts": attempts,
            "diff": diff, "tolerance": tolerance, "note": note}


def stamp_id(challenge: str) -> str:
    """TSA 요청에 넣는 값(챌린지의 해시). 원문 챌린지를 TSA 에 보내지 않는다."""
    return hashlib.sha256((challenge or "").strip().lower().encode()).hexdigest()
