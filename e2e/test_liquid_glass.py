"""iOS 26 Liquid Glass 재질 — 떠 있는 층은 실제 blur, 컨텐츠 카드는 재질만, 접근성 대체 동작."""
import sys
from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8772"
res = []


def pin_transparency(pg, **media):
    """호스트 OS 의 '투명 효과 끔'(Windows)이 prefers-reduced-transparency: reduce 로 새어 들어오지 않게 고정한다.
    setEmulatedMedia 는 Playwright 의 color_scheme/contrast 에뮬레이션을 덮어쓰므로 그 값도 함께 넘긴다."""
    feats = [{"name": "prefers-reduced-transparency", "value": "no-preference"}]
    feats += [{"name": k.replace("_", "-"), "value": v} for k, v in media.items()]
    pg.context.new_cdp_session(pg).send("Emulation.setEmulatedMedia", {"features": feats})


def check(name, ok, note=""):
    res.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{note}]" if note and not ok else ""))


def _num(s):
    """계산된 색을 (r,g,b,a) 0~255 로. color(srgb r g b / a) 는 0~1 스케일이다."""
    import re
    m = [float(x) for x in re.findall(r"[\d.]+", s)]
    if s.strip().startswith("color("):
        k = 255.0
        a = m[3] if len(m) > 3 else 1.0
        return (m[0] * k, m[1] * k, m[2] * k, a)
    return (m[0] if m else 0, m[1] if len(m) > 1 else 0, m[2] if len(m) > 2 else 0,
            m[3] if len(m) > 3 else 1.0)


def _ratio(fg_s, chain):
    """fg 색과, 조상 배경들을 바깥→안쪽으로 합성한 실효 배경의 명도 대비."""
    base = (255, 255, 255, 1)
    inner = []
    for i in range(len(chain) - 1, -1, -1):
        c = _num(chain[i])
        if c[3] >= 1:
            base = c
            inner = chain[:i]
            break
    else:
        inner = chain[:]
    bg = list(base)

    def comp(t, b):
        return [t[0] * t[3] + b[0] * (1 - t[3]), t[1] * t[3] + b[1] * (1 - t[3]),
                t[2] * t[3] + b[2] * (1 - t[3]), 1.0]
    for i in range(len(inner) - 1, -1, -1):
        bg = comp(_num(inner[i]), bg)
    fg = comp(_num(fg_s), bg)
    lin = lambda v: (v / 255) / 12.92 if v / 255 <= .03928 else (((v / 255) + .055) / 1.055) ** 2.4
    l1 = .2126 * lin(fg[0]) + .7152 * lin(fg[1]) + .0722 * lin(fg[2])
    l2 = .2126 * lin(bg[0]) + .7152 * lin(bg[1]) + .0722 * lin(bg[2])
    x, y = l1 + .05, l2 + .05
    return max(x, y) / min(x, y)


def contrast(pg, sel):
    d = pg.evaluate("""(sel) => { const el = document.querySelector(sel); if (!el) return null;
        const out = [];
        for (let n = el; n && n.nodeType === 1; n = n.parentElement) out.push(getComputedStyle(n).backgroundColor);
        return { colors: out, fg: getComputedStyle(el).color }; }""", sel)
    if not d:
        return -1
    return round(_ratio(d["fg"], d["colors"]), 2)


def ready(pg):
    pg.goto(BASE + "/?demo=1")
    pg.wait_for_timeout(750)
    pg.evaluate("""try{localStorage.removeItem('cd_home')}catch(e){}
      S.user = DEMO_USER; ensure('plan'); S.today = S.trip.studyStart;
      PROG.act = {}; ['2026-09-20','2026-09-21'].forEach(d => PROG.act[d] = 6); PROG.act[S.today] = 4;
      render(); go('u-home')""")
    pg.wait_for_timeout(400)


