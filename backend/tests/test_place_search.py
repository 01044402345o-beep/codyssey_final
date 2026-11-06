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


class EnrichTest(unittest.TestCase):
    def test_commons_thumbnail_uses_md5_path_and_standard_width(self):
        im = place_check.commons_image("Statue of Liberty 7.jpg")
        self.assertEqual(im["src"], "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a1/Statue_of_Liberty_7.jpg/500px-Statue_of_Liberty_7.jpg")
        self.assertEqual(im["page"], "https://commons.wikimedia.org/wiki/File:Statue_of_Liberty_7.jpg")
        self.assertTrue(place_check.commons_image("Map.svg")["src"].endswith("500px-Map.svg.png"))
        for bad in ("", "../x.jpg", "a/b.jpg", "file.pdf"):
            self.assertIsNone(place_check.commons_image(bad))

    def test_wikidata_address_and_image_from_claims(self):
        cl = {"P18": [{"mainsnak": {"datavalue": {"value": "Todaiji.jpg"}}}],
              "P6375": [{"mainsnak": {"datavalue": {"value": {"text": "406-1 Zoshicho, Nara", "language": "en"}}}}]}
        self.assertEqual(place_check._wd_text(cl, "P6375"), "406-1 Zoshicho, Nara")
        self.assertTrue(place_check._wd_image(cl)["src"].endswith("/500px-Todaiji.jpg"))
        self.assertIsNone(place_check._wd_image({}))

    def test_enrich_fills_missing_photo_and_address_but_keeps_found(self):
        got = {"status": "found", "name": "X", "lat": 1.0, "lon": 2.0, "address": "", "image": None}
        img = {"src": "https://upload.wikimedia.org/a.jpg", "page": "", "credit": "Wikimedia Commons", "license": "CC BY-SA 4.0"}
        with mock.patch.object(place_check, "_photo_near", return_value=img), \
                mock.patch.object(place_check, "_reverse", return_value="1 <b>Main</b> St https://evil.example"):
            out = place_check._enrich(None, "X", dict(got))
        self.assertEqual((out["image"], out["address"], out["address_source"]), (img, "1 b Main /b St", "OpenStreetMap (ODbL)"))
        with mock.patch.object(place_check, "_photo_near", side_effect=RuntimeError), \
                mock.patch.object(place_check, "_reverse", side_effect=RuntimeError):
            out = place_check._enrich(None, "X", dict(got))
        self.assertEqual((out["status"], out["image"], out["address"]), ("found", None, ""))   # 보강 실패해도 찾은 결과는 그대로

    def test_photo_without_license_is_dropped(self):
        got = {"status": "found", "name": "X", "lat": 1.0, "lon": 2.0, "address": "a",
               "image": place_check.commons_image("X.jpg")}
        with mock.patch.object(place_check, "commons_meta", return_value=None):
            self.assertIsNone(place_check._enrich(None, "X", dict(got))["image"])      # 저작자·라이선스를 못 알면 사진 없음

    def test_commons_meta_reads_author_license_and_api_thumb(self):
        api = {"query": {"pages": {"1": {"imageinfo": [{
            "thumburl": "https://thumb.wikimedia.org/wikipedia/commons/thumb/6/63/G.jpg/500px-G.jpg?utm_source=x",
            "descriptionurl": "https://commons.wikimedia.org/wiki/File:G.jpg",
            "extmetadata": {"Artist": {"value": '<a href="//commons.wikimedia.org/wiki/User:Kim">Kim &amp; Lee</a>'},
                            "LicenseShortName": {"value": "CC BY-SA 4.0"},
                            "LicenseUrl": {"value": "https://creativecommons.org/licenses/by-sa/4.0"}}}]}}}}
        http = mock.Mock()
        http.get_json.return_value = (net.Response(200, b"{}"), api)
        m = place_check.commons_meta(http, place_check.commons_image("G.jpg"))
        self.assertEqual(m, {"src": "https://thumb.wikimedia.org/wikipedia/commons/thumb/6/63/G.jpg/500px-G.jpg",
                             "page": "https://commons.wikimedia.org/wiki/File:G.jpg", "credit": "Wikimedia Commons",
                             "author": "Kim & Lee", "license": "CC BY-SA 4.0",
                             "license_url": "https://creativecommons.org/licenses/by-sa/4.0"})
        api["query"]["pages"]["1"]["imageinfo"][0]["extmetadata"].pop("LicenseShortName")
        self.assertIsNone(place_check.commons_meta(http, place_check.commons_image("G.jpg")))

    def test_borrowed_photo_needs_same_name(self):
        near = {"status": "found", "name": "Jamba Juice Shibuya", "lat": 35.66, "lon": 139.70,
                "image": {"src": "https://upload.wikimedia.org/j.jpg"}}
        with mock.patch.object(place_check, "_by_wikidata", return_value=near):
            self.assertIsNone(place_check._photo_near(None, "Blue Bottle Coffee Shibuya", 35.66, 139.70))
            self.assertEqual(place_check._photo_near(None, "Jamba Juice", 35.66, 139.70), near["image"])

    def test_found_result_carries_address_and_image_fields(self):
        r = place_check._found("tourapi", "근대역사박물관", 35.98, 126.71, "https://x", 0.5, "attraction", address="전북 군산시 해망로 240")
        self.assertEqual((r["address"], r["image"]), ("전북 군산시 해망로 240", None))


