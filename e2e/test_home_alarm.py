"""홈 '학습 현황' — iOS 알람 카드형 목록. 행을 세로로 쌓고 오른쪽 스위치로 설명을 접는다."""
import sys
from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8772"
res = []


def check(name, ok, note=""):
    res.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{note}]" if note and not ok else ""))


def ready(pg):
    pg.goto(BASE + "/?demo=1")
    pg.wait_for_timeout(700)
    pg.evaluate("try{localStorage.removeItem('cd_home')}catch(e){}")
    pg.evaluate("S.user = DEMO_USER; ensure('plan'); S.today = S.trip.studyStart; render(); go('u-home')")
    pg.wait_for_timeout(350)


def act(pg, n, extra=None):
    pg.evaluate("""([n, extra]) => { PROG.act = {}; if (extra) extra.forEach(d => PROG.act[d] = 6);
      if (n) PROG.act[S.today] = n; render(); }""", [n, extra])
    pg.wait_for_timeout(250)


with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True)
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    ready(pg)

    # ── 알람 카드 구조 ──
    check("카드가 하나다", pg.locator(".al-card").count() == 1)
    check("행이 3개", pg.locator(".al-row").count() == 3)
    check("행 제목 순서", pg.locator(".al-row .al-t").all_inner_texts() == ["오늘의 목표", "연속 학습", "여행 전체"],
          str(pg.locator(".al-row .al-t").all_inner_texts()))
    check("행마다 스위치가 있다", pg.locator(".al-sw").count() == 3)
    check("스위치는 role=switch + aria-checked", pg.evaluate(
        "[...document.querySelectorAll('.al-sw')].every(e => e.getAttribute('role') === 'switch' && e.getAttribute('aria-checked') === 'true')"))
    check("행 사이 구분선이 있다", pg.evaluate("""(() => {
        const r = [...document.querySelectorAll('.al-row')];
        return r.length === 3 && r.slice(1).every(e => parseFloat(getComputedStyle(e).borderTopWidth) >= 1); })()"""))
    check("구분선은 카드 안쪽에서 시작한다(카드 테두리와 겹치지 않음)", pg.evaluate("""(() => {
        const c = document.querySelector('.al-card').getBoundingClientRect();
        const r = document.querySelectorAll('.al-row')[1].getBoundingClientRect();
        return r.left >= c.left - 1 && r.right <= c.right + 1; })()"""))
    check("큰 숫자가 24px 이상", pg.evaluate("parseFloat(getComputedStyle(document.querySelector('.al-main b')).fontSize)") >= 24)
    check("큰 숫자는 굵기 500 이하(알람 시계처럼 가볍게)", pg.evaluate(
        "parseFloat(getComputedStyle(document.querySelector('.al-main b')).fontWeight)") <= 500,
        str(pg.evaluate("getComputedStyle(document.querySelector('.al-main b')).fontWeight")))
    check("스위치 트랙이 46x28", pg.evaluate("""(() => {
        const t = document.querySelector('.al-sw i').getBoundingClientRect();
        return Math.abs(t.width - 46) < 1 && Math.abs(t.height - 28) < 1; })()"""))
    check("스위치 버튼 높이 44px 이상", pg.evaluate(
        "[...document.querySelectorAll('.al-sw')].every(e => e.getBoundingClientRect().height >= 43.5)"))
    check("넘김·점·멈춤 버튼이 없다", pg.locator(".deck-dot, .deck-auto, .duo-dot, .duo-pg").count() == 0)
    check("'undefined'/'NaN' 없음", "undefined" not in pg.inner_text("body") and "NaN" not in pg.inner_text("body"))
    check("페이지 오류 없음", not errs, str(errs[:1]))

    # ── 세 값이 동시에 보인다 ──
    t = pg.inner_text(".al-card")
    check("오늘/연속/여행 전체가 한 카드에 동시에", all(k in t for k in ("/10장", "연속 학습", "여행 전체")), t[:80])
    check("주간 막대 7칸", pg.locator(".al-week i").count() == 7)

    # ── 스위치 = 접기/펼치기 ──
    h0 = pg.evaluate("document.querySelector('.al-card').getBoundingClientRect().height")
    pg.click('.al-sw[data-k="goal"]')
    pg.wait_for_timeout(250)
    check("스위치를 끄면 aria-checked=false", pg.get_attribute('.al-sw[data-k="goal"]', "aria-checked") == "false")
    check("끄면 행은 남는다", pg.locator('.al-row[data-k="goal"]').count() == 1)
    check("끄면 설명이 사라진다", pg.locator('.al-row[data-k="goal"] .al-sub').count() == 0)
    h1 = pg.evaluate("document.querySelector('.al-card').getBoundingClientRect().height")
    check("끄면 카드가 줄어든다", h1 < h0 - 10, f"{h0} → {h1}")
    check("끈 행은 흐리게", pg.evaluate("getComputedStyle(document.querySelector('.al-row[data-k=goal] .al-main b')).color")
          != pg.evaluate("getComputedStyle(document.querySelector('.al-row[data-k=prog] .al-main b')).color"))
    pg.click('.al-sw[data-k="goal"]')
    pg.wait_for_timeout(250)
    check("다시 켜면 설명이 돌아온다", pg.locator('.al-row[data-k="goal"] .al-sub').count() == 1)
    check("다시 켜면 높이가 복구", abs(pg.evaluate("document.querySelector('.al-card').getBoundingClientRect().height") - h0) < 2)

    # ── 저장 ──
    pg.click('.al-sw[data-k="prog"]')
    pg.wait_for_timeout(250)
    pg.reload()
    pg.wait_for_timeout(700)
    pg.evaluate("S.user = DEMO_USER; ensure('plan'); S.today = S.trip.studyStart; render(); go('u-home')")
    pg.wait_for_timeout(350)
    check("새로 고쳐도 스위치 상태가 남는다", pg.get_attribute('.al-sw[data-k="prog"]', "aria-checked") == "false")
    pg.evaluate("try{localStorage.removeItem('cd_home')}catch(e){}")
    pg.evaluate("render()")
    pg.wait_for_timeout(250)
    check("저장값을 지우면 기본(모두 켜짐)", pg.evaluate(
        "[...document.querySelectorAll('.al-sw')].every(e => e.getAttribute('aria-checked') === 'true')"))

    # ── 행을 누르면 이동 ──
    act(pg, 4)
    pg.click('.al-row[data-k="goal"] .al-main')
    pg.wait_for_timeout(400)
    check("'오늘의 목표' 행을 누르면 학습 화면", pg.evaluate("S.screen") == "u-study", pg.evaluate("S.screen"))
    pg.evaluate("go('u-home')")
    pg.wait_for_timeout(300)
    pg.click('.al-row[data-k="prog"] .al-main')
    pg.wait_for_timeout(350)
    check("'여행 전체' 행을 누르면 일정표", pg.evaluate("S.screen") == "u-sched", pg.evaluate("S.screen"))
    pg.evaluate("go('u-home')")
    pg.wait_for_timeout(300)

    # ── 값 ──
    act(pg, 0)
    check("0장이면 0 표시", pg.inner_text('.al-row[data-k="goal"] .al-main b').strip() == "0")
    act(pg, 10)
    check("10장이면 달성 안내", "채웠어요" in pg.inner_text('.al-row[data-k="goal"]'))
    act(pg, 3, ["2026-09-20", "2026-09-21"])
    check("연속 일수가 계산된다", pg.inner_text('.al-row[data-k="streak"] .al-main b').strip().isdigit())
    check("이번 주 학습 일수 문구", "이번 주" in pg.inner_text('.al-row[data-k="streak"]'))

    # ── 레이아웃 ──
    for w in (320, 390, 430):
        pg.set_viewport_size({"width": w, "height": 900})
        pg.wait_for_timeout(250)
        check(f"{w}px: 가로 넘침 없음", pg.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"))
        check(f"{w}px: 숫자와 스위치가 겹치지 않는다", pg.evaluate("""(() => {
            return [...document.querySelectorAll('.al-row')].every(r => {
              const m = r.querySelector('.al-main').getBoundingClientRect();
              const s = r.querySelector('.al-sw').getBoundingClientRect();
              return m.right <= s.left + 1; }); })()"""))
        check(f"{w}px: 카드가 화면 안에", pg.evaluate("""(() => {
            const c = document.querySelector('.al-card').getBoundingClientRect();
            return c.left >= 0 && c.right <= innerWidth + 1; })()"""))
        check(f"{w}px: 카드 높이가 320px 이하(공간 절약)", pg.evaluate(
            "document.querySelector('.al-card').getBoundingClientRect().height") <= 320,
            str(round(pg.evaluate("document.querySelector('.al-card').getBoundingClientRect().height"))))
    pg.set_viewport_size({"width": 1280, "height": 900})
    pg.wait_for_timeout(250)
    check("1280px: 가로 넘침 없음", pg.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"))
    check("1280px: 숫자와 스위치가 한 줄에 나란히", pg.evaluate("""(() => {
        return [...document.querySelectorAll('.al-row')].every(r => {
          const m = r.querySelector('.al-main').getBoundingClientRect();
          const s = r.querySelector('.al-sw').getBoundingClientRect();
          return Math.abs((m.top + m.height / 2) - (s.top + s.height / 2)) < 60; }); })()"""))
    check("1280px: 행 높이가 과하게 늘지 않는다(<=140px)", pg.evaluate(
        "Math.max(...[...document.querySelectorAll('.al-row')].map(e => e.getBoundingClientRect().height))") <= 140,
        str(round(pg.evaluate("Math.max(...[...document.querySelectorAll('.al-row')].map(e => e.getBoundingClientRect().height))"))))

    # ── 다른 화면 ──
    pg.evaluate("go('u-sched')")
    pg.wait_for_timeout(250)
    check("다른 화면에는 없다", pg.locator(".al-card").count() == 0)
    pg.evaluate("go('u-home')")
    pg.wait_for_timeout(250)
    check("홈으로 돌아오면 다시 있다", pg.locator(".al-card").count() == 1)

    # ── 움직임 줄이기 ──
    cr = b.new_context(viewport={"width": 390, "height": 844}, reduced_motion="reduce")
    p2 = cr.new_page()
    ready(p2)
    check("reduced-motion: 행 3개 그대로", p2.locator(".al-row").count() == 3)
    check("reduced-motion: 스위치 전환 애니메이션 없음", p2.evaluate("""(() => {
        const s = getComputedStyle(document.querySelector('.al-sw i'));
        return s.transitionProperty === 'none' || parseFloat(s.transitionDuration) === 0; })()"""))
    cr.close()
    check("페이지 오류 없음(전체)", not errs, str(errs[:1]))
    b.close()

print(f"\n{sum(res)}/{len(res)} passed")
sys.exit(0 if all(res) else 1)
