"""실시간 통역 중계(서버 WebSocket).

브라우저 마이크 PCM16(16 kHz, mono) → 이 서버 → 통역 제공자 → 자막·번역 음성 → 브라우저.
키는 서버에만 둔다(브라우저로 내보내지 않는다). 우리 서버는 오디오를 저장하지 않는다.

제공자(2026-10-21 문서 확인):
- soniox: wss://stt-rt.soniox.com/transcribe-websocket, `translation.type=two_way`(a↔b) 한 세션에서 양방향.
  토큰마다 translation_status=translation 이면 번역, 아니면 원문. https://soniox.com/docs/translation/stt-translation/rt-translation
- openai: wss://api.openai.com/v1/realtime/translations?model=gpt-realtime-translate
  `session.update` 로 출력 언어를 정하고, 오디오를 계속 append. 출력 오디오/자막이 이벤트로 온다.
  https://developers.openai.com/api/docs/guides/realtime-translation
- fake: 키 없이 파이프(마이크→서버→자막)만 검사할 때. INTERP_ALLOW_FAKE=1 일 때만 켠다.

제공자 5개 + 시험 모드(2026-10-21 공식 문서 대조, 실제 호출은 아직 없음):
- gemini: Live API BidiGenerateContent, models/gemini-3.5-live-translate-preview, translationConfig. https://ai.google.dev/gemini-api/docs/live-api/live-translate
- deepl: POST /v3/voice/realtime → streaming_url?token=, 최상위 키 메시지(source_media_chunk 등). run_deepl 참고
- azure: Speech SDK 번역(자동 언어 감지). 패키지가 없으면 '사용 불가'
켜는 제공자와 우선순위는 INTERP_PROVIDERS(적힌 순서 = 우선순위, 기본 soniox,openai,fake)로 정한다 — 키가 있다고 저절로 켜지지 않는다. 관리자 안내: docs/ops/INTERP_ENGINES.md
환경 변수: INTERP_PROVIDERS, INTERP_PROVIDER(고정), SONIOX_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY, DEEPL_API_KEY,
          AZURE_SPEECH_KEY/AZURE_SPEECH_REGION, INTERP_ALLOW_FAKE, INTERP_MAX_SECONDS,
          INTERP_STARTS(창당 시작 수, 기본 6), INTERP_WINDOW(초, 기본 600)

유료 제공자(fake 를 뺀 전부)는 키가 서버에 있으면 누구나 과금을 일으킬 수 있으므로:
- 첫 메시지의 Firebase ID 토큰을 확인한다(브라우저 WebSocket 은 헤더를 못 붙인다). 익명 로그인·로그인 없이 시작은 거절.
- IP 와 계정마다 시작 횟수를 제한하고, 세션은 MAX_SECONDS 가 지나면 입력이 없어도 끊는다.
시험 모드(fake)는 외부 호출이 없어 토큰을 요구하지 않는다.
"""
from __future__ import annotations

import asyncio
import collections
import base64
import json
import logging
import os
import threading
import time
from typing import Callable

from fastapi import WebSocket, WebSocketDisconnect

from . import interp_local

log = logging.getLogger("interp")

SONIOX_URL = "wss://stt-rt.soniox.com/transcribe-websocket"
OPENAI_URL = "wss://api.openai.com/v1/realtime/translations?model=gpt-realtime-translate"
MAX_SECONDS = int(os.getenv("INTERP_MAX_SECONDS", "180") or 180)   # 한 세션 상한(비용·악용 방지)
MAX_BYTES = 16_000 * 2 * MAX_SECONDS                              # 16 kHz 16-bit
LANGS = {"ko", "en"}                                              # 지금 화면이 쓰는 쌍만 받는다
STARTS = int(os.getenv("INTERP_STARTS", "6") or 6)                # 창당 시작 수(IP·계정 각각)
WINDOW = int(os.getenv("INTERP_WINDOW", "600") or 600)
_starts: dict[str, collections.deque] = collections.defaultdict(collections.deque)
_starts_lock = threading.Lock()


def allow_start(*keys: str) -> bool:
    """키(IP·계정)마다 WINDOW 초 안 시작 수가 STARTS 미만이면 기록하고 True. 프로세스 메모리 — 임시 방어."""
    now = time.time()
    with _starts_lock:
        if len(_starts) > 10_000:
            for k in [k for k, v in _starts.items() if not v or now - v[-1] > WINDOW]:
                del _starts[k]
        qs = []
        for k in keys:
            q = _starts[k]
            while q and now - q[0] > WINDOW:
                q.popleft()
            if len(q) >= STARTS:
                return False
            qs.append(q)
        for q in qs:
            q.append(now)
    return True


