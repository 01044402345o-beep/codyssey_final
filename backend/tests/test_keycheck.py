"""키 점검 — 약한 키·같은 키 재사용을 통과시키지 않는지."""
import base64

from app import keycheck

def b64(n: int, seed: int = 0) -> str:
    return base64.urlsafe_b64encode(bytes((i * 7 + seed) % 256 for i in range(n))).decode().rstrip("=")


def test_난수_32바이트는_통과한다():
    r = keycheck.check({"EVIDENCE_SIGN_KEY": b64(32)})
    assert r["ok"] is True and r["keys"]["EVIDENCE_SIGN_KEY"]["bytes"] == 32


def test_설정이_없으면_오류가_아니다():
    r = keycheck.check({})
    assert r["ok"] is True and r["keys"] == {}


def test_짧은_키는_잡는다():
    r = keycheck.check({"EVIDENCE_SIGN_KEY": b64(16)})
    assert r["ok"] is False and any(i["code"] == "too_short" for i in r["issues"])


def test_같은_바이트_반복은_잡는다():
    r = keycheck.check({"EVIDENCE_SIGN_KEY": base64.urlsafe_b64encode(b"a" * 32).decode().rstrip("=")})
    assert any(i["code"] == "low_diversity" for i in r["issues"])


def test_한_비밀을_두_역할에_쓰면_잡는다():
    v = b64(32, seed=3)
    r = keycheck.check({"EVIDENCE_SIGN_KEY": v, "EVIDENCE_PUBKEY": v})
    assert r["ok"] is False and [i["code"] for i in r["issues"]] == ["reused"]


def test_요약에_비밀값이_들어가지_않는다():
    v = b64(32, seed=5)
    r = keycheck.check({"EVIDENCE_SIGN_KEY": v})
    assert v not in str(r)
