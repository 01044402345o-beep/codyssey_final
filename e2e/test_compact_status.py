#!/usr/bin/env python3
"""세로가 아주 좁을 때(≤480px, 가로 폰) 학습·상황별 연습의 완료 안내 버튼을 접고 앱바 발음기호 옆에 한 줄로 보인다.

  A 가로 폰(844×390·568×320): 큰 안내 버튼 숨김, 발음기호 옆 한 줄(n/m), 카드를 뒤집으면 숫자가 바로 바뀐다
  B 상황별 연습도 같은 방식
  C 세로(390×844)·넓은 화면은 그대로 큰 버튼, 한 줄은 안 보인다
  E 안내 상자('지난 날짜예요'·'완료한 날이에요'·상황별 연습 설명)는 좁을 때 제목 옆 ⓘ 말풍선으로
  F 카드 아래 점·쪽수·‹ › 줄을 접고 카드 오른쪽 위에 '1 / 5 · 뒤집은 카드 n', 밀어 넘기기는 한 장씩
  D 같은 조건에서 제목 아래 머리를 접고 앱바 제목 자리에 학습은 '날짜 (요일)', 상황별 연습은 상황 이름(세로는 '학습'·'상황별 연습' 그대로)
"""
import sys
from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8899"
fails = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ((" — " + str(extra)) if (extra and not cond) else ""))
    if not cond:
        fails.append(name)


STATE = """() => { const vis = e => !!e && getComputedStyle(e).display !== 'none' && e.getBoundingClientRect().height > 0;
  const m = document.querySelector('.appbar .done-mini'), ipa = document.querySelector('.appbar .ipa-btn');
  return { mini: vis(m) ? m.textContent.trim() : null, full: vis(document.querySelector('.study-status')),
           nextToIpa: !!(m && ipa && m.nextElementSibling === ipa), title: document.querySelector('.appbar h2').innerText.trim(),
           head: vis(document.querySelector('.study-head')), hs: document.documentElement.scrollWidth - document.documentElement.clientWidth }; }"""


def open_page(b, w, h):
    pg = b.new_page(viewport={"width": w, "height": h}, is_mobile=True, has_touch=True)
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(BASE + "/?demo=1&gate=off", timeout=60000); pg.wait_for_timeout(2000)
    if pg.locator('[data-act="guest"]').count():
        pg.locator('[data-act="guest"]').first.click(); pg.wait_for_timeout(800)
    pg.evaluate("try{saveConsentHere(true)}catch(e){}; ensure('plan')")
    return pg, errs


def to_study(pg):
    pg.evaluate("navFromMenu('u-study')"); pg.wait_for_timeout(700)
    pg.evaluate("S.modal && ACT['modal-ok'] && ACT['modal-ok']()"); pg.wait_for_timeout(200)


def to_drill(pg):
    pg.evaluate("navFromMenu('u-coll')"); pg.wait_for_timeout(500)
    pg.locator('[data-act="drill"]').first.click(); pg.wait_for_timeout(700)


