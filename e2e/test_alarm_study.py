#!/usr/bin/env python3
"""학습 덱의 첫 장 = '오늘의 알람' 카드. 그 카드만 진도율에 안 들어간다.

  1. 학습 탭 덱의 0번이 알람 카드. 홈에는 없다.
  2. 알람 장은 뒤집기 대상이 아니다 — 뒤집어도 S.card.flipped 가 늘지 않는다.
  3. 뒤집은 카드 수·완료 판정은 문장 수(r.ids.length)만 센다.
  4. 다음/이전으로 오가면 문장 덱의 1번으로 이어진다(알람을 건너뛰지 않고 1장으로 센다).
  5. 일정표·문장 모음에서 들어온 학습 덱에는 알람 장이 없다.
  6. 위아래 패딩은 뷰포트 높이에 따라 유동(dvh), 위·아래 대칭.
"""
import sys
from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8772"
passed = failed = 0


def check(name, ok, note=""):
    global passed, failed
    if ok:
        passed += 1; print("PASS " + name)
    else:
        failed += 1; print("FAIL " + name + (f"  [{note}]" if note else ""))


SNAP = """() => JSON.stringify({ act: PROG.act, done: PROG.done, pre: PROG.pre, rate: progress().rate,
    flipped: S.card.flipped.size, i: S.card.i, completed: S.sched.filter(x => x.completed).length })"""


def ready(pg):
    pg.goto(BASE + "/?demo=1"); pg.wait_for_timeout(780)
    pg.evaluate("""() => { S.user = DEMO_USER; ensure('plan'); S.today = S.trip.studyStart;
        PROG.act = {}; PROG.act[S.today] = 4; render(); go('u-home'); }""")
    pg.wait_for_timeout(380)


