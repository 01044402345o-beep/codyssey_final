#!/usr/bin/env python3
"""학습 덱 첫 장 = '오늘의 알람'. 그 카드만 진도에서 빠진다.

핵심 계약: S.card.i 는 언제나 문장 인덱스다. 알람은 S.card.alarm 이라는 별도 상태이며
인덱스에 1을 더하지 않는다. 그래야 화면·경로가 바뀌어도 같은 문장이 같은 인덱스를 갖는다.
(이전 구현은 S.card.i 가 '덱 위치'라 말하기·약점 저장이 이웃 문장을 잡는 버그가 있었다.)
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
    flipped: S.card.flipped.size, i: S.card.i, alarm: S.card.alarm !== false })"""


with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True)
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(BASE + "/?demo=1"); pg.wait_for_timeout(780)
    pg.evaluate("""() => { S.user = DEMO_USER; ensure('plan'); S.today = S.trip.studyStart;
        PROG.act = {}; PROG.act[S.today] = 4; render(); go('u-home'); }""")
    pg.wait_for_timeout(380)

    check("홈에는 알람 카드 없음", pg.locator(".alarm").count() == 0, str(pg.locator(".alarm").count()))

    pg.evaluate("() => { S.studyEntry = 'tab'; go('u-study'); }"); pg.wait_for_timeout(430)
    n = pg.evaluate("() => pickRow().ids.length")
    check("학습 탭: 알람 장이 보인다", pg.locator(".alarm").count() == 1 and pg.evaluate("() => S.card.i") == 0,
          f'alarm={pg.locator(".alarm").count()} i={pg.evaluate("() => S.card.i")}')
    check("알람 장에는 뒤집기 카드가 없다", pg.locator(".flip").count() == 0)
    check("점(dots)은 문장 수만큼", pg.locator(".dots i").count() == n, f'{pg.locator(".dots i").count()} vs {n}')
    check("카운터가 알람을 알린다", "오늘의 알람" in pg.inner_text("[data-live=flipcount]"),
          pg.inner_text("[data-live=flipcount]"))
    check("이전 버튼 비활성(첫 장)", pg.locator("[data-act=card-prev]").is_disabled())
    check("알람 장에 말하기·회화 버튼 없음",
          pg.locator("[data-act=sheet-open], [data-act=speak-card], [data-act=weak-save]").count() == 0)

    before = pg.evaluate(SNAP)
    pg.locator(".alarm").click(position={"x": 20, "y": 20}); pg.wait_for_timeout(300)
    check("알람 본문 탭은 뒤집기가 아니다", pg.evaluate("() => S.card.flipped.size") == 0)

    pg.locator("[data-act=alarm-next]").click(); pg.wait_for_timeout(420)
    check("주 버튼이 첫 문장으로", pg.evaluate("() => S.card.i") == 0 and pg.locator(".flip").count() == 1)
    check("알람 꺼짐 상태 기록", pg.evaluate("() => S.card.alarm") is False)
    check("1번 문장 카운터 1/N", pg.inner_text("[data-live=flipcount]").startswith(f"1 / {n}"),
          pg.inner_text("[data-live=flipcount]"))

    # 문장 인덱스가 곧 표시 문장인가 — 말하기·시트가 이웃 문장을 잡지 않는지
    idx_now = pg.evaluate("() => { const r = pickRow(); return { i: S.card.i, id: S.smap[r.ids[S.card.i]].id, en: S.smap[r.ids[S.card.i]].en }; }")
    shown = pg.evaluate("() => document.querySelector('.face.front .ko').innerText.trim()")
    expect_ko = pg.evaluate("(i) => { const r = pickRow(); return S.smap[r.ids[i]].ko; }", idx_now["i"])
    check("표시된 카드와 S.card.i 가 같은 문장", shown[:12] in expect_ko or expect_ko[:12] in shown, f'{shown[:20]} / {expect_ko[:20]}')
    check("curSent 가 표시 문장과 일치", pg.evaluate("(id) => curSent() && curSent().id === id", idx_now["id"]))

    pg.locator("[data-act=card-next]").click(); pg.wait_for_timeout(340)
    check("다음: 문장 인덱스 +1", pg.evaluate("() => S.card.i") == 1, str(pg.evaluate("() => S.card.i")))
    check("문장 2 카운터 2/N", pg.inner_text("[data-live=flipcount]").startswith(f"2 / {n}"),
          pg.inner_text("[data-live=flipcount]"))
    check("문장 2에서 curSent 도 2번째", pg.evaluate("""() => { const r = pickRow();
        return curSent() && curSent().id === S.smap[r.ids[1]].id; }"""))
    pg.locator("[data-act=card-prev]").click(); pg.wait_for_timeout(340)
    check("이전: 문장 인덱스 -1", pg.evaluate("() => S.card.i") == 0)
    pg.locator("[data-act=card-prev]").click(); pg.wait_for_timeout(340)
    check("첫 문장에서 이전 = 알람 장", pg.locator(".alarm").count() == 1 and pg.evaluate("() => S.card.alarm") is True)

    # 진도 미반영
    after = pg.evaluate(SNAP)
    b0 = eval(before.replace("null", "None").replace("true", "True").replace("false", "False"))
    a0 = eval(after.replace("null", "None").replace("true", "True").replace("false", "False"))
    check("알람 노출·이동이 진도·완료율을 바꾸지 않는다",
          all(b0[k] == a0[k] for k in ("act", "done", "pre", "rate")), f'{b0} → {a0}')

    # 문장 전부 뒤집기 → 뒤집은 카드 = 문장 수
    for k in range(n):
        pg.evaluate("(k) => { S.card.i = k; S.card.alarm = false; render(); }", k); pg.wait_for_timeout(110)
        if pg.locator(".flip").count():
            pg.locator(".flip").click(); pg.wait_for_timeout(140)
    flipped = pg.evaluate("() => S.card.flipped.size")
    check("문장을 다 뒤집으면 뒤집은 카드 = 문장 수", flipped == n, f'{flipped} vs {n}')
    check("마지막 문장에서 다음 버튼 비활성",
          pg.locator("[data-act=card-next]").is_disabled() and pg.evaluate("() => S.card.i") == n - 1)
    check("인덱스가 문장 수를 넘지 않는다", pg.evaluate("() => S.card.i") <= n - 1)

    # 넓은 화면: 같은 문장이 유지되는가(이전 버그의 재현 지점)
    pg.evaluate("() => { S.card.i = 1; S.card.alarm = false; render(); }"); pg.wait_for_timeout(200)
    pg.set_viewport_size({"width": 1280, "height": 900}); pg.wait_for_timeout(320)
    pg.evaluate("() => go('u-sched')"); pg.wait_for_timeout(380)
    wide = pg.evaluate("""() => { const r = pickRow(); const shown = document.querySelector('.split-detail .face.front .ko');
        return { i: S.card.i, alarm: document.querySelectorAll('.split-detail .alarm').length,
                 same: !!shown && shown.innerText.trim().slice(0, 12) === S.smap[r.ids[1]].ko.slice(0, 12) }; }""")
    check("1280 일정표: 알람이 뜨지 않는다", wide["alarm"] == 0, str(wide["alarm"]))
    check("1280 일정표: 같은 문장(2번)이 유지된다", wide["same"], str(wide))
    check("1280 일정표: 문장 인덱스 불변", wide["i"] == 1, str(wide["i"]))
    pg.set_viewport_size({"width": 390, "height": 844}); pg.wait_for_timeout(300)

    # 다른 입구
    pg.evaluate("""() => { S.studyDate = (S.sched.find(x => x.kind !== 'free') || S.sched[0]).date;
        S.studyEntry = 'list'; S.card = { date: null, i: 0, alarm: false, flipped: new Set() }; go('u-study'); }""")
    pg.wait_for_timeout(400)
    check("일정표 경로: 알람 없음", pg.locator(".alarm").count() == 0 and pg.locator(".flip").count() == 1,
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
    # 알람 장에서는 말하기·녹음·복습 저장이 시작되지 않는다(대상 문장이 화면에 없다)
    pg.evaluate("() => { S.studyEntry = 'tab'; S.studyDate = null; S.card = { date: null, i: 0, alarm: true, flipped: new Set() }; go('u-study'); }")
    pg.wait_for_timeout(300)
    check("알람 장에서 녹음이 시작되지 않는다", pg.evaluate("() => { consentMem = true; const st = SPK.state; toggleSpeak(); return st === 'idle' && SPK.state === st && !S.modal; }"))
    pg.evaluate("() => { go('u-coll'); }"); pg.wait_for_timeout(320)
    pg.evaluate("""() => { const d = [...document.querySelectorAll('[data-act=drill]')][0]; if (d) d.click(); }""")
    pg.wait_for_timeout(460)
    check("문장 모음 연습: 알람 없음", pg.locator(".alarm").count() == 0, str(pg.locator(".alarm").count()))
    check("연습 진입이 실제로 됐다", pg.evaluate("() => !!S.drill"))

    # 유동 패딩
    pg.evaluate("() => { S.drill = null; S.studyEntry = 'tab'; S.studyDate = null; S.card = { date: null, i: 0, alarm: true, flipped: new Set() }; go('u-study'); }")
    pg.wait_for_timeout(420)
    pads = {}
    for w, h in [(320, 568), (390, 640), (390, 844), (430, 932), (1280, 1000)]:
        pg.set_viewport_size({"width": w, "height": h}); pg.wait_for_timeout(250)
        pads[f"{w}x{h}"] = pg.evaluate("""() => { const el = document.querySelector('.alarm'); if (!el) return null;
            const s = getComputedStyle(el); return { top: parseFloat(s.paddingTop), bottom: parseFloat(s.paddingBottom) }; }""")
    vals = [v["top"] for v in pads.values() if v]
    check("위아래 패딩 대칭", all(abs(v["top"] - v["bottom"]) < 0.5 for v in pads.values() if v), str(pads))
    check("높이에 따라 패딩 유동(3종 이상)", len(set(round(x, 1) for x in vals)) >= 3, str(vals))
    check("패딩 clamp 범위(14~34)", all(13.5 <= x <= 34.5 for x in vals), str(vals))
    pg.set_viewport_size({"width": 320, "height": 568}); pg.wait_for_timeout(240)
    check("320px 가로 넘침 없음", pg.evaluate("document.documentElement.scrollWidth") <= 320,
          str(pg.evaluate("document.documentElement.scrollWidth")))
    check("JS 오류 없음", not errs, str(errs[:2]))
    b.close()

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
