"""Azure Speech 엔진: 실제 SDK 로 설정·연결 실패 경로를 돈다(키·네트워크 없이).

닫힌 로컬 포트를 엔드포인트로 주면 SDK 가 연결에 실패하고 canceled 이벤트를 낸다.
그 사이 우리 코드가 쓰는 SDK API(설정 인자·속성 이름·이벤트·비동기 시작/정지)가 실제로 있는지 확인된다.
SDK 를 불러올 수 없는 환경(리눅스 의존 라이브러리 없음 등)에서는 건너뛰고, 대신 '사용 불가' 처리만 본다.
실행: cd backend && python -m unittest tests.test_interp_azure
"""
import os
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from app import firebase_auth, interp, main

try:
    import azure.cognitiveservices.speech  # noqa: F401
    SDK = True
except Exception:      # noqa: BLE001
    SDK = False

ENV = {"INTERP_PROVIDERS": "azure", "INTERP_PROVIDER": "", "AZURE_SPEECH_KEY": "test-key",
       "AZURE_SPEECH_REGION": "koreacentral", "AZURE_SPEECH_ENDPOINT": "wss://127.0.0.1:9/speech/universal/v2"}


class T(unittest.TestCase):
    def setUp(self):
        interp._starts.clear()

    def test_locales_for_language_identification(self):
        self.assertEqual(interp.AZURE_LOCALES, {"ko": "ko-KR", "en": "en-US"})

    def test_unavailable_without_region_or_allowlist(self):
        with mock.patch.dict(os.environ, {**ENV, "AZURE_SPEECH_REGION": ""}):
            self.assertFalse(interp.provider_available("azure"))
        with mock.patch.dict(os.environ, {**ENV, "INTERP_PROVIDERS": "soniox"}):
            self.assertFalse(interp.provider_available("azure"))

    @unittest.skipUnless(SDK, "Azure Speech SDK 를 불러올 수 없는 환경")
    def test_real_sdk_connect_failure_is_reported(self):
        with mock.patch.dict(os.environ, ENV), \
             mock.patch.object(firebase_auth, "verify_bearer", return_value={"uid": "u1", "provider": "google.com"}):
            self.assertTrue(interp.provider_available("azure"))
            with TestClient(main.app).websocket_connect("/interp/stream") as ws:
                ws.send_json({"type": "start", "a": "ko", "b": "en", "token": "x", "provider": "azure"})
                first = ws.receive_json()
                self.assertEqual(first.get("provider"), "azure", first)
                ws.send_bytes(b"\x00\x00" * 1600)
                seen = []
                for _ in range(10):
                    m = ws.receive_json()
                    seen.append(m)
                    if m["type"] in ("error", "closed"):
                        break
        self.assertTrue(any(m.get("type") == "error" for m in seen), seen)


if __name__ == "__main__":
    unittest.main()
