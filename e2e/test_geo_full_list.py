#!/usr/bin/env python3
"""빈 칸일 때 '생략 없는 전체 목록'이 나오는가.

신고: 아무것도 입력하지 않았을 때 국가·도시 목록의 전체 목록이 보이지 않는다.
원인: 프론트가 국가를 slice(0, 60) 으로, 도시를 limit=20 으로 말없이 잘랐다(백엔드도 50 상한).
      화면 어디에도 '몇 개 중 몇 개'인지 적히지 않아 잘린 것을 알 수 없었다.
원인 2: 칸에 값이 이미 있으면(고른 나라·저장된 여행) 열자마자 그 값으로 걸러 '미국' 하나만 보였다.
원인 3: 서버가 도시를 첫 샤드(인구 상위)·한 번 2000곳까지만 줘서 큰 나라는 끝까지 닿을 수 없었다.
       → 빈 칸 목록은 서버가 쪽(offset)으로 그 나라 전체를 준다.
11/05 사용자 지시: '더 보기'를 누르지 않아도 불러온 전체 목록이 보여야 한다.
       → 불러온 것은 처음부터 전부 그리고(국가 248·도시 한 쪽 500), 서버에 남은 도시는 목록을 내리면 저절로 이어 받는다.
         '더 보기'(다시 불러오기) 단추는 이어 받기가 실패했을 때만 목록 안에 나온다.

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
# 도시 1,234곳 — 서버 한 쪽(500)보다 많아, 목록을 내려 서버에서 다음 쪽을 이어 받아야 끝까지 닿는다
CITIES = [{"id": i, "name": "City %04d" % i, "ko": "", "label": "City %04d" % i, "region": "R", "population": 100000 - i} for i in range(1234)]
city_calls = []
FAIL_ONCE = set()   # 이 offset 은 한 번 실패시킨다(다시 불러오기 검사)


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
        if off in FAIL_ONCE:
            FAIL_ONCE.discard(off); r.fulfill(status=503, body="busy"); return
        rows = [c for c in CITIES if not q or q in (c["name"] + c["label"]).lower()]
        body = {"country": "US", "cities": rows[off:off + lim], "total": len(rows), "attribution": "GeoNames, CC BY 4.0"}
    r.fulfill(status=200, content_type="application/json", body=json.dumps(body, ensure_ascii=False))


def scroll_end(pg, sel):
    pg.evaluate("(() => { const u = document.querySelector('%s'); u.scrollTop = u.scrollHeight; u.dispatchEvent(new Event('scroll')); })()" % sel)


def opts(pg, sel):
    return pg.evaluate("[...document.querySelectorAll('%s .geo-opt b')].map(b => b.textContent)" % sel)


with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True)
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.route("**/geo/**", route)
    pg.goto(BASE + "/?demo=1&gate=off"); pg.wait_for_timeout(720)
    pg.evaluate("S.user = DEMO_USER; go('u-input')"); pg.wait_for_timeout(320)

    # ── 1. 국가: 빈 칸 → 처음부터 248개국 전부(더 보기 없이) ──
    pg.fill("#geo-country", ""); pg.focus("#geo-country"); pg.wait_for_timeout(420)
    n1 = len(opts(pg, "#geo-list-country"))
    check("빈 칸: 국가 248개국이 처음부터 전부 보인다", n1 == 248, f"{n1}개")
    check("빈 칸: '더 보기' 단추가 없다", not pg.evaluate("!!document.querySelector('#geo-list-country [data-act=geo-more]')"))
    cnt = pg.inner_text("#geo-list-country .geo-count")
    check("빈 칸: '전체 248개국 중 248개국 표시'", "248개국 중 248개국" in cnt, cnt)
    labels0 = opts(pg, "#geo-list-country")
    check("빠지거나 겹친 나라가 없다", len(set(labels0)) == 248)

    # ── 2. 목록 안에서 바깥으로 포커스가 나가면 닫힌다 ──
    pg.evaluate("document.activeElement.blur()"); pg.wait_for_timeout(300)
    check("바깥으로 포커스가 나가면 목록이 닫힌다", pg.evaluate("document.getElementById('geo-list-country').hidden"))
    pg.focus("#geo-country"); pg.wait_for_timeout(400)

    # ── 2-1. 칸에 이미 나라가 있어도(고른 뒤·저장된 여행) 열면 전체 목록, 적힌 나라는 표시만 ──
    pg.locator("#geo-list-country .geo-opt", has_text="미국").first.click(); pg.wait_for_timeout(200)
    check("나라를 고르면 칸이 채워진다", pg.input_value("#geo-country") == "미국")
    pg.evaluate("document.activeElement.blur()"); pg.wait_for_timeout(250)
    pg.focus("#geo-country"); pg.wait_for_timeout(400)
    n3 = len(opts(pg, "#geo-list-country"))
    check("값이 있는 칸을 열어도 '미국' 하나로 걸러지지 않는다(전체 248개국)", n3 == 248, f"{n3}개")
    check("적힌 나라가 목록에서 선택 표시된다", pg.evaluate(
        "(() => { const li = document.querySelector('#geo-list-country .geo-opt[aria-selected=\"true\"] b'); return li && li.textContent; })()") == "미국")
    pg.keyboard.type("일"); pg.wait_for_timeout(300)
    check("글자를 치면 그때부터 거른다", opts(pg, "#geo-list-country") == ["일본"], str(opts(pg, "#geo-list-country")))
    pg.keyboard.press("Escape"); pg.fill("#geo-country", "미국"); pg.keyboard.press("Escape")
    pg.evaluate("S.draft.countries[0] = '미국'; draftSync(S.draft)"); pg.wait_for_timeout(80)

    # ── 3. 도시: 빈 칸 → 받은 쪽(500곳) 전부 + 내리면 서버의 다음 쪽을 저절로 이어 받아 1,234곳 전부 ──
    pg.fill('[data-geo="city.0"]', ""); pg.focus('[data-geo="city.0"]'); pg.wait_for_timeout(500)
    c1 = len(opts(pg, "#geo-list-city-0"))
    ccnt = pg.inner_text("#geo-list-city-0 .geo-count")
    check("도시: 받은 한 쪽(500곳)이 처음부터 전부 보인다", c1 == 500, f"{c1}곳")
    check("도시 전체 개수(서버의 그 나라 전부)를 화면에 적는다", "1,234" in ccnt and "500곳 표시" in ccnt, ccnt)
    check("도시: '더 보기' 단추가 없다(남은 줄은 안내만)",
          not pg.evaluate("!!document.querySelector('#geo-list-city-0 [data-act=geo-more]')")
          and "내리면" in pg.inner_text("#geo-list-city-0 .geo-more"), pg.inner_text("#geo-list-city-0 .geo-more"))
    for _ in range(6):
        scroll_end(pg, "#geo-list-city-0"); pg.wait_for_timeout(350)
    c2 = len(opts(pg, "#geo-list-city-0"))
    check("내리기만 해도 서버의 다음 쪽까지 받아 1,234곳 전부", c2 == 1234, f"{c2}곳")
    check("빈 칸 목록은 offset 으로 쪽을 받는다(500·1000)", {o for q, o, _ in city_calls if not q} >= {0, 500, 1000}, str(city_calls))
    check("끝까지 보면 '전체 1,234곳 중 1,234곳 표시'·남은 줄 안내 없음",
          "1,234곳 중 1,234곳" in pg.inner_text("#geo-list-city-0 .geo-count")
          and not pg.evaluate("!!document.querySelector('#geo-list-city-0 .geo-more')"))
    labels = opts(pg, "#geo-list-city-0")
    check("빠지거나 겹친 줄이 없다", len(set(labels)) == 1234 and labels[0] == "City 0000" and labels[-1] == "City 1233")
    check("목록은 내리는 동안 열린 채, 칸이 포커스를 지킨다",
          not pg.evaluate("document.getElementById('geo-list-city-0').hidden") and pg.evaluate("document.activeElement.dataset.geo") == "city.0")

    # ── 3-0. 이어 받기가 실패했을 때만 목록 안에 '다시 불러오기' 단추 ──
    pg.evaluate("document.activeElement.blur()"); pg.wait_for_timeout(250)
    pg.evaluate("GEO.cities.clear()"); FAIL_ONCE.add(500)
    pg.fill('[data-geo="city.0"]', ""); pg.focus('[data-geo="city.0"]'); pg.wait_for_timeout(500)
    scroll_end(pg, "#geo-list-city-0"); pg.wait_for_timeout(450)
    btn = pg.locator("#geo-list-city-0 [data-act='geo-more']")
    check("실패하면 그때만 '다시 불러오기' 단추가 나온다", btn.count() == 1 and "다시 불러오기" in btn.inner_text(), btn.count())
    check("실패해도 이미 받은 500곳은 그대로", len(opts(pg, "#geo-list-city-0")) == 500)
    pd = pg.evaluate("""() => { const b = document.querySelector('#geo-list-city-0 [data-act=geo-more]');
      const ev = new PointerEvent('pointerdown', { bubbles: true, cancelable: true, pointerType: 'touch' });
      b.dispatchEvent(ev); return ev.defaultPrevented; }""")
    check("'다시 불러오기'는 눌러도 칸의 포커스를 빼앗지 않는다", pd)
    btn.tap(); pg.wait_for_timeout(450)
    check("'다시 불러오기'를 누르면 다음 쪽을 받고 목록은 열린 채",
          len(opts(pg, "#geo-list-city-0")) >= 1000 and not pg.evaluate("document.getElementById('geo-list-city-0').hidden"),
          len(opts(pg, "#geo-list-city-0")))
    for _ in range(4):
        scroll_end(pg, "#geo-list-city-0"); pg.wait_for_timeout(300)
    check("다시 불러온 뒤에도 끝까지 닿는다(1,234곳)", len(opts(pg, "#geo-list-city-0")) == 1234)

    # ── 3-1. 칸에 도시가 이미 있어도 열면 전체(인구순) 목록 ──
    pg.locator("#geo-list-city-0 .geo-opt", has_text="City 0005").first.click(); pg.wait_for_timeout(200)
    pg.evaluate("document.activeElement.blur()"); pg.wait_for_timeout(250)
    pg.focus('[data-geo="city.0"]'); pg.wait_for_timeout(450)
    c4 = len(opts(pg, "#geo-list-city-0"))
    check("값이 있는 도시 칸을 열어도 전체 목록(받은 500곳)", c4 >= 500, f"{c4}곳")
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
