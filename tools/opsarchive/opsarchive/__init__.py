"""opsarchive — 탈퇴 실패 증거 봉인 관리 도구(앱과 독립 프로세스).

앱(`backend/`)의 어떤 모듈도 import 하지 않는다. 개인키는 이 프로세스의 로컬 파일에만 있고,
네트워크로는 공개키와 봉인된 아카이브만 나간다. 자세한 설계는 `docs/ops/EVIDENCE_SEAL.md`.
"""

__all__ = ["container", "commands", "gcp", "render", "cli"]

VERSION = "0.1.0"
