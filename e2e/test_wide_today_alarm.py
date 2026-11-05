#!/usr/bin/env python3
"""넓은 화면(PC) 2열의 날짜 목록 — 오늘의 알람과 '아직 학습일이 아니에요'(11/05 사용자 지시).

  · 오늘을 보고 있으면(날짜를 따로 고르지 않음) 오늘의 알람이 '아직 학습일이 아니에요'보다 먼저 나온다 — 학습·일정표 모두
  · 사용자가 오늘이 아닌 다른 날짜를 고르면 알람은 나오지 않는다 — 학습·일정표 모두
  · 학습 메뉴에서만 '아직 학습일이 아니에요'를 띄우지 않고 바로 카드를 연다. 일정표는 그대로 묻는다
  · 폰(좁은 화면)에서 일정표 → 미래 날짜로 들어온 학습은 그대로 묻는다(학습 메뉴가 아니라 일정표 경로)
데모 여행은 오늘이 학습 시작 전이라, 기본 선택(첫 학습일)이 미래 날짜다.
"""
import sys
from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8899"
fails = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ((" — " + str(extra)) if (extra and not cond) else ""))
    if not cond:
        fails.append(name)


DETAIL = """() => { const d = document.querySelector('.split-detail') || document.querySelector('.pmain');
  const t = d ? d.innerText : '';
  return { alarm: d ? d.querySelectorAll('.alarm').length : 0, gate: t.includes('아직 학습일이 아니에요'),
           flip: d ? d.querySelectorAll('.flip').length : 0, modal: !!S.modal && /아직 학습일/.test(S.modal.title || '') }; }"""


def boot(pg):
    pg.goto(BASE + "/?demo=1&gate=off", timeout=60000); pg.wait_for_timeout(2200)
    if pg.locator('[data-act="guest"]').count():
        pg.locator('[data-act="guest"]').first.click(); pg.wait_for_timeout(1000)
    pg.evaluate("try{saveConsentHere(true)}catch(e){}; ensure('plan')")


with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1280, "height": 900})
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    boot(pg)
    first = pg.evaluate("S.sched.find(r => r.kind !== 'free' && r.kind !== 'drill').date")
    later = pg.evaluate("S.sched.filter(r => r.kind !== 'free' && r.kind !== 'drill')[2].date")
    check("데모: 오늘은 학습 시작 전(기본 선택이 미래 날짜)", pg.evaluate("S.today") < first, (pg.evaluate("S.today"), first))

    # ── 일정표(2열) ──
    pg.evaluate("navFromMenu('u-sched')"); pg.wait_for_timeout(700)
    d = pg.evaluate(DETAIL)
    check("일정표: 오늘을 보고 있으면 오늘의 알람이 먼저", d["alarm"] == 1 and not d["gate"], d)
    pg.locator(".split-detail [data-act=card-next]").first.click(); pg.wait_for_timeout(400)
    d = pg.evaluate(DETAIL)
    check("일정표: 알람을 넘기면 그다음에 '아직 학습일이 아니에요'", d["alarm"] == 0 and d["gate"], d)
    pg.locator(f'.split-list [data-date="{later}"]').first.click(); pg.wait_for_timeout(450)
    d = pg.evaluate(DETAIL)
    check("일정표: 다른 날짜를 고르면 알람 없이 '아직 학습일이 아니에요'", d["alarm"] == 0 and d["gate"], d)

    # ── 학습(2열) ──
    pg.locator('.pnav button[data-id="u-study"]').click(); pg.wait_for_timeout(700)   # 사용자가 누르는 학습 탭
    pg.evaluate("S.modal && /발음기호/.test(S.modal.title || '') && ACT['modal-ok']()"); pg.wait_for_timeout(200)
    d = pg.evaluate(DETAIL)
    check("학습: 오늘을 보고 있으면 오늘의 알람이 먼저", d["alarm"] == 1 and not d["gate"], d)
    pg.locator(".split-detail [data-act=card-next]").first.click(); pg.wait_for_timeout(400)
    d = pg.evaluate(DETAIL)
    check("학습: 알람을 넘기면 묻지 않고 바로 카드", d["flip"] == 1 and not d["gate"] and not d["modal"], d)
    pg.locator(f'.split-list [data-date="{later}"]').first.click(); pg.wait_for_timeout(450)
    d = pg.evaluate(DETAIL)
    check("학습: 다른(미래) 날짜를 고르면 알람 없이 바로 카드", d["alarm"] == 0 and d["flip"] == 1 and not d["gate"] and not d["modal"], d)
    check("학습: 고른 날짜의 카드다", pg.evaluate("pickRow().date") == later, pg.evaluate("pickRow().date"))
    check("페이지 오류 없음", not errs, errs[:2])
    pg.close()

    # ── 폰: 일정표 → 미래 날짜는 그대로 묻는다(학습 메뉴 예외는 학습 탭에서만) ──
    pg = b.new_page(viewport={"width": 390, "height": 844})
    boot(pg)
    pg.evaluate("navFromMenu('u-sched')"); pg.wait_for_timeout(600)
    pg.evaluate(f"ACT['study-date']({{ dataset: {{ date: '{later}' }} }})"); pg.wait_for_timeout(500)
    d = pg.evaluate(DETAIL)
    check("폰 일정표 → 미래 날짜: '아직 학습일이 아니에요'를 묻는다", d["modal"] and d["alarm"] == 0, d)
    pg.locator('[data-act="modal-cancel"]').click(); pg.wait_for_timeout(400)   # '일정표로' — 사용자가 창을 닫는 길
    pg.locator('.pnav button[data-id="u-study"]').click(); pg.wait_for_timeout(600)
    pg.evaluate("S.modal && /발음기호/.test(S.modal.title || '') && ACT['modal-ok']()"); pg.wait_for_timeout(200)
    d = pg.evaluate(DETAIL)
    check("폰 학습 탭: 오늘의 알람이 먼저(묻지 않음)", d["alarm"] == 1 and not d["modal"], d)
    pg.close()
    b.close()

print("---")
print("ALL PASS" if not fails else "FAILED: " + ", ".join(fails))
sys.exit(1 if fails else 0)