class GooglePhotoTest(unittest.TestCase):
    """무료 공용 사진이 없을 때만 Google 사진 — 화면이 바로 부르는 photoUri + 찍은 사람 표시, 저장·캐시하지 않는다."""
    ITEM = {"photos": [{"name": "places/ChIJabc/photos/AU3ubuXYZ",
                        "authorAttributions": [{"displayName": "Kim <b>", "uri": "//maps.google.com/maps/contrib/123"}]}]}

    def test_first_photo_reads_reference_and_author(self):
        from app.research.sources import google_places as gp
        self.assertEqual(gp._first_photo(self.ITEM), {"name": "places/ChIJabc/photos/AU3ubuXYZ",
                                                       "authors": [{"name": "Kim", "uri": "https://maps.google.com/maps/contrib/123"}]})
        self.assertIsNone(gp._first_photo({"photos": [{"name": "../../etc"}]}))
        self.assertIsNone(gp._first_photo({}))

    @mock.patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "SECRET", "RESEARCH_SOURCES": "", "ITINERARY_DAILY_CAP": "50"})
    def test_photo_uri_keeps_key_in_header_and_only_googleusercontent(self):
        from app.agents import itinerary
        from app.research.sources import google_places as gp
        itinerary.reset_daily_cap()
        seen = {}

        def req(method, url, headers=None, **kw):
            seen.update(url=url, headers=headers)
            return net.Response(200, b'{"photoUri": "https://lh3.googleusercontent.com/place-photos/AbC=s500"}')
        http = mock.Mock(request=req)
        got = gp.photo_uri(http, gp._first_photo(self.ITEM))
        self.assertEqual(got["src"], "https://lh3.googleusercontent.com/place-photos/AbC=s500")
        self.assertEqual((got["provider"], got["authors"][0]["name"]), ("google", "Kim"))
        self.assertNotIn("SECRET", seen["url"])                                           # 키는 주소가 아니라 머리글에
        self.assertEqual(seen["headers"]["X-Goog-Api-Key"], "SECRET")
        self.assertIn("skipHttpRedirect=true", seen["url"])
        http2 = mock.Mock(request=lambda *a, **k: net.Response(200, b'{"photoUri": "https://evil.example/x.jpg"}'))
        self.assertIsNone(gp.photo_uri(http2, gp._first_photo(self.ITEM)))
        with mock.patch.object(itinerary, "_reserve", return_value=0):
            self.assertIsNone(gp.photo_uri(http, gp._first_photo(self.ITEM)))              # 일 한도를 다 쓰면 부르지 않는다

    def test_google_photo_only_when_no_free_photo_and_never_remembered(self):
        from app.research.sources import google_places as gp
        gimg = {"src": "https://lh3.googleusercontent.com/p/A=s500", "provider": "google", "credit": "Google 지도", "authors": []}
        wd = {"status": "found", "name": "Myeongdong Kyoja", "lat": 37.5638, "lon": 126.9853, "distance_km": 1.0, "kind": "",
              "address": "", "image": None, "source": {"provider": "wikidata", "url": "https://www.wikidata.org/wiki/Q1", "title": "x", "license": "CC0"}}
        hit = {"name": "Myeongdong Kyoja Main", "lat": 37.5639, "lon": 126.9854, "url": "https://maps.google.com/?cid=1", "address": "",
               "photo": {"name": "places/x/photos/y", "authors": []}}
        place_check.clear()
        with mock.patch.object(place_check, "_photo_near", return_value=None),                 mock.patch.object(place_check, "_reverse", return_value="서울 중구 명동10길 29"),                 mock.patch.object(gp, "available", return_value=True),                 mock.patch.object(gp, "find", return_value=hit),                 mock.patch.object(gp, "photo_uri", return_value=gimg) as pu:
            out = place_check._enrich(None, "Myeongdong Kyoja", dict(wd))
            self.assertEqual(out["image"], gimg)
            pu.assert_called_once()
            # 이름이 다르면(근처 다른 가게) Google 사진도 붙이지 않는다
            other = dict(hit, name="Jamba Juice")
            with mock.patch.object(gp, "find", return_value=other):
                self.assertIsNone(place_check._enrich(None, "Myeongdong Kyoja", dict(wd))["image"])
        # 공용 사진이 있으면 Google 은 부르지 않는다
        free = dict(wd, image={"src": "https://upload.wikimedia.org/a.jpg", "license": "CC BY-SA 4.0"})
        with mock.patch.object(gp, "find") as f, mock.patch.object(gp, "photo_uri") as pu2,                 mock.patch.object(place_check, "_reverse", return_value=""):
            self.assertEqual(place_check._enrich(None, "x", dict(free))["image"]["license"], "CC BY-SA 4.0")
            f.assert_not_called(); pu2.assert_not_called()

    def test_check_does_not_memo_google_photo(self):
        place_check.clear()
        gimg = {"src": "https://lh3.googleusercontent.com/p/A=s500", "provider": "google"}
        found = {"status": "found", "name": "X", "lat": 1.0, "lon": 2.0, "image": None, "address": "a",
                 "source": {"provider": "wikidata"}}
        with mock.patch.object(place_check.config, "research_enabled", return_value=True),                 mock.patch.object(place_check.identity, "resolve", return_value={"cities": [{"ref": {"key": "JP_1", "lat": 1.0, "lon": 2.0}}]}),                 mock.patch.object(place_check.nodes, "enrich_unresolved"),                 mock.patch.object(place_check, "_by_tourapi", return_value=None),                 mock.patch.object(place_check, "_by_wikidata", return_value=dict(found)),                 mock.patch.object(place_check, "_enrich", side_effect=lambda h, n, g: {**g, "image": gimg}):
            r = place_check.check({"country": {"name": "일본"}, "city": {"name": "나라"}, "place": {"name": "X"}},
                                  http=mock.Mock(), store=mock.Mock(), cache=mock.Mock())
            self.assertEqual(r["image"], gimg)                                               # 이번 확인 창에는 보이고
            again = place_check.check({"country": {"name": "일본"}, "city": {"name": "나라"}, "place": {"name": "X"}},
                                      http=mock.Mock(), store=mock.Mock(), cache=mock.Mock())
        self.assertTrue(again.get("cached"))
        self.assertIsNone(again["image"])                                                    # 기억한 결과에는 Google 사진이 없다

    def test_csp_allows_google_photo_host_only_for_images(self):
        csp = TestClient(main.app).get("/health").headers.get("content-security-policy", "")
        img = next(p for p in csp.split(";") if p.strip().startswith("img-src"))
        self.assertIn("https://*.googleusercontent.com", img)
        self.assertNotIn("googleusercontent", csp.replace(img, ""))                          # 스크립트·연결에는 열지 않는다


class PhotoProxyTest(unittest.TestCase):
    def setUp(self):
        main._photos.clear(); main._photo_cache.clear()
        self.http = TestClient(main.app)

    def test_only_wikimedia_images(self):
        for src in ("http://upload.wikimedia.org/a.jpg", "https://evil.example/a.jpg", "https://upload.wikimedia.org@evil.example/a.jpg",
                    "https://169.254.169.254/latest/meta-data", "https://commons.wikimedia.org/wiki/File:a.jpg"):
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
            r3 = self.http.get("/place-photo", params={"src": "https://thumb.wikimedia.org/x/b.jpg"})
            bad = self.http.get("/place-photo", params={"src": "https://upload.wikimedia.org/x/a.png"})
        self.assertEqual((r.status_code, r.headers["content-type"], r.content), (200, "image/jpeg", jpg))
        self.assertEqual((r2.status_code, r3.status_code), (200, 200))      # 공용 API 가 주는 thumb 호스트도
        self.assertEqual(len([c for c in calls if c.endswith("/a.jpg")]), 1)                 # 두 번째는 캐시
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
