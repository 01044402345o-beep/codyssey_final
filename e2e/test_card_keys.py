#!/usr/bin/env python3
"""학습 카드 키보드: ↑·↓ 뒤집기, ←·→ 이전·다음 카드 (휴대폰·컴퓨터 모두).

  A 컴퓨터(1280×800, 2열 학습)·휴대폰(390×844, 상황별 연습): ↓ 뒤집기·↑ 되돌리기, → 다음·← 이전, 첫 장에서 ← 는 그대로
  B 화살표가 문서를 스크롤하지 않는다
  D 컴퓨터 2열 학습(날짜별 카드)에서도 같은 키
  C 글자 칸에 쓰는 중·확인 창이 떠 있을 때·Ctrl 을 함께 누를 때는 카드가 움직이지 않는다
"""
import sys
from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8899"
fails = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ((" — " + str(extra)) if (extra and not cond) else ""))
    if not cond:
        fails.append(name)


ST = "() => ({ i: S.card.i, back: S.card.back === S.card.i, flipped: S.card.flipped.size, y: Math.round(scrollY), alarm: !!S.card.alarm })"

with sync_playwright() as p:
    b = p.chromium.launch()
    for label, w, h, mobile in [("컴퓨터", 1280, 800, False), ("휴대폰", 390, 844, True)]:
        pg = b.new_page(viewport={"width": w, "height": h}, is_mobile=mobile, has_touch=mobile)
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(BASE + "/?demo=1&gate=off", timeout=60000); pg.wait_for_timeout(2000)
        if pg.locator('[data-act="guest"]').count():
            pg.locator('[data-act="guest"]').first.click(); pg.wait_for_timeout(800)
        pg.evaluate("try{saveConsentHere(true)}catch(e){}; ensure('plan')")
        pg.evaluate("navFromMenu('u-coll')"); pg.wait_for_timeout(500)
        pg.locator('[data-act="drill"]').first.click(); pg.wait_for_timeout(700)
        pg.evaluate("S.modal && ACT['modal-ok'] && ACT['modal-ok']()"); pg.wait_for_timeout(200)
        pg.evaluate("document.activeElement && document.activeElement.blur(); scrollTo(0, 0)")
        s0 = pg.evaluate(ST)
        check(f"A {label} 시작: 1번째 카드 앞면", s0["i"] == 0 and not s0["back"], s0)
        pg.keyboard.press("ArrowDown"); pg.wait_for_timeout(300)
        s1 = pg.evaluate(ST)
        check(f"A {label} ↓ 뒤집기(뒤집은 카드 1)", s1["back"] and s1["flipped"] == 1, s1)
        check(f"B {label} ↓ 가 문서를 스크롤하지 않는다", s1["y"] == s0["y"], [s0["y"], s1["y"]])
        pg.keyboard.press("ArrowUp"); pg.wait_for_timeout(300)
        check(f"A {label} ↑ 다시 앞면", not pg.evaluate(ST)["back"])
        pg.keyboard.press("ArrowRight"); pg.wait_for_timeout(300)
        s2 = pg.evaluate(ST)
        check(f"A {label} → 다음 카드(2번째)", s2["i"] == 1, s2)
        pg.keyboard.press("ArrowLeft"); pg.wait_for_timeout(300)
        check(f"A {label} ← 이전 카드(1번째)", pg.evaluate(ST)["i"] == 0)
        pg.keyboard.press("ArrowLeft"); pg.wait_for_timeout(300)
        check(f"A {label} 첫 장에서 ← 는 그대로", pg.evaluate(ST)["i"] == 0)
        # C: 글자 칸·확인 창·조합 키
        pg.evaluate("""() => { const i = document.createElement('input'); i.id = 'kb-probe'; document.querySelector('.pmain').prepend(i); i.focus(); }""")
        pg.keyboard.press("ArrowRight"); pg.keyboard.press("ArrowDown"); pg.wait_for_timeout(250)
        s3 = pg.evaluate(ST)
        check(f"C {label} 글자 칸에서는 카드가 움직이지 않는다", s3["i"] == 0 and not s3["back"], s3)
        pg.evaluate("document.getElementById('kb-probe').remove(); document.activeElement && document.activeElement.blur()")
        pg.keyboard.press("Control+ArrowRight"); pg.wait_for_timeout(250)
        check(f"C {label} Ctrl+→ 는 카드를 넘기지 않는다", pg.evaluate(ST)["i"] == 0)
        pg.evaluate("confirmBox('확인', '시험', '확인', () => { S.modal = null; render(); })"); pg.wait_for_timeout(300)
        pg.keyboard.press("ArrowRight"); pg.wait_for_timeout(250)
        check(f"C {label} 확인 창이 떠 있으면 카드를 넘기지 않는다", pg.evaluate(ST)["i"] == 0)
        pg.evaluate("S.modal = null; render()"); pg.wait_for_timeout(300)
        pg.keyboard.press("ArrowRight"); pg.wait_for_timeout(300)
        check(f"C {label} 창을 닫으면 다시 → 로 넘긴다", pg.evaluate(ST)["i"] == 1)
        check(f"{label} 자바스크립트 오류 없음", not errs, errs[:2])
        pg.close()
    # D: 컴퓨터 2열 학습(날짜별 카드, 오른쪽 상세)에서도 같은 키
    pg = b.new_page(viewport={"width": 1280, "height": 800})
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(BASE + "/?demo=1&gate=off", timeout=60000); pg.wait_for_timeout(2000)
    if pg.locator('[data-act="guest"]').count():
        pg.locator('[data-act="guest"]').first.click(); pg.wait_for_timeout(800)
    pg.evaluate("try{saveConsentHere(true)}catch(e){}; ensure('plan'); S.today = S.sched[0].date; navFromMenu('u-study')"); pg.wait_for_timeout(700)
    pg.evaluate("S.modal && ACT['modal-ok'] && ACT['modal-ok']()"); pg.wait_for_timeout(300)
    check("D 2열 학습 화면이다(오른쪽 상세 카드)", pg.evaluate("!!document.querySelector('.split-detail .flip')"))
    pg.keyboard.press("ArrowRight"); pg.wait_for_timeout(300)
    pg.keyboard.press("ArrowDown"); pg.wait_for_timeout(300)
    d = pg.evaluate(ST)
    check("D 2열 학습: → 다음 카드, ↓ 뒤집기", d["i"] == 1 and d["back"], d)
    check("D 자바스크립트 오류 없음", not errs, errs[:2])
    pg.close()
    b.close()

print("---")
print("ALL PASS" if not fails else "FAILED: " + ", ".join(fails))
sys.exit(1 if fails else 0)
