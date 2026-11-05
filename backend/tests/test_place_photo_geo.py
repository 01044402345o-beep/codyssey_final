"""장소 사진: 좌표 검색 + 이름 일치 게이트 + 라이선스 필터 (외부 호출 없이 규칙만).

    cd backend && python3 tests/test_place_photo_geo.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.research import place_check  # noqa: E402


class Resp:
    def __init__(self, ok, data):
        self.ok, self._d = ok, data

    def json(self):
        return self._d


class Http:
    """commons 호출만 가로챈다. 받은 URL 을 기록해 파라미터를 검사한다."""
    def __init__(self, pages, geo=None):
        self.pages, self.geo, self.urls = pages, geo or [], []

    def get_json(self, url, timeout=8):
        self.urls.append(url)
        data = {"query": {"pages": self.pages, "geosearch": self.geo}}
        return Resp(True, data), data            # 실제 SafeHttp.get_json 은 (응답, 본문) 튜플을 준다


def page(pid, title, thumb, short, artist="홍길동", dist=None):
    p = {"pageid": pid, "title": title,
         "imageinfo": [{"thumburl": thumb,
                        "extmetadata": {"LicenseShortName": {"value": short},
                                        "Artist": {"value": f"<a href='#'>{artist}</a>"},
                                        "LicenseUrl": {"value": "https://creativecommons.org/licenses/by-sa/4.0/"}}}]}
    if dist is not None:
        p["dist"] = dist
    return p


THUMB = "https://thumb.wikimedia.org/wikipedia/commons/thumb/a/ab/X.jpg/500px-X.jpg"


class NameGate(unittest.TestCase):
    def test_all_tokens_required(self):
        # 'Shibuya Sky' 조회에 라멘집 사진이 통과했던 실제 사례
        self.assertFalse(place_check._title_matches("Shibuya Sky", "Nissin Donbei noodle stand, Shibuya Sta.jpg"))
        self.assertTrue(place_check._title_matches("Shibuya Sky", "Shibuya Sky (49287086252).jpg"))

    def test_diacritics_fold(self):
        self.assertTrue(place_check._title_matches("Tōdai-ji", "Todai-ji Daibutsu-den.jpg"))
        self.assertTrue(place_check._title_matches("Todai-ji", "Tōdai-ji, Nara.jpg"))

    def test_unrelated_place_rejected(self):
        self.assertFalse(place_check._title_matches("하동관", "Bulgogi 5.jpg"))
        self.assertFalse(place_check._title_matches("Shibuya Sky", "Eiffel Tower.jpg"))

    def test_empty_never_matches(self):
        self.assertFalse(place_check._title_matches("", "Anything.jpg"))
        self.assertFalse(place_check._title_matches("ab", "ab.jpg"))


class License(unittest.TestCase):
    def test_accepts_free(self):
        for s in ("CC0", "CC BY 4.0", "CC BY-SA 4.0", "Public domain", "PD-USGov", "cc by-sa 2.0"):
            self.assertTrue(place_check._license_ok(s), s)

    def test_rejects_nonfree(self):
        for s in ("", "CC BY-NC 4.0", "CC BY-ND 4.0", "Fair use", "non-free", "All rights reserved"):
            self.assertFalse(place_check._license_ok(s), s)

    def test_artist_html_is_plain_text(self):
        self.assertEqual(place_check._plain_text("<a href='x'>Wei-Te Wong</a>"), "Wei-Te Wong")


class GeoSearch(unittest.TestCase):
    def test_uses_api_thumburl_verbatim(self):
        h = Http({"1": page(1, "File:Shibuya Sky.jpg", THUMB, "CC BY-SA 2.0")},
                 [{"pageid": 1, "dist": 42.0}])
        got = place_check.commons_geosearch(h, "Shibuya Sky", 35.658, 139.7016)
        self.assertEqual(got["src"], THUMB)          # 호스트·폭을 다시 조립하지 않는다
        self.assertEqual(got["credit"], "홍길동")
        self.assertEqual(got["license"], "CC BY-SA 2.0")
        self.assertEqual(got["km"], 0.04)             # dist 는 query.geosearch 배열에 있다
        self.assertIn("ggscoord=35.658000%7C139.701600", h.urls[0])
        self.assertIn("iiurlwidth=500", h.urls[0])

    def test_nonfree_photo_skipped(self):
        h = Http({"1": page(1, "File:Shibuya Sky.jpg", THUMB, "CC BY-NC 4.0")}, [{"pageid": 1, "dist": 10}])
        self.assertIsNone(place_check.commons_geosearch(h, "Shibuya Sky", 35.6, 139.7))

    def test_name_mismatch_is_not_used_as_place_photo(self):
        h = Http({"1": page(1, "File:Street Itaewon.jpg", THUMB, "CC0")}, [{"pageid": 1, "dist": 5}])
        self.assertIsNone(place_check.commons_geosearch(h, "Shibuya Sky", 35.6, 139.7))

    def test_http_only_thumb_rejected(self):
        h = Http({"1": page(1, "File:Shibuya Sky.jpg", "http://thumb.wikimedia.org/x.jpg", "CC0")}, [{"pageid": 1}])
        self.assertIsNone(place_check.commons_geosearch(h, "Shibuya Sky", 35.6, 139.7))

    def test_api_failure_returns_none(self):
        class Bad:
            def get_json(self, url, timeout=8):
                return Resp(False, {}), {}
        self.assertIsNone(place_check.commons_geosearch(Bad(), "Shibuya Sky", 35.6, 139.7))


if __name__ == "__main__":
    unittest.main(verbosity=2)
