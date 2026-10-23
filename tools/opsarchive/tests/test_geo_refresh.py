"""국가·도시 주간 수집 스크립트(`.github/scripts/geo_refresh.py`) — 작은 픽스처로 규칙을 고정한다.

네트워크는 가짜 opener 로 바꾼다(GeoNames 덤프·교차 소스·Firestore REST). 실제 덤프로 돈 결과는 docs/ops/GEO_REFRESH.md.
"""
from __future__ import annotations

import gzip
import importlib.util
import io
import json
import os
import shutil
import tempfile
import unittest
import urllib.error
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
_spec = importlib.util.spec_from_file_location("geo_refresh", os.path.join(ROOT, ".github", "scripts", "geo_refresh.py"))
geo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(geo)

COUNTRY_INFO = "\n".join([
    "#ISO\tISO3\tISO-Numeric\tfips\tCountry\tCapital\tArea\tPopulation\tContinent\ttld\tCurrencyCode\tCurrencyName\tPhone\tPostal\tRegex\tLanguages\tgeonameid\tneighbours\tEquivalentFipsCode",
    "KR\tKOR\t410\tKS\tSouth Korea\tSeoul\t98480\t51635256\tAS\t.kr\tKRW\tWon\t82\t\t\tko-KR,en\t1835841\tKP\t",
    "US\tUSA\t840\tUS\tUnited States\tWashington\t9629091\t327167434\tNA\t.us\tUSD\tDollar\t1\t\t\ten-US\t6252001\tCA,MX\t",
]) + "\n"
ADMIN1 = "KR.11\tSeoul\tSeoul\t1835847\nUS.NY\tNew York\tNew York\t5128638\nXX.01\tNowhere\tNowhere\t1\n"


def place(gid, name, cc, fclass="P", fcode="PPL", pop=0, lat=37.5, lon=127.0, admin1="11"):
    cols = [str(gid), name, name, "", str(lat), str(lon), fclass, fcode, cc, "", admin1, "", "", "", str(pop),
            "", "", "Asia/Seoul", "2026-10-01"]
    return "\t".join(cols)


ALL = "\n".join([
    place(1835848, "Seoul", "KR", fcode="PPLC", pop=10_000_000),
    place(1838524, "Busan", "KR", fcode="PPLA", pop=3_400_000, admin1="26"),
    place(1, "Old Town", "KR", fcode="PPLH"),             # 역사적 → 제외
    place(2, "Gangnam", "KR", fcode="PPLX"),              # 도시 내 구역 → 제외
    place(3, "Han River", "KR", fclass="H", fcode="STM"),  # 사람이 사는 곳 아님 → 제외
    place(5128581, "New York City", "US", fcode="PPL", pop=8_800_000, lat=40.7, lon=-74.0, admin1="NY"),
    place(4140963, "Washington", "US", fcode="PPLC", pop=690_000, lat=38.9, lon=-77.0, admin1="DC"),
    place(9, "Atlantis", "ZZ", pop=1),                     # 모르는 국가 → 제외
    "bad\trow",
]) + "\n"
ALT = "\n".join([
    "1\t1835848\tko\t서울\t1\t\t\t\t\t",
    "2\t1835848\tko\t서울특별시\t\t\t\t\t\t",            # preferred 아님 → 뒤로
    "3\t1838524\tko\t부산\t\t\t\t\t\t",
    "4\t5128581\tko\t뉴욕\t\t\t\t\t\t",
    "5\t5128581\tko\t옛날뉴욕\t\t\t\t1\t\t",              # 역사적 이름 → 제외
    "6\t1835841\tko\t대한민국\t1\t\t\t\t\t",
    "7\t6252001\tko\t미국\t1\t\t\t\t\t",
    "8\t1835848\tja\tソウル\t\t\t\t\t\t",
]) + "\n"


