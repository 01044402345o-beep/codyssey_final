"""원격 음소 노드 호출 — 본체(Render 무료 512MB)는 모델(+358MB)을 못 띄우므로, 상시 가동 PC 가 그 일만 맡는다.

PHONEME_REMOTE_URL  노드 주소(https://<기기>.<tailnet>.ts.net). 없으면 부르지 않는다.
PHONEME_TOKEN       노드와 같은 공유 비밀. 없으면 부르지 않는다(인증 없는 노드로 음성을 보내지 않는다).
PHONEME_REMOTE_TIMEOUT  초(기본 8).

어떤 실패도 예외로 새지 않는다. 음소는 부가 정보라, 노드가 꺼져 있거나 느리면 없는 것과 같게 둔다.
노드 응답은 그대로 믿지 않는다 — 크기를 제한하고, 화면이 쓰는 필드만 골라 형식을 확인한다.
"""
from __future__ import annotations

import io
import json
import os
import urllib.error
import urllib.request
import uuid
import wave
from typing import Any

import numpy as np

MAX_RESPONSE_BYTES = 256 * 1024


def url() -> str:
    return os.getenv("PHONEME_REMOTE_URL", "").strip().rstrip("/")


def token() -> str:
    return os.getenv("PHONEME_TOKEN", "").strip()


def configured() -> bool:
    """https 주소 + 토큰이 있어야 부른다. http 는 같은 PC(127.0.0.1·localhost)일 때만 — 음성이 평문으로 밖에 나가지 않게."""
    u = url()
    local = u.startswith(("http://127.0.0.1:", "http://localhost:"))
    return (u.startswith("https://") or local) and bool(token())


def timeout() -> float:
    try:
        return max(1.0, min(30.0, float(os.getenv("PHONEME_REMOTE_TIMEOUT", "8"))))
    except ValueError:
        return 8.0


def wav_bytes(samples: np.ndarray, rate: int = 16000) -> bytes:
    pcm = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((pcm * 32767).astype("<i2").tobytes())
    return buf.getvalue()


def _multipart(fields: dict[str, str], audio: bytes) -> tuple[bytes, str]:
    boundary = "----madi" + uuid.uuid4().hex
    body = io.BytesIO()
    for name, value in fields.items():
        body.write(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        body.write(value.encode("utf-8") + b"\r\n")
    body.write(f'--{boundary}\r\nContent-Disposition: form-data; name="audio"; filename="a.wav"\r\n'
               "Content-Type: audio/wav\r\n\r\n".encode())
    body.write(audio + b"\r\n")
    body.write(f"--{boundary}--\r\n".encode())
    return body.getvalue(), f"multipart/form-data; boundary={boundary}"


def _num(v: Any, lo: float, hi: float) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and lo <= v <= hi else None


def _short(v: Any, n: int = 40) -> str | None:
    return v[:n] if isinstance(v, str) and v else None


def sanitize(raw: Any) -> dict[str, Any]:
    """노드 응답에서 화면·로그가 쓰는 필드만 꺼낸다. 형식이 틀리면 status=bad_response."""
    if not isinstance(raw, dict) or raw.get("status") != "ok":
        reason = _short(raw.get("reason")) if isinstance(raw, dict) else None
        status = _short(raw.get("status")) if isinstance(raw, dict) else None
        return {"status": "unavailable", "reason": reason or status or "bad_response", "via": "remote"}
    acc = _num(raw.get("phoneme_accuracy"), 0, 100)
    rows = []
    for r in (raw.get("phonemes") or [])[:80] if isinstance(raw.get("phonemes"), list) else []:
        if not isinstance(r, dict) or r.get("status") not in ("ok", "weak", "missing"):
            continue
        rows.append({"ipa": _short(r.get("ipa"), 6), "word": _short(r.get("word")), "status": r["status"],
                     "gop": _num(r.get("gop"), 0, 1), "heard_as": _short(r.get("heard_as"), 6),
                     "start_ms": _num(r.get("start_ms"), 0, 60000), "end_ms": _num(r.get("end_ms"), 0, 60000)})
    f = raw.get("focus")
    focus = None
    if isinstance(f, dict) and _short(f.get("ipa"), 6) and _short(f.get("word")):
        focus = {"ipa": _short(f["ipa"], 6), "word": _short(f["word"]), "heard_as": _short(f.get("heard_as"), 6),
                 "label": _short(f.get("label"), 30), "tip": _short(f.get("tip"), 200), "gop": _num(f.get("gop"), 0, 1)}
    lex = raw.get("lexicon") if isinstance(raw.get("lexicon"), dict) else {}
    fb = lex.get("fallback_words") if isinstance(lex.get("fallback_words"), list) else []
    return {
        "status": "ok", "basis": "acoustic", "via": "remote",
        "model": _short(raw.get("model"), 80),
        "phoneme_accuracy": acc,
        "phonemes": rows,
        "focus": focus,
        "fallback_words": [w for w in (_short(x) for x in fb[:10]) if w],
    }


def analyze(samples: np.ndarray, target: str) -> dict[str, Any]:
    if not configured():
        return {"status": "disabled", "reason": "not_configured"}
    body, ctype = _multipart({"text": target[:300]}, wav_bytes(samples))
    req = urllib.request.Request(url() + "/phoneme-check", data=body, method="POST")
    req.add_header("Content-Type", ctype)
    req.add_header("X-Phoneme-Token", token())
    try:
        with urllib.request.urlopen(req, timeout=timeout()) as res:
            data = res.read(MAX_RESPONSE_BYTES + 1)
        if len(data) > MAX_RESPONSE_BYTES:
            return {"status": "unavailable", "reason": "response_too_large", "via": "remote"}
        return sanitize(json.loads(data.decode("utf-8")))
    except urllib.error.HTTPError as exc:
        return {"status": "unavailable", "reason": f"http_{exc.code}", "via": "remote"}
    except Exception as exc:  # noqa: BLE001 — 타임아웃·DNS·연결 거부·JSON 오류 전부
        return {"status": "unavailable", "reason": type(exc).__name__, "via": "remote"}
