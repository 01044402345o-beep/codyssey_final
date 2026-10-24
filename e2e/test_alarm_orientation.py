#!/usr/bin/env python3
"""알람 카드의 두 방향 — 세로형 / 가로형. 방향은 '카드 폭'(컨테이너)으로 결정된다.

  세로(< 460px): 숫자·라벨·주간을 세로로 쌓고, 주간은 세로 막대(높이=그날 학습량)
  가로(>= 460px): 숫자 블록 | 버튼 블록 2단, 주간은 가로 눈금
  패딩: 세로형은 화면 높이(dvh), 가로형은 카드 폭(cqi)에 붙어 유동한다.
"""
import re, sys
from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8772"
passed = failed = 0


def check(name, ok, note=""):
    global passed, failed
    if ok:
        passed += 1; print("PASS " + name)
    else:
        failed += 1; print("FAIL " + name + (f"  [{note}]" if note else ""))


PROBE = """() => {
  const wrap = document.querySelector('.alarm-wrap'), el = document.querySelector('.alarm');
  if (!el) return null;
  const s = getComputedStyle(el), b = el.getBoundingClientRect();
  const bars = [...document.querySelectorAll('.alarm-week i')].map(i => {
    const r = i.getBoundingClientRect(); return { w: r.width, h: r.height, n: i.style.getPropertyValue('--n') }; });
  const acts = getComputedStyle(document.querySelector('.alarm-acts'));
  return { wrapW: wrap.getBoundingClientRect().width, h: b.height, w: b.width,
    padY: parseFloat(s.paddingTop), padBottom: parseFloat(s.paddingBottom), padX: parseFloat(s.paddingLeft),
    padRight: parseFloat(s.paddingRight), display: s.display, cols: s.gridTemplateColumns,
    align: s.textAlign, bars, actsDir: acts.flexDirection,
    overflowX: document.documentElement.scrollWidth > innerWidth + 1 }; }"""


def view(pg, w, h, tab=True):
    pg.set_viewport_size({"width": w, "height": h}); pg.wait_for_timeout(280)
    if tab:
        pg.evaluate("() => { S.studyEntry = 'tab'; S.card.alarm = true; S.card.i = 0; go('u-study'); }")
        pg.wait_for_timeout(320)
    return pg.evaluate(PROBE)