def zipped(member: str, text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(member, text)
    return buf.getvalue()


class Resp:
    def __init__(self, body: bytes, headers=None):
        self.raw, self.headers = io.BytesIO(body), headers or {}

    def read(self, n=-1):
        return self.raw.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeNet:
    """GeoNames 덤프 · 교차 소스 · Firestore REST 를 흉내 낸다."""

    def __init__(self, prev_meta=None):
        self.files = {"countryInfo.txt": COUNTRY_INFO.encode(), "admin1CodesASCII.txt": ADMIN1.encode(),
                      "allCountries.zip": zipped("allCountries.txt", ALL),
                      "alternateNamesV2.zip": zipped("alternateNamesV2.txt", ALT)}
        self.docs = {}
        if prev_meta is not None:
            self.docs["geo_meta/current"] = {"fields": {k: geo._fs_value(v) for k, v in prev_meta.items()}}
        self.commits = []

    def __call__(self, req, timeout=None):
        url = req.full_url
        if url.startswith(geo.DUMP):
            return Resp(self.files[url[len(geo.DUMP):]], {"Last-Modified": "Fri, 23 Oct 2026 01:00:00 GMT"})
        if url == geo.DR5HN:
            return Resp(json.dumps([{"iso2": "KR"}, {"iso2": "US"}, {"iso2": "FR"}]).encode())
        if url == geo.COUNTRIESNOW:
            return Resp(json.dumps({"error": False, "data": [{"iso2": "KR", "cities": ["Seoul"] * 3}]}).encode())
        if "firestore.googleapis.com" in url:
            if url.endswith("documents:commit"):
                self.commits.append(json.loads(req.data))
                return Resp(b"{}")
            key = url.split("/documents/", 1)[1]
            if key in self.docs:
                return Resp(json.dumps(self.docs[key]).encode())
            raise urllib.error.HTTPError(url, 404, "nf", {}, None)
        raise AssertionError(url)


class ParseTest(unittest.TestCase):
    def test_countries_admin1_and_korean_names(self):
        countries = geo.parse_countries(io.StringIO(COUNTRY_INFO))
        geo.parse_admin1(io.StringIO(ADMIN1), countries)
        self.assertEqual(set(countries), {"KR", "US"})
        self.assertEqual((countries["KR"]["iso3"], countries["KR"]["capital"], countries["KR"]["geonameid"]),
                         ("KOR", "Seoul", 1835841))
        self.assertEqual(countries["KR"]["admin1"], {"11": "Seoul"})
        ko = geo.parse_ko_names(io.StringIO(ALT))
        self.assertEqual(ko[1835848], "서울")              # preferred 우선
        self.assertEqual(ko[5128581], "뉴욕")              # 역사적 이름은 버린다
        self.assertNotIn(1838524 + 1, ko)

    def test_split_keeps_only_living_places_of_known_countries(self):
        countries = geo.parse_countries(io.StringIO(COUNTRY_INFO))
        ko = geo.parse_ko_names(io.StringIO(ALT))
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        counts = geo.split_places(io.StringIO(ALL), countries, ko, tmp)
        self.assertEqual(counts, {"KR": 2, "US": 2})
        with open(os.path.join(tmp, "KR.jsonl"), encoding="utf-8") as fh:
            rows = [json.loads(x) for x in fh]
        self.assertEqual([r[1] for r in rows], ["Seoul", "Busan"])
        self.assertEqual(rows[0][3], "서울")


class ShardTest(unittest.TestCase):
    def test_sorted_by_population_and_under_limit(self):
        rows = [[i, "c%d" % i, "c%d" % i, "", "01", i, 1.0, 2.0, "PPL"] for i in range(2000)]
        old_max, old_chunk = geo.SHARD_MAX, geo.RAW_CHUNK
        geo.SHARD_MAX, geo.RAW_CHUNK = 4000, 20000           # 작은 상한으로 여러 샤드가 생기게
        self.addCleanup(setattr, geo, "SHARD_MAX", old_max)
        self.addCleanup(setattr, geo, "RAW_CHUNK", old_chunk)
        parts = geo._shard_rows(rows)
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(len(data) <= 4000 for data, _n in parts))
        back = [r for data, _n in parts for r in json.loads(gzip.decompress(data))]
        self.assertEqual(back, rows)                          # 빠짐·중복 없이 순서 유지

    def test_same_content_same_bytes(self):
        self.assertEqual(geo._gz(b"abc"), geo._gz(b"abc"))   # mtime=0 → 해시가 안정적


class CheckTest(unittest.TestCase):
    def countries(self, n_cc=250, per=5000):
        return {"C%03d" % i: {"city_count": per, "capital": ""} for i in range(n_cc)}

    def test_first_load_passes_with_warning(self):
        rep = geo.check(self.countries(), {}, None, {})
        self.assertTrue(rep["ok"], rep["errors"])
        self.assertTrue(any("첫 적재" in w for w in rep["warnings"]))

    def test_regressions_block_storing(self):
        prev = {"counts": {"cities": 2_000_000, "ko_ratio": 0.5},
                "country_counts": {"C000": 9000, "GONE": 10}}
        rep = geo.check(self.countries(), {}, prev, {})
        self.assertFalse(rep["ok"])
        text = " ".join(rep["errors"])
        self.assertIn("전체 도시 수 급감", text)
        self.assertIn("사라진 국가: GONE", text)
        self.assertIn("C000 9000 → 5000", text)
        self.assertIn("한국어 이름 비율 급감", text)

    def test_small_country_wobble_is_ignored(self):
        prev = {"counts": {"cities": 1_250_000}, "country_counts": {"C000": 5040}}
        self.assertTrue(geo.check(self.countries(), {}, prev, {})["ok"])

    def test_truncated_dump_fails(self):
        self.assertFalse(geo.check(self.countries(per=10), {}, None, {})["ok"])

    def test_cross_source_differences_are_warnings(self):
        rep = geo.check(self.countries(), {}, None, {"dr5hn": {"C000", "XX"}, "countriesnow": "URLError"})
        self.assertTrue(rep["ok"])
        self.assertTrue(any("dr5hn" in w for w in rep["warnings"]))
        self.assertTrue(any("CountriesNow" in w for w in rep["warnings"]))


