"""Gemini API 키 여러 개: 주 키가 막히면 예비 키로, 주 키가 풀리면 되돌아온다(롤백).

실행: cd backend && python -m unittest tests.test_gemini_keys
가짜 클라이언트로 '어느 키로 몇 번 요청했는지'를 센다. 네트워크·실제 키 없이 돈다.
"""
from __future__ import annotations

import json
import os
import unittest
from types import SimpleNamespace
from typing import Any
from unittest import mock

from app import gemini as ai
from app import main

LIST = [SimpleNamespace(name="models/gemini-2.5-flash", supported_actions=["generateContent"]),
        SimpleNamespace(name="models/gemini-2.5-pro", supported_actions=["generateContent"])]


class ApiErr(Exception):
    def __init__(self, code: int, msg: str) -> None:
        super().__init__(msg)
        self.code = code


BAD_KEY = ApiErr(400, "400 INVALID_ARGUMENT. API key not valid. Please pass a valid API key.")
LEAKED = ApiErr(403, "403 PERMISSION_DENIED. Your API key was reported as leaked.")
QUOTA = ApiErr(429, "429 RESOURCE_EXHAUSTED. Quota exceeded for metric generate_content_free_tier_requests per minute")
DAILY = ApiErr(429, "429 RESOURCE_EXHAUSTED. Quota exceeded: GenerateRequestsPerDayPerProjectPerModel")


class KeyWorld:
    """키 → 가짜 클라이언트. fail[key] 가 있으면 그 키로 하는 모든 호출이 그 오류로 실패한다."""

    def __init__(self) -> None:
        self.fail: dict[str, Exception] = {}
        self.calls: list[tuple[str, str]] = []   # (키, 'list'|모델)

    def client(self, key: str) -> Any:
        world = self

        class Models:
            def list(self) -> Any:
                world.calls.append((key, "list"))
                if key in world.fail:
                    raise world.fail[key]
                return iter(LIST)

            def generate_content(self, *, model: str, contents: Any, config: Any) -> Any:
                world.calls.append((key, model))
                if key in world.fail:
                    raise world.fail[key]
                return SimpleNamespace(text=json.dumps({"ok": key}))

        return SimpleNamespace(models=Models())


def gen(client: Any, model: str, _attempt: int) -> str:
    return json.loads(client.models.generate_content(model=model, contents="", config=None).text)["ok"]


class T(unittest.TestCase):
    def setUp(self) -> None:
        self.env = dict(os.environ)
        for k in ("AI_MIN_ATTEMPTS", "GEMINI_MODEL", "AI_MODELS_TTL", "AI_KEY_COOLDOWN_BAD",
                  "AI_KEY_COOLDOWN_QUOTA", "AI_KEY_COOLDOWN_DAILY"):
            os.environ.pop(k, None)
        os.environ["GEMINI_API_KEY"] = "primary-secret"
        os.environ["GEMINI_API_KEY_FALLBACK"] = "backup-secret"
        ai._sleep = lambda _s: None
        ai.reset_cache()
        self.w = KeyWorld()
        ai._key_client_factory = self.w.client

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self.env)
        ai._sleep = __import__("time").sleep
        ai._key_client_factory = None
        ai.reset_cache()

    def test_keys_from_env(self):
        os.environ["GEMINI_API_KEY_FALLBACK"] = " b1 , ,primary-secret, b2"
        self.assertEqual(ai.api_keys(), ["primary-secret", "b1", "b2"])   # 빈 값·중복 제거, 순서 유지

    def test_single_key_has_no_rotation(self):
        os.environ.pop("GEMINI_API_KEY_FALLBACK")
        self.assertNotIsInstance(ai.make_client(), ai.KeyRotatingClient)

    def test_healthy_primary_is_used(self):
        r = ai.run("t", gen)
        self.assertEqual(r.value, "primary-secret")
        self.assertTrue(all(k == "primary-secret" for k, _ in self.w.calls))

    def test_invalid_primary_falls_back_without_cooling_models(self):
        self.w.fail["primary-secret"] = BAD_KEY
        r = ai.run("t", gen)
        self.assertEqual(r.value, "backup-secret")
        self.assertEqual(self.w.calls[0], ("primary-secret", "list"))   # 목록 조회도 키를 바꿔 이어 간다
        self.assertEqual(ai.model_health()["cooling"], {})               # 키 거부는 모델 탓이 아니다
        self.assertIn("주 키", ai.key_health()["cooling"])

    def test_rollback_to_primary_after_cooldown(self):
        self.w.fail["primary-secret"] = LEAKED
        self.assertEqual(ai.run("t", gen).value, "backup-secret")
        self.assertEqual(ai.key_health()["active"], "예비 키 1")
        self.w.fail.clear()                                    # 주 키가 다시 쓸 수 있게 됨
        self.assertEqual(ai.run("t", gen).value, "backup-secret")   # 쿨다운 중에는 예비 키 유지
        later = __import__("time").time() + 3601
        with mock.patch.object(ai.time, "time", return_value=later), self.assertLogs("app.gemini", "WARNING") as lg:
            self.assertEqual(ai.run("t", gen).value, "primary-secret")
        self.assertEqual(ai.key_health()["active"], "주 키")
        self.assertTrue(any("롤백" in m for m in lg.output))

    def test_quota_cooldowns(self):
        self.assertEqual(ai.key_cooldown_for(QUOTA)[0], 120.0)
        self.assertEqual(ai.key_cooldown_for(DAILY)[0], 3600.0)
        self.assertIsNone(ai.key_cooldown_for(ApiErr(503, "overloaded")))      # 과부하는 키를 바꾸지 않는다
        self.assertIsNone(ai.key_cooldown_for(ApiErr(403, "model access denied")))   # 'API key' 문구 없는 403 은 모델 탓
        self.w.fail["primary-secret"] = QUOTA
        self.assertEqual(ai.run("t", gen).value, "backup-secret")

    def test_all_keys_down_still_tries_min_attempts(self):
        self.w.fail = {"primary-secret": BAD_KEY, "backup-secret": BAD_KEY}
        with self.assertRaises(ai.AttemptsExhausted) as cm:
            ai.run("t", gen)
        self.assertGreaterEqual(cm.exception.attempts, ai.MIN_ATTEMPTS)   # 30회 규칙은 키가 다 막혀도 그대로
        used = {k for k, _ in self.w.calls}
        self.assertEqual(used, {"primary-secret", "backup-secret"})

    def test_health_never_shows_key_values(self):
        self.w.fail["primary-secret"] = BAD_KEY
        ai.run("t", gen)
        from fastapi.testclient import TestClient
        body = TestClient(main.app).get("/health").text
        self.assertNotIn("primary-secret", body)
        self.assertNotIn("backup-secret", body)
        h = json.loads(body)["gemini_keys"]
        self.assertEqual(h["count"], 2)
        self.assertEqual(h["active"], "예비 키 1")


if __name__ == "__main__":
    unittest.main()
