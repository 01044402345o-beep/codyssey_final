"""보안 헤더 (ZAP 2026-10-16 스캔 대응).  실행: cd backend && python -m unittest discover -s tests -t .

ZAP 가 운영(Render)에서 잡은 것: CSP 없음 · 클릭재킹 헤더 없음 · HSTS 없음 · nosniff 없음 · Cache-Control 없음 ·
외부 스타일시트 SRI 없음. 이 테스트는 정적 화면과 API 응답 모두에 헤더가 붙는지, CSP 가 앱을 깨지 않는 모양인지 본다
(실제 브라우저 위반 검사는 e2e/test_csp.py)."""
import os
import re
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from app import main, security_headers as sh

ROOT = Path(__file__).resolve().parents[2]


def csp_dict(value):
    out = {}
    for part in value.split(";"):
        words = part.split()
        if words:
            out[words[0]] = words[1:]
    return out


class SecurityHeaders(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)

    def get(self, path, **env):
        with mock.patch.dict(os.environ, env):
            return self.client.get(path)

    def test_every_response_has_baseline_headers(self):
        for path in ("/", "/app.js", "/styles.css", "/health", "/auth/config", "/no-such-file.js"):
            r = self.get(path)
            with self.subTest(path=path):
                self.assertEqual(r.headers.get("x-content-type-options"), "nosniff")
                self.assertEqual(r.headers.get("x-frame-options"), "DENY")
                self.assertEqual(r.headers.get("strict-transport-security"), "max-age=31536000")
                self.assertEqual(r.headers.get("referrer-policy"), "strict-origin-when-cross-origin")
                self.assertIn("microphone=(self)", r.headers.get("permissions-policy", ""))   # 말하기·통역 녹음

    def test_hsts_does_not_claim_the_shared_parent_domain(self):
        # onrender.com 은 우리 도메인이 아니다 — includeSubDomains·preload 를 넣지 않는다
        hsts = self.get("/").headers["strict-transport-security"]
        self.assertNotIn("includeSubDomains", hsts)
        self.assertNotIn("preload", hsts)

    def test_csp_blocks_inline_script_eval_framing_and_plugins(self):
        c = csp_dict(self.get("/").headers["content-security-policy"])
        self.assertNotIn("'unsafe-inline'", c["script-src"])
        self.assertNotIn("'unsafe-eval'", c["script-src"])
        self.assertEqual(c["frame-ancestors"], ["'none'"])
        self.assertEqual(c["object-src"], ["'none'"])
        self.assertEqual(c["base-uri"], ["'self'"])
        self.assertEqual(c["default-src"], ["'self'"])

    def test_csp_allows_what_the_app_loads(self):
        c = csp_dict(self.get("/", FIREBASE_AUTH_DOMAIN="demo-proj.firebaseapp.com").headers["content-security-policy"])
        self.assertIn("https://www.gstatic.com", c["script-src"])          # Firebase SDK 동적 import
        self.assertIn("https://apis.google.com", c["script-src"])          # 구글 팝업 로그인(gapi)
        self.assertIn("https://fonts.googleapis.com", c["style-src"])
        self.assertIn("https://cdn.jsdelivr.net", c["style-src"])
        self.assertIn("https://fonts.gstatic.com", c["font-src"])
        self.assertIn("blob:", c["media-src"])                             # 내 발음 다시 듣기
        self.assertIn("blob:", c["connect-src"])                           # 녹음 blob 다시 읽기
        self.assertIn("https://identitytoolkit.googleapis.com", c["connect-src"])
        self.assertIn("https://securetoken.googleapis.com", c["connect-src"])
        self.assertIn("wss://testserver", c["connect-src"])                # 같은 출처 통역 스트림
        self.assertEqual(c["frame-src"], ["https://demo-proj.firebaseapp.com"])   # signInWithPopup 의 숨은 iframe

    def test_interp_ws_on_another_host_is_allowed(self):
        c = csp_dict(self.get("/", INTERP_WS_URL="wss://codyssey-api-abc.a.run.app/interp/stream").headers["content-security-policy"])
        self.assertIn("wss://codyssey-api-abc.a.run.app", c["connect-src"])

    def test_no_auth_domain_means_no_frames(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FIREBASE_AUTH_DOMAIN", None)
            c = csp_dict(self.client.get("/").headers["content-security-policy"])
        self.assertEqual(c["frame-src"], ["'none'"])

    def test_csp_mode_switch(self):
        r = self.get("/", CSP_MODE="report")
        self.assertNotIn("content-security-policy", r.headers)
        self.assertIn("content-security-policy-report-only", r.headers)
        r = self.get("/", CSP_MODE="off")
        self.assertNotIn("content-security-policy", r.headers)
        self.assertNotIn("content-security-policy-report-only", r.headers)
        self.assertEqual(r.headers.get("x-frame-options"), "DENY")       # CSP 를 꺼도 나머지는 그대로
        self.assertIn("content-security-policy", self.get("/", CSP_MODE="bogus").headers)   # 모르는 값 → 기본(enforce)

    def test_swagger_docs_are_exempt_from_csp(self):
        r = self.get("/docs")
        self.assertNotIn("content-security-policy", r.headers)

    def test_cache_control(self):
        self.assertEqual(self.get("/").headers.get("cache-control"), "no-cache")
        self.assertEqual(self.get("/app.js").headers.get("cache-control"), "no-cache")
        self.assertEqual(self.get("/user/state").headers.get("cache-control"), "no-store")
        self.assertEqual(self.get("/auth/me").headers.get("cache-control"), "no-store")      # 계정 이메일

    def test_host_header_cannot_inject_csp_directives(self):
        bad = sh.build_csp("evil.example; script-src *")
        self.assertNotIn("script-src *", bad)
        self.assertNotIn("evil.example", bad)
        self.assertIn("wss://codyssey-final.onrender.com", sh.build_csp("codyssey-final.onrender.com"))

    def test_index_has_no_inline_scripts_and_boot_js_exists(self):
        html = (ROOT / "mockup" / "index.html").read_text(encoding="utf-8")
        inline = [m for m in re.finditer(r"<script(?![^>]*\bsrc=)[^>]*>", html)]
        self.assertEqual(inline, [], "인라인 <script> 가 생기면 CSP 가 막는다 — boot.js 같은 파일로")
        self.assertNotRegex(html, r"\son[a-z]+=", "인라인 이벤트 핸들러(onclick= 등)도 CSP 가 막는다")
        self.assertTrue((ROOT / "mockup" / "boot.js").is_file())
        # boot.js 는 스타일시트보다 먼저(첫 그림 전에 테마·모드를 정한다)
        self.assertLess(html.index('src="boot.js"'), html.index('rel="stylesheet"'))

    def test_pinned_cdn_stylesheet_has_sri(self):
        html = (ROOT / "mockup" / "index.html").read_text(encoding="utf-8")
        tag = re.search(r'<link[^>]+pretendard@v[\d.]+[^>]+>', html).group(0)
        self.assertRegex(tag, r'integrity="sha384-[A-Za-z0-9+/=]{64}"')
        self.assertIn('crossorigin="anonymous"', tag)


if __name__ == "__main__":
    unittest.main()