class RunTest(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="geo-")
        self.addCleanup(shutil.rmtree, self.work, True)
        self.orig_check = geo.check

    def run_geo(self, net, dry=False, token="tok"):
        # 픽스처는 국가 2·도시 4 라 '너무 적음' 검사를 끄고 나머지 흐름을 본다
        geo.check = lambda *a, **k: dict(self.orig_check(*a, **k), ok=True, errors=[])
        self.addCleanup(setattr, geo, "check", self.orig_check)
        return geo.run(self.work, dry_run=dry, project="p1", token=token, opener=net)

    def test_end_to_end_writes_then_meta_last(self):
        net = FakeNet()
        rep = self.run_geo(net)
        self.assertEqual(rep["counts"]["cities"], 4)
        writes = [w for c in net.commits for w in c["writes"]]
        names = [w["update"]["name"].split("/documents/")[1] for w in writes if "update" in w]
        self.assertEqual(names[-1], "geo_meta/current")       # 메타는 맨 마지막
        self.assertIn("geo_cities/KR_000", names)
        self.assertIn("geo_countries/KR", names)
        kr = next(w for w in writes if w.get("update", {}).get("name", "").endswith("geo_countries/KR"))
        self.assertEqual(kr["update"]["fields"]["ko"]["stringValue"], "대한민국")
        shard = next(w for w in writes if w.get("update", {}).get("name", "").endswith("geo_cities/KR_000"))
        import base64
        rows = json.loads(gzip.decompress(base64.b64decode(shard["update"]["fields"]["data"]["bytesValue"])))
        self.assertEqual([r[1] for r in rows], ["Seoul", "Busan"])
        meta = writes[-1]["update"]["fields"]
        self.assertIn("CC BY 4.0", meta["attribution"]["stringValue"])

    def test_second_run_writes_only_meta_and_deletes_stale_shards(self):
        net = FakeNet()
        self.run_geo(net)
        meta = net.commits[-1]["writes"][0]["update"]["fields"]
        prev = {k: geo._fs_plain(v) for k, v in meta.items()}
        prev["shards"]["FR_000"] = "old"                     # 지난주엔 있었고 이번엔 없는 샤드
        net2 = FakeNet(prev_meta=prev)
        rep = self.run_geo(net2)
        self.assertEqual(rep["stored"]["written"], 0)         # 바뀐 문서 없음
        self.assertEqual(rep["stored"]["deleted"], 1)
        deletes = [w["delete"] for c in net2.commits for w in c["writes"] if "delete" in w]
        self.assertTrue(deletes[0].endswith("geo_cities/FR_000"))

    def test_dry_run_and_missing_token_write_nothing(self):
        net = FakeNet()
        self.assertTrue(self.run_geo(net, dry=True)["stored"].startswith("skipped"))
        self.assertTrue(self.run_geo(net, token="")["stored"].startswith("skipped"))
        self.assertEqual(net.commits, [])

    def test_regression_failure_writes_nothing(self):
        net = FakeNet()
        rep = geo.run(self.work, dry_run=False, project="p1", token="tok", opener=net)   # 실제 검사: 너무 적음 → 실패
        self.assertFalse(rep["ok"])
        self.assertEqual(net.commits, [])


class CommitBatchTest(unittest.TestCase):
    def test_batches_respect_size_and_count(self):
        calls = []
        fs = geo.Firestore("p1", "tok", opener=lambda req, timeout=None: calls.append(json.loads(req.data)) or Resp(b"{}"))
        old = geo.COMMIT_MAX_BYTES
        geo.COMMIT_MAX_BYTES = 2000
        self.addCleanup(setattr, geo, "COMMIT_MAX_BYTES", old)
        writes = [{"update": {"name": "x/%d" % i, "fields": {"d": {"stringValue": "y" * 300}}}} for i in range(20)]
        n = fs.commit(writes)
        self.assertEqual(n, len(calls))
        self.assertGreater(n, 1)
        self.assertEqual(sum(len(c["writes"]) for c in calls), 20)
        self.assertTrue(all(len(json.dumps(c)) < 2600 for c in calls))

    def test_bad_project_rejected(self):
        with self.assertRaises(geo.GeoError):
            geo.Firestore("a/b", "tok")


if __name__ == "__main__":
    unittest.main()
