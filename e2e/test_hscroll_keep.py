#!/usr/bin/env python3
"""가로 스크롤 목록을 옆으로 밀고 항목을 누르면 목록이 처음으로 튀던 결함 — 앱 전역(render) 회귀 시험.

render() 가 화면을 통째로 다시 그려 scrollLeft 가 0 으로 돌아갔다. 지금은 같은 화면을 다시 그리면 위치를
되돌리고, 선택된 항목이 목록 밖이면 그 목록만 옆으로 맞춘다.
  A 문장 모음 필터 칩: 끝까지 밀고 마지막 칩 → 위치 유지, 누른 칩이 보인다
  B 발음기호 눈금: 가운데까지 밀고 보이는 칸 → 위치 유지, 누른 칸이 현재
  C 발음기호 '다음' 버튼: 현재 칸이 눈금 밖이면 따라간다
  D 다른 화면에서 들어와도 현재 칸이 보인다
"""
import sys
from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8899"
fails = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ((" — " + str(extra)) if (extra and not cond) else ""))
    if not cond:
        fails.append(name)


def boot(pg):
    pg.goto(BASE + "/?demo=1&gate=off"); pg.wait_for_timeout(2200)
    if pg.locator('[data-act="guest"]').count():
        pg.locator('[data-act="guest"]').first.click(); pg.wait_for_timeout(1000)
    pg.evaluate("try{saveConsentHere(true)}catch(e){}; ensure('plan')")


def visible_in(pg, list_sel, item_sel):
    return pg.evaluate(f"""() => {{ const l = document.querySelector('{list_sel}'), c = l && l.querySelector('{item_sel}');
        if (!l || !c) return false; const a = l.getBoundingClientRect(), b = c.getBoundingClientRect();
        return b.left >= a.left - 1 && b.right <= a.right + 1; }}""")


with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 390, "height": 844})
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    boot(pg)

    # ── A: 문장 모음 필터 칩 ──
    pg.evaluate("navFromMenu('u-coll')"); pg.wait_for_timeout(900)
    pg.evaluate("S.modal && ACT['modal-ok'] && ACT['modal-ok']()"); pg.wait_for_timeout(200)
    chips = '.chips'
    over = pg.evaluate(f"(() => {{ const c = document.querySelector('{chips}'); return c ? c.scrollWidth - c.clientWidth : 0; }})()")
    check("A0 칩 줄이 옆으로 밀린다(390px)", over > 20, over)
    pg.evaluate(f"document.querySelector('{chips}').scrollLeft = 99999"); pg.wait_for_timeout(200)
    x0 = pg.evaluate(f"document.querySelector('{chips}').scrollLeft")
    last = pg.locator(f"{chips} button").last
    label = last.inner_text().strip()
    last.click(); pg.wait_for_timeout(500)
    x1 = pg.evaluate(f"document.querySelector('{chips}').scrollLeft")
    check("A1 누른 뒤에도 칩 줄 위치 유지(처음으로 안 튐)", x1 > 20 and abs(x1 - x0) < 30, f"{x0} → {x1}")
    check("A2 누른 칩이 선택됨", pg.locator(f"{chips} button.on").count() == 1 and pg.locator(f"{chips} button.on").inner_text().strip() == label,
          pg.locator(f"{chips} button.on").all_inner_texts())
    check("A3 누른 칩이 화면 안에 보인다", visible_in(pg, chips, "button.on"))

    # ── B: 발음기호 눈금 ──
    pg.evaluate("S.ipa = { i: 0, seen: [] }; go('u-ipa')"); pg.wait_for_timeout(700)
    strip = '.ipa-strip'
    # 눈금을 화면 가운데로 먼저 — 하단바 근처에 있으면 클릭 직전 Playwright 가 스크롤해 x0 가 바뀐다(측정 오류)
    pg.evaluate(f"document.querySelector('{strip}').scrollIntoView({{block: 'center', inline: 'nearest'}})"); pg.wait_for_timeout(150)
    pg.evaluate(f"document.querySelector('{strip}').scrollLeft = 1200"); pg.wait_for_timeout(200)
    x0 = pg.evaluate(f"document.querySelector('{strip}').scrollLeft")
    k = pg.evaluate(f"""() => {{ const l = document.querySelector('{strip}'), a = l.getBoundingClientRect();
        return [...l.children].findIndex(c => {{ const r = c.getBoundingClientRect(); return r.left > a.left + 40 && r.right < a.right - 40; }}); }}""")
    check("B0 밀린 눈금에 보이는 칸이 있다", k > 10, k)
    pg.locator(f"{strip} .ipa-cell").nth(k).click(); pg.wait_for_timeout(500)
    x1 = pg.evaluate(f"document.querySelector('{strip}').scrollLeft")
    check("B1 누른 뒤에도 눈금 위치 유지", abs(x1 - x0) < 30, f"{x0} → {x1}")
    check("B2 누른 칸이 현재 기호", pg.evaluate("S.ipa.i") == k, pg.evaluate("S.ipa.i"))
    check("B3 현재 칸이 눈금 안에 보인다", visible_in(pg, strip, ".ipa-cell.cur"))

    # ── C: '다음' 이웃 버튼으로 옮기면 눈금이 따라간다 ──
    pg.evaluate("S.ipa.i = 0; render()"); pg.wait_for_timeout(300)
    pg.evaluate(f"document.querySelector('{strip}').scrollLeft = 0"); pg.wait_for_timeout(100)
    for _ in range(12):
        pg.locator(".ipa-neigh-b").last.click(); pg.wait_for_timeout(120)
    check("C1 12칸 뒤로 옮김", pg.evaluate("S.ipa.i") == 12, pg.evaluate("S.ipa.i"))
    check("C2 현재 칸이 눈금 안에 보인다", visible_in(pg, strip, ".ipa-cell.cur"))
    y = pg.evaluate("window.scrollY")
    check("C3 눈금을 맞추느라 페이지가 세로로 튀지 않는다", y == 0, y)

    # ── D: 다른 화면에서 들어와도 현재 칸이 보인다 ──
    pg.evaluate("go('u-study')"); pg.wait_for_timeout(400)
    pg.evaluate("S.ipa.i = 40; go('u-ipa')"); pg.wait_for_timeout(600)
    check("D1 들어오자마자 현재 칸(41번째)이 보인다", visible_in(pg, strip, ".ipa-cell.cur"))

    check("페이지 오류 없음", not errs, errs[:2])
    b.close()

print("---")
print("ALL PASS" if not fails else "FAILED: " + ", ".join(fails))
sys.exit(1 if fails else 0)
