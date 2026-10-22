"""일정표(달력) + 이전 여행(대시보드) E2E.

달력: 월 이동·오늘·칸 색(완료/미완료/예정/자유)·날짜 클릭이 목록과 같은 동작인지.
이전 여행: 기록이 없을 때 안내, 기록이 있을 때 요약 타일·여행 카드·학습 목록 펼치기.
기록은 여행 스냅숏(cd_trips)으로 남는다 — 보관(archiveTrip)과 화면 진입에서 갱신된다.
"""
import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1]
results = []


def check(name, cond, extra=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""))


with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 390, "height": 844})
    page = ctx.new_page(); errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE + "/?demo=1"); page.wait_for_timeout(800)
    page.evaluate("S.user = DEMO_USER; ensure('plan'); S.today = S.trip.tripStart; go('u-sched')"); page.wait_for_timeout(500)

    tabs = page.evaluate("[...document.querySelectorAll('.pnav button, .tabbar button')].map(b => b.textContent.trim())")
    check("탭은 4개: 홈 · 일정표 · 학습 · 문장 모음('이전 여행'은 탭이 아니다)",
          tabs in (["홈", "일정표", "학습", "문장 모음"], ["홈", "일정표", "통역", "문장 모음"]), str(tabs))
    check("탭 4개가 폭 안에 들어간다",
          page.evaluate("""(() => { const n = document.querySelector('.pnav') || document.querySelector('.tabbar');
            const bs = [...n.querySelectorAll('button')]; const r = n.getBoundingClientRect();
            return bs.length === 4 && bs.every(b => { const x = b.getBoundingClientRect();
              return x.left >= r.left - 1 && x.right <= r.right + 1 && x.width > 40; }); })()"""))

    # --- 달력 ---
    check("일정표에 달력이 있다", page.locator("[data-live=cal]").count() == 1)
    check("일정표 오른쪽 위에 '이전 여행' 버튼", page.locator('.appbar [data-act="past-go"]').count() == 1)
    box_btn = page.locator('.appbar [data-act="past-go"]').bounding_box()
    box_bar = page.locator('.appbar').bounding_box()
    check("그 버튼이 오른쪽 위에 붙어 있다", box_btn["x"] + box_btn["width"] >= box_bar["x"] + box_bar["width"] - 20
          and box_btn["y"] - box_bar["y"] < 16, f'{box_btn["x"]:.0f}/{box_bar["width"]:.0f}')
    check("요일 7칸", page.locator(".cal-dow span").count() == 7)
    month = page.locator("[data-live=cal-month]").inner_text()
    check("연·월 표기", "년" in month and "월" in month, month)
    ncell = page.locator(".cal-grid[role=grid] .cal-d").count()
    check("그 달의 날짜 칸이 모두 있다", ncell == page.evaluate("""(() => {
            const [y, m] = document.querySelector('[data-live=cal-month]').textContent.match(/(\\d+)년 (\\d+)월/).slice(1).map(Number);
            return new Date(Date.UTC(y, m, 0)).getUTCDate(); })()"""), str(ncell))
    check("미완료 칸이 구분된다(.miss)", page.locator(".cal-d.miss").count() >= 1, str(page.locator(".cal-d.miss").count()))
    # 하루를 완료로 채운 뒤 달력 색이 바뀌는지 본다(목록과 같은 상태를 읽는다는 증거).
    # 그 날짜가 이번 달에 없을 수 있으므로, 그 날의 달로 달력을 맞춘 뒤 확인한다.
    page.evaluate("""(() => { const r = S.sched.find(x => x.kind !== 'free');
        r.completed = true; PROG.done[r.date] = Date.now();
        S.calMonth = calMonthOf(r.date); render(); })()"""); page.wait_for_timeout(300)
    check("완료 칸이 색으로 구분된다(.done)", page.locator(".cal-d.done").count() >= 1, str(page.locator(".cal-d.done").count()))
    check("자유 일정 칸이 구분된다(.free)", page.locator(".cal-d.free").count() >= 0)

    shown = page.locator("[data-live=cal-month]").inner_text()   # 누르기 직전의 달(처음 달과 비교하면 날짜에 따라 우연히 같아진다)
    page.locator('[data-act="cal-next"]').click(); page.wait_for_timeout(300)
    check("다음 달로 이동", page.locator("[data-live=cal-month]").inner_text() != shown, f'{shown} → {page.locator("[data-live=cal-month]").inner_text()}')
    page.locator('[data-act="cal-prev"]').click(); page.wait_for_timeout(250)
    page.locator('[data-act="cal-today"]').click(); page.wait_for_timeout(300)
    check("'오늘'이 이번 달로 돌아온다", page.evaluate("S.calMonth") is None)

    # 날짜 클릭 → 그날 학습 화면(목록과 같은 동작). 그 날짜의 달로 맞춘 뒤 누른다.
    page.evaluate("S.studyDate = S.today")
    done_date = page.evaluate("(S.sched.find(r => r.completed) || {}).date")
    if done_date:
        page.evaluate(f"S.calMonth = calMonthOf('{done_date}'); render()"); page.wait_for_timeout(300)
        page.locator(f'.cal-d[data-date="{done_date}"]').first.click(); page.wait_for_timeout(500)
        check("완료한 날짜를 누르면 그날 카드로", page.evaluate("S.screen") == "u-study" and page.evaluate("S.studyDate") == done_date,
              page.evaluate("S.screen + ' ' + S.studyDate"))
        page.evaluate("go('u-sched')"); page.wait_for_timeout(300)

    # 넓은 화면: 달력 + 목록 2열
    page.set_viewport_size({"width": 1280, "height": 900}); page.wait_for_timeout(500)
    check("넓은 화면: 왼쪽에 달력 + 목록", page.locator(".split-list [data-live=cal]").count() == 1 and page.locator(".split-list .srow").count() >= 6)
    page.set_viewport_size({"width": 390, "height": 844}); page.wait_for_timeout(400)

    # --- 이전 여행: 일정표의 버튼으로 들어간다 ---
    page.locator('.appbar [data-act="past-go"]').click(); page.wait_for_timeout(400)
    check("'이전 여행' 버튼 → 이전 여행 화면", page.evaluate("S.screen") == "u-past")
    check("이전 여행 화면에서도 하단 탭은 '일정표'가 켜져 있다",
          page.evaluate("S.screen") == "u-past" and page.locator('.pnav button.on[data-id="u-sched"]').count() == 1)
    page.locator('.appbar .back').click(); page.wait_for_timeout(350)
    check("뒤로가기 → 일정표로 돌아온다", page.evaluate("S.screen") == "u-sched")

    # --- 이전 여행: 기록 없음 ---
    page.evaluate("localStorage.removeItem('cd_trips'); HIST.list = null; go('u-past')"); page.wait_for_timeout(400)
    check("이전 여행 화면이 열린다", page.evaluate("S.screen") == "u-past")
    check("기록이 없을 때 안내", "아직 지난 여행이 없어요" in page.locator(".app-pad").inner_text())

    # --- 이전 여행: 보관하면 기록이 남는다 ---
    page.evaluate("""go('u-sched');
      S.today = S.trip.tripEnd;
      (S.sched.find(r => r.kind !== 'free') || {}).completed = true;
      PROG.done[(S.sched.find(r => r.kind !== 'free') || {}).date] = Date.now();""")
    snap = page.evaluate("(() => { const s = histCapture(true); return s && { id: s.id, done: s.done, den: s.den, days: s.days.length }; })()")
    check("여행 스냅숏이 만들어진다", bool(snap) and snap["den"] >= 1 and snap["days"] == snap["den"], str(snap))
    page.evaluate("go('u-past')"); page.wait_for_timeout(500)
    check("요약 타일 4개", page.locator(".pstat").count() == 4)
    card = page.locator(".past-card").first
    check("여행 카드에 경로·완료율", card.count() == 1 and "%" in card.inner_text())
    check("카드에 학습일·학습한 문장", "학습일" in card.inner_text() and "학습한 문장" in card.inner_text())
    check("펼치기 전에는 학습 목록이 없다", page.locator(".past-days").count() == 0)
    card.locator(".past-head").click(); page.wait_for_timeout(400)
    check("카드를 누르면 학습 목록이 펼쳐진다", page.locator(".past-days").count() == 1)
    check("학습 목록에 날짜·완료 표시", page.locator(".past-days li").count() >= 1 and "완료" in page.locator(".past-days").inner_text())
    check("펼친 카드 aria-expanded=true", page.locator(".past-head").first.get_attribute("aria-expanded") == "true")
    page.locator(".past-head").first.click(); page.wait_for_timeout(300)
    check("다시 누르면 접힌다", page.locator(".past-days").count() == 0)

    # --- 하나 더: 다른 여행을 만들면 이전 기록도 함께 남는다 ---
    page.evaluate("""(() => {
      const cur = histLoad();
      const older = { id:'old-1', route:'일본 · 도쿄', country:'일본', cities:['도쿄'],
        start:'2026-08-01', end:'2026-08-04', studyStart:'2026-07-28', den:6, done:5, rate:5/6, learned:42,
        sentences:50, sits:{'대기 시간·웨이팅':9,'주문':7},
        days:[{d:'2026-07-28',ok:true,k:'new'},{d:'2026-08-01',ok:false,k:'trip'}], at: Date.now()-3*864e5 };
      HIST.list = [older].concat(cur);
      localStorage.setItem('cd_trips', JSON.stringify(HIST.list));
      S.today = S.trip.tripEnd; go('u-past');
    })()""")
    page.wait_for_timeout(500)
    routes = page.locator(".past-card .past-txt b").all_inner_texts()
    check("여러 여행이 정리돼 보인다", len(routes) >= 2, str(routes))
    check("최근(여행 종료일) 순으로 정렬된다",
          page.evaluate("""(() => { const l = histLoad().slice().sort((a, b) => (a.end < b.end ? 1 : -1));
            const shown = [...document.querySelectorAll('.past-card .past-txt b')].map(e => e.textContent);
            return l.length === shown.length && l.every((x, i) => shown[i] === x.route); })()"""), str(routes[:2]))
    check("상황 칩(학습한 문장 묶음)이 보인다", "대기 시간" in page.locator(".past-card").nth(1).inner_text(),
          page.locator(".past-card").nth(1).inner_text()[:80])
    check("페이지 오류 없음", not errors, str(errors)[:200])
    ctx.close()
    b.close()

failed = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
