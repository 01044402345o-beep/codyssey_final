#!/usr/bin/env python3
"""가로 모드 화면 키보드가 떠 있을 때 나라·도시 목록이 키보드 뒤로 들어가 잘리지 않는다(11/07 실기기 iPhone 가로).

iOS 는 키보드가 올라와도 innerHeight·vh 는 그대로고 보이는 영역(visualViewport)만 줄어든다.
Chromium 에는 화면 키보드가 없어 window.visualViewport 를 흉내 낸 객체로 바꿔 끼운다(높이를 줄이고 resize 를 보낸다).

  A 가로(932×430) 키보드(보이는 높이 170px): 나라 목록이 보이는 영역 안에 들어간다(아래가 키보드에 안 가림)
  B 도시 목록도 같다
  C 키보드가 내려가면(보이는 높이 = 화면) 목록이 다시 넉넉해진다
  D 키보드 없는 세로·컴퓨터: 예전처럼 칸 아래로 열리고 화면이 튀지 않는다
"""
import json
import sys
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8899"
fails = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ((" — " + str(extra)) if (extra and not cond) else ""))
    if not cond:
        fails.append(name)


# /geo/* 가짜 응답 — test_geo_picker 와 같다(CI 서버에는 Firestore 가 없다)
COUNTRIES = [
    {"iso2": "US", "name": "United States", "ko": "미국", "capital": "Washington", "population": 327000000, "continent": "NA"},
    {"iso2": "AU", "name": "Australia", "ko": "오스트레일리아", "capital": "Canberra", "population": 25000000, "continent": "OC"},
    {"iso2": "JP", "name": "Japan", "ko": "일본", "capital": "Tokyo", "population": 126000000, "continent": "AS"},
    {"iso2": "FR", "name": "France", "ko": "프랑스", "capital": "Paris", "population": 67000000, "continent": "EU"},
] + [  # 목록이 칸보다 길어 스크롤이 생기게(실제는 248개국)
    {"iso2": "Z%s" % chr(65 + i), "name": "Testland %02d" % i, "ko": "테스트국 %02d" % i, "capital": "", "population": 1, "continent": "EU"}
    for i in range(26)
]
CITIES = {
    "US": [{"id": 1, "name": "New York City", "ko": "뉴욕", "label": "뉴욕", "region": "New York", "population": 8800000, "capital": False},
           {"id": 2, "name": "Los Angeles", "ko": "로스앤젤레스", "label": "로스앤젤레스", "region": "California", "population": 3800000, "capital": False},
           {"id": 3, "name": "Boston", "ko": "보스턴", "label": "보스턴", "region": "Massachusetts", "population": 653833, "capital": False},
           {"id": 4, "name": "Boston", "ko": "", "label": "Boston", "region": "Georgia", "population": 1323, "capital": False}],
    "AU": [{"id": 9, "name": "Sydney", "ko": "시드니", "label": "시드니", "region": "New South Wales", "population": 4600000, "capital": False}],
}
calls = []


def geo_route(route):
    url = urlparse(route.request.url)
    calls.append(url.path + ("?" + url.query if url.query else ""))
    if url.path.endswith("/geo/countries"):
        body = {"countries": COUNTRIES, "attribution": "GeoNames, CC BY 4.0"}
    else:
        qs = parse_qs(url.query)
        cc, q = qs.get("country", [""])[0], qs.get("q", [""])[0].lower().replace(" ", "")
        rows = [c for c in CITIES.get(cc, []) if not q or q in (c["name"] + c["ko"]).lower().replace(" ", "")]
        body = {"country": cc, "cities": rows, "attribution": "GeoNames, CC BY 4.0"}
    route.fulfill(status=200, content_type="application/json", body=json.dumps(body, ensure_ascii=False))



