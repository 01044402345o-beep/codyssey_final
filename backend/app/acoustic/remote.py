"""원격 음소 노드 호출 — 본체(Render 무료 512MB)는 모델(+358MB)을 못 올리므로, 상시 가동 PC 가 그 일만 맡는다.
노드가 여러 대면 살아 있는 곳으로 넘기고(페일오버), 죽은 노드는 쉬게 했다가 살아나면 되돌린다(복구).

설계 원칙
  1) 어떤 실패도 예외로 새지 않는다. 음소는 부가 정보라, 노드가 모두 없으면 없는 대로 둔다(채점은 그대로).
  2) 요청 경로에서 죽은 노드를 다시 두드리지 않는다(서킷브레이커) — 느린 실패가 가장 나쁘다.
  3) 조정자·레지스트리를 두지 않는다. 노드는 무상태(같은 모델·코드·토큰)라 주소 목록만 있으면 된다.
  4) 노드마다 https(또는 같은 PC 의 http)·공유 토큰이 있어야 음성을 보낸다. 노드 응답은 그대로 믿지 않는다.

환경변수
  PHONEME_REMOTE_URLS       쉼표 목록, 앞에 있는 것을 먼저 쓴다(https://a.ts.net,https://b.ts.net)
  PHONEME_REMOTE_URL        목록이 없을 때의 단일 주소(하위 호환)
  PHONEME_TOKEN             노드와 같은 공유 비밀(모든 노드가 같은 값)
  PHONEME_REMOTE_TIMEOUT    노드 한 곳당 시도 제한(초, 기본 4)
  PHONEME_REMOTE_BUDGET     모든 시도를 합친 상한(초, 기본 6) — 응답 지연의 상한
  PHONEME_BREAKER_FAILS     연속 실패 몇 번에 그 노드를 쉬게 할지(기본 2)
  PHONEME_BREAKER_COOLDOWN  쉬게 하는 시간(초, 기본 60)
  PHONEME_PROBE_INTERVAL    쉬는 노드를 /healthz 로 다시 보는 주기(초, 기본 30, 최소 10)

Render 는 공인 인터넷에 있으므로 집 LAN 주소(192.168.x.x)나 Tailscale IP(100.x)는 닿지 않는다 — Funnel 주소만 쓴다.
"""
from __future__ import annotations

import io
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import wave
from typing import Any

import numpy as np

log = logging.getLogger("app.acoustic.remote")

MAX_RESPONSE_BYTES = 256 * 1024

_lock = threading.Lock()
_nodes: dict[str, "_Node"] = {}
_prober: threading.Thread | None = None


# ---------------------------------------------------------------- 설정
def _env_float(name: str, default: float, lo: float, hi: float) -> float:
    try:
        v = float(os.getenv(name, "").strip() or default)
    except ValueError:
        v = default
    return max(lo, min(hi, v))


def token() -> str:
    return os.getenv("PHONEME_TOKEN", "").strip()


def _allowed(u: str) -> bool:
    """https, 또는 같은 PC(127.0.0.1·localhost)의 http 만 — 음성이 평문으로 밖에 나가지 않게."""
    return u.startswith("https://") or u.startswith(("http://127.0.0.1:", "http://localhost:"))


def urls() -> list[str]:
    """쓸 수 있는 노드 주소(순서 유지, 중복·허용 안 되는 주소 제거)."""
    raw = os.getenv("PHONEME_REMOTE_URLS", "").strip()
    items = raw.split(",") if raw else [os.getenv("PHONEME_REMOTE_URL", "")]
    out: list[str] = []
    for item in items:
        u = item.strip().rstrip("/")
        if u and _allowed(u) and u not in out:
            out.append(u)
    return out


def configured() -> bool:
    return bool(urls()) and bool(token())


def per_node_timeout() -> float:
    return _env_float("PHONEME_REMOTE_TIMEOUT", 4.0, 1.0, 30.0)


def budget() -> float:
    return _env_float("PHONEME_REMOTE_BUDGET", 6.0, 1.0, 30.0)