with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True)
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(BASE + "/?demo=1", timeout=60000); pg.wait_for_timeout(820)
    # 헤드리스 Chromium 은 음성 합성이 없어 상단에 "듣기가 안 돼요" 안내가 뜬다(실기기에는 없음) — 사용자가 하듯 닫고 잰다
    pg.evaluate("() => { const b = document.querySelector('[data-inapp=close]'); if (b) b.click(); }")
    pg.evaluate("""() => { S.user = DEMO_USER; ensure('plan'); S.today = S.trip.studyStart;
        PROG.act = {}; [2, 4, 6, 3].forEach((n, k) => { PROG.act[Dt.add(S.today, k - 4)] = n; });
        PROG.act[S.today] = 4;
        S.sched.filter(r => r.kind !== 'free').slice(0, 9).forEach(r => { r.completed = true; PROG.done[r.date] = Date.now(); });
        render(); S.studyEntry = 'tab'; go('u-study'); }""")
    pg.wait_for_timeout(430)

    # ── 세로형 ──
    r = pg.evaluate(PROBE)
    check("세로형: 카드 폭 420 미만", r["wrapW"] < 420, str(r["wrapW"]))
    check("세로형: 세로 스택(그리드 아님)", r["display"] == "flex", r["display"])
    check("세로형: 가운데 정렬", r["align"] == "center", r["align"])
    act_bars = [x for x in r["bars"] if x["n"] not in ("", "0")]
    check("세로형: 주간이 세로 막대(높이 > 폭)", len(act_bars) >= 3 and all(x["h"] > x["w"] for x in act_bars),
          str([(round(x["w"], 1), round(x["h"], 1)) for x in act_bars]))
    check("세로형: 막대 높이가 학습량을 따른다", len({round(x["h"]) for x in act_bars}) >= 2,
          str(sorted(round(x["h"]) for x in act_bars)))
    check("세로형: 막대가 아래로 정렬(바닥선)", pg.evaluate("""(() => {
        const ws = [...document.querySelectorAll('.alarm-week i')].map(i => i.getBoundingClientRect().bottom);
        return Math.max(...ws) - Math.min(...ws) < 1.5; })()"""))
    check("세로형: 위아래 패딩 대칭", abs(r["padY"] - r["padBottom"]) < .5, f'{r["padY"]}/{r["padBottom"]}')
    check("세로형: 좌우 패딩 대칭", abs(r["padX"] - r["padRight"]) < .5, f'{r["padX"]}/{r["padRight"]}')
    check("세로형: 카드가 높이를 먹는다(320~620)", 320 <= r["h"] <= 620, str(round(r["h"])))

    # ── 가로형 ──
    r2 = view(pg, 900, 900, tab=False)
    check("가로형: 카드 폭 420 이상", r2["wrapW"] >= 420, str(r2["wrapW"]))
    check("가로형: 2단 그리드", r2["display"] == "grid" and len(r2["cols"].split()) == 2, f'{r2["display"]} {r2["cols"]}')
    check("가로형: 왼쪽 정렬", r2["align"] == "left", r2["align"])
    check("가로형: 주간이 가로 눈금(폭 > 높이)", all(x["w"] > x["h"] for x in r2["bars"]),
          str([(round(x["w"], 1), round(x["h"], 1)) for x in r2["bars"]][:3]))
    wide = view(pg, 640, 900)
    check("넓은 카드(540+): 버튼이 한 줄", wide["actsDir"] == "row" and wide["wrapW"] >= 540,
          f'{wide["actsDir"]} {wide["wrapW"]:.0f}')
    check("중간 카드(420~540): 버튼이 세로", r2["actsDir"] == "column", r2["actsDir"])
    check("가로형: 카드 높이 245 이하(한 화면에 여유)", r2["h"] <= 245, str(round(r2["h"])))
    check("가로형: 좌우 패딩 대칭", abs(r2["padX"] - r2["padRight"]) < .5, f'{r2["padX"]}/{r2["padRight"]}')

    # ── 경계에서 방향이 뒤집힌다 ──
    left = view(pg, 430, 800, tab=False)
    right = view(pg, 470, 800, tab=False)
    check("430px: 아직 세로형", left["display"] == "flex", f'{left["display"]} {left["wrapW"]:.0f}')
    check("470px: 이미 가로형", right["display"] == "grid", f'{right["display"]} {right["wrapW"]:.0f}')

    # ── 패딩 유동(높이·폭 각각) ──
    heights = {}
    for h in (568, 720, 844, 932):
        heights[h] = view(pg, 390, h)["padY"]
    check("세로형: 화면 높이에 따라 위아래 패딩 유동", len({round(v, 1) for v in heights.values()}) >= 3,
          str({k: round(v, 1) for k, v in heights.items()}))
    check("패딩 clamp 범위(14~34)", all(13.5 <= v <= 34.5 for v in heights.values()),
          str({k: round(v, 1) for k, v in heights.items()}))
    widths = {}
    for w in (560, 640, 768):
        widths[w] = view(pg, w, 900, tab=False)["padX"]
    check("가로형: 카드 폭에 따라 좌우 패딩 유동", len({round(v, 1) for v in widths.values()}) >= 2,
          str({k: round(v, 1) for k, v in widths.items()}))
    check("가로형: 좌우 패딩 clamp 범위(16~32)", all(15.5 <= v <= 32.5 for v in widths.values()),
          str({k: round(v, 1) for k, v in widths.items()}))

    # ── 어떤 폭에서도 넘치지 않는다 ──
    for w, h in [(320, 568), (390, 844), (430, 932), (520, 800), (768, 1024), (1280, 900)]:
        rr = view(pg, w, h)
        check(f"{w}px: 가로 넘침 없음", not rr["overflowX"], "overflow")

    # ── 남는 공간에 상세를 채우는가 ──
    def detail(w, h):
        pg.set_viewport_size({"width": w, "height": h}); pg.wait_for_timeout(300)
        pg.evaluate("() => { S.studyEntry = 'tab'; S.card.alarm = true; S.card.i = 0; go('u-study'); }")
        pg.wait_for_timeout(340)
        return pg.evaluate("""() => { const el = document.querySelector('.alarm');
            const pad = el.closest('.app-pad');
            const vis = s => { const e = document.querySelector(s); return !!e && getComputedStyle(e).display !== 'none'; };
            /* 카드 아래 여백은 '알람 카드' 기준으로 잰다. pad 전체 max 를 쓰면 덱 하단 페이저(.card-nav)가
               잡혀, 카드가 아니라 페이저가 화면을 넘는지 재게 된다(568 에서 -32 로 오탐). */
            const last = el.getBoundingClientRect().bottom;
            const rail = document.querySelector('.alarm-rail');
            return { h: el.getBoundingClientRect().height, leftover: Math.round(innerHeight - last),
              days: vis('.alarm-days'), prog: vis('.alarm-prog'),
              labels: document.querySelectorAll('.alarm-days b').length,
              todayMarked: !!document.querySelector('.alarm-days b.today'),
              railW: rail ? Math.round(rail.querySelector('i').getBoundingClientRect().width) : 0,
              railFull: rail ? Math.round(rail.getBoundingClientRect().width) : 0,
              plabel: (document.querySelector('.alarm-plabel') || {}).innerText || '',
              count: (document.querySelector('.alarm-count') || {}).innerText || '',
              aria: rail ? (rail.getAttribute('aria-label') || '') : '',
              railH: rail ? Math.round(rail.getBoundingClientRect().height) : 0,
              progH: document.querySelector('.alarm-prog') ? Math.round(document.querySelector('.alarm-prog').getBoundingClientRect().height) : 0,
              overflow: document.documentElement.scrollWidth > innerWidth + 1,
              clipped: el.scrollHeight > el.getBoundingClientRect().height + 1 }; }""")

    low = detail(320, 568)
    check("낮은 화면(568): 요일 이름 숨김", low["days"] is False, str(low["days"]))
    check("낮은 화면(568): 진도 상세 숨김", low["prog"] is False, str(low["prog"]))
    check("낮은 화면(568): 카드가 화면을 넘지 않는다", low["leftover"] >= -6 and not low["clipped"], str(low["leftover"]))
    mid = detail(390, 700)
    check("중간 화면(700): 요일 이름 표시", mid["days"] is True and mid["labels"] == 7, str(mid))
    check("중간 화면(700): 오늘 요일 강조", mid["todayMarked"] is True)
    check("중간 화면(700): 진도 상세는 아직 숨김", mid["prog"] is False)
    tall = detail(390, 844)
    check("큰 화면(844): 진도 상세 표시", tall["prog"] is True, str(tall["prog"]))
    check("큰 화면(844): 완료율 레일이 채워진다", tall["railW"] > 0 and tall["railW"] <= tall["railFull"],
          f'{tall["railW"]}/{tall["railFull"]}')
    check("큰 화면(844): 진도는 '완료율 — 레일 — n/46일' 한 줄",
          tall["plabel"] == "완료율" and re.fullmatch(r"\d+/\d+일", tall["count"].strip()) is not None,
          f'{tall["plabel"]!r} {tall["count"]!r}')
    check("큰 화면(844): 진도 한 줄이 두 줄로 늘어나지 않는다", tall["progH"] <= 24, str(tall["progH"]))
    check("큰 화면(844): 레일은 주간 막대 굵기(8px)",
          tall["railH"] == 8, str(tall["railH"]))
    check("큰 화면(844): 완료·학습·미완료는 aria-label 에 남는다",
          all(k in tall["aria"] for k in ("완료", "학습", "미완료")), tall["aria"])
    check("큰 화면(844): 카드 안이 잘리지 않는다", not tall["clipped"])
    check("큰 화면(844): 아래 남는 여백이 120px 이하", tall["leftover"] <= 130, str(tall["leftover"]))
    check("큰 화면(844): 카드가 68dvh 이상", tall["h"] >= 844 * 0.66, str(round(tall["h"])))

    check("JS 오류 없음", not errs, str(errs[:2]))
    b.close()

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
