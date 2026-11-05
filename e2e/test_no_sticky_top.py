#!/usr/bin/env python3
"""화면에 고정되는 띠는 내비(폰 하단 탭·넓은 화면 왼쪽 레일)뿐이다 — 나머지는 내용과 함께 스크롤된다(11/05 사용자 지시).

예전에는 앱바('일정표 · 이전 여행')가 position: sticky 로 위에 붙어 스크롤해도 따라왔다.
  A 폰·레일·사이드 폭 × 주요 화면: 아래로 스크롤하면 앱바가 화면 위로 사라진다
  B 내비는 그대로 화면에 있다(폰: 아래 고정, 넓은 화면: 왼쪽 레일)
  C 위쪽에 붙는(top 지정 sticky/fixed) 띠가 내비 말고는 없다(시트·창 같은 겹침 화면은 제외)
"""
import sys
from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8899"
fails = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ((" — " + str(extra)) if (extra and not cond) else ""))
    if not cond:
        fails.append(name)


PINNED = """() => [...document.querySelectorAll('.pframe *')].filter(e => {
    const cs = getComputedStyle(e);
    if (!['sticky', 'fixed'].includes(cs.position) || cs.top === 'auto') return false;
    if (e.closest('.pnav')) return false;                                   // 내비는 예외
    const r = e.getBoundingClientRect();
    if (!r.width || !r.height || r.height >= innerHeight * 0.9) return false;   // 시트·창(전체 겹침)은 띠가 아니다
    return true; }).map(e => e.className || e.tagName)"""

with sync_playwright() as p:
    b = p.chromium.launch()
    for w, h, kind in ((390, 844, "폰"), (768, 1024, "레일"), (1280, 800, "사이드")):
        pg = b.new_page(viewport={"width": w, "height": h})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(BASE + "/?demo=1&gate=off", timeout=60000); pg.wait_for_timeout(2200)
        if pg.locator('[data-act="guest"]').count():
            pg.locator('[data-act="guest"]').first.click(); pg.wait_for_timeout(1000)
        pg.evaluate("try{saveConsentHere(true)}catch(e){}; ensure('plan')")
        for sid in ("u-home", "u-sched", "u-study", "u-coll", "u-ipa"):
            pg.evaluate(f"navFromMenu('{sid}')"); pg.wait_for_timeout(600)
            pg.evaluate("S.modal && ACT['modal-ok'] && ACT['modal-ok']()"); pg.wait_for_timeout(200)
            # 스크롤할 만큼 길게 — 화면이 짧으면 아래를 늘려 둔다(앱바의 성질만 본다)
            pg.evaluate("(() => { const a = document.querySelector('.pmain .app, .pmain'); const s = document.createElement('div'); s.id = '__pad'; s.style.height = '2000px'; a.appendChild(s); })()")
            pg.evaluate("window.scrollTo(0, 600)"); pg.wait_for_timeout(150)
            ab = pg.evaluate("(() => { const a = document.querySelector('.pmain .appbar'); return a ? a.getBoundingClientRect().bottom : null; })()")
            if ab is not None:
                check(f"A {kind} {sid}: 스크롤하면 앱바가 위로 사라진다", ab <= 0, ab)
            nav = pg.evaluate("""(() => { const n = document.querySelector('.pnav'); if (!n) return null; const r = n.getBoundingClientRect();
                return { pos: getComputedStyle(n).position, top: r.top, bottom: r.bottom, vh: innerHeight }; })()""")
            if nav:
                on = (nav["bottom"] <= nav["vh"] + 1 and nav["bottom"] >= nav["vh"] - 1) if nav["pos"] == "fixed" else abs(nav["top"]) <= 1
                check(f"B {kind} {sid}: 내비는 화면에 그대로({nav['pos']})", on, nav)
            pinned = pg.evaluate(PINNED)
            check(f"C {kind} {sid}: 위에 붙는 띠가 내비 말고 없다", not pinned, pinned[:3])
            pg.evaluate("document.getElementById('__pad') && document.getElementById('__pad').remove(); window.scrollTo(0, 0)")
        check(f"{kind}: 페이지 오류 없음", not errs, errs[:2])
        pg.close()
    b.close()

print("---")
print("ALL PASS" if not fails else "FAILED: " + ", ".join(fails))
sys.exit(1 if fails else 0)
