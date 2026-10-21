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

환경 변수: INTERP_PROVIDER(soniox|openai|fake), SONIOX_API_KEY, OPENAI_API_KEY, INTERP_ALLOW_FAKE, INTERP_MAX_SECONDS
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time

from fastapi import WebSocket, WebSocketDisconnect

log = logging.getLogger("interp")

SONIOX_URL = "wss://stt-rt.soniox.com/transcribe-websocket"
OPENAI_URL = "wss://api.openai.com/v1/realtime/translations?model=gpt-realtime-translate"
MAX_SECONDS = int(os.getenv("INTERP_MAX_SECONDS", "180") or 180)   # 한 세션 상한(비용·악용 방지)
MAX_BYTES = 16_000 * 2 * MAX_SECONDS                              # 16 kHz 16-bit


def provider_choice() -> str:
    """쓸 수 있는 제공자를 고른다. 키가 없으면 'none' — 화면은 그대로 '지금은 못 쓴다'고 말한다."""
    want = (os.getenv("INTERP_PROVIDER") or "").strip().lower()
    if want in ("soniox", "openai", "fake"):
        if want == "soniox" and not (os.getenv("SONIOX_API_KEY") or "").strip():
            return "none"
        if want == "openai" and not (os.getenv("OPENAI_API_KEY") or "").strip():
            return "none"
        if want == "fake" and os.getenv("INTERP_ALLOW_FAKE") != "1":
            return "none"
        return want
    if (os.getenv("SONIOX_API_KEY") or "").strip():
        return "soniox"
    if (os.getenv("OPENAI_API_KEY") or "").strip():
        return "openai"
    if os.getenv("INTERP_ALLOW_FAKE") == "1":
        return "fake"
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


class _Session:
    def __init__(self, ws: WebSocket, provider: str, a: str, b: str):
        self.ws = ws
        self.provider = provider
        self.a, self.b = a, b
        self.started = time.monotonic()
        self.bytes_in = 0
        self.closed = False

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
            await _send(self.ws, {"type": "ready", "provider": "soniox", "pair": [self.a, self.b], "audio_out": False})

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
            await _send(self.ws, {"type": "ready", "provider": "openai", "pair": [self.a, self.b], "audio_out": True})
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
        await _send(self.ws, {"type": "ready", "provider": "fake", "pair": [self.a, self.b], "audio_out": False, "test": True})
        lines = [("Where is the train station?", "기차역이 어디예요?"),
                 ("It's about five minutes on foot.", "걸어서 5분쯤 걸려요.")]
        frames = [0]

        async def to_provider(data: bytes) -> None:
            frames[0] += 1
            if frames[0] % 12:            # 100 ms 프레임 12개마다 한 줄
                return
            i = (frames[0] // 12 - 1) % len(lines)
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


async def serve(ws: WebSocket) -> None:
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

    provider = provider_choice()
    if first.get("provider") == "fake" and provider != "fake":
        provider = provider_choice()
    if provider == "none":
        await _send(ws, {"type": "error", "code": "no_key",
                         "message": "서버에 통역 서비스 키가 없어 지금은 실시간 통역을 쓸 수 없어요. 운영자에게 문의해 주세요."})
        await ws.close()
        return

    a = str(first.get("a") or "ko")[:5]
    b = str(first.get("b") or "en")[:5]
    sess = _Session(ws, provider, a, b)
    log.info("interp start provider=%s pair=%s", provider, (a, b))
    try:
        if provider == "soniox":
            await sess.run_soniox()
        elif provider == "openai":
            await sess.run_openai()
        else:
            await sess.run_fake()
    except WebSocketDisconnect:
        pass
    except Exception as exc:      # noqa: BLE001 — 제공자 연결 실패는 사용자에게 상태로 알린다
        log.warning("interp failed: %s", exc)
        try:
            await _send(ws, {"type": "error", "code": "provider",
                             "message": "통역 서비스에 연결하지 못했어요. 잠시 뒤 다시 시도해 주세요."})
        except Exception:         # noqa: BLE001
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