with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True)
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    ready(pg)

    check("홈에는 알람 카드 없음", pg.locator(".alarm").count() == 0, str(pg.locator(".alarm").count()))

    pg.evaluate("() => { S.studyEntry = 'tab'; go('u-study'); }"); pg.wait_for_timeout(430)
    n_ids = pg.evaluate("() => pickRow().ids.length")
    check("학습 탭: 덱 0번이 알람", pg.evaluate("() => S.card.i") == 0 and pg.locator(".alarm").count() == 1,
          f'i={pg.evaluate("() => S.card.i")} n={pg.locator(".alarm").count()}')
    check("알람 장에서는 뒤집기 카드가 없다", pg.locator(".flip").count() == 0, str(pg.locator(".flip").count()))
    check("카운터가 알람을 알린다", "오늘의 알람" in pg.inner_text("[data-live=flipcount]"),
          pg.inner_text("[data-live=flipcount]"))
    check("점(dots)은 문장 수만큼", pg.locator(".dots i").count() == n_ids, f'{pg.locator(".dots i").count()} vs {n_ids}')
    check("이전 버튼 비활성(첫 장)", pg.locator("[data-act=card-prev]").is_disabled())
    check("다음 버튼 활성", pg.locator("[data-act=card-next]").is_enabled())
    check("회화 연습 버튼은 알람 장에 없다", pg.locator("[data-act=sheet-open]").count() == 0)

    before = pg.evaluate(SNAP)
    pg.locator(".alarm").click(position={"x": 20, "y": 20}); pg.wait_for_timeout(420)
    after = pg.evaluate(SNAP)
    b0, a0 = eval(before.replace("null", "None").replace("true", "True").replace("false", "False")), \
             eval(after.replace("null", "None").replace("true", "True").replace("false", "False"))
    check("알람 카드를 눌러도 뒤집은 카드가 늘지 않는다", b0["flipped"] == 0 and a0["flipped"] == 0, f'{b0["flipped"]}→{a0["flipped"]}')
    check("알람 카드 조작은 진도·완료율을 바꾸지 않는다",
          all(b0[k] == a0[k] for k in ("act", "done", "pre", "rate", "completed")), f'{b0} → {a0}')
    check("알람 카드는 뒤집히지 않는다(본문 탭 무반응)", a0["i"] == 0 and pg.locator(".alarm").count() == 1, str(a0["i"]))
    pg.locator("[data-act=alarm-next]").click(); pg.wait_for_timeout(400)
    # S.card.i 는 문장 번호, 알람을 보는지는 S.card.alarm (덱 위치를 i 에 섞지 않는다)
    check("주 버튼이 첫 문장으로 넘긴다", pg.evaluate("() => S.card.alarm === false && S.card.i === 0 && deckPos(pickRow()) === 1"),
          pg.evaluate("() => JSON.stringify({ i: S.card.i, alarm: S.card.alarm })"))
    check("첫 문장 장에 뒤집기 카드가 있다", pg.locator(".flip").count() == 1)
    check("1번 문장 카운터 1/N", pg.inner_text("[data-live=flipcount]").startswith(f"1 / {n_ids}"),
          pg.inner_text("[data-live=flipcount]"))
    pg.locator("[data-act=card-prev]").click(); pg.wait_for_timeout(380)
    check("이전으로 알람 장 복귀", pg.locator(".alarm").count() == 1 and pg.evaluate("() => S.card.i") == 0)

    for k in range(1, n_ids + 1):
        pg.evaluate("(k) => { S.card.alarm = false; S.card.i = k - 1; render(); }", k); pg.wait_for_timeout(120)
        if pg.locator(".flip").count():
            pg.locator(".flip").click(); pg.wait_for_timeout(140)
    flipped = pg.evaluate("() => S.card.flipped.size")
    check("문장을 다 뒤집으면 뒤집은 카드 = 문장 수(알람 미포함)", flipped == n_ids, f'{flipped} vs {n_ids}')
    check("덱 길이 = 문장 수 + 1", pg.evaluate("() => deckLen(pickRow())") == n_ids + 1,
          str(pg.evaluate("() => deckLen(pickRow())")))

    # 다른 입구
    pg.evaluate("() => { S.modal = null; go('u-sched'); }"); pg.wait_for_timeout(320)
    pg.evaluate("""() => { S.studyDate = (S.sched.find(x => x.kind !== 'free') || S.sched[0]).date;
        S.studyEntry = 'list'; S.card = { date: null, i: 0, flipped: new Set() }; go('u-study'); }""")
    pg.wait_for_timeout(400)
    check("일정표에서 들어온 덱: 알람 없음", pg.locator(".alarm").count() == 0 and pg.locator(".flip").count() == 1,
          f'alarm={pg.locator(".alarm").count()} flip={pg.locator(".flip").count()}')
    check("일정표 경로 덱 길이 = 문장 수", pg.evaluate("() => deckLen(pickRow())") == pg.evaluate("() => pickRow().ids.length"))
    # 입구가 바뀌어도 보던 문장이 밀리지 않는다: 학습 탭에서 2번째 문장을 보다가 같은 날짜를 일정표에서 열면 같은 문장
    pg.evaluate("""() => { S.studyDate = null; S.studyEntry = 'tab'; S.card = { date: null, i: 0, flipped: new Set() }; go('u-study'); }""")
    pg.wait_for_timeout(300)
    pg.evaluate("() => { ACT['card-next'](); ACT['card-next'](); }"); pg.wait_for_timeout(200)
    seen_tab = pg.evaluate("() => curSent() && curSent().id")
    pg.evaluate("""() => { const d = pickRow().date; go('u-sched'); ACT['study-date']({ dataset: { date: d } }); }""")
    pg.wait_for_timeout(350)
    seen_list = pg.evaluate("() => curSent() && curSent().id")
    check("입구가 바뀌어도 같은 문장(한 칸 밀리지 않음)", seen_tab and seen_tab == seen_list, f"{seen_tab} / {seen_list}")
    pg.evaluate("() => { S.studyEntry = 'tab'; go('u-study'); }"); pg.wait_for_timeout(200)
    pg.evaluate("() => { const r = pickRow(); S.card.alarm = false; S.card.i = 1; render(); }"); pg.wait_for_timeout(150)
    picked = pg.evaluate("""() => { const r = pickRow(); const s = r && S.smap[r.ids[deckIdx(r)]];
        return { shown: document.querySelector('.flip .en') ? document.querySelector('.flip .en').textContent.trim() : null, cur: s && s.en }; }""")
    check("말하기·복습 저장이 보는 문장과 같은 문장을 쓴다", picked["shown"] and picked["cur"] and picked["shown"].replace(" ", "") == picked["cur"].replace(" ", ""),
          str(picked))
    pg.evaluate("() => { go('u-coll'); }"); pg.wait_for_timeout(320)
    pg.evaluate("""() => { const d = [...document.querySelectorAll('[data-act=drill]')][0]; if (d) d.click(); }""")
    pg.wait_for_timeout(480)
    check("문장 모음 연습: 알람 없음", pg.locator(".alarm").count() == 0, str(pg.locator(".alarm").count()))
    check("연습 진입이 실제로 됐다", pg.evaluate("() => !!S.drill"))

    # 유동 패딩
    pg.evaluate("() => { S.drill = null; S.studyEntry = 'tab'; S.studyDate = null; S.card = { date: null, i: 0, flipped: new Set() }; go('u-study'); }")
    pg.wait_for_timeout(420)
    pads = {}
    for w, h in [(320, 568), (390, 640), (390, 844), (430, 932), (1280, 1000)]:
        pg.set_viewport_size({"width": w, "height": h}); pg.wait_for_timeout(250)
        pads[f"{w}x{h}"] = pg.evaluate("""() => { const el = document.querySelector('.alarm'); if (!el) return null;
            const s = getComputedStyle(el); return { top: parseFloat(s.paddingTop), bottom: parseFloat(s.paddingBottom) }; }""")
    vals = [v["top"] for v in pads.values() if v]
    check("위아래 패딩 대칭", all(abs(v["top"] - v["bottom"]) < 0.5 for v in pads.values() if v), str(pads))
    check("높이에 따라 패딩 유동(3종 이상)", len(set(round(x, 1) for x in vals)) >= 3, str(vals))
    check("패딩 clamp 범위(14~24)", all(13.5 <= x <= 24.5 for x in vals), str(vals))
    pg.set_viewport_size({"width": 320, "height": 568}); pg.wait_for_timeout(240)
    check("320px 가로 넘침 없음", pg.evaluate("document.documentElement.scrollWidth") <= 320,
          str(pg.evaluate("document.documentElement.scrollWidth")))
    check("JS 오류 없음", not errs, str(errs[:2]))
    b.close()

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
