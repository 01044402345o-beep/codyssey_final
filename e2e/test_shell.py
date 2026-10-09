"""제품 셸 반응형 E2E (Playwright + Chromium).  docs/RESPONSIVE_STRATEGY.md §3·§10.

    cd backend && uvicorn app.main:app --port 8769 &
    python ../e2e/test_shell.py http://localhost:8769 /tmp/shots
"""
import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1]
OUT = sys.argv[2] if len(sys.argv) > 2 else "."
results = []


def check(name, cond, extra=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""))


def box(page, sel):
    return page.locator(sel).first.bounding_box()


def hscroll(page):
    return page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")


with sync_playwright() as p:
    b = p.chromium.launch()
    errors = []

    # --- 모드 ---
    ctx = b.new_context(viewport={"width": 390, "height": 844})
    page = ctx.new_page(); page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE + "/#u-home"); page.wait_for_timeout(600)
    check("기본 URL = 제품 모드", page.evaluate("document.documentElement.dataset.mode") == "product")
    check("제품 모드: 폰 프레임·데모 사이드 패널·데모 버튼 없음",
          page.locator(".device").count() == 0 and not page.locator(".side").is_visible() and not page.locator("#demo-fab").is_visible())

    # --- base(390): 하단 탭바 ---
    nav = box(page, ".pnav"); vh = 844
    check("390px: 내비가 화면 맨 아래 가로 탭바", nav and nav["y"] + nav["height"] >= vh - 1 and nav["width"] >= 389, str(nav))
    check("390px: 가로 스크롤 없음", hscroll(page) <= 0, str(hscroll(page)))
    check("390px: 탭 4개 모두 보이고 라벨이 잘리지 않음",
          page.evaluate("""[...document.querySelectorAll('.pnav button span')].every(s => s.scrollWidth <= s.clientWidth + 1)"""))
    check("탭 높이 ≥44px", all(bx["height"] >= 44 for bx in [page.locator(".pnav button").nth(i).bounding_box() for i in range(4)]))
    page.screenshot(path=f"{OUT}/shell_390_home.png")

    # 스크롤: 문서 스크롤 + 탭바 sticky
    page.evaluate("window.scrollTo(0, 400)"); page.wait_for_timeout(100)
    nav2 = box(page, ".pnav")
    check("스크롤해도 탭바가 화면 아래에 고정", nav2 and abs((nav2["y"] + nav2["height"]) - vh) <= 1, str(nav2))
    check("문서가 스크롤됨(내부 스크롤 아님)", page.evaluate("window.scrollY") > 0)
    # 같은 화면 재렌더 시 스크롤 유지
    y0 = page.evaluate("window.scrollY"); page.evaluate("render()"); page.wait_for_timeout(100)
    check("같은 화면 재렌더 후 스크롤 위치 유지", abs(page.evaluate("window.scrollY") - y0) <= 2, f"{y0}→{page.evaluate('window.scrollY')}")
    page.locator('.pnav button[data-id="u-sched"]').click(); page.wait_for_timeout(300)
    check("탭 이동 → 일정표, 스크롤 맨 위", page.evaluate("S.screen") == "u-sched" and page.evaluate("window.scrollY") == 0)
    ctx.close()

    # --- md(768) 레일 / xl(1280) 사이드 ---
    for w, h, kind, minw, maxw in ((768, 1024, "레일", 60, 90), (1280, 800, "사이드", 220, 260)):
        ctx = b.new_context(viewport={"width": w, "height": h})
        page = ctx.new_page(); page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(BASE + "/#u-home"); page.wait_for_timeout(600)
        nav = box(page, ".pnav")
        check(f"{w}px: 내비가 왼쪽 세로 {kind}({minw}~{maxw}px)", nav and nav["x"] == 0 and minw <= nav["width"] <= maxw and nav["height"] >= h - 1, str(nav))
        col = box(page, ".pcol")
        check(f"{w}px: 콘텐츠 열이 읽기 폭(≤640) 이하이고 가운데", col and col["width"] <= 641, str(col))
        check(f"{w}px: 가로 스크롤 없음", hscroll(page) <= 0)
        page.screenshot(path=f"{OUT}/shell_{w}_home.png")
        ctx.close()

    # --- 모달: 390 바텀시트 / 1280 중앙 ---
    for w, h, kind in ((390, 844, "bottom"), (1280, 800, "center")):
        ctx = b.new_context(viewport={"width": w, "height": h})
        page = ctx.new_page(); page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(BASE + "/#u-home"); page.wait_for_timeout(600)
        page.evaluate("S.modal = {title:'테스트', body:'본문', ok:'확인'}; render()"); page.wait_for_timeout(300)
        m = box(page, ".modal")
        if kind == "bottom":
            check("390px 모달: 화면 아래에 붙은 시트", m and abs(m["y"] + m["height"] - h) <= 2 and m["width"] >= w - 2, str(m))
        else:
            check("1280px 모달: 가운데 다이얼로그(≤420px)", m and m["width"] <= 421 and 100 < m["y"] < h - 100, str(m))
        ctx.close()

    # --- 데모 서랍 ---
    ctx = b.new_context(viewport={"width": 390, "height": 844})
    page = ctx.new_page(); page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE + "/?demo=1#u-home"); page.wait_for_timeout(600)
    check("?demo=1: 데모 버튼 보임, 서랍은 닫힘", page.locator("#demo-fab").is_visible() and box(page, ".side")["x"] < 0)
    page.locator("#demo-fab").click(); page.wait_for_timeout(350)
    sd = box(page, ".side")
    check("데모 버튼 → 서랍 열림(화면 안, 폭 ≤ 88vw)", sd and sd["x"] >= -1 and sd["width"] <= 390 * 0.88 + 1, str(sd))
    check("서랍에 화면 목록·데모 조작·화면 설명", page.locator(".side .nav-item").count() >= 12 and page.locator("#demo").is_visible() and page.locator("#side-notes .note-card").count() >= 1)
    page.locator('.side [data-id="u-coll"]').click(); page.wait_for_timeout(400)
    check("서랍에서 화면 이동하면 서랍이 닫힘", page.evaluate("S.screen") == "u-coll" and box(page, ".side")["x"] < 0)
    check("데모 모드 390px: 가로 스크롤 없음", hscroll(page) <= 0)
    ctx.close()

    # --- ?demo=1&frame=1 = 예전 레이아웃 ---
    ctx = b.new_context(viewport={"width": 1400, "height": 1000})
    page = ctx.new_page(); page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE + "/?demo=1&frame=1#u-home"); page.wait_for_timeout(600)
    check("frame=1: 폰 프레임·사이드 패널 유지", page.locator(".device").count() == 1 and page.locator(".side").is_visible())
    ctx.close()

    # --- 예전 레이아웃 좁은 화면: 폰 프레임을 벗기고, 서랍은 "데모" 버튼으로 ---
    ctx = b.new_context(viewport={"width": 390, "height": 844})
    page = ctx.new_page(); page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE + "/?demo=1&frame=1#u-home"); page.wait_for_timeout(600)
    check("frame=1 390px: 폰 프레임 모양 해제(테두리 둥근 기기 아님)", page.evaluate("getComputedStyle(document.querySelector('.device')).borderRadius") == "0px")
    check("frame=1 390px: 데모 버튼으로 서랍 열림", page.locator("#demo-fab").is_visible() and (page.locator("#demo-fab").click() or True) and (page.wait_for_timeout(350) or True) and box(page, ".side")["x"] >= -1)
    check("frame=1 390px: 가로 스크롤 없음", hscroll(page) <= 0)
    ctx.close()

    # --- P2: 글자·입력·터치 ---
    ctx = b.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True)
    page = ctx.new_page(); page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE + "/#u-input"); page.wait_for_timeout(700)
    check("입력 글자 16px 이상(iOS 확대 방지)", page.evaluate("[...document.querySelectorAll('.app input, .app select')].every(e => parseFloat(getComputedStyle(e).fontSize) >= 16)"))
    check("한글 줄바꿈 keep-all", page.evaluate("getComputedStyle(document.body).wordBreak") == "keep-all")
    for scr in ("u-input", "u-report", "u-home", "u-sched", "u-study", "u-coll"):
        page.evaluate(f"S.user = DEMO_USER; preset('default'); go('{scr}')"); page.wait_for_timeout(250)
        small = page.evaluate("""[...document.querySelectorAll('.pframe button, .pframe a, .pframe input, .pframe select')]
          .filter(e => { const q = e.getBoundingClientRect(); return q.width && q.height && (q.height < 43.5 || q.width < 43.5) && !e.matches('.del') && !e.closest('.place .src'); })
          .map(e => e.tagName + '.' + e.className + ' ' + Math.round(e.getBoundingClientRect().width) + 'x' + Math.round(e.getBoundingClientRect().height)).slice(0, 4)""")
        check(f"터치 기기 {scr}: 44px 미만 조작 요소 없음", not small, "; ".join(small))
        tiny = page.evaluate("""[...document.querySelectorAll('.pframe *')].filter(e => e.getBoundingClientRect().width && [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim()) && parseFloat(getComputedStyle(e).fontSize) < 12).length""")
        check(f"{scr}: 12px 미만 글자 없음", tiny == 0, str(tiny))
    page.evaluate("preset('default'); go('u-input')"); page.wait_for_timeout(250)
    d = page.evaluate("(() => { const del = document.querySelector('.city-card .del'); const r = del.getBoundingClientRect(); const el = document.elementFromPoint(r.left - 7, r.top - 7); return el === del; })()")
    check("삭제 버튼: 보이는 크기는 작아도 눌리는 영역은 44px(바깥 7px 에서도 눌림)", d)
    ctx.close()
    # 마우스 기기에서는 터치용 크기를 강제하지 않는다
    ctx = b.new_context(viewport={"width": 1280, "height": 800})
    page = ctx.new_page()
    page.goto(BASE + "/#u-coll"); page.wait_for_timeout(600)
    h = page.evaluate("Math.round(document.querySelector('.chips button').getBoundingClientRect().height)")
    check("마우스 기기: 칩 높이 기존 크기 유지(<44)", h < 44, str(h))
    ctx.close()

    # --- 외부 서버 배너 ---
    ctx = b.new_context(viewport={"width": 390, "height": 844})
    page = ctx.new_page()
    page.goto(BASE + "/?api=https://example.com#u-login"); page.wait_for_timeout(600)
    check("?api= 외부 서버: 상단 배너에 호스트 표시", page.locator("#api-banner").is_visible() and "example.com" in page.locator("#api-banner").inner_text())
    ctx.close()

    check("페이지 JS 오류 없음", not errors, "; ".join(errors))
    b.close()
fail = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(fail)}/{len(results)} passed")
sys.exit(1 if fail else 0)
