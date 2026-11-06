"""영수증 서명 — 위조·키 교체·서명 없음이 모두 걸러지는지."""
import base64
import os

import pytest

from app import evidence, receipt_signing

ENTRY = {"seq": 42, "digest": "ab" * 32, "created_at": 1762400000000}


@pytest.fixture
def signed(monkeypatch):
    seed = base64.urlsafe_b64encode(b"\x07" * 32).decode().rstrip("=")
    monkeypatch.setenv("EVIDENCE_SIGN_KEY", seed)
    return evidence.receipt_for("c" * 32, ENTRY, "ok")


def test_서명된_영수증은_검증을_통과한다(signed):
    assert signed["signed"] is True and signed["alg"] == "Ed25519"
    assert receipt_signing.verify(signed)["ok"] is True


def test_결과를_바꾸면_서명이_깨진다(signed):
    tampered = dict(signed, outcome="failed")      # 서버가 '성공'이라 했는데 화면이 바꿔치기하는 경우
    assert receipt_signing.verify(tampered)["reason"] == "invalid"


def test_체인_위치를_바꾸면_서명이_깨진다(signed):
    assert receipt_signing.verify(dict(signed, seq=43))["reason"] == "invalid"


def test_핀이_다르면_키가_다르다고_알린다(signed, monkeypatch):
    other = base64.urlsafe_b64encode(b"\x09" * 32).decode().rstrip("=")
    monkeypatch.setenv("EVIDENCE_SIGN_KEY", other)
    pin = receipt_signing.public_key_b64()          # 다른 키를 핀으로 고정
    monkeypatch.setenv("EVIDENCE_SIGN_KEY", base64.urlsafe_b64encode(b"\x07" * 32).decode().rstrip("="))
    res = receipt_signing.verify(signed, pin)
    assert res["ok"] is False and res["reason"] == "key_mismatch"


def test_키가_없으면_서명하지_않는다(monkeypatch):
    monkeypatch.delenv("EVIDENCE_SIGN_KEY", raising=False)
    r = evidence.receipt_for("d" * 32, ENTRY, "ok")
    assert r["signed"] is False and r["reason"] == "not_configured"
    assert receipt_signing.verify(r)["reason"] == "unsigned"


def test_health_에는_공개키만_나간다(monkeypatch):
    monkeypatch.setenv("EVIDENCE_SIGN_KEY", base64.urlsafe_b64encode(b"\x07" * 32).decode().rstrip("="))
    info = receipt_signing.public_info()
    assert info["configured"] and info["alg"] == "Ed25519"
    secret = base64.urlsafe_b64encode(b"\x07" * 32).decode().rstrip("=")
    assert secret not in str(info)                  # 개인키 시드가 새면 안 된다
