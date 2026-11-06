#!/usr/bin/env python3
"""가로 모드·좁은 폰에서 레이아웃이 가로 폭 고정값에 묶이지 않는다 — 노치(안전 영역)까지 포함.

재현(11/05 사용자 화면): 가로 모드 아이폰은 env(safe-area-inset-left) 가 ~59px 인데 레일 칸이 72px 고정이라
레일 안쪽이 13px 로 줄어 '일정표'·'문장 모음'이 글자마다 꺾이고 아이콘이 잘렸다.
노치는 CDP Emulation.setSafeAreaInsetsOverride 로 흉내 낸다.

  A 가로 모드 + 왼쪽 노치: 레일 폭 = 72 + 노치, 라벨 한 줄, 아이콘 안 잘림
  B 가로 모드 + 오른쪽 노치: 내용(앱바·본문)이 노치에 가려지지 않는다
  C 여러 폭(세로·가로): 주요 화면 가로 스크롤 0, 화면 밖으로 나간 요소 0
  D 가로 모드 폰(높이 430)의 2열 학습 카드가 화면 높이를 넘지 않는다
"""
import sys
from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8899"
fails = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ((" — " + str(extra)) if (extra and not cond) else ""))
    if not cond:
        fails.append(name)


def page(b, w, h, insets=None, mobile=True):
    pg = b.new_page(viewport={"width": w, "height": h}, is_mobile=mobile, has_touch=mobile)
    if insets:
        cdp = pg.context.new_cdp_session(pg)
        cdp.send("Emulation.setSafeAreaInsetsOverride", {"insets": insets})
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(BASE + "/?demo=1&gate=off", timeout=60000); pg.wait_for_timeout(2200)
    if pg.locator('[data-act="guest"]').count():
        pg.locator('[data-act="guest"]').first.click(); pg.wait_for_timeout(1000)
    pg.evaluate("try{saveConsentHere(true)}catch(e){}; ensure('plan')")
    pg.evaluate("() => { const b = document.querySelector('[data-inapp=close]'); if (b) b.click(); }")
    return pg, errs


def go(pg, sid):
    pg.evaluate(f"navFromMenu('{sid}')"); pg.wait_for_timeout(700)
    pg.evaluate("S.modal && ACT['modal-ok'] && ACT['modal-ok']()"); pg.wait_for_timeout(250)


RAIL = """() => { const n = document.querySelector('.pnav'), nr = n.getBoundingClientRect();
  return { w: nr.width, pos: getComputedStyle(n).position,
    lines: [...n.querySelectorAll('button span')].map(s => { const r = document.createRange(); r.selectNodeContents(s);
      return [s.textContent, new Set([...r.getClientRects()].map(x => Math.round(x.top))).size]; }),
    clipped: [...n.querySelectorAll('svg')].filter(s => { const r = s.getBoundingClientRect(); return r.right > nr.right + 0.5 || r.left < nr.left - 0.5; }).length }; }"""

OVER = """() => { const vw = document.documentElement.clientWidth;
  const out = [...document.querySelectorAll('.pmain *')].filter(e => { const r = e.getBoundingClientRect();
    if (!r.width || !r.height) return false;
    let p = e.parentElement;   // 옆으로 밀리는 목록(칩·눈금) 안의 항목은 목록이 잘라 보여 주므로 제외
    while (p) { const ox = getComputedStyle(p).overflowX; if (ox === 'auto' || ox === 'scroll' || ox === 'hidden') return false; p = p.parentElement; }
    return r.right > vw + 1 || r.left < -1; }).map(e => e.className || e.tagName);
  return { hs: document.documentElement.scrollWidth - vw, out: out.slice(0, 4), n: out.length }; }"""

with sync_playwright() as p:
    b = p.chromium.launch()

    # ── A: 가로 모드 + 왼쪽 노치(아이폰 15 Pro Max 가로 932×430, 노치 59) ──
    pg, errs = page(b, 932, 430, {"left": 59, "right": 0, "top": 0, "bottom": 21})
    go(pg, "u-home")
    r = pg.evaluate(RAIL)
    check("A1 레일 폭이 노치만큼 넓어진다(72+59)", r["w"] >= 72 + 59 - 1, r["w"])
    check("A2 레일 라벨이 모두 한 줄", all(n == 1 for _, n in r["lines"]), r["lines"])
    check("A3 레일 아이콘이 잘리지 않는다", r["clipped"] == 0, r["clipped"])
    left = pg.evaluate("document.querySelector('.pmain .app-pad, .pmain .split').getBoundingClientRect().left")
    check("A4 본문은 레일 오른쪽에서 시작", left >= r["w"] - 1, (left, r["w"]))
    check("A5 페이지 오류 없음", not errs, errs[:2])
    pg.close()

    # ── B: 가로 모드 + 오른쪽 노치 ──
    pg, errs = page(b, 932, 430, {"left": 0, "right": 59, "top": 0, "bottom": 21})
    for sid in ("u-home", "u-coll"):
        go(pg, sid)
        rr = pg.evaluate("""() => { const vw = document.documentElement.clientWidth;
          const xs = [...document.querySelectorAll('.pmain .appbar *, .pmain .app-pad > *, .pmain .split > *')].map(e => e.getBoundingClientRect())
            .filter(r => r.width && r.height).map(r => r.right);
          return { vw, maxRight: Math.max(0, ...xs) }; }""")
        check(f"B {sid}: 내용이 오른쪽 노치(59px)에 가려지지 않는다", rr["maxRight"] <= rr["vw"] - 59 + 1, rr)
    pg.close()

    # ── C: 여러 폭 — 가로 스크롤·화면 밖 요소 0 ──
    sizes = [(320, 568), (360, 740), (390, 844), (568, 320), (667, 375), (844, 390), (932, 430), (1024, 768), (1280, 800)]
    for w, h in sizes:
        lm = w > h
        pg, errs = page(b, w, h, {"left": 47 if lm else 0, "right": 0, "top": 0 if lm else 47, "bottom": 21})
        bad = []
        for sid in ("u-home", "u-sched", "u-study", "u-coll", "u-ipa"):
            go(pg, sid)
            o = pg.evaluate(OVER)
            if o["hs"] > 0 or o["n"]:
                bad.append((sid, o))
        go(pg, "u-home")   # 발음기호 화면은 탭바가 없다 — 레일은 홈에서 잰다
        if pg.evaluate("getComputedStyle(document.querySelector('.pnav')).position") != "fixed":
            rl = pg.evaluate(RAIL)
            if not all(n == 1 for _, n in rl["lines"]) or rl["clipped"]:
                bad.append(("rail", rl))
        check(f"C {w}×{h}: 가로 스크롤·넘침 없음, 레일 라벨 한 줄", not bad and not errs, (bad[:2], errs[:1]))
        pg.close()

    # ── D: 가로 모드 폰의 2열 학습 카드 높이 ──
    pg, errs = page(b, 932, 430, {"left": 59, "right": 0, "top": 0, "bottom": 21})
    go(pg, "u-sched")
    fh = pg.evaluate("(() => { const f = document.querySelector('.split-detail .flip'); return f ? f.getBoundingClientRect().height : null; })()")
    check("D 2열 학습 카드가 화면 높이(430)를 넘지 않는다", fh is None or fh <= 430, fh)
    pg.close()
    b.close()

print("---")
print("ALL PASS" if not fails else "FAILED: " + ", ".join(fails))
sys.exit(1 if fails else 0)
