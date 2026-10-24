#!/usr/bin/env python3
"""빈 칸일 때 '생략 없는 전체 목록'이 나오는가.

신고: 아무것도 입력하지 않았을 때 국가·도시 목록의 전체 목록이 보이지 않는다.
원인: 프론트가 국가를 slice(0, 60) 으로, 도시를 limit=20 으로 말없이 잘랐다(백엔드도 50 상한).
      화면 어디에도 '몇 개 중 몇 개'인지 적히지 않아 잘린 것을 알 수 없었다.
원인 2: 칸에 값이 이미 있으면(고른 나라·저장된 여행) 열자마자 그 값으로 걸러 '미국' 하나만 보였다.
원인 3: 서버가 도시를 첫 샤드(인구 상위)·한 번 2000곳까지만 줘서 큰 나라는 끝까지 닿을 수 없었다.
       → 빈 칸 목록은 서버가 쪽(offset)으로 그 나라 전체를 주고, '더 보기'가 다음 쪽을 받는다.

    python3 test_geo_full_list.py http://127.0.0.1:8772
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


# 248개국(실제 규모) · 한 나라에 도시 120곳(잘리기 쉬운 규모)
COUNTRIES = [{"iso2": "US", "name": "United States", "ko": "미국", "capital": "Washington", "population": 327000000, "continent": "NA"},
             {"iso2": "JP", "name": "Japan", "ko": "일본", "capital": "Tokyo", "population": 126000000, "continent": "AS"}] + \
            [{"iso2": "X%02d" % i, "name": "Testland %03d" % i, "ko": "테스트국 %03d" % i, "capital": "", "population": 1000 + i, "continent": "EU"} for i in range(246)]
# 도시 1,234곳 — 서버 한 쪽(500)보다 많아 '더 보기'가 서버에서 다음 쪽을 받아야 끝까지 닿는다
CITIES = [{"id": i, "name": "City %04d" % i, "ko": "", "label": "City %04d" % i, "region": "R", "population": 100000 - i} for i in range(1234)]
city_calls = []


def route(r):
    from urllib.parse import parse_qs, urlparse
    u = r.request.url
    if "/geo/countries" in u:
        body = {"countries": COUNTRIES, "attribution": "GeoNames, CC BY 4.0"}
    else:
        # 실제 백엔드처럼: q 로 거르고, offset·limit 로 쪽을 나누고, total 은 맞는 것 전부
        qs = parse_qs(urlparse(u).query)
        q = qs.get("q", [""])[0].strip().lower()
        off, lim = int(qs.get("offset", ["0"])[0]), int(qs.get("limit", ["20"])[0])
        city_calls.append((q, off, lim))
        rows = [c for c in CITIES if not q or q in (c["name"] + c["label"]).lower()]
        body = {"country": "US", "cities": rows[off:off + lim], "total": len(rows), "attribution": "GeoNames, CC BY 4.0"}
    r.fulfill(status=200, content_type="application/json", body=json.dumps(body, ensure_ascii=False))


def opts(pg, sel):
    return pg.evaluate("[...document.querySelectorAll('%s .geo-opt b')].map(b => b.textContent)" % sel)


with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True)
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.route("**/geo/**", route)
    pg.goto(BASE + "/?demo=1"); pg.wait_for_timeout(720)
    pg.evaluate("S.user = DEMO_USER; go('u-input')"); pg.wait_for_timeout(320)

    # ── 1. 국가: 빈 칸 → 전체 248개국 ──
    pg.fill("#geo-country", ""); pg.focus("#geo-country"); pg.wait_for_timeout(420)
    n1 = len(opts(pg, "#geo-list-country"))
    more = pg.evaluate("!!document.querySelector('#geo-list-country .geo-more')")
    check("빈 칸: 국가 목록이 60개에서 잘리지 않는다", n1 > 60, f"{n1}개")
    check("빈 칸: 첫 묶음은 80줄", n1 == 80, f"{n1}개")
    check("빈 칸: 남은 줄은 '더 보기'로 이어진다", more)
    cnt = pg.inner_text("#geo-list-country .geo-count")
    check("빈 칸: '전체 248개국'을 화면에 적는다", "248" in cnt and "개국" in cnt, cnt)

    # ── 2. 더 보기 → 전부 도달(생략 없음) ──
    for _ in range(4):
        btn = pg.locator("#geo-list-country [data-act='geo-more']")
        if not btn.count():
            break
        btn.click(); pg.wait_for_timeout(120)
    n2 = len(opts(pg, "#geo-list-country"))
    check("더 보기를 끝까지 누르면 248개국 전부", n2 == 248, f"{n2}개")
    check("전부 나오면 '더 보기'가 사라진다", not pg.evaluate("!!document.querySelector('#geo-list-country .geo-more')"))

    # ── 2-1. 칸에 이미 나라가 있어도(고른 뒤·저장된 여행) 열면 전체 목록, 적힌 나라는 표시만 ──
    pg.locator("#geo-list-country .geo-opt", has_text="미국").first.click(); pg.wait_for_timeout(200)
    check("나라를 고르면 칸이 채워진다", pg.input_value("#geo-country") == "미국")
    pg.evaluate("document.activeElement.blur()"); pg.wait_for_timeout(250)
    pg.focus("#geo-country"); pg.wait_for_timeout(400)
    n3 = len(opts(pg, "#geo-list-country"))
    check("값이 있는 칸을 열어도 '미국' 하나로 걸러지지 않는다(전체 목록)", n3 >= 80, f"{n3}개")
    check("적힌 나라가 목록에서 선택 표시된다", pg.evaluate(
        "(() => { const li = document.querySelector('#geo-list-country .geo-opt[aria-selected=\"true\"] b'); return li && li.textContent; })()") == "미국")
    pg.keyboard.type("일"); pg.wait_for_timeout(300)
    check("글자를 치면 그때부터 거른다", opts(pg, "#geo-list-country") == ["일본"], str(opts(pg, "#geo-list-country")))
    pg.keyboard.press("Escape"); pg.fill("#geo-country", "미국"); pg.keyboard.press("Escape")
    pg.evaluate("S.draft.countries[0] = '미국'; draftSync(S.draft)"); pg.wait_for_timeout(80)

    # ── 3. 도시: 빈 칸 → 서버 쪽을 이어 받아 1,234곳 전부 + 전체 개수 ──
    pg.fill('[data-geo="city.0"]', ""); pg.focus('[data-geo="city.0"]'); pg.wait_for_timeout(500)
    c1 = len(opts(pg, "#geo-list-city-0"))
    ccnt = pg.inner_text("#geo-list-city-0 .geo-count")
    check("도시도 20곳에서 잘리지 않는다", c1 > 20, f"{c1}곳")
    check("도시 전체 개수(서버의 그 나라 전부)를 화면에 적는다", "1,234" in ccnt and "80곳 표시" in ccnt, ccnt)
    for _ in range(40):
        btn = pg.locator("#geo-list-city-0 [data-act='geo-more']")
        if not btn.count():
            break
        btn.click(); pg.wait_for_timeout(160)
    c2 = len(opts(pg, "#geo-list-city-0"))
    check("더 보기로 서버의 다음 쪽까지 받아 1,234곳 전부", c2 == 1234, f"{c2}곳")
    check("빈 칸 목록은 offset 으로 쪽을 받는다(500·1000)", {o for q, o, _ in city_calls if not q} >= {0, 500, 1000}, str(city_calls))
    check("끝까지 보면 '전체 1,234곳 중 1,234곳 표시'·더 보기 없음",
          "1,234곳 중 1,234곳" in pg.inner_text("#geo-list-city-0 .geo-count")
          and not pg.evaluate("!!document.querySelector('#geo-list-city-0 .geo-more')"))
    labels = opts(pg, "#geo-list-city-0")
    check("빠지거나 겹친 줄이 없다", len(set(labels)) == 1234 and labels[0] == "City 0000" and labels[-1] == "City 1233")

    # ── 3-1. 칸에 도시가 이미 있어도 열면 전체(인구순) 목록 ──
    pg.locator("#geo-list-city-0 .geo-opt", has_text="City 0005").first.click(); pg.wait_for_timeout(200)
    pg.evaluate("document.activeElement.blur()"); pg.wait_for_timeout(250)
    pg.focus('[data-geo="city.0"]'); pg.wait_for_timeout(450)
    c4 = len(opts(pg, "#geo-list-city-0"))
    check("값이 있는 도시 칸을 열어도 전체 목록", c4 >= 80, f"{c4}곳")
    check("적힌 도시가 목록에서 선택 표시된다", pg.evaluate(
        "(() => { const li = document.querySelector('#geo-list-city-0 .geo-opt[aria-selected=\"true\"] b'); return li && li.textContent; })()") == "City 0005")

    # ── 4. 검색하면 전체 개수도 함께 줄어든다 ──
    pg.fill('[data-geo="city.0"]', "City 0012"); pg.wait_for_timeout(420)
    c3 = opts(pg, "#geo-list-city-0")
    check("검색하면 결과만 남고 개수도 그에 맞다", c3 == ["City 0012"] and "전체 1곳" in pg.inner_text("#geo-list-city-0 .geo-count"), str(c3))

    # ── 5. 넓은 화면/좁은 화면 모두 넘침 없음 ──
    for w in (320, 390, 820):
        pg.set_viewport_size({"width": w, "height": 800}); pg.wait_for_timeout(200)
        pg.fill("#geo-country", ""); pg.focus("#geo-country"); pg.wait_for_timeout(300)
        ok = pg.evaluate("(() => { const u = document.getElementById('geo-list-country'), r = u.getBoundingClientRect();"
                         " return r.left >= 0 && r.right <= innerWidth + 1 && document.documentElement.scrollWidth <= innerWidth + 1; })()")
        check(f"{w}px: 전체 목록이 화면 밖으로 넘치지 않는다", ok)

    check("JS 오류 없음", not errs, str(errs[:2]))
    b.close()

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
