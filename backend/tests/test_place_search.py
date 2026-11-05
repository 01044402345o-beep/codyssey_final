"""장소 직접 추가·장소 생성 하루 한도(11/05) — 네트워크 없음.

- POST /research(장소 생성 요청)는 사용자/IP 당 하루 PLACE_SEARCH_DAILY_LIMIT 번(기본 3). 넘으면 429 + 안내.
  서버가 바빠 거절(503)·조사 꺼짐(unavailable)·오류는 세지 않는다. 0 이면 제한 없음. /place-check 는 세지 않는다.
- /place-check 결과에 확인 창용 주소·사진(위키미디어 공용 썸네일)을 붙인다.
- GET /place-photo 는 upload.wikimedia.org 의 이미지 파일만 서버가 받아 내보낸다.
- 확인된 주소는 문장 생성 프롬프트의 사실(USER_CONFIRMED_PLACES)로만 들어간다.
"""
import os
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from app import main, place_quota
from app.research import net, place_check

BODY = {"countries": [{"name": "일본", "iso2": "JP"}],
        "cities": [{"name": "나라", "ci": 0, "start": "2026-12-01", "end": "2026-12-03", "attr": 2, "rest": 2}]}
RUNNING = {"status": "running", "job_id": "a" * 20, "progress": []}


class QuotaTest(unittest.TestCase):
    def setUp(self):
        place_quota.clear()
        main._hits.clear()
        self.http = TestClient(main.app)

    def post(self, headers=None):
        return self.http.post("/research", json=BODY, headers=headers or {})

    @mock.patch.dict(os.environ, {"PLACE_SEARCH_DAILY_LIMIT": ""})
    def test_default_three_per_day_then_429_with_message(self):
        with mock.patch.object(main.research, "submit", return_value=dict(RUNNING)):
            codes = [self.post().status_code for _ in range(3)]
            r = self.post()
        self.assertEqual(codes, [202, 202, 202])
        self.assertEqual(r.status_code, 429)
        d = r.json()
        self.assertEqual((d["code"], d["limit"], d["message"]), ("place_search_quota", 3, "하루에 장소 검색을 할 수 있는 횟수를 초과했어요"))

    @mock.patch.dict(os.environ, {"PLACE_SEARCH_DAILY_LIMIT": "1"})
    def test_env_changes_limit_and_header_shows_remaining(self):
        with mock.patch.object(main.research, "submit", return_value={"status": "done", "report": {}}):
            r1 = self.post()
            r2 = self.post()
        self.assertEqual((r1.status_code, r1.headers.get("x-place-search-remaining")), (200, "0"))
        self.assertEqual(r2.status_code, 429)

    @mock.patch.dict(os.environ, {"PLACE_SEARCH_DAILY_LIMIT": "0"})
    def test_zero_means_unlimited(self):
        with mock.patch.object(main.research, "submit", return_value=dict(RUNNING)):
            self.assertTrue(all(self.post().status_code == 202 for _ in range(6)))

    @mock.patch.dict(os.environ, {"PLACE_SEARCH_DAILY_LIMIT": "1"})
    def test_busy_disabled_and_errors_are_not_counted(self):
        with mock.patch.object(main.research, "submit", side_effect=main.research.Busy()):
            self.assertEqual(self.post().status_code, 503)
        with mock.patch.object(main.research, "submit", return_value={"status": "unavailable", "reason": "research_disabled"}):
            self.assertEqual(self.post().status_code, 200)
        with mock.patch.object(main.research, "submit", side_effect=RuntimeError("x")):
            self.assertEqual(self.post().json()["reason"], "research_error")
        with mock.patch.object(main.research, "submit", return_value=dict(RUNNING)):
            self.assertEqual(self.post().status_code, 202)                    # 앞의 셋은 세지 않았다 — 아직 한 번 남아 있었다
            self.assertEqual(self.post().status_code, 429)

    @mock.patch.dict(os.environ, {"PLACE_SEARCH_DAILY_LIMIT": "1", "RENDER": "true"})
    def test_separate_users_by_forwarded_ip_when_proxy_hops_unknown(self):
        with mock.patch.object(main, "TRUSTED_PROXY_HOPS", 0), \
                mock.patch.object(main.research, "submit", return_value=dict(RUNNING)):
            a = self.post({"X-Forwarded-For": "203.0.113.1"}).status_code
            b = self.post({"X-Forwarded-For": "203.0.113.2"}).status_code
            a2 = self.post({"X-Forwarded-For": "203.0.113.1"}).status_code
        self.assertEqual((a, b, a2), (202, 202, 429))

    @mock.patch.dict(os.environ, {"PLACE_SEARCH_DAILY_LIMIT": "1"})
    def test_new_day_resets(self):
        with mock.patch.object(main.research, "submit", return_value=dict(RUNNING)):
            with mock.patch.object(place_quota, "today", return_value="2026-11-05"):
                self.assertEqual(self.post().status_code, 202)
                self.assertEqual(self.post().status_code, 429)
            with mock.patch.object(place_quota, "today", return_value="2026-11-06"):
                self.assertEqual(self.post().status_code, 202)

    @mock.patch.dict(os.environ, {"PLACE_SEARCH_DAILY_LIMIT": "1"})
    def test_place_check_is_not_counted(self):
        with mock.patch.object(place_check, "check", return_value={"status": "not_found"}):
            for _ in range(3):
                self.http.post("/place-check", json={"country": {"name": "일본"}, "city": {"name": "나라"},
                                                     "place": {"name": "Todaiji", "kind": "attraction"}})
        with mock.patch.object(main.research, "submit", return_value=dict(RUNNING)):
            self.assertEqual(self.post().status_code, 202)

    def test_raw_ip_is_not_kept(self):
        k = place_quota.key_for(ip="203.0.113.7")
        self.assertNotIn("203.0", k)
        self.assertNotEqual(k, place_quota.key_for(uid="203.0.113.7"))      # 계정과 IP 는 다른 칸


