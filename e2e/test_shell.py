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

    # --- P3: 라이트 / 다크 / 시스템 ---
    bg = "getComputedStyle(document.body).backgroundColor"
    LIGHT_BG, DARK_BG = "rgb(251, 248, 241)", "rgb(18, 21, 28)"
    ctx = b.new_context(viewport={"width": 390, "height": 844}, color_scheme="dark")
    page = ctx.new_page(); page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE + "/#u-home"); page.wait_for_timeout(600)
    check("시스템 다크 → 다크 배경(저장값 없음)", page.evaluate(bg) == DARK_BG and page.evaluate("document.documentElement.dataset.theme") is None, page.evaluate(bg))
    check("theme-color 메타가 다크 값", page.evaluate("document.getElementById('theme-color').content") == "#12151c")
    check("카드가 다크 표면(흰색 아님)", page.evaluate("getComputedStyle(document.querySelector('.today-card, .card')).backgroundColor") != "rgb(255, 255, 255)")
    page.locator('[data-act="theme"][data-v="light"]').scroll_into_view_if_needed(); page.locator('[data-act="theme"][data-v="light"]').click(); page.wait_for_timeout(200)
    check("화면 모드 '라이트' 선택 → 시스템이 다크여도 라이트", page.evaluate(bg) == LIGHT_BG and page.evaluate("localStorage.getItem('cd_theme')") == "light", page.evaluate(bg))
    check("선택한 버튼이 눌림 표시(aria-pressed)", page.locator('[data-act="theme"][data-v="light"]').get_attribute("aria-pressed") == "true")
    check("theme-color 메타가 라이트 값", page.evaluate("document.getElementById('theme-color').content") == "#fbf8f1")
    page.reload(wait_until="domcontentloaded")
    check("새로고침: CSS 가 그려지기 전에 data-theme 적용(깜빡임 없음)", page.evaluate("document.documentElement.dataset.theme") == "light" and page.evaluate(bg) == LIGHT_BG)
    page.wait_for_timeout(500)
    page.locator('[data-act="theme"][data-v="system"]').scroll_into_view_if_needed(); page.locator('[data-act="theme"][data-v="system"]').click(); page.wait_for_timeout(200)
    check("'시스템'으로 되돌리면 저장값 삭제 + 시스템(다크)을 따름", page.evaluate("localStorage.getItem('cd_theme')") is None and page.evaluate(bg) == DARK_BG)
    page.emulate_media(color_scheme="light"); page.wait_for_timeout(200)
    check("시스템 설정이 바뀌면 새로고침 없이 따라감", page.evaluate(bg) == LIGHT_BG and page.evaluate("document.getElementById('theme-color').content") == "#fbf8f1")
    ctx.close()
    ctx = b.new_context(viewport={"width": 390, "height": 844}, color_scheme="light")
    ctx.add_init_script("try { localStorage.setItem('cd_theme', 'dark'); } catch (e) {}")
    page = ctx.new_page(); page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE + "/#u-home", wait_until="domcontentloaded")
    check("저장된 다크 + 시스템 라이트 → 첫 화면부터 다크", page.evaluate("document.documentElement.dataset.theme") == "dark" and page.evaluate(bg) == DARK_BG)
    ctx.close()
    # localStorage 를 쓸 수 없는 환경(시크릿 모드 등): 화면은 정상, 선택은 이번 접속에서만
    ctx = b.new_context(viewport={"width": 390, "height": 844}, color_scheme="light")
    ctx.add_init_script("Object.defineProperty(window, 'localStorage', { get() { throw new Error('blocked'); } });")
    page = ctx.new_page(); errs2 = []; page.on("pageerror", lambda e: errs2.append(str(e)))
    page.goto(BASE + "/#u-home"); page.wait_for_timeout(700)
    ok_render = page.locator(".pnav").count() == 1
    page.locator('[data-act="theme"][data-v="dark"]').scroll_into_view_if_needed(); page.locator('[data-act="theme"][data-v="dark"]').click(); page.wait_for_timeout(200)
    check("저장소 차단: 화면 정상 + 다크 선택은 그 접속에서 적용", ok_render and page.evaluate(bg) == DARK_BG, "; ".join(errs2)[:120])
    ctx.close()
    # 다크 모드에서 데스크톱 레이아웃·관리자도 같은 토큰
    ctx = b.new_context(viewport={"width": 1280, "height": 800}, color_scheme="dark")
    page = ctx.new_page()
    page.goto(BASE + "/#a-metrics"); page.wait_for_timeout(600)
    check("다크 관리자 화면: 표면이 어두움", page.evaluate("getComputedStyle(document.querySelector('.admin-main')).backgroundColor") != "rgb(250, 248, 243)")
    ctx.close()

    # --- 날짜 입력이 칸을 넘치지 않는다 (iOS 날짜 입력 고유 폭 이슈의 회귀 방지; 실기기 iOS 는 이 환경에서 검증 불가) ---
    for w in (320, 360, 390, 430, 768):
        ctx = b.new_context(viewport={"width": w, "height": 900}, has_touch=True, is_mobile=True)
        page = ctx.new_page(); page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(BASE + "/#u-input"); page.wait_for_timeout(600)
        r = page.evaluate("""[...document.querySelectorAll('input[type=date].input')].map(i => {
          const q = i.getBoundingClientRect(), host = i.closest('.city-card, .field').getBoundingClientRect();
          return { out: q.right > host.right + 0.5 || q.left < host.left - 0.5, app: getComputedStyle(i).appearance, w: Math.round(q.width), host: Math.round(host.width) }; })""")
        check(f"{w}px: 날짜 입력 {len(r)}개가 카드·필드 안에 들어감", r and not any(x["out"] for x in r), str(r[:2]))
        check(f"{w}px: 날짜 입력 appearance:none(iOS 고유 폭 무시 방지)", all(x["app"] == "none" for x in r))
        if w <= 430:
            cols = page.evaluate("getComputedStyle(document.querySelector('.city-card .row2')).gridTemplateColumns.split(' ').length")
            check(f"{w}px: 날짜 두 칸이 한 줄씩 쌓임(칸 최소 12rem)", cols == 1, str(cols))
        ctx.close()

    # --- P4: 마스터-디테일 (≥900px) ---
    ctx = b.new_context(viewport={"width": 1280, "height": 800})
    page = ctx.new_page(); page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE + "/#u-sched"); page.wait_for_timeout(700)
    check("1280px 일정표: 2열(목록+상세)", page.locator(".split-list .srow").count() >= 6 and page.locator(".split-detail .flip").count() == 1)
    check("1280px: 콘텐츠 열이 읽기 폭(640)보다 넓다", page.evaluate("document.querySelector('.pcol').getBoundingClientRect().width") > 800)
    check("1280px: 가로 스크롤 없음", hscroll(page) <= 0)
    sel0 = page.evaluate("document.querySelector('.srow.sel').dataset.date")
    page.evaluate("document.querySelector('.split-list').scrollTop = 260"); page.wait_for_timeout(100)
    target = page.evaluate("[...document.querySelectorAll('.split-list .srow')].find(r => r.dataset.date !== document.querySelector('.srow.sel').dataset.date && r.getBoundingClientRect().top > 300).dataset.date")
    page.locator(f'.split-list .srow[data-date="{target}"]').click(); page.wait_for_timeout(300)
    check("날짜 선택: 화면 이동 없이 오른쪽 상세만 바뀜", page.evaluate("S.screen") == "u-sched" and page.evaluate("document.querySelector('.srow.sel').dataset.date") == target and target != sel0)
    check("선택 표시가 하나", page.locator(".srow.sel").count() == 1 and page.locator(".srow.sel").get_attribute("aria-current") == "true")
    check("목록 스크롤 위치 유지", abs(page.evaluate("document.querySelector('.split-list').scrollTop") - 260) <= 4, str(page.evaluate("document.querySelector('.split-list').scrollTop")))
    check("상세 머리글이 선택한 날짜", page.evaluate("document.querySelector('.split-detail .study-head b').textContent").replace(" ", "").startswith(page.evaluate("Dt.full(document.querySelector('.srow.sel').dataset.date)").replace(" ", "")[:5]))
    page.locator(".split-detail .flip").click(); page.wait_for_timeout(300)
    check("카드 뒤집기가 2열에서도 동작(뒤집은 카드 1)", "뒤집은 카드 1" in page.locator("[data-live=flipcount]").inner_text())
    page.locator('.pnav button[data-id="u-study"]').click(); page.wait_for_timeout(300)
    check("'학습' 탭도 2열(화면 u-study)", page.evaluate("S.screen") == "u-study" and page.locator(".split-list .srow").count() >= 6)
    page.locator('.pnav button[data-id="u-coll"]').click(); page.wait_for_timeout(300)
    check("문장 모음 2열: 왼쪽 필터 + 오른쪽 문장", page.locator(".split.coll .split-list .chips button").count() >= 5 and page.locator(".split.coll .split-detail .sent").count() >= 3)
    n0 = page.locator(".split-detail .sent").count()
    page.locator(".split.coll .split-list .chips button").nth(1).click(); page.wait_for_timeout(300)
    check("필터를 누르면 오른쪽 목록이 바뀜", page.locator(".split-detail .sent").count() < n0 and page.locator(".split.coll").count() == 1)
    page.locator('.pnav button[data-id="u-sched"]').click(); page.wait_for_timeout(300)
    page.set_viewport_size({"width": 768, "height": 1024}); page.wait_for_timeout(400)
    check("폭이 768 로 줄면 1열로 되돌아감(.split 없음)", page.locator(".split").count() == 0 and page.locator(".srow").count() >= 6)
    page.locator(".srow").nth(2).click(); page.wait_for_timeout(300)
    check("768px: 날짜를 누르면 학습 화면으로 이동", page.evaluate("S.screen") == "u-study" and page.locator(".split").count() == 0)
    page.set_viewport_size({"width": 1280, "height": 800}); page.wait_for_timeout(400)
    check("다시 1280 으로 넓히면 2열 복귀(재렌더)", page.locator(".split").count() == 1)
    ctx.close()
    ctx = b.new_context(viewport={"width": 1280, "height": 800})
    page = ctx.new_page(); page.goto(BASE + "/?demo=1&frame=1#u-sched"); page.wait_for_timeout(700)
    check("legacy 레이아웃은 2열을 쓰지 않음", page.locator(".split").count() == 0)
    ctx.close()

    # --- 접근성: 글자 200% 확대(WCAG 1.4.4/1.4.10) · 모션 줄이기 ---
    ctx = b.new_context(viewport={"width": 320, "height": 640})
    page = ctx.new_page(); page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE + "/#u-home"); page.wait_for_timeout(600)
    page.add_style_tag(content="html{font-size:200%}")
    bad = []
    for scr in ("u-input", "u-report", "u-route", "u-home", "u-sched", "u-study", "u-coll", "a-metrics", "a-jobs", "a-common", "a-users"):
        page.evaluate(f"S.user = DEMO_USER; go('{scr}')"); page.wait_for_timeout(200)
        if hscroll(page) > 0: bad.append(f"{scr}:{hscroll(page)}")
    check("320px + 글자 200%: 11개 화면 가로 스크롤 없음", not bad, ", ".join(bad))
    check("글자 200%: 하단 탭 라벨이 말줄임으로 잘리지 않고 줄바꿈", page.evaluate("[...document.querySelectorAll('.pnav button span')].every(s => getComputedStyle(s).textOverflow !== 'ellipsis')") if page.locator(".pnav").count() else True)
    ctx.close()
    ctx = b.new_context(viewport={"width": 390, "height": 844}, reduced_motion="reduce")
    page = ctx.new_page()
    page.goto(BASE + "/#u-home"); page.wait_for_timeout(500)
    page.evaluate("ACT['demo-gen']()"); page.wait_for_timeout(500)
    d = page.evaluate("(() => { const e = document.querySelector('.orbit .plane'); return e ? parseFloat(getComputedStyle(e).animationDuration) : -1; })()")
    check("모션 줄이기: 생성 화면 회전 애니메이션이 사실상 꺼짐", 0 <= d < 0.001, str(d))
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
