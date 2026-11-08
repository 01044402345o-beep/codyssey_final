"""hosting_deploy — 네트워크 없이. 실행: python -m unittest discover -s .github/scripts -p "test_hosting_deploy.py" """
import gzip
import hashlib
import io
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hosting_deploy as hd  # noqa: E402

REPO = Path(__file__).resolve().parents[2]

FIREBASE_JSON = {
    "firestore": [{"rules": "firestore.rules"}],
    "hosting": {
        "public": "web",
        "ignore": ["firebase.json", "**/.*", "**/node_modules/**", "**/*.py", "**/*.map"],
        "cleanUrls": False,
        "headers": [{"source": "/app.js", "headers": [{"key": "Cache-Control", "value": "no-cache"}]}],
    },
}


def make_site(tmp: Path, hosting: dict | None = None) -> Path:
    cfg = dict(FIREBASE_JSON)
    if hosting is not None:
        cfg["hosting"] = hosting
    (tmp / "firebase.json").write_text(json.dumps(cfg), encoding="utf-8")
    web = tmp / "web"
    for rel, body in {"index.html": b"<html>", "app.js": b"let a=1", "sub/x.js": b"x",
                      ".hidden": b"h", "tool.py": b"p", "a.js.map": b"m", "node_modules/k/i.js": b"n",
                      "sub/.env": b"e"}.items():
        p = web / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body)
    return tmp


class Res(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeApi:
    """Hosting REST API 흉내. 호출을 기록하고, populateFiles 에서는 일부 해시만 올리라고 한다."""

    def __init__(self, already_have: set[str] | None = None):
        self.calls = []
        self.uploaded = {}
        self.manifest = {}
        self.already = already_have or set()
        self.version_body = None

    def __call__(self, req, timeout=0):
        url, method, body = req.full_url, req.get_method(), req.data
        self.calls.append((method, url.split("?")[0]))
        assert req.get_header("Authorization") == "Bearer tok"
        if method == "POST" and url.endswith("/versions"):
            self.version_body = json.loads(body)
            return Res(json.dumps({"name": "sites/s1/versions/abc123"}).encode())
        if url.endswith(":populateFiles") and "upload" not in url:
            self.manifest = json.loads(body)["files"]
            need = [h for h in self.manifest.values() if h not in self.already]
            return Res(json.dumps({"uploadRequiredHashes": need, "uploadUrl": "https://upload.example/v"}).encode())
        if url.startswith("https://upload.example/v/"):
            self.uploaded[url.rsplit("/", 1)[1]] = body
            return Res(b"")
        if method == "PATCH":
            assert json.loads(body) == {"status": "FINALIZED"}
            return Res(b"{}")
        if "releases" in url:
            return Res(b"{}")
        raise AssertionError("예상하지 못한 호출 " + url)


class GlobTest(unittest.TestCase):
    def test_firebase_ignore_패턴(self):
        rx = [hd.glob_regex(p) for p in FIREBASE_JSON["hosting"]["ignore"]]
        ignored = lambda p: any(r.match(p) for r in rx)  # noqa: E731
        for p in [".hidden", "sub/.env", "tool.py", "a/b/c.py", "a.js.map", "node_modules/k/i.js", "firebase.json"]:
            self.assertTrue(ignored(p), p)
        for p in ["app.js", "sub/x.js", "index.html", "a/firebase.json.txt"]:
            self.assertFalse(ignored(p), p)


class ListAndConfigTest(unittest.TestCase):
    def test_올릴_파일만_고른다(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_site(Path(d))
            self.assertEqual(hd.list_files(root, hd.load_hosting(root)), ["/app.js", "/index.html", "/sub/x.js"])

    def test_헤더는_glob_으로_옮기고_기본값은_빼다(self):
        conf = hd.version_config(FIREBASE_JSON["hosting"])
        self.assertEqual(conf, {"headers": [{"glob": "/app.js", "headers": {"Cache-Control": "no-cache"}}]})

    def test_옮기지_못하는_설정은_거부한다(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_site(Path(d), {**FIREBASE_JSON["hosting"], "rewrites": [{"source": "**", "run": {"serviceId": "x"}}]})
            with self.assertRaises(hd.DeployError):
                hd.load_hosting(root)

    def test_저장소_firebase_json_을_옮길_수_있다(self):
        """실제 저장소 설정에 이 스크립트가 모르는 키가 생기면 여기서 깨진다(배포가 조용히 빠뜨리지 않게)."""
        hosting = hd.load_hosting(REPO)
        files = hd.list_files(REPO, hosting)
        self.assertIn("/index.html", files)
        self.assertIn("/app.js", files)
        self.assertFalse(any(f.endswith(".py") or "/." in f for f in files))


class DeployTest(unittest.TestCase):
    def test_필요한_해시만_올리고_확정한_뒤_live_에_릴리스한다(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_site(Path(d))
            have = hashlib.sha256(gzip.compress(b"<html>", mtime=0)).hexdigest()
            api = FakeApi(already_have={have})
            name = hd.deploy(root, "s1", "live", "tok", opener=api, label="ABC123def")
            self.assertEqual(name, "sites/s1/versions/abc123")
            self.assertEqual(sorted(api.manifest), ["/app.js", "/index.html", "/sub/x.js"])
            self.assertEqual(len(api.uploaded), 2)                          # index.html 은 이미 있다
            for digest, body in api.uploaded.items():
                self.assertEqual(hashlib.sha256(body).hexdigest(), digest)  # 올린 바이트 = 해시
                gzip.decompress(body)
            self.assertEqual(api.version_body["labels"]["commit"], "abc123def")
            methods = [m for m, _ in api.calls]
            self.assertLess(methods.index("PATCH"), len(methods) - 1)      # 확정 뒤에 릴리스
            self.assertTrue(api.calls[-1][1].endswith("/sites/s1/releases"))

    def test_미리보기_채널로_릴리스(self):
        with tempfile.TemporaryDirectory() as d:
            api = FakeApi()
            hd.deploy(make_site(Path(d)), "s1", "preview-1", "tok", opener=api)
            self.assertTrue(api.calls[-1][1].endswith("/sites/s1/channels/preview-1/releases"))

    def test_API_오류는_DeployError(self):
        def boom(req, timeout=0):
            raise urllib.error.HTTPError(req.full_url, 403, "no", {}, io.BytesIO(b"PERMISSION_DENIED"))
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(hd.DeployError) as ctx:
                hd.deploy(make_site(Path(d)), "s1", "live", "tok", opener=boom)
            self.assertIn("403", str(ctx.exception))
            self.assertNotIn("tok", str(ctx.exception))


class DriftTest(unittest.TestCase):
    def _opener(self, served: dict):
        def op(req, timeout=0):
            path = req.full_url.split("example.app", 1)[1]
            if path not in served:
                raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, io.BytesIO(b""))
            return Res(served[path])
        return op

    def test_같으면_빈_목록_다르거나_없으면_그_파일(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_site(Path(d))
            same = {"/app.js": b"let a=1", "/index.html": b"<html>", "/sub/x.js": b"x"}
            self.assertEqual(hd.drift(root, "https://example.app", self._opener(same)), [])
            changed = {**same, "/app.js": b"let a=1\r\n"}
            changed.pop("/sub/x.js")
            self.assertEqual(hd.drift(root, "https://example.app", self._opener(changed)), ["/app.js", "/sub/x.js"])


if __name__ == "__main__":
    unittest.main()