class _FakeHttp:
    """공용 API(이미지 정보)만 흉내 낸다."""
    _PAGES = {"1": {"pageid": 1, "title": "File:X.jpg", "imageinfo": [{
        "thumburl": "https://thumb.wikimedia.org/wikipedia/commons/thumb/a/a1/X.jpg/500px-X.jpg?utm_source=commons.wikimedia.org",
        "extmetadata": {"LicenseShortName": {"value": "CC BY-SA 4.0"},
                        "Artist": {"value": "<a href='#'>Wei-Te Wong</a>"},
                        "LicenseUrl": {"value": "https://creativecommons.org/licenses/by-sa/4.0/"}}}]}}

    def get_json(self, url, timeout=8):
        import urllib.parse as up
        title = up.parse_qs(up.urlparse(url).query).get("titles", ["File:X.jpg"])[0].replace("File:", "")
        pg = {"pageid": 1, "title": "File:" + title, "imageinfo": [{
            "thumburl": f"https://thumb.wikimedia.org/wikipedia/commons/thumb/a/a1/{title}/500px-{title}?utm_source=commons.wikimedia.org",
            "extmetadata": {"LicenseShortName": {"value": "CC BY-SA 4.0"},
                            "Artist": {"value": "<a href='#'>Wei-Te Wong</a>"},
                            "LicenseUrl": {"value": "https://creativecommons.org/licenses/by-sa/4.0/"}}}]}

        class R:
            ok = True
        return R(), {"query": {"pages": {"1": pg}}}