# 제공자 표 — 화면의 '통역 엔진' 선택과 /interp/providers 가 쓴다. 키 이름·값은 내려보내지 않는다.
# verified: 공식 문서와 코드를 대조한 범위(실제 호출 확인은 아님). False 면 화면에 '확인 필요'.
PROVIDERS = {
    "soniox": {"label": "Soniox", "key": "SONIOX_API_KEY", "audio_out": False, "two_way": True,
               "verified": True, "note": "한 세션 양방향(ko↔en), 자막만"},
    "openai": {"label": "OpenAI Realtime", "key": "OPENAI_API_KEY", "audio_out": True, "two_way": False,
               "verified": True, "note": "번역 음성까지, 출력 언어 1개(한국어 출력은 문서 미확인)"},
    "gemini": {"label": "Gemini Live", "key": "GEMINI_API_KEY", "audio_out": True, "two_way": False,
               "verified": True, "note": "번역 음성까지, 출력 언어 1개(미리보기 모델)"},
    "deepl": {"label": "DeepL Voice", "key": "DEEPL_API_KEY", "audio_out": False, "two_way": False,
              "verified": False, "note": "자막만, PCM 입력 형식 확인 필요"},
    "azure": {"label": "Azure Speech", "key": "AZURE_SPEECH_KEY", "audio_out": False, "two_way": True,
              "verified": False, "note": "자동 언어 감지, Speech SDK 필요"},
    "local": {"label": "마디 서버(자체)", "key": "", "audio_out": False, "two_way": True,
              "verified": True, "note": "외부 키 없이 우리 서버에서 Whisper+Argos. 말이 끝난 뒤 문장 단위, 유료 인스턴스 권장"},
    "fake": {"label": "시험 모드", "key": "", "audio_out": False, "two_way": True,
             "verified": True, "note": "키 없이 배관만 검사(번역 아님)"},
}
# 운영자가 켠 제공자만 쓴다. 키가 있다는 이유만으로 켜지지 않게 — 특히 gemini 는 앱의 문장 생성 키(GEMINI_API_KEY)를
# 같이 쓰므로 자동으로 켜지면 음성이 처리방침에 없는 곳(Google)으로 간다. 처리방침 3절에 적은 제공자만 기본으로 둔다.
DEFAULT_ENABLED = "soniox,openai,fake"
AZURE_LOCALES = {"ko": "ko-KR", "en": "en-US"}   # Azure 언어 식별 후보는 로캘로 준다


def _key(name: str) -> str:
    return (os.getenv(name) or "").strip()


def enabled_providers() -> list[str]:
    """켠 엔진을 **적힌 순서대로** 돌려준다 — 이 순서가 우선순위다(앞에 쓴 엔진을 먼저 쓴다). 운영 안내: docs/ops/INTERP_ENGINES.md"""
    raw = (os.getenv("INTERP_PROVIDERS") or "").strip()   # 비어 있으면 기본값(빈 값으로 모든 엔진이 꺼지지 않게)
    names = [x.strip().lower() for x in (raw or DEFAULT_ENABLED).split(",")]
    out: list[str] = []
    for x in names:
        if x in PROVIDERS and x not in out:
            out.append(x)
    return out


def provider_available(pid: str) -> bool:
    info = PROVIDERS.get(pid)
    if not info or pid not in enabled_providers():
        return False
    if pid == "fake":
        return os.getenv("INTERP_ALLOW_FAKE") == "1"
    if pid == "local":   # 키 대신 패키지·모델. 불러오다 실패했으면 쓰지 않는다(다음 엔진으로)
        return interp_local.deps_ok() and interp_local.status()["status"] != "error"
    if pid == "azure":
        if not (_key("AZURE_SPEECH_KEY") and _key("AZURE_SPEECH_REGION")):
            return False
        return azure_sdk_ok()   # 미설치·리눅스 의존 라이브러리 없음이면 '사용 불가'
    return bool(_key(info["key"]))


_azure_sdk: bool | None = None


def azure_sdk_ok() -> bool:
    """/health 용 — Azure Speech SDK 를 불러올 수 있는지(리눅스 의존 라이브러리 포함). 한 번만 시도한다."""
    global _azure_sdk
    if _azure_sdk is None:
        try:
            import azure.cognitiveservices.speech  # noqa: F401
            _azure_sdk = True
        except Exception as exc:      # noqa: BLE001
            log.warning("azure speech sdk import failed: %s: %s", type(exc).__name__, str(exc)[:200])
            _azure_sdk = False
    return _azure_sdk


