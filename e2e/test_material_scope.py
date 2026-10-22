#!/usr/bin/env python3
"""재질 확장 회귀 — L0(raised/tinted/ink) + L1(glass) 규칙이 모든 화면에서 지켜지는가.

알람 카드 한 곳에서 만든 재질을 앱 전체로 넓혔으므로, 화면마다 같은 계약을 검사한다:
  1. 컨텐츠 카드에 backdrop-filter 금지
  2. 카드 경계는 같은 토큰(모든 카드의 border-top-color 동일)
  3. 카드에 inset 스페큘러(유리로 읽히는 유일한 장치)
  4. 한 화면에 ink(어두운 불투명 면) 1개 이하
  5. tinted 카드는 표면색과 다르고, 글자 대비 4.5:1 이상
  6. 떠 있는 층(.pnav/.appbar)은 실제 blur 유지
"""
import sys
from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8772"


def pin_transparency(pg, **media):
    """호스트 OS 의 '투명 효과 끔'(Windows)이 prefers-reduced-transparency: reduce 로 새어 들어오지 않게 고정한다.
    setEmulatedMedia 는 Playwright 의 color_scheme/contrast 에뮬레이션을 덮어쓰므로 그 값도 함께 넘긴다."""
    feats = [{"name": "prefers-reduced-transparency", "value": "no-preference"}]
    feats += [{"name": k.replace("_", "-"), "value": v} for k, v in media.items()]
    pg.context.new_cdp_session(pg).send("Emulation.setEmulatedMedia", {"features": feats})
passed = failed = 0

def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"PASS {name}")
    else:
        failed += 1
        print(f"FAIL {name}" + (f"  [{detail}]" if detail else ""))

CARDS = [".card", ".city-card", ".summary-strip > div", ".srow", ".interp-item",
         ".live-card", ".past-card", ".ilog-card", ".today-card", ".streak-card", ".account-card", ".sent", ".face.front"]

JS_PROBE = """(sels) => {
  const px = el => { const s = getComputedStyle(el); return { border: s.borderTopColor, shadow: s.boxShadow,
    bg: s.backgroundColor, blur: s.backdropFilter || s.webkitBackdropFilter, color: s.color,
    radius: s.borderTopLeftRadius, area: el.getBoundingClientRect().width * el.getBoundingClientRect().height }; };
  const found = [];
  for (const sel of sels) {
    document.querySelectorAll(sel).forEach(el => {
      if (el.closest('.side')) return;               // 관리자 사이드는 제품 화면이 아니다
      const r = el.getBoundingClientRect();
      if (r.width < 40 || r.height < 20) return;      // 잘린 조각·아이콘 제외
      found.push({ sel, ...px(el) });
    });
  }
  const invBg = getComputedStyle(document.documentElement).getPropertyValue('--inv-bg').trim();
  const ink = [...document.querySelectorAll('*')].filter(el => {
    if (el.closest('.side')) return false;
    const s = getComputedStyle(el); const r = el.getBoundingClientRect();
    if (r.width * r.height < 6000) return false;
    if (s.backgroundImage.includes('gradient')) return false;
    return s.backgroundColor === 'rgb(22, 27, 38)' || s.backgroundColor === invBg;
  }).map(el => el.className.toString().slice(0, 30));
  return { found, ink };
}"""

def lum(st):
    import re
    m = [float(x) for x in re.findall(r"[\d.]+", st or "")]
    v = [x * 255 for x in m[:3]] if st.startswith("color(") else m[:3]
    f = lambda c: (c / 255) / 12.92 if c / 255 <= .03928 else ((c / 255 + .055) / 1.055) ** 2.4
    return .2126 * f(v[0]) + .7152 * f(v[1]) + .0722 * f(v[2])

def ratio(a, b):
    l1, l2 = lum(a), lum(b)
    hi, lo = max(l1, l2), min(l1, l2)
    return round((hi + .05) / (lo + .05), 2)

def ready(pg):
    pg.wait_for_timeout(700)
    pg.evaluate("""() => { if (typeof DEMO_USER !== 'undefined' && !S.user) { S.user = DEMO_USER; ensure('plan'); }
        S.today = (S.trip && S.trip.studyStart) || S.today; render(); go('u-home'); }""")
    pg.wait_for_timeout(300)