with sync_playwright() as p:
    b = p.chromium.launch()
    for w, h in [(844, 390), (568, 320)]:
        pg, errs = open_page(b, w, h)
        to_study(pg)
        s0 = pg.evaluate(STATE)
        check(f"A {w}x{h} 학습: 큰 안내 버튼 숨김 + 발음기호 옆 한 줄", not s0["full"] and s0["mini"] and "0/" in s0["mini"] and s0["nextToIpa"], s0)
        pg.locator('.pmain .flip').first.click(); pg.wait_for_timeout(400)
        s1 = pg.evaluate(STATE)
        check(f"A {w}x{h} 카드를 뒤집으면 한 줄 숫자가 바로 바뀐다", s1["mini"] and "1/" in s1["mini"], s1)
        check(f"A {w}x{h} 가로 스크롤 없음", s1["hs"] <= 0, s1)
        check(f"D {w}x{h} 학습: 머리('여행 전 학습'·'새 문장') 접힘, 앱바 제목이 '날짜 (요일)'",
              not s1["head"] and s1["title"] != "학습" and "(" in s1["title"] and "/" in s1["title"], s1)
        to_drill(pg)
        d = pg.evaluate(STATE)
        check(f"B {w}x{h} 상황별 연습도 한 줄(봤어요)", not d["full"] and d["mini"] and "봤어요" in d["mini"], d)
        label = pg.evaluate("S.drill.label")
        check(f"D {w}x{h} 상황별 연습: 머리 접힘, 앱바 제목이 상황 이름", not d["head"] and d["title"] == label, [d, label])
        check(f"{w}x{h} 자바스크립트 오류 없음", not errs, errs[:2])
        pg.close()
    pg, errs = open_page(b, 390, 844)
    to_study(pg)
    s = pg.evaluate(STATE)
    check("C 세로 화면은 큰 안내 버튼 그대로, 한 줄은 안 보인다", s["full"] and s["mini"] is None, s)
    check("D 세로 학습: 머리 그대로, 앱바 제목 '학습'", s["head"] and s["title"] == "학습", s)
    to_drill(pg)
    s = pg.evaluate(STATE)
    check("C 세로 상황별 연습도 그대로", s["full"] and s["mini"] is None, s)
    check("D 세로 상황별 연습: 머리 그대로, 앱바 제목 '상황별 연습'", s["head"] and s["title"] == "상황별 연습", s)
    check("C 자바스크립트 오류 없음", not errs, errs[:2])
    pg.close()
    # ── E: 안내 상자('지난 날짜예요' 등)는 좁을 때 제목 옆 ⓘ 말풍선으로, 세로는 상자 그대로 ──
    TIP = """() => { const v = e => !!e && getComputedStyle(e).display !== 'none' && e.getBoundingClientRect().height > 0;
      const t = document.querySelector('.appbar .ab-tip'), pop = document.querySelector('.appbar .ab-tip-pop');
      return { tip: v(t), tipW: t ? t.getBoundingClientRect().width : 0, pop: v(pop) ? pop.innerText.trim() : null,
               banner: v(document.querySelector('.study-banner')) }; }"""
    PAST = "S.today = S.sched[2].date; navFromMenu('u-study'); S.studyDate = S.sched[0].date; render()"
    pg, errs = open_page(b, 844, 390)
    pg.evaluate(PAST); pg.wait_for_timeout(600)
    t0 = pg.evaluate(TIP)
    check("E 좁을 때 지난 날짜: 상자 대신 제목 옆 ⓘ(누를 자리 44px), 말풍선은 닫혀 있다", t0["tip"] and not t0["banner"] and t0["pop"] is None and t0["tipW"] >= 44, t0)
    pg.locator('.appbar .ab-tip').click(); pg.wait_for_timeout(200)
    t1 = pg.evaluate(TIP)
    check("E ⓘ 를 누르면 '지난 날짜예요' 말풍선", t1["pop"] and "지난 날짜예요" in t1["pop"]
          and pg.evaluate("document.querySelector('.appbar .ab-tip').getAttribute('aria-expanded')") == "true", t1)
    pg.mouse.click(420, 300); pg.wait_for_timeout(200)
    check("E 말풍선 밖을 누르면 닫힌다", pg.evaluate(TIP)["pop"] is None)
    to_drill(pg)
    pg.locator('.appbar .ab-tip').click(); pg.wait_for_timeout(200)
    t2 = pg.evaluate(TIP)
    check("E 상황별 연습: 상황 이름 옆 ⓘ — '완료율에는 들어가지 않아요'", t2["pop"] and "완료율에는 들어가지 않아요" in t2["pop"], t2)
    check("E 자바스크립트 오류 없음", not errs, errs[:2])
    pg.close()
    pg, errs = open_page(b, 390, 844)
    pg.evaluate(PAST); pg.wait_for_timeout(600)
    t3 = pg.evaluate(TIP)
    check("E 세로는 안내 상자 그대로, ⓘ 없음", t3["banner"] and not t3["tip"], t3)
    pg.close()
    # ── F: 카드 아래 점·쪽수·‹ › 줄을 접고 카드 오른쪽 위에 쪽수(앞·뒷면), 밀어 넘기기는 그대로 한 장씩 ──
    NAV = """() => { const v = e => !!e && getComputedStyle(e).display !== 'none' && e.getBoundingClientRect().height > 0;
      const face = document.querySelector(S.card.back === S.card.i ? '.pmain .face.back' : '.pmain .face.front');
      const c = face && face.querySelector('.face-count'), fr = face && face.getBoundingClientRect(), cr = c && c.getBoundingClientRect();
      return { nav: v(document.querySelector('.pmain .card-nav')), count: v(c) ? c.textContent.trim() : null,
               topRight: !!(cr && fr && cr.right > fr.left + fr.width * 0.6 && cr.top < fr.top + fr.height * 0.35), i: S.card.i }; }"""
    ctx = b.new_context(viewport={"width": 844, "height": 390}, has_touch=True, is_mobile=True)
    pg = ctx.new_page(); errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
    cdp = ctx.new_cdp_session(pg)
    pg.goto(BASE + "/?demo=1&gate=off", timeout=60000); pg.wait_for_timeout(2000)
    if pg.locator('[data-act="guest"]').count():
        pg.locator('[data-act="guest"]').first.click(); pg.wait_for_timeout(800)
    pg.evaluate("try{saveConsentHere(true)}catch(e){}; ensure('plan')")
    to_drill(pg); pg.evaluate("scrollTo(0, 0)")
    n0 = pg.evaluate(NAV)
    check("F 카드 아래 줄(점·쪽수·‹ ›) 접힘, 카드 오른쪽 위에 '1 / 5 · 뒤집은 카드 0'", not n0["nav"] and n0["count"] == "1 / 5 · 뒤집은 카드 0" and n0["topRight"], n0)
    pg.locator('.pmain .flip').first.click(); pg.wait_for_timeout(400)
    n1 = pg.evaluate(NAV)
    check("F 뒤집으면 뒷면 오른쪽 위에 '뒤집은 카드 1'", n1["count"] == "1 / 5 · 뒤집은 카드 1" and n1["topRight"], n1)
    box = pg.locator(".pmain .flip").first.bounding_box()
    x0, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x0, "y": y}]})
    for k in range(1, 7):
        cdp.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [{"x": x0 - 220 * k / 6, "y": y}]}); pg.wait_for_timeout(16)
    cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []}); pg.wait_for_timeout(600)
    n2 = pg.evaluate(NAV)
    check("F 버튼 없이 왼쪽으로 밀면 한 장 넘어가고 쪽수가 '2 / 5'", n2["i"] == 1 and n2["count"] and n2["count"].startswith("2 / 5"), n2)
    check("F 자바스크립트 오류 없음", not errs, errs[:2])
    ctx.close()
    pg, errs = open_page(b, 390, 844)
    to_drill(pg)
    n3 = pg.evaluate(NAV)
    check("F 세로는 카드 아래 줄 그대로, 카드 안 쪽수 없음", n3["nav"] and n3["count"] is None, n3)
    pg.close()
    b.close()

print("---")
print("ALL PASS" if not fails else "FAILED: " + ", ".join(fails))
sys.exit(1 if fails else 0)