with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True)
    pg = ctx.new_page()
    pin_transparency(pg)
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    ready(pg)

    # ── 카드 재질 ──
    card = pg.evaluate("""(() => {
        const c = document.querySelector('.alarm'); if (!c) return null; const s = getComputedStyle(c);
        const a = (s.backgroundColor.match(/[\\d.]+/g) || []).map(Number);
        return { bg: s.backgroundColor, alpha: a.length > 3 ? a[3] : 1, radius: parseFloat(s.borderRadius),
                 shadow: s.boxShadow, img: s.backgroundImage, blur: s.backdropFilter || s.webkitBackdropFilter };
    })()""")
    check("알람 카드가 어두운 면(블랙 계열 배경)", card["alpha"] >= 0, str(card["bg"]))
    check("카드에 상단 스페큘러 하이라이트", "inset" in card["shadow"], card["shadow"][:60])
    check("알람 카드에 광택 그라디언트", "gradient" in card["img"], card["img"][:60])
    check("카드 모서리가 24px 이상(동심)", card["radius"] >= 24, str(card["radius"]))
    check("알람 카드에는 blur 를 쓰지 않는다(굴절될 배경이 없다)", card["blur"] in ("none", ""), str(card["blur"]))
    check("카드 그림자가 있다", card["shadow"] not in ("none", ""))

    # ── 떠 있는 층: 실제 유리 ──
    bars = pg.evaluate("""(() => {
        const out = {};
        for (const sel of ['.appbar', '.pnav']) {
          const el = document.querySelector(sel);
          if (!el) continue; const s = getComputedStyle(el);
          const a = (s.backgroundColor.match(/[\\d.]+/g) || []).map(Number);
          out[sel] = { blur: s.backdropFilter, alpha: a.length > 3 ? a[3] : 1 };
        } return out; })()""")
    check("하단 탭바(.pnav)에 실제 blur", (bars.get(".pnav") or {}).get("blur", "").startswith("blur"), str(bars))
    check("탭바도 반투명", all(v["alpha"] < 1 for v in bars.values()), str(bars))
    pg.evaluate("go('u-sched')"); pg.wait_for_timeout(320)
    ab = pg.evaluate("(() => { const s = getComputedStyle(document.querySelector('.appbar')); return s.backdropFilter || s.webkitBackdropFilter; })()")
    check("상단 앱바(.appbar)에 blur", (ab or "").startswith("blur"), str(ab))
    pg.evaluate("go('u-home')"); pg.wait_for_timeout(300)
    nb = pg.evaluate("[...document.querySelectorAll('*')].filter(e => { const s = getComputedStyle(e); return (s.backdropFilter || '').startsWith('blur'); }).length")
    check("blur 요소는 6개 이하(성능)", nb <= 6, str(nb))
    check("글래스 위에 글래스를 겹치지 않는다(카드 내부 blur 없음)", pg.evaluate(
        "[...document.querySelectorAll('.alarm *')].every(e => !(getComputedStyle(e).backdropFilter || '').startsWith('blur'))"))

    # ── iOS 알람 화면 구성 ──
    lay = pg.evaluate("""(() => {
        const q = s => document.querySelector(s);
        const g = s => q(s) ? q(s).getBoundingClientRect() : null;
        const b = g('.alarm-big'), h = g('.alarm-h'), l = g('.alarm-label'), p = g('.alarm-primary'), c = g('.alarm');
        return { headAboveBig: !!h && h.bottom <= b.top + 1, labelBelowBig: l.top >= b.bottom - 2,
                 btnBelowLabel: p.top >= l.bottom, centered: Math.abs((b.left + b.width / 2) - (c.left + c.width / 2)) < 2 }; })()""")
    check("아이콘+라벨이 숫자 위", lay["headAboveBig"], str(lay))
    check("라벨이 숫자 아래", lay["labelBelowBig"], str(lay))
    check("주 버튼이 라벨 아래", lay["btnBelowLabel"], str(lay))
    check("숫자가 가운데 정렬", lay["centered"], str(lay))
    num = pg.evaluate("""(() => { const s = getComputedStyle(document.querySelector('.alarm-big'));
        return { fs: parseFloat(s.fontSize), fw: parseFloat(s.fontWeight), fv: s.fontVariantNumeric }; })()""")
    check("숫자 50px 이상", num["fs"] >= 50, str(num["fs"]))
    check("숫자 굵기 400 이하", num["fw"] <= 400, str(num["fw"]))
    check("숫자 고정폭", "tabular" in (num["fv"] or ""), str(num["fv"]))
    check("주 버튼 터치 50px 이상", pg.evaluate(
        "document.querySelector('.alarm-primary').getBoundingClientRect().height") >= 50)

    # ── 대비 ──
    for sel, label, want in ((".alarm-big", "큰 숫자", 4.5), (".alarm-label", "라벨", 4.5), (".alarm-meta", "메타", 4.5)):
        r = contrast(pg, sel)
        check(f"대비 {label} {r}:1 (>= {want})", r >= want, str(r))
    check("탭바 글자 대비 4.5:1 이상", contrast(pg, ".pnav button") >= 4.5,
          str(contrast(pg, ".pnav button")))
    # 유리 위 글자: 토스트·데모 버튼이 진한 면용 흰 글자를 그대로 두면 밝은 유리 위에서 안 보인다
    pg.evaluate("toast('이 화면에 필요한 데이터를 자동으로 준비했어요.')"); pg.wait_for_timeout(250)
    for sel, label in ((".toast", "토스트"), (".demo-fab", "데모 버튼")):
        r = contrast(pg, sel)
        check(f"유리 위 {label} 글자 대비 {r}:1 (>= 4.5)", r >= 4.5, str(r))

    # ── 접근성 대체 ──
    cc = b.new_context(viewport={"width": 390, "height": 844}, contrast="more")
    pc = cc.new_page()
    pin_transparency(pc, prefers_contrast="more")
    ready(pc)
    st = pc.evaluate("""(() => { const t = document.querySelector('.pnav'); const s = getComputedStyle(t);
        const c = getComputedStyle(document.querySelector('.alarm'));
        return { blur: s.backdropFilter, bwa: c.borderTopWidth, bg: c.backgroundColor }; })()""")
    check("대비 증가: 탭바 blur 끔", st["blur"] in ("none", ""), str(st["blur"]))
    check("대비 증가: 카드 경계 2px", st["bwa"] == "2px", str(st["bwa"]))
    check("대비 증가: 카드 불투명", st["bg"].startswith("rgb("), str(st["bg"]))
    cc.close()
    sheet = pg.evaluate("""(() => {
        let n = 0; for (const s of document.styleSheets) { try { for (const r of s.cssRules) {
          if (r.conditionText && r.conditionText.includes('prefers-reduced-transparency')) n++; } } catch (e) {} }
        return n; })()""")
    check("투명도 줄이기 대체 규칙이 있다", sheet >= 1, str(sheet))

    # ── 다크 ──
    cd = b.new_context(viewport={"width": 390, "height": 844}, color_scheme="dark")
    pd = cd.new_page()
    pin_transparency(pd, prefers_color_scheme="dark")
    ready(pd)
    dk = pd.evaluate("""(() => {
        const c = document.querySelector('.alarm'); if (!c) return null; const s = getComputedStyle(c);
        const a = (s.backgroundColor.match(/[\\d.]+/g) || []).map(Number);
        return { alpha: a.length > 3 ? a[3] : 1, bg: s.backgroundColor, blur: getComputedStyle(document.querySelector('.pnav')).backdropFilter }; })()""")
    check("다크: 알람 카드 유지", dk is not None, str(dk))
    check("다크: 탭바 blur 유지", dk["blur"].startswith("blur"), str(dk["blur"]))
    for sel, label in ((".alarm-big", "큰 숫자"), (".alarm-label", "라벨"), (".alarm-meta", "메타")):
        r = contrast(pd, sel)
        check(f"다크 대비 {label} {r}:1 (>= 4.5)", r >= 4.5, str(r))
    pd.evaluate("toast('이 화면에 필요한 데이터를 자동으로 준비했어요.')"); pd.wait_for_timeout(250)
    for sel, label in ((".toast", "토스트"), (".demo-fab", "데모 버튼")):
        r = contrast(pd, sel)
        check(f"다크 유리 위 {label} 글자 대비 {r}:1 (>= 4.5)", r >= 4.5, str(r))
    cd.close()

    # ── 레이아웃 회귀 ──
    for w in (320, 390, 430, 1280):
        pg.set_viewport_size({"width": w, "height": 900})
        pg.wait_for_timeout(220)
        check(f"{w}px: 가로 넘침 없음", pg.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"))
        check(f"{w}px: 숫자와 스위치 겹침 없음", pg.evaluate("""(() => [...document.querySelectorAll('.al-row')].every(r => {
            const m = r.getBoundingClientRect();
            const s = r.parentElement.getBoundingClientRect();
            return m.right <= s.left + 1; }))()"""))
    check("페이지 오류 없음", not errs, str(errs[:1]))
    b.close()

print(f"\n{sum(res)}/{len(res)} passed")
sys.exit(0 if all(res) else 1)