def timeout() -> float:
    """호출 쪽(main)이 기다릴 상한 — 전체 예산과 같다."""
    return budget()


# ---------------------------------------------------------------- 노드 상태
class _Node:
    __slots__ = ("url", "fails", "down_until", "inflight", "ok_count", "last_error")

    def __init__(self, url: str) -> None:
        self.url = url
        self.fails = 0
        self.down_until = 0.0
        self.inflight = 0
        self.ok_count = 0
        self.last_error = ""


def _node(url: str) -> _Node:
    n = _nodes.get(url)
    if n is None:
        n = _nodes[url] = _Node(url)
    return n


def reset_state() -> None:
    """테스트용."""
    with _lock:
        _nodes.clear()


def _mark_ok(n: _Node) -> None:
    with _lock:
        n.fails = 0
        n.down_until = 0.0
        n.ok_count += 1
        n.last_error = ""


def _mark_fail(n: _Node, reason: str) -> None:
    limit = int(_env_float("PHONEME_BREAKER_FAILS", 2, 1, 10))
    cooldown = _env_float("PHONEME_BREAKER_COOLDOWN", 60.0, 5.0, 3600.0)
    with _lock:
        n.fails += 1
        n.last_error = reason
        blocked = n.fails >= limit
        if blocked:
            n.down_until = time.monotonic() + cooldown
    if blocked:
        log.warning("음소 노드 %d초 쉼: %s (%s)", int(cooldown), _host(n.url), reason)
        _ensure_prober()


def _plan() -> list[_Node]:
    """정상 노드(진행 중 요청이 적은 순, 같으면 목록 순). 모두 쉬는 중이면 가장 먼저 풀릴 한 곳만(반쯤 열어 확인)."""
    now = time.monotonic()
    with _lock:
        order = {u: i for i, u in enumerate(urls())}
        nodes = [_node(u) for u in order]
        healthy = sorted((n for n in nodes if n.down_until <= now), key=lambda n: (n.inflight, order[n.url]))
        resting = sorted((n for n in nodes if n.down_until > now), key=lambda n: n.down_until)
    return healthy if healthy else resting[:1]


def _host(u: str) -> str:
    return urllib.parse.urlsplit(u).hostname or "?"


def status() -> dict[str, Any]:
    """진단용(/health 상세, 관리자 토큰). 주소는 호스트 이름만."""
    now = time.monotonic()
    with _lock:
        return {
            "configured": configured(),
            "nodes": [{"host": _host(n.url), "up": n.down_until <= now, "fails": n.fails, "ok": n.ok_count,
                       "inflight": n.inflight, "last_error": n.last_error or None,
                       "rest_s": max(0, int(n.down_until - now))} for n in (_node(u) for u in urls())],
        }


# ---------------------------------------------------------------- 복구 감시
def _probe(n: _Node, t: float = 3.0) -> bool:
    """/healthz 만 본다(모델 추론 없음, 토큰 불필요)."""
    try:
        with urllib.request.urlopen(n.url + "/healthz", timeout=t) as res:
            return res.status == 200 and bool(json.loads(res.read(4096).decode("utf-8")).get("ready"))
    except Exception:  # noqa: BLE001
        return False


def probe_resting() -> int:
    """쉬는 노드를 한 번 확인해 살아난 것은 되돌린다. 되돌린 수. (감시 스레드와 테스트가 쓴다)"""
    now = time.monotonic()
    with _lock:
        resting = [n for n in _nodes.values() if n.down_until > now and n.url in urls()]
    back = 0
    for n in resting:
        if _probe(n):
            with _lock:
                n.fails = 0
                n.down_until = 0.0
            back += 1
            log.info("음소 노드 복구: %s", _host(n.url))
    return back


def _prober_loop() -> None:
    global _prober
    while True:
        time.sleep(_env_float("PHONEME_PROBE_INTERVAL", 30.0, 10.0, 600.0))
        probe_resting()
        with _lock:
            if not any(n.down_until > time.monotonic() for n in _nodes.values()):
                _prober = None      # 쉬는 노드가 없으면 끝낸다(다음 차단 때 다시 뜬다)
                return


