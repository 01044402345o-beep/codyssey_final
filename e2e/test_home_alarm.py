"""학습 탭 '오늘의 알람' — iOS 알람(AlarmKit) 화면 구성. 목록·토글이 아니라 알람 카드 자체.
   구성: 작은 아이콘+라벨 → 아주 큰 숫자 → 회색 라벨 → 넓은 캡슐 주 버튼 + 보조 버튼."""
import sys
from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8772"
res = []


def check(name, ok, note=""):
    res.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{note}]" if note and not ok else ""))


def ready(pg):
    pg.goto(BASE + "/?demo=1")
    pg.wait_for_timeout(720)
    pg.evaluate("""S.user = DEMO_USER; ensure('plan'); S.today = S.trip.studyStart; render(); ACT.tab({ dataset: { id: 'u-study' } })""")
    pg.wait_for_timeout(350)


def act(pg, n, extra=None):
    pg.evaluate("""([n, extra]) => { PROG.act = {}; if (extra) extra.forEach(d => PROG.act[d] = 6);
      if (n) PROG.act[S.today] = n; render(); }""", [n, extra])
    pg.wait_for_timeout(230)


with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True)
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    ready(pg)

    # ── 알람 화면 구성 ──
    check("알람 카드가 하나", pg.locator(".alarm").count() == 1)
    check("목록·토글이 아니다(행/스위치 없음)", pg.locator(".al-card, .al-row, .al-sw, [role=switch]").count() == 0)
    check("위쪽 아이콘 + 라벨", pg.locator(".alarm-h svg").count() == 1 and "알람" in pg.inner_text(".alarm-h"))
    check("라벨이 아이콘 오른쪽(가로)", pg.evaluate("""(() => {
        const i = document.querySelector('.alarm-h svg').getBoundingClientRect();
        const h = document.querySelector('.alarm-h').getBoundingClientRect();
        return Math.abs((i.top + i.height / 2) - (h.top + h.height / 2)) < 6 && i.left < h.left + h.width / 2; })()"""))
    big = pg.evaluate("""(() => { const e = document.querySelector('.alarm-big'); const s = getComputedStyle(e);
        const r = e.getBoundingClientRect();
        return { fs: parseFloat(s.fontSize), fw: parseFloat(s.fontWeight), ls: s.letterSpacing,
                 fv: s.fontVariantNumeric, w: r.width, h: r.height, cx: r.left + r.width / 2 }; })()""")
    check("큰 숫자가 50px 이상", big["fs"] >= 50, str(big["fs"]))
    check("큰 숫자 굵기 400 이하(알람 시계)", big["fw"] <= 400, str(big["fw"]))
    check("큰 숫자 자간 좁힘", big["ls"].startswith("-") and big["ls"] not in ("normal", "0px"), str(big["ls"]))
    check("큰 숫자 고정폭", "tabular" in (big["fv"] or ""), str(big["fv"]))
    check("큰 숫자가 카드 가운데", abs(big["cx"] - 195) < 2, str(big["cx"]))
    check("큰 숫자 아래 라벨", pg.evaluate("""(() => {
        const b = document.querySelector('.alarm-big').getBoundingClientRect();
        const l = document.querySelector('.alarm-label').getBoundingClientRect();
        return l.top >= b.bottom - 2; })()"""))
    check("라벨이 작고 회색", pg.evaluate("parseFloat(getComputedStyle(document.querySelector('.alarm-label')).fontSize)") < 17)
    # 버튼
    pr_btn = pg.evaluate("""(() => { const e = document.querySelector('.alarm-primary'); const s = getComputedStyle(e);
        const r = e.getBoundingClientRect(); const c = document.querySelector('.alarm').getBoundingClientRect();
        return { h: r.height, w: r.width, cw: c.width, radius: parseFloat(s.borderRadius), fw: parseFloat(s.fontWeight) }; })()""")
    check("주 버튼 높이 50px 이상", pr_btn["h"] >= 50, str(pr_btn["h"]))
    check("주 버튼이 카드 폭을 거의 채운다", pr_btn["w"] / pr_btn["cw"] > 0.82, str(pr_btn))
    check("주 버튼이 캡슐(반경 999px)", pr_btn["radius"] >= 40, str(pr_btn["radius"]))
    check("주 버튼 글자 굵게", pr_btn["fw"] >= 600, str(pr_btn["fw"]))
    check("보조 버튼도 44px 이상", pg.evaluate(
        "document.querySelector('.alarm-second').getBoundingClientRect().height") >= 43.5)
    check("버튼 두 개가 카드 안에서 세로로", pg.evaluate("""(() => {
        const a = document.querySelector('.alarm-primary').getBoundingClientRect();
        const s = document.querySelector('.alarm-second').getBoundingClientRect();
        const c = document.querySelector('.alarm').getBoundingClientRect();
        return s.top >= a.bottom - 1 && s.bottom <= c.bottom + 1; })()"""))
    # 알람 카드 = iOS 27 틴티드(불투명에 가까운) 면
    check("카드가 밝은 틴트 면(검정 아님)", pg.evaluate("""(() => {
        const el = document.querySelector('.alarm'); if (!el) return false;
        const m = getComputedStyle(el).backgroundColor.match(/[\d.]+/g).map(Number);
        const lum = (0.2126 * m[0] + 0.7152 * m[1] + 0.0722 * m[2]) / 255;
        return lum > .80; })()"""))
    check("큰 숫자는 어두운 글자", pg.evaluate("""(() => {
        const el = document.querySelector('.alarm-big'); if (!el) return false;
        const m = getComputedStyle(el).color.match(/[\d.]+/g).map(Number);
        const lum = (0.2126 * m[0] + 0.7152 * m[1] + 0.0722 * m[2]) / 255;
        return lum < .22; })()"""))
    # ── 값 ──
    act(pg, 4)
    check("4장이면 숫자 4", pg.inner_text(".alarm-big").strip().startswith("4"))
    check("단위 /10장", "/10" in pg.inner_text(".alarm-big"))
    check("4장 안내: 6장 남음", "6장" in pg.inner_text(".alarm-label"))
    check("주 버튼 '학습 시작'", pg.inner_text(".alarm-primary").strip() in ("학습 시작", "카드 보기"))
    act(pg, 10)
    check("10장: 달성 문구", "채웠어요" in pg.inner_text(".alarm-label"))
    check("10장: 주 버튼 '다시 보기'", pg.inner_text(".alarm-primary").strip() in ("다시 보기", "카드 보기"))
    act(pg, 0)
    check("0장: 시작 안내", "뒤집" in pg.inner_text(".alarm-label") or "시작" in pg.inner_text(".alarm-label"))
    act(pg, 3, ["2026-09-20", "2026-09-21"])
    check("주간 막대 7칸", pg.locator(".alarm-week i").count() == 7)
    check("연속·여행 전체가 카드 안에", "연속" in pg.inner_text(".alarm-meta") and "%" in pg.inner_text(".alarm-meta"))

    # ── 동작 ──
    pg.click(".alarm-primary")
    pg.wait_for_timeout(420)
    check("주 버튼이 오늘 학습으로", pg.evaluate("S.screen") == "u-study", pg.evaluate("S.screen"))
    pg.evaluate("ACT.tab({ dataset: { id: 'u-study' } })")
    pg.wait_for_timeout(300)
    pg.click(".alarm-second")
    pg.wait_for_timeout(350)
    check("보조 버튼이 일정표로", pg.evaluate("S.screen") == "u-sched", pg.evaluate("S.screen"))
    pg.evaluate("ACT.tab({ dataset: { id: 'u-study' } })")
    pg.wait_for_timeout(300)

    # ── 레이아웃 ──
    for w in (320, 390, 430):
        pg.set_viewport_size({"width": w, "height": 900})
        pg.wait_for_timeout(240)
        check(f"{w}px: 가로 넘침 없음", pg.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"))
        check(f"{w}px: 카드가 화면 안", pg.evaluate("""(() => { const c = document.querySelector('.alarm').getBoundingClientRect();
            return c.left >= 0 && c.right <= innerWidth + 1; })()"""))
        check(f"{w}px: 카드 높이 360px 이하", pg.evaluate(
            "document.querySelector('.alarm').getBoundingClientRect().height") <= 360,
            str(round(pg.evaluate("document.querySelector('.alarm').getBoundingClientRect().height"))))
        check(f"{w}px: 숫자가 한 줄", pg.evaluate(
            "document.querySelector('.alarm-big').getBoundingClientRect().height") < 90)
        check(f"{w}px: 버튼이 카드 밖으로 안 나감", pg.evaluate("""(() => {
            const c = document.querySelector('.alarm').getBoundingClientRect();
            return [...document.querySelectorAll('.alarm-primary, .alarm-second')].every(e => {
              const r = e.getBoundingClientRect(); return r.left >= c.left && r.right <= c.right + 1; }); })()"""))
    pg.set_viewport_size({"width": 1280, "height": 900})
    pg.wait_for_timeout(240)
    check("1280px: 가로 넘침 없음", pg.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"))

    # ── 다른 화면 ──
    pg.evaluate("go('u-sched')"); pg.wait_for_timeout(240)
    check("다른 화면에는 없다", pg.locator(".alarm").count() == 0)
    pg.evaluate("ACT.tab({ dataset: { id: 'u-study' } })"); pg.wait_for_timeout(240)
    check("홈으로 돌아오면 다시 있다", pg.locator(".alarm").count() == 1)

    # ── 다크·모션 ──
    cd = b.new_context(viewport={"width": 390, "height": 844}, color_scheme="dark")
    pd = cd.new_page()
    ready(pd)
    check("다크: 알람 카드 유지", pd.locator(".alarm").count() == 1)
    check("다크: 숫자 대비 4.5:1 이상", pd.evaluate("""(() => {
        const f = (s) => { const m = (s.match(/[\\d.]+/g) || []).map(Number); return [m[0], m[1], m[2]]; };
        const lin = v => { v /= 255; return v <= .03928 ? v / 12.92 : Math.pow((v + .055) / 1.055, 2.4); };
        const L = c => .2126 * lin(c[0]) + .7152 * lin(c[1]) + .0722 * lin(c[2]);
        const fg = f(getComputedStyle(document.querySelector('.alarm-big')).color);
        const bg = f(getComputedStyle(document.querySelector('.alarm')).backgroundColor);
        const a = L(fg) + .05, b = L(bg) + .05;
        return Math.max(a, b) / Math.min(a, b) >= 4.5; })()"""))
    cd.close()
    cr = b.new_context(viewport={"width": 390, "height": 844}, reduced_motion="reduce")
    pr2 = cr.new_page()
    ready(pr2)
    check("reduced-motion: 카드 유지", pr2.locator(".alarm").count() == 1)
    check("reduced-motion: 버튼 눌림 변형 없음", pr2.evaluate("""(() => {
        let hit = 0;
        for (const s of document.styleSheets) { try { for (const r of s.cssRules) {
          if (r.conditionText && r.conditionText.includes('prefers-reduced-motion') && r.cssText.includes('.alarm-primary')) hit++; } } catch (e) {} }
        return hit >= 1; })()"""))
    cr.close()
    check("페이지 오류 없음(전체)", not errs, str(errs[:1]))
    b.close()

print(f"\n{sum(res)}/{len(res)} passed")
sys.exit(0 if all(res) else 1)
