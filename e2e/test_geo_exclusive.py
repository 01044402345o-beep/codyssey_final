#!/usr/bin/env python3
"""나라·도시 선택 목록은 '한 번에 하나만' 열린다 — 두 목록이 동시에 열리던 충돌 회귀 테스트.

실기기 신고: 여행 입력에서 나라 목록과 도시 목록이 둘 다 열려 화면이 겹친다.
원인: GEO.open 은 칸 하나짜리 상태인데 geoRender 가 다른 칸의 목록을 접지 않았다.
      주인을 잃은 목록은 Esc·바깥 탭으로도 닫히지 않아 유령으로 남았다.

    python3 test_geo_exclusive.py http://127.0.0.1:8772
"""
import json
import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8772"
passed = failed = 0


def check(name, ok, note=""):
    global passed, failed
    if ok:
        passed += 1; print("PASS " + name)
    else:
        failed += 1; print("FAIL " + name + (f"  [{note}]" if note else ""))


COUNTRIES = [{"iso2": "US", "name": "United States", "ko": "미국", "capital": "Washington", "population": 327000000, "continent": "NA"},
             {"iso2": "JP", "name": "Japan", "ko": "일본", "capital": "Tokyo", "population": 126000000, "continent": "AS"},
             {"iso2": "FR", "name": "France", "ko": "프랑스", "capital": "Paris", "population": 67000000, "continent": "EU"}] + \
            [{"iso2": "Z%s" % chr(65 + i), "name": "Testland %02d" % i, "ko": "테스트국 %02d" % i,
              "capital": "", "population": 1, "continent": "EU"} for i in range(20)]
CITIES = {"US": [{"id": 1, "name": "New York City", "ko": "뉴욕", "label": "뉴욕", "region": "New York", "population": 8800000},
                 {"id": 2, "name": "Boston", "ko": "보스턴", "label": "보스턴", "region": "Massachusetts", "population": 653833}]}


def route(r):
    u = r.request.url
    if "/geo/countries" in u:
        body = {"countries": COUNTRIES, "attribution": "GeoNames, CC BY 4.0"}
    else:
        cc = "US" if "country=US" in u else ""
        body = {"country": cc, "cities": CITIES.get(cc, []), "attribution": "GeoNames, CC BY 4.0"}
    r.fulfill(status=200, content_type="application/json", body=json.dumps(body, ensure_ascii=False))


# 화면에 실제로 보이는 geo 목록의 수와, 각 칸의 aria-expanded
STATE = """() => {
  const vis = [...document.querySelectorAll('.geo-list')].filter(u => {
    const r = u.getBoundingClientRect(); return !u.hidden && r.height > 0 && r.width > 0; }).map(u => u.id);
  const exp = [...document.querySelectorAll('[data-geo]')].map(e => [e.dataset.geo, e.getAttribute('aria-expanded')]);
  return { vis, exp, open: GEO.open && GEO.open.key }; }"""

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True)
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.route("**/geo/**", route)
    pg.goto(BASE + "/?demo=1"); pg.wait_for_timeout(700)
    pg.evaluate("S.user = DEMO_USER; go('u-input')"); pg.wait_for_timeout(320)
    pg.evaluate("S.draft.country = '미국'; S.draft.cities[0].name = ''; updateInputLive && updateInputLive()")
    pg.wait_for_timeout(120)

    # ── 1. 나라 목록만 열린다 ──
    pg.focus("#geo-country"); pg.wait_for_timeout(320)
    s = pg.evaluate(STATE)
    check("나라 칸에 포커스하면 나라 목록만 열린다", s["vis"] == ["geo-list-country"] and s["open"] == "country", str(s))

    # ── 2. 도시 칸으로 옮기면 나라 목록이 닫힌다 (핵심 결함) ──
    pg.focus('[data-geo="city.0"]'); pg.wait_for_timeout(420)
    s = pg.evaluate(STATE)
    check("도시 칸으로 옮기면 나라 목록이 닫힌다", "geo-list-country" not in s["vis"], str(s))
    check("동시에 열린 목록은 하나뿐이다", len(s["vis"]) == 1, str(s))
    check("도시 목록이 열린다", s["vis"] == ["geo-list-city-0"], str(s))
    check("나라 칸의 aria-expanded 가 false 로 돌아간다",
          dict(s["exp"]).get("country") == "false", str(s["exp"]))

    # ── 3. 다시 나라로 돌아오면 도시 목록이 닫힌다 ──
    pg.focus("#geo-country"); pg.wait_for_timeout(340)
    s = pg.evaluate(STATE)
    check("나라로 돌아오면 도시 목록이 닫힌다", s["vis"] == ["geo-list-country"], str(s))

    # ── 4. Esc 는 지금 열린 목록만 닫는다(유령 목록 없음) ──
    pg.keyboard.press("Escape"); pg.wait_for_timeout(180)
    s = pg.evaluate(STATE)
    check("Esc 로 열린 목록이 모두 닫힌다", s["vis"] == [] and s["open"] is None, str(s))

    # ── 5. 나라 목록을 연 뒤 도시로 옮기고 Esc — 남는 목록이 없어야 한다 ──
    pg.focus("#geo-country"); pg.wait_for_timeout(300)
    pg.focus('[data-geo="city.0"]'); pg.wait_for_timeout(400)
    pg.keyboard.press("Escape"); pg.wait_for_timeout(180)
    s = pg.evaluate(STATE)
    check("칸을 옮긴 뒤 Esc 를 눌러도 남는 목록이 없다", s["vis"] == [], str(s))

    # ── 6. 다른 칸의 목록을 키보드로 조작하지 않는다 ──
    pg.focus("#geo-country"); pg.wait_for_timeout(300)
    pg.focus('[data-geo="city.0"]'); pg.wait_for_timeout(380)
    pg.keyboard.press("ArrowDown"); pg.wait_for_timeout(200)
    s = pg.evaluate(STATE)
    check("도시 칸에서 ↓ 를 눌러도 나라 목록이 되살아나지 않는다", "geo-list-country" not in s["vis"], str(s))
    check("↓ 는 지금 칸의 목록을 연다", s["vis"] == ["geo-list-city-0"] and s["open"] == "city.0", str(s))

    # ── 7. 고르면 그 칸만 닫히고 값이 들어간다 ──
    pg.locator("#geo-list-city-0 .geo-opt").first.click(); pg.wait_for_timeout(250)
    s = pg.evaluate(STATE)
    val = pg.evaluate("document.querySelector('[data-geo=\"city.0\"]').value")
    check("항목을 고르면 목록이 닫히고 값이 채워진다", s["vis"] == [] and val == "뉴욕", f'{s} / {val!r}')

    # ── 8. 나라를 바꾸면 도시 칸이 새 나라 기준으로 다시 열린다 ──
    pg.focus("#geo-country"); pg.wait_for_timeout(300)
    pg.locator("#geo-list-country .geo-opt").first.click(); pg.wait_for_timeout(250)
    s = pg.evaluate(STATE)
    check("나라를 고르면 나라 목록만 닫힌다", s["vis"] == [], str(s))

    check("JS 오류 없음", not errs, str(errs[:2]))
    b.close()

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
