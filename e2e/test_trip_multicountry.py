#!/usr/bin/env python3
"""여행 입력·설정 수정의 '국가 추가' 와 병렬 구조 E2E.

요구: 나라 카드 하단에 '도시 추가'와 같은 모양의 '국가 추가' 버튼. 국가가 2개 이상이면
단순 국가-도시 목록이 아니라 국가별로 나뉜 병렬 구조로 보여 주고 설정한다.

    python3 test_trip_multicountry.py http://127.0.0.1:8772
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


CO = [{"iso2": "US", "name": "United States", "ko": "미국", "capital": "Washington", "population": 327000000, "continent": "NA"},
      {"iso2": "JP", "name": "Japan", "ko": "일본", "capital": "Tokyo", "population": 126000000, "continent": "AS"}]
CI = {"US": [{"id": 1, "name": "New York City", "ko": "뉴욕", "label": "뉴욕", "region": "New York", "population": 8800000}],
      "JP": [{"id": 5, "name": "Tokyo", "ko": "도쿄", "label": "도쿄", "region": "Tokyo", "population": 13900000}]}


def route(r):
    u = r.request.url
    if "/geo/countries" in u:
        body = {"countries": CO, "attribution": "GeoNames, CC BY 4.0"}
    else:
        cc = "JP" if "country=JP" in u else "US"
        body = {"country": cc, "cities": CI[cc], "attribution": "GeoNames, CC BY 4.0"}
    r.fulfill(status=200, content_type="application/json", body=json.dumps(body, ensure_ascii=False))


SHAPE = """() => {
  const cols = [...document.querySelectorAll('.geo-col')];
  const par = document.querySelector('.geo-par');
  return {
    cards: document.querySelectorAll('.ctry-card').length,
    cols: cols.length,
    colCities: cols.map(c => c.querySelectorAll('.city-card').length),
    colAdd: cols.map(c => !!c.querySelector('.add-city')),
    colCountry: cols.map(c => (c.querySelector('.ctry-card input') || {}).value || ''),
    colsCss: par ? getComputedStyle(par).gridTemplateColumns.split(' ').length : 0,
    addCountry: !!document.querySelector('[data-act="add-country"]'),
    addCountryLabel: (document.querySelector('[data-act="add-country"]') || {}).textContent || '',
    addCity: document.querySelectorAll('[data-act="add-city"]').length,
    addCitySameStyle: (() => { const a = document.querySelector('[data-act="add-country"]'), c = document.querySelector('[data-act="add-city"]');
      if (!a || !c) return false; const x = getComputedStyle(a), y = getComputedStyle(c);
      return x.borderStyle === y.borderStyle && x.borderRadius === y.borderRadius && x.fontSize === y.fontSize && x.height === y.height; })(),
    err: [...document.querySelectorAll('.err')].map(e => e.textContent.trim()).filter(Boolean),
    overflow: document.documentElement.scrollWidth > innerWidth + 1,
  }; }"""

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True)
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.route("**/geo/**", route)
    pg.goto(BASE + "/?demo=1"); pg.wait_for_timeout(720)
    pg.evaluate("S.user = DEMO_USER; go('u-input')"); pg.wait_for_timeout(320)

    # ── 1. 한 국가일 때: 지금 모양 그대로 + 국가 추가 버튼 ──
    s = pg.evaluate(SHAPE)
    check("한 국가: 국가 카드 1개", s["cards"] == 1 and s["cols"] == 1, str(s["cards"]))
    check("한 국가: 도시 추가 버튼이 국가 안에 있다", s["colAdd"] == [True], str(s["colAdd"]))
    check("'국가 추가' 버튼이 있다", s["addCountry"] and "국가 추가" in s["addCountryLabel"], s["addCountryLabel"])
    check("'국가 추가'는 '도시 추가'와 같은 모양", s["addCitySameStyle"], "style mismatch")

    # ── 2. 국가 추가 → 병렬 구조 ──
    pg.locator('[data-act="add-country"]').click(); pg.wait_for_timeout(320)
    s = pg.evaluate(SHAPE)
    check("국가를 추가하면 국가 카드가 2개", s["cards"] == 2 and s["cols"] == 2, str(s))
    check("국가마다 자기 도시 묶음을 갖는다", s["colCities"] == [2, 1], str(s["colCities"]))
    check("국가마다 자기 '도시 추가' 버튼을 갖는다", s["colAdd"] == [True, True])
    check("병렬 컨테이너(.geo-par)로 묶인다", s["colsCss"] >= 1)
    check("390px 에서는 한 열로 쌓인다(날짜 칸이 눌리지 않게)", s["colsCss"] == 1, str(s["colsCss"]))
    check("좁은 화면에서도 가로 넘침 없음", not s["overflow"])

    # ── 3. 두 번째 국가에 도시 추가 → 그 국가에만 붙는다 ──
    pg.locator('.geo-col[data-col="1"] [data-act="add-city"]').click(); pg.wait_for_timeout(300)
    s = pg.evaluate(SHAPE)
    check("두 번째 국가의 도시 추가는 그 국가에만 붙는다", s["colCities"] == [2, 2], str(s["colCities"]))

    # ── 4. 넓은 화면에서는 실제로 나란히 ──
    pg.set_viewport_size({"width": 820, "height": 900}); pg.wait_for_timeout(320)
    s = pg.evaluate(SHAPE)
    check("820px 에서는 두 국가가 나란히 선다", s["colsCss"] == 2, str(s["colsCss"]))
    pg.set_viewport_size({"width": 390, "height": 844}); pg.wait_for_timeout(300)

    # ── 5. 국가 이름 비우고 제출 → 그 국가 자리에 오류 ──
    pg.fill('.geo-col[data-col="1"] .ctry-card input', "")
    pg.locator('[data-act="submit-trip"]').click(); pg.wait_for_timeout(360)
    s = pg.evaluate(SHAPE)
    check("국가 이름이 비면 제출이 막히고 그 자리에 오류가 선다",
          any("국가 2" in e for e in s["err"]), str(s["err"]))

    # ── 6. 도시 선택이 '그 도시의 국가'를 쓴다 ──
    pg.fill('.geo-col[data-col="1"] .ctry-card input', "일본"); pg.dispatch_event('.geo-col[data-col="1"] .ctry-card input', "input"); pg.wait_for_timeout(200)
    pg.focus('.geo-col[data-col="1"] .city-card input'); pg.wait_for_timeout(500)
    # 목록 id 는 포커스된 칸의 aria-controls 에서 가져온다(도시 순번을 손으로 세지 않는다)
    opts = pg.evaluate("""() => { const el = document.activeElement, ul = document.getElementById(el.getAttribute('aria-controls'));
      return { key: el.dataset.geo, opts: [...ul.querySelectorAll('.geo-opt b')].map(b => b.textContent) }; }""")
    check("두 번째 국가의 도시 목록은 그 국가(일본) 기준이다", opts["opts"] == ["도쿄"], str(opts))

    # ── 7. 국가 삭제 → 한 국가 구조로 되돌아간다 ──
    pg.locator('.geo-col[data-col="1"] [data-act="del-country"]').click(); pg.wait_for_timeout(320)
    s = pg.evaluate(SHAPE)
    check("국가를 지우면 한 국가 구조로 돌아간다", s["cards"] == 1 and s["cols"] == 1, str(s))
    check("지운 국가의 도시도 함께 사라진다", s["colCities"] == [2], str(s["colCities"]))

    # ── 8. 여행 설정 수정 화면에도 같은 버튼·같은 구조 ──
    pg.evaluate("openTripEdit(); go('u-edit')"); pg.wait_for_timeout(420)
    s = pg.evaluate(SHAPE)
    check("여행 설정 수정에도 '국가 추가' 버튼이 있다", s["addCountry"] and s["cards"] == 1, str(s))
    pg.locator('[data-act="add-country"]').click(); pg.wait_for_timeout(320)
    s = pg.evaluate(SHAPE)
    check("여행 설정 수정에서도 병렬 구조가 된다", s["cards"] == 2 and s["cols"] == 2, str(s))

    # ── 9. 저장하면 여행에 국가 목록이 남는다 ──
    pg.evaluate("""() => { S.draft.countries = ['미국', '일본'];
      S.draft.cities = [{ name: '뉴욕', start: S.draft.cities[0].start, end: S.draft.cities[0].end, ci: 0 },
                        { name: '도쿄', start: S.draft.cities[0].end, end: Dt.add(S.draft.cities[0].end, 2), ci: 1 }]; }""")
    pg.evaluate("() => { const d = S.draft; S.trip = tripFromInput(d); }")
    saved = pg.evaluate("({ c: S.trip.countries, first: S.trip.country, ci: S.trip.cities.map(c => c.ci) })")
    check("저장하면 국가 목록과 도시별 국가가 남는다", saved["c"] == ["미국", "일본"] and saved["ci"] == [0, 1], str(saved))
    back = pg.evaluate("() => { const d = tripInputOf(S.trip); return { c: d.countries, ci: d.cities.map(c => c.ci), country: d.country }; }")
    check("저장한 여행을 다시 열면 국가 구조가 복원된다", back["c"] == ["미국", "일본"] and back["ci"] == [0, 1] and back["country"] == "미국", str(back))

    check("JS 오류 없음", not errs, str(errs[:2]))
    b.close()

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