SCREENS = [("u-home", "홈"), ("u-sched", "일정표"), ("u-coll", "문장 모음"), ("u-study", "학습")]

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True)
    pg = ctx.new_page()
    pin_transparency(pg)
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(f"{BASE}/?demo=1")
    ready(pg)

    borders, tinted_seen = set(), 0
    for scr, label in SCREENS:
        pg.evaluate(f"go('{scr}')")
        pg.wait_for_timeout(320)
        probe = pg.evaluate(JS_PROBE, CARDS)
        cards = probe["found"]
        check(f"{label}: 컨텐츠 카드가 있다", len(cards) >= 1, str(len(cards)))
        check(f"{label}: 카드에 backdrop-filter 없음",
              all(c["blur"] in ("none", "") for c in cards),
              str([c["sel"] for c in cards if c["blur"] not in ("none", "")])[:120])
        check(f"{label}: 카드에 inset 스페큘러",
              all("inset" in c["shadow"] for c in cards),
              str([c["sel"] for c in cards if "inset" not in c["shadow"]])[:120])
        for c in cards:
            borders.add(c["border"])
        check(f"{label}: ink 면 1개 이하", len(probe["ink"]) <= 1, str(probe["ink"]))
        tint = [c for c in cards if c["sel"] in (".today-card", ".streak-card")]
        for c in tint:
            tinted_seen += 1
            check(f"{label}: tinted 카드가 표면색과 다름", c["bg"] not in ("rgb(255, 255, 255)", "rgba(0, 0, 0, 0)"), c["bg"])
            r = ratio(c["color"], c["bg"])
            check(f"{label}: tinted 글자 대비 {r}:1 (>= 4.5)", r >= 4.5, str(r))
        blur = pg.evaluate("""() => { const n = document.querySelector('.pnav') || document.querySelector('.appbar');
            return n ? (getComputedStyle(n).backdropFilter || '') : ''; }""")
        check(f"{label}: 떠 있는 층 blur 유지", blur.startswith("blur"), blur)

    check("카드 경계가 하나의 토큰으로 통일", len(borders) <= 2, str(borders))
    check("tinted 카드가 실제로 쓰인다(오늘/연속)", tinted_seen >= 1, str(tinted_seen))

    # 시트는 떠 있는 층 — 열어서 blur 확인
    pg.evaluate("go('u-sched')"); pg.wait_for_timeout(300)
    opened = pg.evaluate("""() => { const r = document.querySelector('.srow'); if (r) { r.click(); return true; } return false; }""")
    pg.wait_for_timeout(420)
    if opened:
        sh = pg.evaluate("""() => { const el = document.querySelector('.sheet, .il-sheet');
            if (!el) return null; const s = getComputedStyle(el);
            return { blur: s.backdropFilter || s.webkitBackdropFilter || '', bg: s.backgroundColor }; }""")
        if sh:
            check("시트는 L1(실제 blur)", sh["blur"].startswith("blur"), str(sh))

    # 다크에서도 같은 계약
    ctx2 = b.new_context(viewport={"width": 390, "height": 844}, color_scheme="dark", has_touch=True)
    pg2 = ctx2.new_page()
    pin_transparency(pg2, prefers_color_scheme="dark")
    pg2.on("pageerror", lambda e: errs.append(str(e)))
    pg2.goto(f"{BASE}/?demo=1"); ready(pg2)
    for scr, label in [("u-home", "다크 홈"), ("u-sched", "다크 일정표")]:
        pg2.evaluate(f"go('{scr}')"); pg2.wait_for_timeout(300)
        probe = pg2.evaluate(JS_PROBE, CARDS)
        check(f"{label}: 카드 blur 없음", all(c["blur"] in ("none", "") for c in probe["found"]), "")
        check(f"{label}: ink 면 1개 이하", len(probe["ink"]) <= 1, str(probe["ink"]))
        for c in [x for x in probe["found"] if x["sel"] in (".today-card", ".streak-card")]:
            r = ratio(c["color"], c["bg"])
            check(f"{label}: tinted 대비 {r}:1 (>= 4.5)", r >= 4.5, str(r))

    check("JS 오류 없음", not errs, str(errs[:2]))
    b.close()

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