FAKE_VV = """(() => {
  const vv = new EventTarget();
  vv._h = null; vv.offsetLeft = 0; vv.scale = 1;
  Object.defineProperty(vv, 'height', { get: () => vv._h == null ? window.innerHeight : vv._h });
  Object.defineProperty(vv, 'width', { get: () => window.innerWidth });
  Object.defineProperty(vv, 'offsetTop', { get: () => 0 });
  Object.defineProperty(window, 'visualViewport', { value: vv, configurable: true });
  window.__kb = h => { vv._h = h; vv.dispatchEvent(new Event('resize')); };
})();"""

BOX = """sel => { const ul = document.querySelector(sel); if (!ul || ul.hidden) return null; const r = ul.getBoundingClientRect();
  return { top: Math.round(r.top), bottom: Math.round(r.bottom), h: Math.round(r.height), up: ul.classList.contains('up'), vb: visualViewport.height }; }"""

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 932, "height": 430}, has_touch=True, is_mobile=True)
    ctx.add_init_script(FAKE_VV); ctx.route("**/geo/**", geo_route)
    pg = ctx.new_page(); errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(BASE + "/?demo=1&gate=off", timeout=60000); pg.wait_for_timeout(1500)
    pg.evaluate("S.user = DEMO_USER; go('u-input')"); pg.wait_for_timeout(400)
    country = pg.locator('[data-geo="country"]')
    country.scroll_into_view_if_needed(); country.fill(""); country.focus(); pg.wait_for_timeout(500)   # 포커스하면 목록이 뜬다
    pg.evaluate("__kb(170)"); pg.wait_for_timeout(300)        # 그다음 키보드가 올라온다(보이는 높이 170px)
    a = pg.evaluate(BOX, "#geo-list-country")
    check("A 키보드가 떠 있어도 나라 목록이 보이는 영역(170px) 안에 있다", a and a["bottom"] <= 170 and a["top"] >= 0 and a["h"] >= 64, a)
    pg.evaluate("__kb(null)"); pg.wait_for_timeout(200)         # 키보드가 내려간다
    c = pg.evaluate(BOX, "#geo-list-country")
    check("C 키보드가 내려가면 목록이 다시 넉넉해진다", c and c["h"] > a["h"], [a, c])
    country.fill("미국"); pg.wait_for_timeout(500); pg.keyboard.press("Enter"); pg.wait_for_timeout(500)   # 나라를 고른다
    city = pg.locator('[data-geo="city.0"]')
    city.scroll_into_view_if_needed(); city.fill(""); city.focus(); pg.wait_for_timeout(700)
    pg.evaluate("__kb(170)"); pg.wait_for_timeout(300)
    d = pg.evaluate(BOX, "#geo-list-city-0")
    check("B 키보드가 떠 있어도 도시 목록이 보이는 영역 안에 있다", d and d["bottom"] <= 170 and d["top"] >= 0 and d["h"] >= 64, d)
    check("자바스크립트 오류 없음", not errs, errs[:2])
    ctx.close()

    for label, w, h, mobile in [("세로 휴대폰", 390, 844, True), ("컴퓨터", 1280, 800, False)]:
        ctx = b.new_context(viewport={"width": w, "height": h}, has_touch=mobile, is_mobile=mobile); ctx.route("**/geo/**", geo_route)
        pg = ctx.new_page()
        pg.goto(BASE + "/?demo=1&gate=off", timeout=60000); pg.wait_for_timeout(1500)
        pg.evaluate("S.user = DEMO_USER; go('u-input')"); pg.wait_for_timeout(400)
        y0 = pg.evaluate("scrollY")
        country = pg.locator('[data-geo="country"]'); country.fill(""); country.focus(); pg.wait_for_timeout(500)
        e = pg.evaluate(BOX, "#geo-list-country")
        check(f"D {label}: 칸 아래로 열리고(위로 뒤집지 않음) 화면이 튀지 않는다", e and not e["up"] and pg.evaluate("scrollY") == y0 and e["h"] >= 200, [e, y0, pg.evaluate("scrollY")])
        ctx.close()
    b.close()

print("---")
print("ALL PASS" if not fails else "FAILED: " + ", ".join(fails))
sys.exit(1 if fails else 0)
