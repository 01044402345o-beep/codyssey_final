"""폰 하단 탭(홈·일정표·학습·문장 모음)이 스크롤과 따로 화면 아래에 고정되는지 E2E.

10/20 피드백(iPhone): 아래로 끝까지 스크롤하면 하단 탭이 내용과 함께 움직였다. 탭이 position: sticky 로
문서 흐름 안에 있어서, iOS 의 끝 바운스(고무줄 스크롤) 때 내용과 함께 끌려 올라가고 아래에 빈 바탕이 드러났다.
바운스 자체는 헤드리스로 재현되지 않으므로, 원인이 된 성질(문서 흐름 안의 sticky)과
결과(어느 스크롤 위치에서도 탭이 화면 맨 아래, 마지막 내용이 탭에 가리지 않음)를 본다.
10/22: 탭은 고정하되 화면 내부의 끝 바운스(반응형 움직임)는 허용한다 — 루트 바운스를 끄지 않는다.

    cd backend && uvicorn app.main:app --port 8768
    python ../e2e/test_bottom_nav.py http://localhost:8768
"""
import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1]
results = []


def check(name, cond, extra=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""))


NAV = """() => { const n = document.querySelector('.pnav'); const r = n.getBoundingClientRect();
  return { pos: getComputedStyle(n).position, top: r.top, bottom: r.bottom, h: r.height, vh: innerHeight }; }"""

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True, device_scale_factor=3)
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE + "/?demo=1"); page.wait_for_timeout(800)
    page.evaluate("S.user = DEMO_USER; ensure('plan'); go('u-home')"); page.wait_for_timeout(400)

    n = page.evaluate(NAV)
    check("폰: 하단 탭은 화면에 고정(position: fixed) — 문서 흐름 안의 sticky 가 아니다", n["pos"] == "fixed", n["pos"])
    # 탭만 움직이지 않으면 된다 — 화면 내부의 끝 바운스(반응형 움직임)는 막지 않는다(10/22 피드백).
    root = page.evaluate("""() => { const h = getComputedStyle(document.documentElement), b = getComputedStyle(document.body);
      return { os: h.overscrollBehaviorY, hbg: h.backgroundColor, bbg: b.backgroundColor }; }""")
    check("폰: 화면 내부 바운스 허용(루트 overscroll-behavior-y 를 끄지 않음)", root["os"] == "auto", root["os"])
    check("바운스로 드러나는 문서 바깥도 같은 바탕색(빈 흰 띠 없음)", root["hbg"] == root["bbg"], f"{root['hbg']} / {root['bbg']}")

    for scr in ("u-home", "u-sched"):
        page.evaluate(f"go('{scr}')"); page.wait_for_timeout(400)
        max_y = page.evaluate("document.documentElement.scrollHeight - innerHeight")
        spots = []
        for y in (0, max_y // 2, max_y):
            page.evaluate(f"window.scrollTo(0, {y})"); page.wait_for_timeout(150)
            r = page.evaluate(NAV)
            spots.append(round(r["vh"] - r["bottom"], 1))
        check(f"{scr}: 맨 위·중간·끝 어디서나 탭이 화면 맨 아래에 붙어 있다", max_y > 200 and all(abs(d) <= 1 for d in spots), f"scroll {max_y}px, 아래 틈 {spots}")
        page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)"); page.wait_for_timeout(150)
        last = page.evaluate("""() => { const els = [...document.querySelectorAll('.app *')].filter(e => e.offsetParent && e.getBoundingClientRect().height > 0);
          return Math.max(...els.map(e => e.getBoundingClientRect().bottom)); }""")
        r = page.evaluate(NAV)
        check(f"{scr}: 끝까지 스크롤하면 마지막 내용이 탭 위에서 끝난다(가리지 않음)", last <= r["top"] + 1, f"내용 끝 {last:.0f} / 탭 위 {r['top']:.0f}")

    # 탭 높이가 부풀지 않는다(아이콘+라벨 + 홈 인디케이터 여백)
    h = page.evaluate(NAV)["h"]
    check("탭 높이는 그대로(56~80px)", 56 <= h <= 80, f"{h:.0f}px")
    page.locator('.pnav button[data-id="u-coll"]').click(); page.wait_for_timeout(300)
    check("고정된 탭도 그대로 눌린다", page.evaluate("S.screen") == "u-coll")

    # 글자 200%: 탭이 높아져도 아래 여백이 따라간다
    page.evaluate("document.documentElement.style.fontSize = '200%'; render()"); page.wait_for_timeout(300)
    page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)"); page.wait_for_timeout(150)
    big = page.evaluate(NAV)
    pad = page.evaluate("parseFloat(getComputedStyle(document.querySelector('.pframe')).paddingBottom)")
    check("글자 200%: 아래 여백 = 실제 탭 높이", big["h"] > h and abs(pad - big["h"]) <= 1, f"탭 {big['h']:.0f} / 여백 {pad:.0f}")
    page.evaluate("document.documentElement.style.fontSize = ''; render()"); page.wait_for_timeout(200)

    # 넓은 화면(레일·사이드)은 왼쪽 세로 탭 — 고정 하단 탭 규칙이 새지 않는다
    page.set_viewport_size({"width": 800, "height": 900}); page.wait_for_timeout(300)
    r = page.evaluate(NAV)
    check("넓은 화면: 왼쪽 레일(sticky, 화면 높이), 아래 여백 없음",
          r["pos"] == "sticky" and abs(r["h"] - r["vh"]) <= 1 and page.evaluate("getComputedStyle(document.querySelector('.pframe')).paddingBottom") == "0px", str(r))

    check("페이지 JS 오류 없음", not errors, "; ".join(errors[:3]))
    b.close()

print(f"\n{sum(ok for _, ok in results)}/{len(results)} passed")
sys.exit(0 if all(ok for _, ok in results) else 1)
