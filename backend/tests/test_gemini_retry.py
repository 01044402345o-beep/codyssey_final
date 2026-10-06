"""모델 동적 선택 + AI API 호출당 최소 30회 시도 규칙 테스트.

실행: cd backend && python -m unittest discover -s tests -t .
가짜 클라이언트로 '실제 API 요청 수'를 센다. 네트워크·API 키 없이 돈다.
"""
from __future__ import annotations

import json
import os
import unittest
from types import SimpleNamespace
from typing import Any, Callable

from fastapi.testclient import TestClient

from app import gemini as ai
from app import main


def model(name: str, actions: list[str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(name=f"models/{name}", supported_actions=actions or ["generateContent"])


DEFAULT_LIST = [model("gemini-2.5-flash"), model("gemini-2.5-pro"), model("gemini-2.5-flash-lite")]


class FakeModels:
    def __init__(self, list_fn: Callable[[int], list[Any]], gen_fn: Callable[[int, str], str]) -> None:
        self.list_fn, self.gen_fn = list_fn, gen_fn
        self.list_calls = 0
        self.gen_calls: list[str] = []

    def list(self) -> list[Any]:
        self.list_calls += 1
        return self.list_fn(self.list_calls)

    def generate_content(self, *, model: str, contents: Any, config: Any) -> SimpleNamespace:
        self.gen_calls.append(model)
        return SimpleNamespace(text=self.gen_fn(len(self.gen_calls), model))


def boom(*_: Any) -> Any:
    raise ConnectionError("network down")


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.env = dict(os.environ)
        for k in ("AI_MIN_ATTEMPTS", "GEMINI_MODEL", "AI_MODELS_TTL", "AI_COOLDOWN_BUSY"):
            os.environ.pop(k, None)
        self.sleeps: list[float] = []
        ai._sleep = self.sleeps.append
        ai.reset_cache()
        main._hits.clear()

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self.env)
        ai._sleep = __import__("time").sleep
        ai._client_factory = None
        ai.reset_cache()

    def install(self, list_fn: Callable[[int], list[Any]] = lambda _: DEFAULT_LIST,
                gen_fn: Callable[[int, str], str] = boom) -> FakeModels:
        fake = FakeModels(list_fn, gen_fn)
        ai._client_factory = lambda: SimpleNamespace(models=fake)
        return fake


class MinAttemptsTest(Base):
    def test_floor_is_30(self) -> None:
        self.assertEqual(ai.MIN_ATTEMPTS, 30)
        self.assertEqual(ai.min_attempts(), 30)

    def test_env_cannot_lower_floor(self) -> None:
        for v in ("0", "1", "5", "29", "-3", "abc", ""):
            os.environ["AI_MIN_ATTEMPTS"] = v
            self.assertEqual(ai.min_attempts(), 30, v)

    def test_env_can_raise_floor(self) -> None:
        os.environ["AI_MIN_ATTEMPTS"] = "45"
        self.assertEqual(ai.min_attempts(), 45)

    def test_always_failing_is_attempted_exactly_floor_times(self) -> None:
        calls: list[int] = []

        def fn(attempt: int) -> None:
            calls.append(attempt)
            raise RuntimeError("fail")

        with self.assertRaises(ai.AttemptsExhausted) as cm:
            ai.retry("x", fn)
        self.assertEqual(calls, list(range(1, 31)))
        self.assertEqual(cm.exception.attempts, 30)
        # 대기는 시도 사이에만: 30회 시도 → 29번
        self.assertEqual(len(self.sleeps), 29)

    def test_raised_floor_is_respected(self) -> None:
        os.environ["AI_MIN_ATTEMPTS"] = "33"
        n = 0

        def fn(_: int) -> None:
            nonlocal n
            n += 1
            raise RuntimeError("fail")

        with self.assertRaises(ai.AttemptsExhausted):
            ai.retry("x", fn)
        self.assertEqual(n, 33)

    def test_every_error_type_is_retried(self) -> None:
        errors = [ValueError, KeyError, TimeoutError, PermissionError, ConnectionError]
        n = 0

        def fn(attempt: int) -> None:
            nonlocal n
            n += 1
            raise errors[attempt % len(errors)]("x")

        with self.assertRaises(ai.AttemptsExhausted):
            ai.retry("x", fn)
        self.assertEqual(n, 30)

    def test_success_stops_immediately(self) -> None:
        n = 0

        def fn(attempt: int) -> str:
            nonlocal n
            n += 1
            if attempt < 7:
                raise RuntimeError("fail")
            return "ok"

        value, attempts, failures = ai.retry("x", fn)
        self.assertEqual((value, attempts), ("ok", 7))
        self.assertEqual(n, 7)
        self.assertEqual([f["attempt"] for f in failures], [1, 2, 3, 4, 5, 6])

    def test_success_on_30th(self) -> None:
        def fn(attempt: int) -> str:
            if attempt < 30:
                raise RuntimeError("fail")
            return "ok"

        value, attempts, failures = ai.retry("x", fn)
        self.assertEqual((value, attempts, len(failures)), ("ok", 30, 29))

    def test_every_failure_is_recorded_and_logged(self) -> None:
        def fn(attempt: int) -> None:
            raise RuntimeError("x" * 1000 if attempt == 1 else f"fail {attempt}")

        with self.assertLogs("app.gemini", "WARNING") as logs, \
                self.assertRaises(ai.AttemptsExhausted) as cm:
            ai.retry("x", fn, lambda a: f"m{a}")
        exc = cm.exception
        self.assertEqual(len(exc.failures), 30)
        self.assertEqual(exc.failures[1], {"attempt": 2, "model": "m2", "error": "RuntimeError", "detail": "fail 2"})
        self.assertLessEqual(len(exc.failures[0]["detail"]), ai.ERROR_MAX_CHARS + 1)
        self.assertEqual(exc.last_error, "RuntimeError: fail 30")
        self.assertEqual(sum("실패 model=" in line for line in logs.output), 30)


class ModelListTest(Base):
    def test_filters_and_ranks(self) -> None:
        raw = [
            model("gemini-2.0-flash"),
            model("gemini-2.5-pro"),
            model("gemini-2.5-flash-preview-09-2025"),
            model("gemini-flash-latest"),
            model("gemini-2.5-flash"),
            model("gemini-2.5-flash-lite"),
            model("gemini-embedding-001", ["embedContent"]),
            model("gemini-2.5-flash-preview-tts"),
            model("gemini-2.5-flash-image"),
            model("gemma-3-27b-it"),
            model("text-embedding-004", ["embedContent"]),
            # 실제 배포에서 목록에 나온 용도 전용 모델들
            model("gemini-nano-banana-2.1"),
            model("gemini-3.5-transcribe"),
            model("gemini-robotics-er-2-preview"),
            model("gemini-2.5-computer-use-preview-10-2025"),
            model("gemini-3.1-pro-preview-customtools"),
        ]
        self.assertEqual(ai.pick_models(raw), [
            "gemini-flash-latest", "gemini-2.5-flash", "gemini-2.0-flash",
            "gemini-2.5-flash-lite", "gemini-2.5-pro", "gemini-2.5-flash-preview-09-2025",
        ])

    def test_unversioned_family_goes_after_versioned(self) -> None:
        raw = [model("gemini-omni-1.1-flash"), model("gemini-2.5-flash"), model("gemini-flash-latest")]
        self.assertEqual(ai.pick_models(raw),
                         ["gemini-flash-latest", "gemini-2.5-flash", "gemini-omni-1.1-flash"])

    def test_preferred_model_only_if_listed(self) -> None:
        os.environ["GEMINI_MODEL"] = "gemini-2.5-pro"
        self.assertEqual(ai.pick_models(DEFAULT_LIST)[0], "gemini-2.5-pro")
        os.environ["GEMINI_MODEL"] = "gemini-retired-model"
        self.assertNotIn("gemini-retired-model", ai.pick_models(DEFAULT_LIST))

    def test_list_retries_at_least_30(self) -> None:
        fake = self.install(list_fn=boom)
        with self.assertRaises(ai.AttemptsExhausted) as cm:
            ai.available_models()
        self.assertEqual(fake.list_calls, 30)
        self.assertEqual(cm.exception.what, "models.list")

    def test_empty_list_is_failure_not_fallback(self) -> None:
        fake = self.install(list_fn=lambda _: [model("gemini-embedding-001", ["embedContent"])])
        with self.assertRaises(ai.AttemptsExhausted):
            ai.available_models()
        self.assertEqual(fake.list_calls, 30)

    def test_list_recovers_and_is_cached(self) -> None:
        fake = self.install(list_fn=lambda n: DEFAULT_LIST if n >= 12 else boom())
        self.assertEqual(ai.available_models()[0], "gemini-2.5-flash")
        self.assertEqual(fake.list_calls, 12)
        ai.available_models()
        self.assertEqual(fake.list_calls, 12)  # 캐시
        self.assertEqual(ai.cached_models(), ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro"])

    def test_run_rotates_models(self) -> None:
        fake = self.install()
        with self.assertRaises(ai.AttemptsExhausted):
            ai.run("t", lambda c, m, a: c.models.generate_content(model=m, contents="", config=None) and boom())
        self.assertEqual(len(fake.gen_calls), 30)
        self.assertEqual(fake.gen_calls[:4], [
            "gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro", "gemini-2.5-flash",
        ])


class ApiError(Exception):
    """google.genai.errors.APIError 처럼 code 를 가진 오류."""

    def __init__(self, code: int) -> None:
        super().__init__(f"{code} error")
        self.code = code


class CooldownTest(Base):
    MODELS = ["a", "b", "c", "d"]

    def install_names(self, gen_fn: Callable[[int, str], str]) -> FakeModels:
        return self.install(list_fn=lambda _: [model(f"gemini-{m}") for m in self.MODELS], gen_fn=gen_fn)

    def test_classification(self) -> None:
        self.assertEqual(ai.cooldown_for(ApiError(404))[1], "404 사용 불가")
        self.assertEqual(ai.cooldown_for(ApiError(429))[1], "429 할당량")
        self.assertEqual(ai.cooldown_for(ApiError(503))[1], "503 과부하")
        self.assertEqual(ai.cooldown_for(TimeoutError())[1], "timeout")
        self.assertIsNone(ai.cooldown_for(ValueError("빈 응답")))
        self.assertIsNone(ai.cooldown_for(main.BlockedResult("block")))
        self.assertGreater(ai.cooldown_for(ApiError(404))[0], ai.cooldown_for(ApiError(429))[0])

    def test_order_keeps_every_model(self) -> None:
        models = ["m1", "m2", "m3", "m4"]
        ai.note_failure("m1", ApiError(503))
        ai.note_failure("m2", ApiError(404))
        ai.note_success("m4")
        self.assertEqual(ai.attempt_order(models), ["m4", "m3", "m1", "m2"])

    def test_failed_models_go_last_next_request(self) -> None:
        def gen(_n: int, m: str) -> str:
            if m in ("gemini-a", "gemini-b"):
                raise ApiError(503 if m == "gemini-a" else 404)
            return json.dumps({"ok": 1})

        fake = self.install_names(gen)
        r1 = ai.run("t", lambda c, m, a: json.loads(ai_text(c, m)))
        self.assertEqual((r1.attempts, r1.model), (3, "gemini-c"))
        fake.gen_calls.clear()
        r2 = ai.run("t", lambda c, m, a: json.loads(ai_text(c, m)))
        self.assertEqual((r2.attempts, r2.model), (1, "gemini-c"))   # 마지막 성공 모델부터
        h = ai.model_health()
        self.assertEqual(h["last_good"], "gemini-c")
        self.assertEqual(h["cooling"]["gemini-b"]["reason"], "404 사용 불가")

    def test_all_cooling_still_30_attempts(self) -> None:
        for m in self.MODELS:
            ai.note_failure(f"gemini-{m}", ApiError(429))
        fake = self.install_names(lambda *_: (_ for _ in ()).throw(ApiError(503)))
        with self.assertRaises(ai.AttemptsExhausted) as cm:
            ai.run("t", lambda c, m, a: ai_text(c, m))
        self.assertEqual(cm.exception.attempts, 30)
        self.assertEqual(len(fake.gen_calls), 30)
        self.assertEqual(set(fake.gen_calls), {f"gemini-{m}" for m in self.MODELS})

    def test_cooldown_expires(self) -> None:
        os.environ["AI_COOLDOWN_BUSY"] = "0"
        ai.note_failure("m1", ApiError(503))
        self.assertEqual(ai.attempt_order(["m1", "m2"]), ["m1", "m2"])


def ai_text(client: Any, m: str) -> str:
    return client.models.generate_content(model=m, contents="", config=None).text


GOOD_PACK = {
    "category_id": "restaurant",
    "city": "New York",
    "sentences": [],
}


class EndpointTest(Base):
    def setUp(self) -> None:
        super().setUp()
        os.environ["GEMINI_API_KEY"] = "test-key"
        self.http = TestClient(main.app)
        cfg = main.load_category("restaurant")
        GOOD_PACK["sentences"] = [dict(e, place_type="restaurant") for e in cfg["good_examples"]]

    def body(self) -> dict[str, Any]:
        return {"category_id": "restaurant", "city": "New York",
                "places": [{"name": "Katz's Delicatessen", "place_type": "restaurant"}]}

    def test_generate_api_error_tried_30_times(self) -> None:
        fake = self.install(gen_fn=boom)
        d = self.http.post("/generate", json=self.body()).json()
        self.assertEqual(len(fake.gen_calls), 30)
        self.assertEqual(d["attempts"], 30)
        self.assertEqual(d["usable"], "rejected")
        self.assertTrue(d["degraded"])
        self.assertEqual(len(d["failures"]), 30)
        self.assertEqual(d["failures"][0]["error"], "ConnectionError")

    def test_generate_bad_json_tried_30_times(self) -> None:
        fake = self.install(gen_fn=lambda *_: "not json")
        d = self.http.post("/generate", json=self.body()).json()
        self.assertEqual(len(fake.gen_calls), 30)
        self.assertEqual(d["attempts"], 30)

    def test_generate_blocked_result_tried_30_times(self) -> None:
        bad = dict(GOOD_PACK, category_id="transport")  # category_mismatch → block
        fake = self.install(gen_fn=lambda *_: json.dumps(bad))
        d = self.http.post("/generate", json=self.body()).json()
        self.assertEqual(len(fake.gen_calls), 30)
        self.assertEqual(d["usable"], "rejected")
        self.assertEqual({f["error"] for f in d["failures"]}, {"BlockedResult"})
        self.assertIn("category_mismatch", d["failures"][0]["detail"])

    def test_generate_success_after_failures(self) -> None:
        fake = self.install(gen_fn=lambda n, _m: json.dumps(GOOD_PACK) if n == 4 else "oops")
        d = self.http.post("/generate", json=self.body()).json()
        self.assertEqual(len(fake.gen_calls), 4)
        self.assertEqual(d["attempts"], 4)
        self.assertEqual(d["usable"], "ok")
        self.assertEqual(d["model"], fake.gen_calls[-1])
        self.assertEqual([f["model"] for f in d["failures"]], fake.gen_calls[:3])
        self.assertEqual({f["error"] for f in d["failures"]}, {"ValueError"})

    def test_generate_model_list_failure(self) -> None:
        fake = self.install(list_fn=boom)
        d = self.http.post("/generate", json=self.body()).json()
        self.assertEqual(fake.list_calls, 30)
        self.assertEqual(fake.gen_calls, [])
        self.assertEqual(d["failed_at"], "models.list")
        self.assertEqual(d["attempts"], 0)

    def speak(self) -> dict[str, Any]:
        r = self.http.post("/speak-check", data={"target": "Hello."},
                           files={"file": ("a.webm", b"\x00" * 100, "audio/webm")})
        return r.json()

    def test_speak_error_tried_30_times(self) -> None:
        fake = self.install(gen_fn=boom)
        d = self.speak()
        self.assertEqual(len(fake.gen_calls), 30)
        self.assertEqual(d["attempts"], 30)
        self.assertFalse(d["usable"])

    def test_speak_success_after_failures(self) -> None:
        # 9번째에 받아쓰기 성공 → 10번째 호출은 피드백(글만). 같은 JSON 이 두 역할을 다 채운다.
        ok = json.dumps({"heard": "Hello.", "fix_one": "좋아요", "tip": "또 말해 봐요"})
        fake = self.install(gen_fn=lambda n, _m: ok if n >= 9 else "")
        d = self.speak()
        self.assertEqual(len(fake.gen_calls), 10)
        self.assertEqual(d["attempts"], 9)
        self.assertEqual(d["heard"], "Hello.")
        self.assertEqual(d["score"], 100)                  # 목표 'Hello.' 와 같음 — 코드 판정
        self.assertEqual(len(d["failures"]), 8)
        self.assertEqual(d["feedback"]["attempts"], 1)

    def test_health_reports_dynamic_selection(self) -> None:
        d = self.http.get("/health").json()
        self.assertEqual(d["model_selection"], "dynamic")
        self.assertEqual(d["min_attempts"], 30)
        self.assertNotIn("model", d)
        self.assertEqual(d["model_health"], {"last_good": None, "cooling": {}})


if __name__ == "__main__":
    unittest.main()