def _ensure_prober() -> None:
    global _prober
    with _lock:
        if _prober is None:
            _prober = threading.Thread(target=_prober_loop, name="phoneme-prober", daemon=True)
            _prober.start()


# ---------------------------------------------------------------- 요청
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
    """노드 응답에서 화면·로그가 쓰는 필드만 꺼낸다. 형식이 틀리면 status=unavailable."""
    if not isinstance(raw, dict) or raw.get("status") != "ok":
        reason = _short(raw.get("reason")) if isinstance(raw, dict) else None
        status_ = _short(raw.get("status")) if isinstance(raw, dict) else None
        return {"status": "unavailable", "reason": reason or status_ or "bad_response", "via": "remote"}
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
        "status": "ok", "basis": "acoustic", "via": raw.get("via") if raw.get("via") in ("azure", "speechace") else "remote",
        "model": _short(raw.get("model"), 80),
        "phoneme_accuracy": _num(raw.get("phoneme_accuracy"), 0, 100),
        "phonemes": rows,
        "focus": focus,
        "fallback_words": [w for w in (_short(x) for x in fb[:10]) if w],
    }


class _Unauthorized(Exception):
    pass


def _post(n: _Node, body: bytes, ctype: str, t: float) -> dict[str, Any]:
    req = urllib.request.Request(n.url + "/phoneme-check", data=body, method="POST")
    req.add_header("Content-Type", ctype)
    req.add_header("X-Phoneme-Token", token())
    try:
        with urllib.request.urlopen(req, timeout=t) as res:
            data = res.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise _Unauthorized(f"http_{exc.code}") from exc
        raise ValueError(f"http_{exc.code}") from exc
    if len(data) > MAX_RESPONSE_BYTES:
        raise ValueError("response_too_large")
    out = sanitize(json.loads(data.decode("utf-8")))
    if out["status"] != "ok":
        raise ValueError(out["reason"])      # 노드가 '모델 준비 안 됨' 등을 답하면 다음 노드로
    return out


def analyze(samples: np.ndarray, target: str) -> dict[str, Any]:
    """앞에서부터 시도하고, 실패하면 다음 노드로 넘긴다. 예외를 던지지 않는다."""
    if not configured():
        return {"status": "disabled", "reason": "not_configured"}
    deadline = time.monotonic() + budget()
    body, ctype = _multipart({"text": target[:300]}, wav_bytes(samples))
    attempts: list[dict[str, Any]] = []
    listed = urls()
    for n in _plan():
        i = listed.index(n.url) + 1          # 설정 목록(PHONEME_REMOTE_URLS) 기준 번호
        remaining = deadline - time.monotonic()
        if remaining <= 0.3:
            attempts.append({"node": i, "result": "budget_exhausted"})
            break
        with _lock:
            n.inflight += 1
        started = time.monotonic()
        try:
            out = _post(n, body, ctype, min(per_node_timeout(), remaining))
        except _Unauthorized as exc:
            # 모든 노드가 같은 토큰이라 다른 노드로 넘겨도 같다. 토큰 불일치는 운영 설정 오류다.
            _mark_fail(n, str(exc))
            log.error("음소 노드 인증 실패 — PHONEME_TOKEN 불일치: %s", _host(n.url))
            return {"status": "unavailable", "reason": "unauthorized", "via": "remote"}
        except Exception as exc:  # noqa: BLE001 — 타임아웃·연결 거부·DNS·형식 오류 전부
            reason = (str(exc) if isinstance(exc, ValueError) and str(exc) else type(exc).__name__)[:40]
            _mark_fail(n, reason)
            attempts.append({"node": i, "result": reason, "ms": int((time.monotonic() - started) * 1000)})
            continue
        finally:
            with _lock:
                n.inflight = max(0, n.inflight - 1)
        _mark_ok(n)
        out["node"] = i
        if attempts:
            out["attempts"] = attempts + [{"node": i, "result": "ok", "ms": int((time.monotonic() - started) * 1000)}]
        return out
    return {"status": "unavailable", "reason": "all_nodes_failed", "via": "remote", "attempts": attempts}