def provider_list() -> list[dict]:
    """켠 엔진(우선순위 순) → 나머지. priority 는 1부터(켜지지 않았으면 None). 화면은 이 순서로 칩을 보이고 첫 엔진을 기본으로 한다."""
    on = enabled_providers()
    forced = _key("INTERP_PROVIDER").lower()
    if forced:   # 고정하면 그 엔진만 보인다(사용자 선택이 무시되므로 고를 칸을 보이지 않는다)
        on = [forced] if forced in on else []
    ids = on + [pid for pid in PROVIDERS if pid not in on]
    return [{"id": pid, **{k: v for k, v in PROVIDERS[pid].items() if k != "key"}, "available": pid in on and provider_available(pid),
             "priority": on.index(pid) + 1 if pid in on else None} for pid in ids]


def provider_chain(requested: str | None = None, exclude: tuple[str, ...] = ()) -> list[str]:
    """이번 통역에서 시도할 엔진 순서. 앞 엔진이 연결에 실패하면 다음 엔진으로 넘어간다(자동 전환).
    INTERP_PROVIDER 로 고정하면 그 엔진 하나뿐이다(넘어갈 곳 없음)."""
    forced = _key("INTERP_PROVIDER").lower()
    if forced:
        return [forced] if forced not in exclude and provider_available(forced) else []
    out: list[str] = []
    for pid in ([requested] if requested else []) + enabled_providers():
        if pid and pid not in out and pid not in exclude and provider_available(pid):
            out.append(pid)
    return out


def provider_choice(requested: str | None = None) -> str:
    """INTERP_PROVIDER 고정 → 사용자가 고른 것 → INTERP_PROVIDERS 에 적힌 순서. 쓸 수 있는 게 없으면 'none'."""
    forced = _key("INTERP_PROVIDER").lower()
    if forced:
        return forced if provider_available(forced) else "none"
    order = ([requested] if requested else []) + enabled_providers()
    for pid in order:
        if pid and provider_available(pid):
            return pid
    return "none"


async def _connect(url: str, headers: dict):
    import websockets
    try:
        return await websockets.connect(url, additional_headers=headers, max_size=None)   # websockets>=14
    except TypeError:                                                                     # websockets<14
        return await websockets.connect(url, extra_headers=headers, max_size=None)


def render_tokens(tokens: list[dict]) -> tuple[str, str, str, str]:
    """Soniox 토큰 → (원문 확정, 원문 임시, 번역 확정, 번역 임시)."""
    sf = sp = tf = tp = ""
    for t in tokens or []:
        text = t.get("text") or ""
        if not text:
            continue
        is_tr = t.get("translation_status") == "translation"
        if t.get("is_final"):
            if is_tr:
                tf += text
            else:
                sf += text
        else:
            if is_tr:
                tp += text
            else:
                sp += text
    return sf, sp, tf, tp


async def _send(ws: WebSocket, payload: dict) -> None:
    await ws.send_text(json.dumps(payload, ensure_ascii=False))


class ProviderSetupError(RuntimeError):
    """엔진이 통역을 시작하기 전에 실패(키·요금제·패키지·준비 안 됨). 다음 엔진으로 넘어간다."""


