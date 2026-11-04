"""발음기호 1회 질문의 서버 저장 — 계정/IP 기준, 원본 IP 미저장, 만료."""
import importlib
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def fresh(tmp_path, monkeypatch):
    monkeypatch.setenv("IPA_GATE_STORE", str(tmp_path / "gate.json"))
    import app.ipa_gate as m
    return importlib.reload(m)


def test_marked_once_per_uid(tmp_path, monkeypatch):
    m = fresh(tmp_path, monkeypatch)
    assert m.seen("u1", "1.1.1.1") is None
    m.mark("u1", "1.1.1.1", "course")
    assert m.seen("u1", "9.9.9.9") == "course", "계정은 IP 가 달라도 기억해야 한다"
    assert m.seen("u2", "1.1.1.1") is None


def test_guest_uses_ip(tmp_path, monkeypatch):
    m = fresh(tmp_path, monkeypatch)
    m.mark("", "2.2.2.2", "known")
    assert m.seen("", "2.2.2.2") == "known"
    assert m.seen("", "3.3.3.3") is None


def test_raw_ip_not_stored(tmp_path, monkeypatch):
    m = fresh(tmp_path, monkeypatch)
    m.mark("", "203.0.113.7", "known")
    text = (tmp_path / "gate.json").read_text()
    assert "203.0.113.7" not in text
    assert "203.0" not in text


def test_expired_is_forgotten(tmp_path, monkeypatch):
    m = fresh(tmp_path, monkeypatch)
    m.mark("u9", "4.4.4.4", "known")
    data = m._load()
    for k in data:
        data[k]["at"] = time.time() - m.TTL_SECONDS - 10
    m._save(data)
    assert m.seen("u9", "4.4.4.4") is None


def test_bad_value_falls_back_to_known(tmp_path, monkeypatch):
    m = fresh(tmp_path, monkeypatch)
    m.mark("u3", "5.5.5.5", "<script>")
    assert m.seen("u3", "5.5.5.5") == "known"


def test_invalid_uid_is_ignored(tmp_path, monkeypatch):
    m = fresh(tmp_path, monkeypatch)
    assert m._uid("../../etc/passwd") == ""
    assert m._uid("a" * 200) == ""
    assert m._uid("okUid_1-2") == "okUid_1-2"