class EnrichTest(unittest.TestCase):
    def test_commons_thumbnail_comes_from_the_api_verbatim(self):
        """11/06: md5 로 주소를 조립하던 방식을 버렸다 — 그 주소는 upload.wikimedia.org(데이터센터 IP 403/429)로
        가고 폭을 바꾸면 400 이 났다. 이제 공용 API 가 준 thumburl 을 글자 그대로 쓴다(utm 파라미터 포함)."""
        with mock.patch.object(place_check, "SafeHttp", _FakeHttp):
            im = place_check.commons_image("Statue_of_Liberty_7.jpg", 500)
        self.assertIsNotNone(im)
        self.assertTrue(im["src"].startswith("https://thumb.wikimedia.org/"), im["src"])
        self.assertIn("500px-Statue_of_Liberty_7.jpg", im["src"])
        self.assertEqual(im["license"], "CC BY-SA 4.0")
        self.assertEqual(im["credit"], "Wei-Te Wong")            # 플랫폼 이름이 아니라 저작자
        self.assertEqual(im["page"], "https://commons.wikimedia.org/wiki/File:Statue_of_Liberty_7.jpg")

    def test_commons_rejects_non_image_name(self):
        self.assertIsNone(place_check.commons_image("../../etc/passwd"))
        self.assertIsNone(place_check.commons_image("thing.txt"))
    def test_wikidata_address_and_image_from_claims(self):
        cl = {"P18": [{"mainsnak": {"datavalue": {"value": "Todaiji.jpg"}}}],
              "P6375": [{"mainsnak": {"datavalue": {"value": {"text": "406-1 Zoshicho, Nara", "language": "en"}}}}]}
        self.assertEqual(place_check._wd_text(cl, "P6375"), "406-1 Zoshicho, Nara")
        self.assertIn("500px-Todaiji.jpg", place_check._wd_image(cl)["src"])
        self.assertIsNone(place_check._wd_image({}))

    def test_enrich_fills_missing_photo_and_address_but_keeps_found(self):
        got = {"status": "found", "name": "X", "lat": 1.0, "lon": 2.0, "address": "", "image": None}
        img = {"src": "https://upload.wikimedia.org/a.jpg", "page": "", "credit": "Wikimedia Commons"}
        with mock.patch.object(place_check, "_photo_near", return_value=img), \
                mock.patch.object(place_check, "_reverse", return_value="1 <b>Main</b> St https://evil.example"):
            out = place_check._enrich(None, "X", dict(got))
        self.assertEqual((out["image"], out["address"], out["address_source"]), (img, "1 b Main /b St", "OpenStreetMap (ODbL)"))
        with mock.patch.object(place_check, "_photo_near", side_effect=RuntimeError), \
                mock.patch.object(place_check, "_reverse", side_effect=RuntimeError):
            out = place_check._enrich(None, "X", dict(got))
        self.assertEqual((out["status"], out["image"], out["address"]), ("found", None, ""))   # 보강 실패해도 찾은 결과는 그대로

    def test_found_result_carries_address_and_image_fields(self):
        r = place_check._found("tourapi", "근대역사박물관", 35.98, 126.71, "https://x", 0.5, "attraction", address="전북 군산시 해망로 240")
        self.assertEqual((r["address"], r["image"]), ("전북 군산시 해망로 240", None))


class PhotoProxyTest(unittest.TestCase):
    def setUp(self):
        main._photos.clear(); main._photo_cache.clear()
        self.http = TestClient(main.app)

    def test_only_wikimedia_images(self):
        for src in ("http://upload.wikimedia.org/a.jpg", "https://evil.example/a.jpg", "https://upload.wikimedia.org@evil.example/a.jpg"):
            self.assertEqual(self.http.get("/place-photo", params={"src": src}).status_code, 404, src)

    def test_returns_image_only_by_magic_bytes_and_caches(self):
        jpg = b"\xff\xd8\xff\xe0" + b"0" * 100
        calls = []

        def fake(self, method, url, **kw):
            calls.append(url)
            return net.Response(200, jpg if url.endswith(".jpg") else b"<html>no</html>")
        with mock.patch.object(net.SafeHttp, "request", fake):
            r = self.http.get("/place-photo", params={"src": "https://upload.wikimedia.org/x/a.jpg"})
            r2 = self.http.get("/place-photo", params={"src": "https://upload.wikimedia.org/x/a.jpg"})
            bad = self.http.get("/place-photo", params={"src": "https://upload.wikimedia.org/x/a.png"})
        self.assertEqual((r.status_code, r.headers["content-type"], r.content), (200, "image/jpeg", jpg))
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(len([c for c in calls if c.endswith(".jpg")]), 1)                 # 두 번째는 캐시
        self.assertEqual(bad.status_code, 404)                                              # 이미지가 아니면 내보내지 않는다


class UserPlacesClauseTest(unittest.TestCase):
    def test_only_confirmed_user_addresses_are_facts(self):
        req = main.GenerateRequest(category_id="restaurant", city="Nara", places=[
            main.Place(name="Tōdai-ji Temple", user=True, address="406-1 Zoshicho <b>Nara</b> https://x.example/a"),
            main.Place(name="Kakinoha Sushi", user=True),
            main.Place(name="Nara Park", user=False, address="should not be used")])
        c = main.user_places_clause(req)
        self.assertIn("USER_CONFIRMED_PLACES", c)
        self.assertIn("Tōdai-ji Temple", c)
        self.assertNotIn("Kakinoha", c)
        self.assertNotIn("should not be used", c)
        self.assertNotIn("https://", c)
        self.assertNotIn("<b>", c)
        self.assertEqual(main.user_places_clause(main.GenerateRequest(category_id="restaurant", city="Nara", places=[])), "")


if __name__ == "__main__":
    unittest.main()