class _Session:
    def __init__(self, ws: WebSocket, provider: str, a: str, b: str):
        self.ws = ws
        self.provider = provider
        self.a, self.b = a, b
        self.started = time.monotonic()
        self.bytes_in = 0
        self.closed = False
        self.ready = False   # 'ready' 를 보낸 뒤에 실패하면 자동 전환하지 않는다(이미 말한 소리는 되돌릴 수 없다)

    async def announce(self, payload: dict) -> None:
        self.ready = True
        await _send(self.ws, payload)

    async def pump_client(self, send_audio) -> None:
        """브라우저 → 제공자. 오디오는 바이너리 프레임, 제어는 JSON."""
        while True:
            msg = await self.ws.receive()
            if msg.get("type") == "websocket.disconnect":
                return
            if self.bytes_in > MAX_BYTES or time.monotonic() - self.started > MAX_SECONDS:
                await _send(self.ws, {"type": "error", "code": "too_long",
                                      "message": f"한 번에 {MAX_SECONDS}초까지 통역할 수 있어요. 다시 시작해 주세요."})
                return
            data = msg.get("bytes")
            if data:
                self.bytes_in += len(data)
                await send_audio(data)
                continue
            text = msg.get("text")
            if not text:
                continue
            try:
                evt = json.loads(text)
            except ValueError:
                continue
            if evt.get("type") == "stop":
                return

    # ---- 제공자별 ----
    async def run_soniox(self) -> None:
        key = (os.getenv("SONIOX_API_KEY") or "").strip()
        cfg = {
            "model": (os.getenv("SONIOX_MODEL") or "stt-rt-v5").strip(),
            "audio_format": "pcm_s16le", "sample_rate": 16000, "num_channels": 1,
            "enable_language_identification": True,
            "enable_endpoint_detection": True,
            "translation": {"type": "two_way", "language_a": self.a, "language_b": self.b},
        }
        async with await _connect(SONIOX_URL, {"Authorization": f"Bearer {key}"}) as up:
            await up.send(json.dumps(cfg))
            await self.announce({"type": "ready", "provider": "soniox", "pair": [self.a, self.b], "audio_out": False})

            async def to_provider(data: bytes) -> None:
                await up.send(data)

            client = asyncio.create_task(self.pump_client(to_provider))
            try:
                async for raw in up:
                    evt = json.loads(raw)
                    if evt.get("error_code"):
                        await _send(self.ws, {"type": "error", "code": str(evt.get("error_code")),
                                              "message": str(evt.get("error_message") or "통역 서비스 오류")})
                        break
                    sf, sp, tf, tp = render_tokens(evt.get("tokens") or [])
                    if sf or sp or tf or tp:
                        await _send(self.ws, {"type": "caption", "source": sf, "source_partial": sp,
                                              "target": tf, "target_partial": tp})
                    if evt.get("finished"):
                        break
                    if client.done():
                        await up.send("")   # 입력 끝 알림
                        break
            finally:
                client.cancel()

    async def run_openai(self) -> None:
        key = (os.getenv("OPENAI_API_KEY") or "").strip()
        headers = {"Authorization": f"Bearer {key}", "OpenAI-Safety-Identifier": "codyssey-interp"}
        async with await _connect(OPENAI_URL, headers) as up:
            await up.send(json.dumps({"type": "session.update",
                                      "session": {"audio": {"output": {"language": self.b}}}}))
            await self.announce({"type": "ready", "provider": "openai", "pair": [self.a, self.b], "audio_out": True})
            state = {"source": "", "target": ""}

            async def to_provider(data: bytes) -> None:
                await up.send(json.dumps({"type": "session.input_audio_buffer.append",
                                          "audio": base64.b64encode(data).decode()}))

            client = asyncio.create_task(self.pump_client(to_provider))
            try:
                async for raw in up:
                    evt = json.loads(raw)
                    t = evt.get("type")
                    if t == "session.output_transcript.delta":
                        state["target"] += evt.get("delta") or ""
                        await _send(self.ws, {"type": "caption", "source": state["source"], "source_partial": "",
                                              "target": state["target"], "target_partial": ""})
                    elif t == "session.input_transcript.delta":
                        state["source"] += evt.get("delta") or ""
                        await _send(self.ws, {"type": "caption", "source": state["source"], "source_partial": "",
                                              "target": state["target"], "target_partial": ""})
                    elif t == "session.output_audio.delta":
                        await _send(self.ws, {"type": "audio", "pcm": evt.get("delta") or "", "rate": 24000})
                    elif t in ("error", "session.error"):
                        err = evt.get("error") or evt
                        await _send(self.ws, {"type": "error", "code": str(err.get("code") or "error"),
                                              "message": str(err.get("message") or "통역 서비스 오류")})
                    if client.done():
                        await up.send(json.dumps({"type": "session.close"}))   # 남은 출력을 흘려보낸다
                        client.cancel()
            finally:
                client.cancel()

    async def run_fake(self) -> None:
        """키 없이 파이프만 검사한다. 실제 번역이 아니다 — 화면도 '시험 모드'라고 밝힌다."""
        await self.announce({"type": "ready", "provider": "fake", "pair": [self.a, self.b], "audio_out": False, "test": True})
        lines = [("Where is the train station?", "기차역이 어디예요?"),
                 ("It's about five minutes on foot.", "걸어서 5분쯤 걸려요.")]
        got = [0, 0]   # [받은 바이트, 보낸 줄 수]
        per_line = 16_000 * 2   # 오디오 1초(16 kHz 16-bit)마다 한 줄. 프레임 수로 세면 브라우저 샘플레이트(48k·192k)에 따라 빨라진다

        async def to_provider(data: bytes) -> None:
            got[0] += len(data)
            if got[0] // per_line <= got[1]:
                return
            got[1] += 1
            i = (got[1] - 1) % len(lines)
            en, ko = lines[i]
            src, tgt = (en, ko) if self.a == "en" else (ko, en)
            await _send(self.ws, {"type": "caption", "source": "", "source_partial": "",
                                  "target": "", "target_partial": ""})
            await _send(self.ws, {"type": "caption", "source": src, "source_partial": "",
                                  "target": tgt, "target_partial": ""})

        try:
            await self.pump_client(to_provider)
        finally:
            await _send(self.ws, {"type": "closed"})

    async def run_local(self) -> None:
        """자체 엔진(interp_local): 말이 끝날 때마다 받아쓰고 번역한다. 외부로 음성을 보내지 않는다."""
        waited = 0.0
        while not interp_local.ready():
            st = interp_local.status()["status"]
            if st in ("idle", "error") or waited >= float(os.getenv("INTERP_LOCAL_WAIT") or 15):
                raise ProviderSetupError(f"local engine not ready ({st})")
            await asyncio.sleep(0.5); waited += 0.5
        await self.announce({"type": "ready", "provider": "local", "pair": [self.a, self.b], "audio_out": False})
        import numpy as np

        langs = (self.a, self.b)
        silence_need = interp_local.silence_ms() / 1000.0
        max_bytes = int(interp_local.max_speech_s() * 16000 * 2)
        thr = interp_local.rms_threshold()
        buf = bytearray()
        state = {"speech": False, "quiet": 0.0}
        queue: asyncio.Queue = asyncio.Queue()

        async def worker() -> None:
            while True:
                pcm = await queue.get()
                if pcm is None:
                    return
                try:
                    text, lang = await asyncio.to_thread(interp_local.transcribe, pcm, langs)
                    if not text:
                        continue
                    other = self.b if lang == self.a else self.a
                    out = await asyncio.to_thread(interp_local.translate, text, lang, other)
                    await _send(self.ws, {"type": "caption", "source": text, "source_partial": "",
                                          "target": out, "target_partial": ""})
                except Exception as exc:      # noqa: BLE001 — 한 문장 실패는 그 문장만 버린다
                    log.warning("local interp utterance failed: %s", type(exc).__name__)

        async def to_provider(data: bytes) -> None:
            n = len(data) // 2
            if not n:
                return
            a = np.frombuffer(data[: n * 2], dtype=np.int16).astype(np.float32) / 32768.0
            loud = float(np.sqrt(np.mean(a * a))) > thr
            if loud:
                state["speech"] = True
                state["quiet"] = 0.0
            elif state["speech"]:
                state["quiet"] += n / 16000.0
            if state["speech"]:
                buf.extend(data)
            if state["speech"] and (state["quiet"] >= silence_need or len(buf) >= max_bytes):
                await queue.put(bytes(buf))
                buf.clear(); state["speech"] = False; state["quiet"] = 0.0
                await _send(self.ws, {"type": "caption", "source": "", "source_partial": "…",
                                      "target": "", "target_partial": ""})   # 받아쓰는 중 표시

        task = asyncio.create_task(worker())
        try:
            await self.pump_client(to_provider)
            if buf:
                await queue.put(bytes(buf))
        finally:
            await queue.put(None)
            try:
                await asyncio.wait_for(task, timeout=30)   # 마지막 문장까지 보낸다
            except Exception:      # noqa: BLE001
                task.cancel()

    async def run_deepl(self) -> None:
        """DeepL Voice (2026-10-21 API 참조 대조: request-session · voice.asyncapi.yaml).
        POST /v3/voice/realtime → {streaming_url, token} → WebSocket `{streaming_url}?token=`.
        메시지는 type 필드가 아니라 최상위 키 하나로 구분한다:
          보냄  {"source_media_chunk": {"data": base64}} · {"end_of_source_media": {}}
          받음  source_transcript_update / target_transcript_update {concluded[], tentative[]} ·
                end_of_stream · error {error_code, error_message}
        번역 음성(target_media_chunk)은 요청하지 않는다 — 음성 형식이 opus·webm 등이라 화면의 PCM 재생과 맞지 않는다.
        확인 못 한 것: PCM 입력의 정확한 content type 문자열(DEEPL_VOICE_CONTENT_TYPE 로 바꿀 수 있다), 실제 호출."""
        key = _key("DEEPL_API_KEY")
        url = (os.getenv("DEEPL_VOICE_SESSION_URL") or "https://api.deepl.com/v3/voice/realtime").strip()
        body = {"source_media_content_type": (os.getenv("DEEPL_VOICE_CONTENT_TYPE") or "audio/pcm;encoding=s16le;rate=16000").strip(),
                "message_format": "json", "source_language": self.a, "source_language_mode": "fixed",
                "target_languages": [self.b]}
        import httpx

        async with httpx.AsyncClient(timeout=20) as cli:
            r = await cli.post(url, json=body, headers={"Authorization": f"DeepL-Auth-Key {key}"})
        if r.status_code >= 400:
            raise ProviderSetupError(f"deepl session {r.status_code}")
        info = r.json()
        async with await _connect(f"{info['streaming_url']}?token={info['token']}", {}) as up:
            await self.announce({"type": "ready", "provider": "deepl", "pair": [self.a, self.b], "audio_out": False})

            async def to_provider(data: bytes) -> None:
                await up.send(json.dumps({"source_media_chunk": {"data": base64.b64encode(data).decode()}}))

            def texts(segs) -> str:
                return "".join(str((x or {}).get("text") or "") for x in (segs or []))

            client = asyncio.create_task(self.pump_client(to_provider))
            src_done = tgt_done = ""
            src_tent = tgt_tent = ""
            try:
                async for raw in up:
                    evt = json.loads(raw)
                    if "source_transcript_update" in evt:
                        u = evt["source_transcript_update"] or {}
                        src_done += texts(u.get("concluded")); src_tent = texts(u.get("tentative"))
                    elif "target_transcript_update" in evt:
                        u = evt["target_transcript_update"] or {}
                        tgt_done += texts(u.get("concluded")); tgt_tent = texts(u.get("tentative"))
                    elif "error" in evt:
                        e = evt["error"] or {}
                        await _send(self.ws, {"type": "error", "code": f"deepl_{e.get('error_code', '')}",
                                              "message": str(e.get("error_message") or "DeepL Voice 오류")})
                        break
                    elif "end_of_stream" in evt:
                        break
                    if "source_transcript_update" in evt or "target_transcript_update" in evt:
                        await _send(self.ws, {"type": "caption", "source": src_done, "source_partial": src_tent,
                                              "target": tgt_done, "target_partial": tgt_tent})
                    if client.done():
                        await up.send(json.dumps({"end_of_source_media": {}}))   # 남은 결과를 받고 end_of_stream 으로 끝난다
                        client.cancel()
            finally:
                client.cancel()

    async def run_gemini(self) -> None:
        """Gemini Live Translation — 문서의 setup/realtimeInput 형식 그대로."""
        key = (os.getenv("GEMINI_API_KEY") or "").strip()
        model = (os.getenv("GEMINI_LIVE_MODEL") or "gemini-3.5-live-translate-preview").strip()
        url = ("wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta"
               f".GenerativeService.BidiGenerateContent?key={key}")
        async with await _connect(url, {}) as up:
            await up.send(json.dumps({"setup": {
                "model": f"models/{model}",
                "generationConfig": {
                    "responseModalities": ["AUDIO"],
                    "inputAudioTranscription": {},
                    "outputAudioTranscription": {},
                    "translationConfig": {"targetLanguageCode": self.b, "echoTargetLanguage": True},
                }}}))
            await self.announce({"type": "ready", "provider": "gemini", "pair": [self.a, self.b], "audio_out": True})

            async def to_provider(data: bytes) -> None:
                await up.send(json.dumps({"realtimeInput": {"audio": {
                    "data": base64.b64encode(data).decode(), "mimeType": "audio/pcm;rate=16000"}}}))

            client = asyncio.create_task(self.pump_client(to_provider))
            src = tgt = ""
            try:
                async for raw in up:
                    evt = json.loads(raw)
                    sc = evt.get("serverContent") or {}
                    if sc.get("inputTranscription"):
                        src += str(sc["inputTranscription"].get("text") or "")
                        await _send(self.ws, {"type": "caption", "source": src, "source_partial": "",
                                              "target": tgt, "target_partial": ""})
                    if sc.get("outputTranscription"):
                        tgt += str(sc["outputTranscription"].get("text") or "")
                        await _send(self.ws, {"type": "caption", "source": src, "source_partial": "",
                                              "target": tgt, "target_partial": ""})
                    for part in ((sc.get("modelTurn") or {}).get("parts") or []):
                        inline = part.get("inlineData") or part.get("inline_data") or {}
                        if inline.get("data"):
                            await _send(self.ws, {"type": "audio", "pcm": inline["data"], "rate": 24000})
                    if client.done():
                        client.cancel()
            finally:
                client.cancel()

    async def run_azure(self) -> None:
        """Azure Speech 번역(SDK, 2026-10-21 Microsoft Learn '언어 식별' 문서 대조).
        - 연속 언어 식별: LanguageIdMode=Continuous + v2 엔드포인트(wss://{region}.stt.speech.microsoft.com/speech/universal/v2).
        - 후보 언어는 로캘(ko-KR·en-US)로 준다. speech_recognition_language 는 '필요하지만 무시됨'이라 첫 로캘을 넣는다.
        - 번역 대상은 ko·en 둘 다 — 감지된 말이 한국어면 en 을, 영어면 ko 를 자막으로 보낸다(두 사람이 번갈아 말해도 된다).
        SDK 콜백은 SDK 스레드에서 오므로 이벤트 루프로 넘긴다."""
        try:
            import azure.cognitiveservices.speech as speechsdk
        except Exception as exc:      # noqa: BLE001 — 미설치·리눅스 의존 라이브러리 없음
            raise ProviderSetupError(f"azure speech sdk unavailable: {type(exc).__name__}") from exc
        key, region = _key("AZURE_SPEECH_KEY"), _key("AZURE_SPEECH_REGION")
        endpoint = _key("AZURE_SPEECH_ENDPOINT") or f"wss://{region}.stt.speech.microsoft.com/speech/universal/v2"
        locales = [AZURE_LOCALES[self.a], AZURE_LOCALES[self.b]]
        loop = asyncio.get_running_loop()
        cfg = speechsdk.translation.SpeechTranslationConfig(
            subscription=key, endpoint=endpoint, speech_recognition_language=locales[0],
            target_languages=(self.a, self.b))
        cfg.set_property(property_id=speechsdk.PropertyId.SpeechServiceConnection_LanguageIdMode, value="Continuous")
        auto = speechsdk.languageconfig.AutoDetectSourceLanguageConfig(languages=locales)
        fmt = speechsdk.audio.AudioStreamFormat(samples_per_second=16000, bits_per_sample=16, channels=1)
        stream = speechsdk.audio.PushAudioInputStream(stream_format=fmt)
        recognizer = speechsdk.translation.TranslationRecognizer(
            translation_config=cfg, audio_config=speechsdk.audio.AudioConfig(stream=stream),
            auto_detect_source_language_config=auto)
        await self.announce({"type": "ready", "provider": "azure", "pair": [self.a, self.b], "audio_out": False})
        done = asyncio.Event()
        state = {"src": "", "tgt": ""}

        def emit(payload: dict) -> None:
            asyncio.run_coroutine_threadsafe(_send(self.ws, payload), loop)

        def pick(result) -> str:
            try:   # 문서 예제와 같은 방식(result.properties[PropertyId…])
                detected = result.properties[speechsdk.PropertyId.SpeechServiceConnection_AutoDetectSourceLanguageResult] or ""
            except Exception:      # noqa: BLE001
                detected = ""
            other = self.b if detected.lower().startswith(self.a) else self.a
            return (result.translations or {}).get(other, "")

        def on_recognizing(evt) -> None:
            if evt.result.reason == speechsdk.ResultReason.TranslatingSpeech:
                emit({"type": "caption", "source": state["src"], "source_partial": evt.result.text or "",
                      "target": state["tgt"], "target_partial": pick(evt.result)})

        def on_recognized(evt) -> None:
            if evt.result.reason != speechsdk.ResultReason.TranslatedSpeech:
                return
            state["src"] = evt.result.text or ""            # 확정된 한 문장씩 보여 준다(화면이 지난 문장을 따로 남긴다)
            state["tgt"] = pick(evt.result)
            emit({"type": "caption", "source": state["src"], "source_partial": "",
                  "target": state["tgt"], "target_partial": ""})

        def on_canceled(evt) -> None:
            d = evt.cancellation_details if hasattr(evt, "cancellation_details") else evt
            if getattr(d, "reason", None) == speechsdk.CancellationReason.Error:
                log.warning("azure canceled: %s", _redact(str(getattr(d, "error_details", ""))))
                emit({"type": "error", "code": "provider", "message": "Azure Speech 연결이 끊겼어요. 키·지역을 확인해 주세요."})
            loop.call_soon_threadsafe(done.set)

        recognizer.recognizing.connect(on_recognizing)
        recognizer.recognized.connect(on_recognized)
        recognizer.canceled.connect(on_canceled)
        recognizer.session_stopped.connect(lambda _e: loop.call_soon_threadsafe(done.set))
        await asyncio.to_thread(lambda: recognizer.start_continuous_recognition_async().get())

        async def to_provider(data: bytes) -> None:
            stream.write(data)

        client = asyncio.create_task(self.pump_client(to_provider))
        waiter = asyncio.create_task(done.wait())
        try:
            await asyncio.wait({client, waiter}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            client.cancel(); waiter.cancel()
            try:
                stream.close()
                await asyncio.to_thread(lambda: recognizer.stop_continuous_recognition_async().get())
            except Exception:      # noqa: BLE001 — 이미 종료
                pass


def _redact(text: str) -> str:
    """오류 문구에서 키 값을 지운다(gemini 는 키를 접속 주소의 ?key= 로 보내 오류에 주소가 섞일 수 있다)."""
    for name in ("SONIOX_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "DEEPL_API_KEY", "AZURE_SPEECH_KEY"):
        v = _key(name)
        if v:
            text = text.replace(v, "***")
    return text[:300]


async def _refuse(ws: WebSocket, code: str, message: str) -> None:
    await _send(ws, {"type": "error", "code": code, "message": message})
    await ws.close()


async def serve(ws: WebSocket, ip: str = "unknown", verify: Callable[[str], dict] | None = None) -> None:
    """verify(token) → 계정 요약(uid·provider). 실패하면 예외. main 이 firebase_auth 로 넘겨준다."""
    await ws.accept()
    try:
        first = json.loads(await asyncio.wait_for(ws.receive_text(), timeout=10))
    except (asyncio.TimeoutError, ValueError, KeyError, WebSocketDisconnect):
        try:
            await _send(ws, {"type": "error", "code": "bad_start", "message": "통역을 시작할 수 없어요."})
        except Exception:      # noqa: BLE001 — 이미 끊긴 연결
            pass
        await ws.close()
        return

    exclude = tuple(str(x).lower() for x in (first.get("exclude") or []) if isinstance(x, str))[:10]
    chain = provider_chain(str(first.get("provider") or "").lower() or None, exclude)
    if not chain:
        code = "all_failed" if exclude else "no_key"
        msg = ("쓸 수 있는 통역 엔진이 모두 실패했어요. 아래 '검수 문장'으로 통역할 수 있어요." if exclude else
               "서버에 통역 서비스 키가 없어 지금은 실시간 통역을 쓸 수 없어요. 아래 '검수 문장'으로 통역할 수 있어요.")
        await _send(ws, {"type": "error", "code": code, "message": msg})
        await ws.close()
        return
    provider = chain[0]

    a = str(first.get("a") or "ko")
    b = str(first.get("b") or "en")
    if a not in LANGS or b not in LANGS or a == b:
        await _refuse(ws, "bad_pair", "지원하지 않는 언어 쌍이에요.")
        return
    keys = ["ip:" + ip]
    if any(p != "fake" for p in chain):   # 유료·자체 엔진: 로그인한 계정만(익명·게스트 제외)
        try:
            if verify is None:
                raise ValueError("no verifier")
            account = await asyncio.to_thread(verify, str(first.get("token") or ""))
        except Exception:   # noqa: BLE001 — 토큰 없음·만료·로그인 미설정 모두 같은 안내
            await _refuse(ws, "login_required", "실시간 통역은 로그인한 계정에서만 쓸 수 있어요.")
            return
        if account.get("provider") == "anonymous" or not account.get("uid"):
            await _refuse(ws, "login_required", "실시간 통역은 로그인한 계정에서만 쓸 수 있어요.")
            return
        keys.append("uid:" + account["uid"])
    if not allow_start(*keys):
        await _refuse(ws, "rate_limited", f"잠시 뒤 다시 시도해 주세요({WINDOW // 60}분에 {STARTS}번까지).")
        return
    deadline = time.monotonic() + MAX_SECONDS + 5
    try:
        for idx, provider in enumerate(chain):
            sess = _Session(ws, provider, a, b)
            log.info("interp start provider=%s pair=%s try=%d/%d", provider, (a, b), idx + 1, len(chain))
            run = {"soniox": sess.run_soniox, "openai": sess.run_openai, "gemini": sess.run_gemini,
                   "deepl": sess.run_deepl, "azure": sess.run_azure, "local": sess.run_local,
                   "fake": sess.run_fake}[provider]
            try:
                await asyncio.wait_for(run(), timeout=max(1.0, deadline - time.monotonic()))   # 입력이 멈춰도 열린 채 남지 않게
                break
            except asyncio.TimeoutError:
                await _send(ws, {"type": "error", "code": "too_long",
                                 "message": f"한 번에 {MAX_SECONDS}초까지 통역할 수 있어요. 다시 시작해 주세요."})
                break
            except WebSocketDisconnect:
                break
            except Exception as exc:      # noqa: BLE001 — 엔진 실패: 시작 전이면 다음 엔진으로
                log.warning("interp failed provider=%s: %s", provider, _redact(f"{type(exc).__name__}: {exc}"))
                if sess.ready:   # 통역 중에 끊김 — 화면이 이 엔진을 빼고 다시 연결한다
                    await _send(ws, {"type": "error", "code": "provider_lost", "failed": provider,
                                     "message": "통역이 끊겼어요. 다른 엔진으로 다시 연결할게요."})
                    break
                if idx + 1 < len(chain):
                    await _send(ws, {"type": "switch", "failed": provider, "next": chain[idx + 1]})
                    continue
                await _send(ws, {"type": "error", "code": "all_failed", "failed": provider,
                                 "message": "쓸 수 있는 통역 엔진이 모두 실패했어요. 아래 '검수 문장'으로 통역할 수 있어요."})
    except Exception:      # noqa: BLE001 — 이미 끊긴 연결에 보내다 실패
        pass
    finally:
        try:
            await _send(ws, {"type": "closed"})
        except Exception:         # noqa: BLE001
            pass
        try:
            await ws.close()
        except Exception:         # noqa: BLE001
            pass
