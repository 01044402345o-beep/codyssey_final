"""클라우드 발음 평가 — 음소 노드(PC)가 모두 실패할 때만 쓰는 대체 경로(유료, 하루 상한).

순서: PHONEME_CLOUD_ORDER(기본 "azure,speechace") 중 키가 있는 것만, 앞에서부터. 실패하면 다음으로.
결과는 노드와 같은 형식(remote.sanitize 가 만드는 phonemes_acoustic)으로 바꿔 화면이 그대로 그린다.
어떤 실패도 예외로 새지 않는다 — 다 실패하면 화면은 받아쓴 글자 기준(#211)·단어 쪽만으로 내려간다.

  Azure AI Speech 발음 평가(REST short audio, en-US, 음소 IPA·NBest 음소)
    PHONEME_AZURE_KEY, PHONEME_AZURE_REGION(운영 eastus = 미국. koreacentral 이면 국내 — 바꾸면 처리방침 초안 표도 고친다)
  Speechace(scoring/text v9, 음소 품질 점수·sound_most_like)
    PHONEME_SPEECHACE_KEY, PHONEME_SPEECHACE_URL(선택, 지역 API 주소. 기본 https://api.speechace.co)

  PHONEME_CLOUD_DAILY_CAP   하루 호출 상한(기본 100, 0 이면 끔). 서버 메모리에 센다(재시작하면 0부터)
  PHONEME_CLOUD_TIMEOUT     한 곳당 초(기본 6), PHONEME_CLOUD_BUDGET 전체 초(기본 8)

음성은 동의 v9 ⑤ 에 적은 대로, 노드가 모두 실패했을 때만 이 업체들로 간다.
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any, Callable

import numpy as np

from ..phonemes import ARPABET_IPA
from .inventory import tip_for
from .remote import MAX_RESPONSE_BYTES, wav_bytes
from .score import EQUIVALENT

log = logging.getLogger("app.acoustic.cloud")

OK_SCORE = 80.0       # 음소 점수(0~100) 이상이면 ok
MISSING_SCORE = 50.0  # 미만이면 missing(목표와 다르게 남), 그 사이는 weak

_cap_lock = threading.Lock()
_cap = {"day": "", "used": 0}


# ---------------------------------------------------------------- 설정
def _f(name: str, default: float, lo: float, hi: float) -> float:
    try:
        v = float(os.getenv(name, "").strip() or default)
    except ValueError:
        v = default
    return max(lo, min(hi, v))


def daily_cap() -> int:
    return int(_f("PHONEME_CLOUD_DAILY_CAP", 100, 0, 100000))


def timeout() -> float:
    return _f("PHONEME_CLOUD_TIMEOUT", 6.0, 1.0, 30.0)


def budget() -> float:
    return _f("PHONEME_CLOUD_BUDGET", 8.0, 1.0, 60.0)


def _azure_ready() -> bool:
    return bool(os.getenv("PHONEME_AZURE_KEY", "").strip() and os.getenv("PHONEME_AZURE_REGION", "").strip())


def _speechace_ready() -> bool:
    return bool(os.getenv("PHONEME_SPEECHACE_KEY", "").strip())


def providers() -> list[str]:
    ready = {"azure": _azure_ready, "speechace": _speechace_ready}
    raw = os.getenv("PHONEME_CLOUD_ORDER", "").strip() or "azure,speechace"     # 비어 있으면 기본 순서
    order = [p.strip().lower() for p in raw.split(",")]
    out: list[str] = []
    for p in order:
        if p in ready and ready[p]() and p not in out:
            out.append(p)
    return out


def configured() -> bool:
    return bool(providers()) and daily_cap() > 0


def _take_cap() -> bool:
    today = dt.date.today().isoformat()
    with _cap_lock:
        if _cap["day"] != today:
            _cap.update(day=today, used=0)
        if _cap["used"] >= daily_cap():
            return False
        _cap["used"] += 1
        return True


def cap_state() -> dict[str, Any]:
    with _cap_lock:
        return {"day": _cap["day"] or None, "used": _cap["used"], "limit": daily_cap()}


def reset_cap() -> None:
    with _cap_lock:
        _cap.update(day="", used=0)


def status() -> dict[str, Any]:
    """진단용(/health 상세). 키는 내보내지 않는다."""
    return {"providers": providers(), "azure_region": os.getenv("PHONEME_AZURE_REGION", "").strip() or None,
            "cap": cap_state()}


# ---------------------------------------------------------------- 공통 변환
def _status_of(score: float | None) -> str:
    if score is None:
        return "missing"
    return "ok" if score >= OK_SCORE else ("weak" if score >= MISSING_SCORE else "missing")


# 업체 IPA(길이 표시 없음·r 계열 기호 차이)를 노드(espeak)와 조음 안내 표(inventory.TIPS_KO)의 기호로 맞춘다
NORMALIZE = {"i": "iː", "u": "uː", "ɝ": "ɚ", "r": "ɹ", "g": "ɡ", "ɑː": "ɑ", "ɔː": "ɔ", "e": "eɪ", "o": "oʊ"}


def norm_ipa(p: Any) -> str:
    p = str(p or "").strip()
    return NORMALIZE.get(p, p)


def build_report(rows: list[dict[str, Any]], via: str, model: str) -> dict[str, Any]:
    """[{ipa, word, score(0~100), heard_as, start_ms, end_ms}] → phonemes_acoustic 형식(노드와 같음)."""
    out, worst = [], None
    for r in rows[:80]:
        if r.get("score") is None:
            continue                 # 점수를 모르는 음소는 '틀림'으로 보이지 않고 뺀다(빠진 단어는 Omission → 0점으로 따로 온다)
        r = {**r, "ipa": norm_ipa(r.get("ipa")) or "?", "heard_as": norm_ipa(r.get("heard_as")) or None}
        st = _status_of(r.get("score"))
        heard = r.get("heard_as") or None
        if heard and heard == r["ipa"]:
            heard = None
        if st != "ok" and heard and heard in EQUIVALENT.get(r["ipa"], ()):
            st = "ok"            # 같은 소리의 다른 표기(노드의 score.py 와 같은 규칙)
        row = {"ipa": r["ipa"][:6], "word": (r.get("word") or "")[:40], "status": st,
               "gop": round(max(0.0, min(1.0, (r.get("score") or 0.0) / 100.0)), 3),
               "heard_as": heard[:6] if heard and st != "ok" else None,
               "start_ms": r.get("start_ms"), "end_ms": r.get("end_ms")}
        out.append(row)
        if st != "ok" and (worst is None or row["gop"] < worst["gop"]):
            worst = row
    total = len(out)
    focus = None
    if worst is not None:
        label, tip = tip_for(worst["ipa"])
        focus = {"ipa": worst["ipa"], "word": worst["word"], "heard_as": worst["heard_as"],
                 "label": label[:30], "tip": tip[:200], "gop": worst["gop"]}
    return {"status": "ok", "basis": "acoustic", "via": via, "model": model,
            "phoneme_accuracy": round(100.0 * sum(r["status"] == "ok" for r in out) / total, 1) if total else None,
            "phonemes": out, "focus": focus, "fallback_words": []}


def _read_json(req: urllib.request.Request, t: float) -> Any:
    try:
        with urllib.request.urlopen(req, timeout=t) as res:
            data = res.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise ValueError(f"http_{exc.code}") from exc
    if len(data) > MAX_RESPONSE_BYTES:
        raise ValueError("response_too_large")
    return json.loads(data.decode("utf-8"))


# ---------------------------------------------------------------- Azure
def _assess(obj: dict) -> dict:
    """평가 값이 PronunciationAssessment 아래(SDK·일부 응답)에 있든, 바로 아래(REST format=detailed)에 있든 읽는다."""
    inner = obj.get("PronunciationAssessment")
    return {**obj, **inner} if isinstance(inner, dict) else obj


def azure_rows(data: Any) -> list[dict[str, Any]]:
    """Azure 발음 평가 응답(format=detailed) → 공통 행. 오류 구조면 ValueError.

    2026-11-04 라이브 실측: REST 응답은 음소 점수를 Phonemes[].AccuracyScore 에 바로 둔다(중첩 아님).
    중첩 형식만 읽던 첫 버전은 점수를 못 읽어 20개 음소를 전부 '틀림(0%)'으로 그렸다.
    점수를 하나도 못 읽으면 결과를 만들지 않고 실패로 넘긴다 — 모르는 것을 '전부 틀림'으로 보이지 않게.
    """
    if not isinstance(data, dict) or data.get("RecognitionStatus") != "Success":
        raise ValueError(f"azure_{(data or {}).get('RecognitionStatus', 'bad')}"[:40] if isinstance(data, dict) else "azure_bad")
    nbest = data.get("NBest") or []
    if not nbest or not isinstance(nbest[0], dict):
        raise ValueError("azure_no_nbest")
    rows: list[dict[str, Any]] = []
    for w in nbest[0].get("Words") or []:
        if not isinstance(w, dict):
            continue
        wa = _assess(w)
        word = str(w.get("Word") or "").lower()
        etype = wa.get("ErrorType", "None")
        if etype == "Insertion":
            continue                       # 목표에 없는 말 — 목표 음소 행이 아니다
        for ph in w.get("Phonemes") or []:
            if not isinstance(ph, dict):
                continue
            pa = _assess(ph)
            score = pa.get("AccuracyScore")
            score = float(score) if isinstance(score, (int, float)) and not isinstance(score, bool) else None
            if etype == "Omission":
                score = 0.0
            heard = None
            for cand in pa.get("NBestPhonemes") or []:
                p = str((cand or {}).get("Phoneme") or "")
                if p and p != ph.get("Phoneme"):
                    heard = p
                    break
            off, dur = ph.get("Offset"), ph.get("Duration")
            start = int(off / 10000) if isinstance(off, (int, float)) else None     # 100ns → ms
            end = int((off + dur) / 10000) if isinstance(off, (int, float)) and isinstance(dur, (int, float)) else None
            rows.append({"ipa": str(ph.get("Phoneme") or "?"), "word": word, "score": score, "heard_as": heard,
                         "start_ms": start, "end_ms": end})
    if not rows:
        raise ValueError("azure_no_phonemes")
    if all(r["score"] is None for r in rows):
        raise ValueError("azure_no_scores")
    return rows


def _azure(samples: np.ndarray, target: str, t: float) -> dict[str, Any]:
    region = os.getenv("PHONEME_AZURE_REGION", "").strip()
    if not region.replace("-", "").isalnum():
        raise ValueError("azure_bad_region")
    pa = {"ReferenceText": target[:300], "GradingSystem": "HundredMark", "Granularity": "Phoneme",
          "Dimension": "Comprehensive", "EnableMiscue": True, "PhonemeAlphabet": "IPA", "NBestPhonemeCount": 5}
    url = (f"https://{region}.stt.speech.microsoft.com/speech/recognition/conversation/cognitiveservices/v1"
           "?language=en-US&format=detailed")
    req = urllib.request.Request(url, data=wav_bytes(samples), method="POST")
    req.add_header("Ocp-Apim-Subscription-Key", os.getenv("PHONEME_AZURE_KEY", "").strip())
    req.add_header("Content-Type", "audio/wav; codecs=audio/pcm; samplerate=16000")
    req.add_header("Accept", "application/json")
    req.add_header("Pronunciation-Assessment", base64.b64encode(json.dumps(pa).encode()).decode())
    return build_report(azure_rows(_read_json(req, t)), "azure", f"azure-pronunciation-assessment ({region})")


# ---------------------------------------------------------------- Speechace
def speechace_rows(data: Any) -> list[dict[str, Any]]:
    """Speechace scoring/text 응답 → 공통 행. 음소는 ARPAbet 소문자(iy)라 IPA 로 바꾼다."""
    if not isinstance(data, dict) or data.get("status") != "success":
        raise ValueError(f"speechace_{(data or {}).get('short_message') or (data or {}).get('status') or 'bad'}"[:40]
                         if isinstance(data, dict) else "speechace_bad")
    ts = data.get("text_score") or {}
    rows: list[dict[str, Any]] = []
    to_ipa = lambda p: ARPABET_IPA.get(str(p or "").upper().rstrip("012"), "")
    for w in ts.get("word_score_list") or []:
        word = str(w.get("word") or "").lower()
        for ph in w.get("phone_score_list") or []:
            ipa = to_ipa(ph.get("phone"))
            if not ipa:
                continue
            q = ph.get("quality_score")
            heard = to_ipa(ph.get("sound_most_like")) or None
            ext = ph.get("extent") if isinstance(ph.get("extent"), list) and len(ph.get("extent")) == 2 else None
            rows.append({"ipa": ipa, "word": word, "score": float(q) if isinstance(q, (int, float)) else None,
                         "heard_as": heard, "start_ms": int(ext[0] * 10) if ext else None,
                         "end_ms": int(ext[1] * 10) if ext else None})     # extent 는 10ms 단위
    if not rows:
        raise ValueError("speechace_no_phonemes")
    return rows


def _speechace(samples: np.ndarray, target: str, t: float) -> dict[str, Any]:
    base = (os.getenv("PHONEME_SPEECHACE_URL", "").strip() or "https://api.speechace.co").rstrip("/")
    if not base.startswith("https://"):
        raise ValueError("speechace_bad_url")
    q = urllib.parse.urlencode({"key": os.getenv("PHONEME_SPEECHACE_KEY", "").strip(), "dialect": "en-us"})
    boundary = "----madi" + uuid.uuid4().hex
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="text"\r\n\r\n{target[:300]}\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="user_audio_file"; filename="a.wav"\r\n'
            "Content-Type: audio/wav\r\n\r\n").encode() + wav_bytes(samples) + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(f"{base}/api/scoring/text/v9/json?{q}", data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    return build_report(speechace_rows(_read_json(req, t)), "speechace", "speechace scoring v9")


CALLERS: dict[str, Callable[[np.ndarray, str, float], dict[str, Any]]] = {"azure": _azure, "speechace": _speechace}


def analyze(samples: np.ndarray, target: str) -> dict[str, Any]:
    """키가 있는 업체를 순서대로. 하루 상한을 넘으면 부르지 않는다. 예외를 던지지 않는다."""
    order = providers()
    if not order or daily_cap() <= 0:
        return {"status": "disabled", "reason": "cloud_not_configured"}
    deadline = time.monotonic() + budget()
    attempts: list[dict[str, Any]] = []
    for name in order:
        remaining = deadline - time.monotonic()
        if remaining <= 0.5:
            attempts.append({"provider": name, "result": "budget_exhausted"})
            break
        if not _take_cap():
            log.warning("클라우드 발음 평가 하루 상한(%d) 도달 — 부르지 않음", daily_cap())
            return {"status": "unavailable", "reason": "cloud_daily_cap", "via": "cloud", "attempts": attempts}
        started = time.monotonic()
        try:
            out = CALLERS[name](samples, target, min(timeout(), remaining))
        except Exception as exc:  # noqa: BLE001 — 키 오류·네트워크·형식 전부, 다음 업체로
            reason = (str(exc) if isinstance(exc, ValueError) and str(exc) else type(exc).__name__)[:40]
            log.warning("클라우드 발음 평가 실패(%s): %s", name, reason)
            attempts.append({"provider": name, "result": reason, "ms": int((time.monotonic() - started) * 1000)})
            continue
        if attempts:
            out["attempts"] = attempts
        return out
    return {"status": "unavailable", "reason": "all_cloud_failed", "via": "cloud", "attempts": attempts}
