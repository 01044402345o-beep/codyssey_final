"""여행 입력의 나라·도시 선택 목록(combobox) E2E.

/geo/* 응답은 Playwright 로 가짜를 준다(CI 서버에는 Firestore 서비스 계정이 없다). 실제 데이터는 geo-refresh 가 쌓은 것.
확인: 포커스하면 목록 · 한국어/영문/별칭 검색 · 고르면 칸이 채워짐 · 키보드(↑↓·Enter·Esc) · 나라를 고른 뒤 도시 목록 ·
'호주'(GeoNames 이름은 오스트레일리아)도 영어권 · 목록을 못 받으면 예전처럼 글자 입력 · 좁은 화면 넘침 없음.

    cd backend && uvicorn app.main:app --port 8768
    python ../e2e/test_geo_picker.py http://localhost:8768
"""
import json
import sys
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8768"
results = []


def check(name, cond, extra=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))


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


def open_input(page):
    page.goto(BASE + "/?demo=1"); page.wait_for_timeout(700)
    page.evaluate("S.user = DEMO_USER; go('u-input')"); page.wait_for_timeout(300)


def options(page, sel):
    return page.evaluate(f"[...document.querySelectorAll('{sel} .geo-opt b')].map(b => b.textContent)")


with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 390, "height": 844}, has_touch=True)
    ctx.route("**/geo/**", geo_route)
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    open_input(page)

    country = page.locator('[data-geo="country"]')
    check("나라 칸은 combobox(목록과 연결)", country.get_attribute("role") == "combobox"
          and country.get_attribute("aria-controls") == "geo-list-country")
    country.fill(""); country.focus(); page.wait_for_timeout(300)
    check("포커스하면 나라 목록이 보인다", page.locator("#geo-list-country").is_visible()
          and len(options(page, "#geo-list-country")) == 30 and country.get_attribute("aria-expanded") == "true")
    lst = page.locator("#geo-list-country")
    check("목록이 칸보다 길면 스크롤이 생긴다", page.evaluate(
        "(() => { const u = document.getElementById('geo-list-country'); return u.scrollHeight > u.clientHeight + 50; })()"))
    box = lst.bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.wheel(0, 400); page.wait_for_timeout(250)
    check("마우스 휠로 목록이 스크롤되고 목록은 열린 채", page.evaluate("document.getElementById('geo-list-country').scrollTop") > 100
          and lst.is_visible() and country.input_value() == "", str(page.evaluate("document.getElementById('geo-list-country').scrollTop")))
    # 손가락 스크롤: 항목 위에 손가락을 대고(pointerdown) 끌면 브라우저가 pointercancel 을 보낸다 — 아무것도 고르지 않아야 한다
    page.evaluate("""(() => { const li = document.querySelector('#geo-list-country .geo-opt');
      li.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, cancelable: true, pointerType: 'touch' }));
      li.dispatchEvent(new PointerEvent('pointercancel', { bubbles: true, pointerType: 'touch' })); })()""")
    page.wait_for_timeout(300)
    check("손가락으로 끌어 스크롤하면 아무것도 고르지 않고 목록이 열린 채", country.input_value() == "" and lst.is_visible())
    # 스크롤바를 마우스로 끄는 동안(칸이 포커스를 잃어도) 닫히지 않는다
    page.evaluate("""(() => { const u = document.getElementById('geo-list-country');
      u.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, cancelable: true, pointerType: 'mouse' }));
      document.activeElement.blur(); })()""")
    page.wait_for_timeout(300)
    still = lst.is_visible()
    page.evaluate("document.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, pointerType: 'mouse' }))")
    page.wait_for_timeout(150)
    check("스크롤바를 끄는 동안 목록이 닫히지 않고, 떼면 칸으로 포커스가 돌아온다",
          still and page.evaluate("document.activeElement && document.activeElement.dataset.geo") == "country")
    check("출처 표기(GeoNames CC BY 4.0)", "GeoNames" in page.inner_text("#geo-list-country"))

    country.fill("호주"); page.wait_for_timeout(250)
    check("별칭 '호주' 로 오스트레일리아를 찾는다", options(page, "#geo-list-country") == ["오스트레일리아"])
    page.keyboard.press("ArrowDown"); page.keyboard.press("Enter"); page.wait_for_timeout(200)
    check("↓·Enter 로 고르면 칸이 채워지고 목록이 닫힌다", country.input_value() == "오스트레일리아"
          and page.evaluate("S.draft.country") == "오스트레일리아" and page.locator("#geo-list-country").is_hidden())
    check("오스트레일리아는 영어권 — '영어가 안 통할 수 있다' 경고 없음",
          page.locator('[data-live="noneng"]').is_hidden())

    country.fill("jap"); page.wait_for_timeout(250)
    check("영문으로도 찾는다(jap → 일본)", options(page, "#geo-list-country") == ["일본"])
    page.keyboard.press("Escape"); page.wait_for_timeout(100)
    check("Esc 로 목록을 닫는다", page.locator("#geo-list-country").is_hidden())

    country.fill("미"); page.wait_for_timeout(250)
    page.locator("#geo-list-country .geo-opt").first.tap(); page.wait_for_timeout(250)
    check("목록을 탭해서 고른다(터치)", country.input_value() == "미국" and page.locator("#geo-list-country").is_hidden())

    city = page.locator('[data-geo="city.0"]')
    city.fill(""); city.focus(); page.wait_for_timeout(600)
    check("나라를 고른 뒤 도시 칸: 인구 상위 목록", options(page, "#geo-list-city-0")[:3] == ["뉴욕", "로스앤젤레스", "보스턴"],
          str(options(page, "#geo-list-city-0")))
    check("도시 행에 영문 이름·주·인구가 함께", "New York" in page.inner_text("#geo-list-city-0")
          and "880만" in page.inner_text("#geo-list-city-0"))
    city.fill("보스"); page.wait_for_timeout(600)
    check("한국어로 도시를 찾는다(보스 → 보스턴)", options(page, "#geo-list-city-0")[0] == "보스턴")
    page.keyboard.press("ArrowDown"); page.keyboard.press("Enter"); page.wait_for_timeout(200)
    check("도시를 고르면 칸이 채워진다", city.input_value() == "보스턴" and page.evaluate("S.draft.cities[0].name") == "보스턴")
    check("도시 검색은 고른 나라 코드로 서버에 묻는다", any("/geo/cities?country=US" in c for c in calls))
    check("목록에서 고른 도시는 GeoNames id(gid)를 함께 기억한다", page.evaluate("S.draft.cities[0].gid") == 3)
    city.fill("보스턴 시내"); page.wait_for_timeout(250)
    check("이름을 손으로 고치면 gid 를 버린다(다른 곳일 수 있다)", page.evaluate("S.draft.cities[0].gid === undefined"))
    page.keyboard.press("Escape")

    country.fill("아틀란티스"); page.wait_for_timeout(250)
    check("목록에 없는 나라도 그대로 쓸 수 있다는 안내", "적은 그대로 써도 돼요" in page.inner_text("#geo-list-country"))
    page.keyboard.press("Escape")
    city.fill(""); city.focus(); page.wait_for_timeout(500)
    check("목록에 없는 나라면 도시 칸은 안내만", "국가를 목록에서 고르면" in page.inner_text("#geo-list-city-0"))

    for w in (320, 390):
        page.set_viewport_size({"width": w, "height": 800}); page.wait_for_timeout(150)
        country.fill(""); country.focus(); page.wait_for_timeout(250)
        check(f"{w}px: 목록이 화면 밖으로 넘치지 않는다", page.evaluate(
            "(() => { const r = document.getElementById('geo-list-country').getBoundingClientRect(); "
            "return r.left >= 0 && r.right <= innerWidth + 1 && document.documentElement.scrollWidth <= innerWidth + 1; })()"))
    check("페이지 JS 오류 없음", not errors, "; ".join(errors[:3]))

    # 목록을 못 받으면(서버 오류) 예전처럼 글자 입력만
    ctx2 = b.new_context(viewport={"width": 390, "height": 844})
    ctx2.route("**/geo/**", lambda r: r.fulfill(status=503, content_type="application/json", body='{"detail":"geo_unavailable"}'))
    p2 = ctx2.new_page(); e2 = []; p2.on("pageerror", lambda e: e2.append(str(e)))
    open_input(p2)
    c2 = p2.locator('[data-geo="country"]'); c2.focus(); c2.fill("캐나다"); p2.wait_for_timeout(400)
    check("목록 서버 오류: 목록 없이 글자 입력은 그대로", p2.locator("#geo-list-country").is_hidden()
          and p2.evaluate("S.draft.country") == "캐나다" and not e2, "; ".join(e2[:2]))
    b.close()

print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
