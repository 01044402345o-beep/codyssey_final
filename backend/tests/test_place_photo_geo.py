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
        for s in ("CC0", "CC BY 4.0", "CC BY-SA 4.0", "Public domain", "PD-USGov", "cc by-sa 2.0", "KOGL Type 1", "GFDL", "Attribution"):
            self.assertTrue(place_check._license_ok(s), s)

    def test_rejects_nonfree(self):
        for s in ("", "CC BY-NC 4.0", "CC BY-ND 4.0", "Fair use", "non-free", "All rights reserved", "KOGL Type 2", "KOGL Type 4"):
            self.assertFalse(place_check._license_ok(s), s)

    def test_artist_html_is_plain_text(self):
        self.assertEqual(place_check._plain_text("<a href='x'>Wei-Te Wong</a>"), "Wei-Te Wong")


class GeoSearch(unittest.TestCase):
    def test_uses_api_thumburl_verbatim(self):
        h = Http({"1": page(1, "File:Shibuya Sky.jpg", THUMB, "CC BY-SA 2.0")},
                 [{"pageid": 1, "dist": 42.0}])
        got = place_check.commons_geosearch(h, "Shibuya Sky", 35.658, 139.7016)
        self.assertEqual(got["src"], THUMB)          # 호스트·폭을 다시 조립하지 않는다
        self.assertEqual((got["credit"], got["author"]), ("Wikimedia Commons", "홍길동"))   # main 의 사진 형식(저작자는 author)
        self.assertEqual(got["license"], "CC BY-SA 2.0")
        self.assertEqual(got["license_url"], "https://creativecommons.org/licenses/by-sa/4.0/")
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


class GeoEntity(unittest.TestCase):
    """위키데이터 좌표 조회 — 다국어 라벨 대조."""

    def test_korean_name_matches_korean_label(self):
        self.assertTrue(place_check._label_tokens_match("광장시장", ["광장시장", "Gwangjang Market"]))
        self.assertTrue(place_check._label_tokens_match("Gwangjang Market", ["광장시장", "Gwangjang Market"]))

    def test_partial_place_name_rejected(self):
        # '명동교자' 는 '명동'(동네)과 다른 곳이다 — 두 글자 낱말은 비교에서 빠진다
        self.assertFalse(place_check._label_tokens_match("명동교자", ["명동"]))

    def test_extra_words_in_label_still_match(self):
        self.assertTrue(place_check._label_tokens_match("Eiffel Tower", ["Eiffel Tower", "에펠탑"]))

    def test_sparql_row_parsing_and_exact_label_preference(self):
        def row(item, img, dist, label):
            return {"item": {"value": f"http://www.wikidata.org/entity/{item}"},
                    "img": {"value": f"http://commons.wikimedia.org/wiki/Special:FilePath/{img}"},
                    "dist": {"value": str(dist)}, "label": {"value": label}}
        rows = [row("Q1", "Sub.jpg", 0.059, "경복궁 사정전"), row("Q2", "Main.jpg", 0.036, "경복궁"),
                row("Q3", "Other.jpg", 0.010, "근처호텔")]

        class H:
            def __init__(self):
                self.urls = []

            def get_json(self, url, timeout=8):
                self.urls.append(url)
                if "sparql" in url:
                    d = {"results": {"bindings": rows}}
                else:      # 공용 파일 정보
                    name = "Main.jpg" if "Main" in url else "Sub.jpg"
                    d = {"query": {"pages": {"1": page(1, "File:" + name, THUMB, "CC BY-SA 4.0")}}}
                return Resp(True, d), d
        got = place_check.wikidata_geo_image(H(), "경복궁", 37.5796, 126.9770)
        self.assertTrue(got["page"].endswith("File:Main.jpg"), got)   # 정확 라벨이 더 멀어도 이긴다
        self.assertEqual(got["license"], "CC BY-SA 4.0")
        self.assertEqual(got["author"], "홍길동")
        self.assertEqual(got["km"], 0.04)



class PhotoNearOrder(unittest.TestCase):
    """이름이 맞는 P18 → 좌표의 위키데이터 라벨 → 공용 좌표 검색. 한 방법의 실패가 다음을 막지 않는다."""

    def test_falls_through_in_order(self):
        from unittest import mock
        img = {"src": THUMB, "license": "CC0"}
        with mock.patch.object(place_check, "_by_wikidata", side_effect=RuntimeError("down")),                 mock.patch.object(place_check, "wikidata_geo_image", return_value=None) as wg,                 mock.patch.object(place_check, "commons_geosearch", return_value=img) as cg:
            self.assertEqual(place_check._photo_near(None, "광장시장", 37.57, 127.0), img)
            wg.assert_called_once(); cg.assert_called_once()
        with mock.patch.object(place_check, "_by_wikidata", return_value=None),                 mock.patch.object(place_check, "wikidata_geo_image", return_value=img),                 mock.patch.object(place_check, "commons_geosearch") as cg:
            self.assertEqual(place_check._photo_near(None, "광장시장", 37.57, 127.0), img)
            cg.assert_not_called()
        with mock.patch.object(place_check, "_by_wikidata", return_value=None),                 mock.patch.object(place_check, "wikidata_geo_image", return_value=None),                 mock.patch.object(place_check, "commons_geosearch", side_effect=RuntimeError("x")):
            self.assertIsNone(place_check._photo_near(None, "광장시장", 37.57, 127.0))   # 그다음은 Google 사진

    def test_commons_meta_drops_nonfree_license(self):
        class H:
            def get_json(self, url, timeout=8):
                d = {"query": {"pages": {"1": page(1, "File:A.jpg", THUMB, "CC BY-NC 4.0")}}}
                return Resp(True, d), d
        self.assertIsNone(place_check.commons_meta(H(), place_check.commons_image("A.jpg")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
