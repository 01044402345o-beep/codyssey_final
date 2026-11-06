#!/usr/bin/env python3
"""세로가 아주 좁을 때(≤480px, 가로 폰) 학습·상황별 연습의 완료 안내 버튼을 접고 앱바 발음기호 옆에 한 줄로 보인다.

  A 가로 폰(844×390·568×320): 큰 안내 버튼 숨김, 발음기호 옆 한 줄(n/m), 카드를 뒤집으면 숫자가 바로 바뀐다
  B 상황별 연습도 같은 방식
  C 세로(390×844)·넓은 화면은 그대로 큰 버튼, 한 줄은 안 보인다
  E 안내 상자('지난 날짜예요'·'완료한 날이에요'·상황별 연습 설명)는 좁을 때 제목 옆 ⓘ 말풍선으로
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
    b.close()

print("---")
print("ALL PASS" if not fails else "FAILED: " + ", ".join(fails))
sys.exit(1 if fails else 0)
