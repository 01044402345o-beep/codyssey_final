"""index.html 의 스크립트·스타일 주소에 파일 내용 해시가 붙는다 — 배포 직후 새 JS 와 옛 CSS 가 섞이지 않게.

실행: cd backend && python -m unittest tests.test_asset_versioning
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from app import main

REF = re.compile(r'(?:src|href)="([A-Za-z0-9_.-]+\.(?:js|css))(\?v=[0-9a-f]{10})?"')


class AssetVersioningTest(unittest.TestCase):
    def setUp(self):
        self.c = TestClient(main.app)

    def test_every_local_script_and_style_is_versioned_by_content(self):
        r = self.c.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers.get("cache-control"), "no-cache")
        refs = REF.findall(r.text)
        names = {n for n, _ in refs}
        self.assertTrue({"styles.css", "app.js", "ai.js", "boot.js"} <= names, names)
        for name, v in refs:
            self.assertTrue(v, f"{name} 에 ?v= 가 없다")
            want = hashlib.sha256((main.WEB_DIR / name).read_bytes()).hexdigest()[:10]
            self.assertEqual(v, f"?v={want}", name)

    def test_index_html_path_is_the_same_page(self):
        self.assertEqual(self.c.get("/index.html").text, self.c.get("/").text)

    def test_versioned_url_is_served(self):
        name, v = next((n, v) for n, v in REF.findall(self.c.get("/").text) if n == "styles.css")
        r = self.c.get(f"/{name}{v}")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/css", r.headers["content-type"])

    def test_external_and_non_asset_refs_untouched(self):
        html = self.c.get("/").text
        self.assertIn('href="manifest.json"', html)                 # json 은 대상이 아니다
        self.assertNotIn("googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400..700;1,9..144,400..700&family=JetBrains+Mono:wght@400;500;700&display=swap?v=", html)

    def test_hash_changes_when_file_changes(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            (tmp / "index.html").write_text('<link href="styles.css"><script src="app.js"></script>', encoding="utf-8")
            (tmp / "styles.css").write_text("a{}", encoding="utf-8")
            (tmp / "app.js").write_text("1", encoding="utf-8")
            with mock.patch.object(main, "WEB_DIR", tmp), mock.patch.dict(main._index_cache, {"key": None, "html": None}):
                first = main.versioned_index_html()
                css_v1 = re.search(r'styles\.css\?v=(\w+)', first).group(1)
                js_v1 = re.search(r'app\.js\?v=(\w+)', first).group(1)
                (tmp / "styles.css").write_text("a{color:red}", encoding="utf-8")
                st = (tmp / "styles.css").stat()
                os.utime(tmp / "styles.css", ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000))
                second = main.versioned_index_html()
                self.assertNotEqual(re.search(r'styles\.css\?v=(\w+)', second).group(1), css_v1)
                self.assertEqual(re.search(r'app\.js\?v=(\w+)', second).group(1), js_v1)   # 안 바뀐 파일은 그대로
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
