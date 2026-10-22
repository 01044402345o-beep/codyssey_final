"""연속 학습·오늘의 목표 E2E (Duolingo 처럼).

- 카드를 처음 뒤집을 때마다 그날 활동 +1(같은 카드를 다시 뒤집으면 세지 않는다). 상황별 연습도 센다.
- '오늘의 알람' 카드(학습 탭 덱의 첫 장, 10/23): 큰 숫자 n/10장, '🔥 연속 N일', 최근 7일 막대(오늘 표시).
  오늘 아직이면 어제까지의 연속을 보여 준다.
- 10장이 되면 '오늘 목표 달성!'을 한 번만 알린다. 새로고침해도 남는다. 120일보다 오래된 기록은 지운다.

    cd backend && uvicorn app.main:app --port 8768
    python ../e2e/test_streak.py http://localhost:8768
"""
import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1]
results = []


def check(name, cond, extra=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""))


def drill_flip(page, sit, n):
    """상황별 연습 묶음을 열고 카드 n장을 처음으로 뒤집는다."""
    page.evaluate("navFromMenu('u-coll')"); page.wait_for_timeout(250)
    page.locator(f'[data-act="drill"][data-v="{sit}"]').click(); page.wait_for_timeout(250)
    for k in range(n):
        page.locator(".flip").first.click(); page.wait_for_timeout(80)
        if page.evaluate("S.modal") is not None:
            page.evaluate("ACT['modal-cancel']()"); page.wait_for_timeout(80)
        if k < n - 1:
            page.evaluate("ACT['card-next']()"); page.wait_for_timeout(80)


with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 390, "height": 844})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE + "/?demo=1"); page.wait_for_timeout(800)
    page.evaluate("S.user = DEMO_USER; ensure('plan'); S.today = S.trip.studyStart; ACT.tab({ dataset: { id: 'u-study' } })"); page.wait_for_timeout(300)   # 알람 카드는 학습 탭 덱의 첫 장(학습일이어야 덱이 열린다)
    page.evaluate("window.__t = []; const o = toast; toast = m => { window.__t.push(m); o(m); }")
    today = page.evaluate("S.today")

    card = page.locator('.alarm')
    goal = lambda: page.inner_text('.alarm-big').split('/')[0].strip()                    # noqa: E731 — 오늘 장 수
    streak = lambda: page.inner_text('.alarm-meta').split('연속')[1].split('일')[0].strip()  # noqa: E731 — 연속 일수
    check("학습 탭 '오늘의 알람' 카드: 0/10, 연속 0일, 7일 막대(오늘 표시)",
          card.count() == 1 and goal() == "0" and "/10장" in card.inner_text() and streak() == "0"
          and page.locator(".alarm-week i").count() == 7 and page.locator(".alarm-week i.today").count() == 1, card.inner_text().replace("\n", " / "))

    drill_flip(page, "airport", 3)
    page.locator(".flip").first.click(); page.wait_for_timeout(80); page.locator(".flip").first.click(); page.wait_for_timeout(80)   # 같은 카드 다시
    check("카드를 처음 뒤집을 때만 +1(같은 카드 다시 뒤집기는 세지 않음)", page.evaluate("actToday()") == 3, str(page.evaluate("PROG.act")))

    page.evaluate("ACT.tab({ dataset: { id: 'u-study' } })"); page.wait_for_timeout(250)
    check("알람 카드: 3/10, 연속 1일, '7장만 더'", goal() == "3" and streak() == "1"
          and "7장만 더" in card.inner_text() and page.locator(".alarm-week i.today.on").count() == 1, card.inner_text().replace("\n", " / "))

    # 어제·그제 기록이 있으면 연속이 이어진다
    page.evaluate(f"PROG.act[Dt.add('{today}', -1)] = 4; PROG.act[Dt.add('{today}', -2)] = 11; PROG.act[Dt.add('{today}', -4)] = 2; render()")
    page.wait_for_timeout(200)
    check("오늘·어제·그제 → 연속 3일(나흘 전은 끊김 뒤라 세지 않음)", page.evaluate("streakDays()") == 3 and streak() == "3", streak())
    check("최근 7일 막대: 학습한 날 4개 칠함", page.locator(".alarm-week i.on").count() == 4)

    # 오늘 아직이면 어제까지의 연속을 보여 준다
    saved = page.evaluate("actToday()")
    page.evaluate(f"delete PROG.act['{today}']; render()"); page.wait_for_timeout(150)
    check("오늘 아직: 어제까지 연속 2일 + '오늘 하면 이어져요'", page.evaluate("streakDays()") == 2 and "이어져요" in card.inner_text(), card.inner_text().replace("\n", " / "))
    page.evaluate(f"PROG.act['{today}'] = {saved}; render()")

    # 10장 → 목표 달성 알림 한 번
    drill_flip(page, "immigration", 5)
    drill_flip(page, "hotel", 3)
    n = page.evaluate("actToday()")
    hits = [m for m in page.evaluate("window.__t") if isinstance(m, str) and "오늘 목표 달성" in m]
    check("10장이 되는 순간 '오늘 목표 달성! 🔥 연속 3일' 을 한 번만", n == 11 and len(hits) == 1 and "연속 3일" in hits[0], f"n={n} {hits}")
    page.evaluate("ACT.tab({ dataset: { id: 'u-study' } })"); page.wait_for_timeout(250)
    check("알람 카드: 알람 카드가 채움 문구, 장 수 11", goal() == "11" and "채웠어요" in card.inner_text(), card.inner_text().replace("\n", " / "))

    # 새로고침해도 남는다 + 오래된 기록 정리
    page.reload(); page.wait_for_timeout(1200)
    page.evaluate("S.today = S.trip.studyStart")   # 새로고침하면 S.today 가 실제 날짜로 돌아온다 — 위에서 고정한 날짜로 다시
    check("새로고침 뒤에도 오늘 활동·연속이 남는다", page.evaluate("actToday()") == 11 and page.evaluate("streakDays()") == 3, str(page.evaluate("PROG.act")))
    page.evaluate(f"PROG.act[Dt.add('{today}', -200)] = 5; bumpAct()")
    check("120일보다 오래된 기록은 지운다", page.evaluate(f"PROG.act[Dt.add('{today}', -200)]") is None)

    check("페이지 JS 오류 없음", not errors, "; ".join(errors[:3]))
    b.close()

print(f"\n{sum(ok for _, ok in results)}/{len(results)} passed")
sys.exit(0 if all(ok for _, ok in results) else 1)
