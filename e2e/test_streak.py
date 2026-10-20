"""연속 학습·오늘의 목표 E2E (Duolingo 처럼).

- 카드를 처음 뒤집을 때마다 그날 활동 +1(같은 카드를 다시 뒤집으면 세지 않는다). 상황별 연습도 센다.
- 홈: 오늘 n/10장 원, '🔥 연속 N일', 최근 7일 점(오늘 표시). 오늘 아직이면 어제까지의 연속을 보여 준다.
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
    page.evaluate("S.user = DEMO_USER; ensure('plan'); go('u-home')"); page.wait_for_timeout(300)
    page.evaluate("window.__t = []; const o = toast; toast = m => { window.__t.push(m); o(m); }")
    today = page.evaluate("S.today")

    card = page.locator(".streak-card")
    check("홈에 오늘의 목표 카드: 0/10, 연속 0일, 7일 점(오늘 표시)",
          card.count() == 1 and page.inner_text(".goal-ring").replace("\n", "") == "0/10장" and "연속 0일" in card.inner_text()
          and page.locator(".week i").count() == 7 and page.locator(".week i.today").count() == 1, card.inner_text().replace("\n", " / "))

    drill_flip(page, "airport", 3)
    page.locator(".flip").first.click(); page.wait_for_timeout(80); page.locator(".flip").first.click(); page.wait_for_timeout(80)   # 같은 카드 다시
    check("카드를 처음 뒤집을 때만 +1(같은 카드 다시 뒤집기는 세지 않음)", page.evaluate("actToday()") == 3, str(page.evaluate("PROG.act")))

    page.evaluate("go('u-home')"); page.wait_for_timeout(250)
    check("홈: 3/10, 연속 1일, '7장만 더'", page.inner_text(".goal-ring").replace("\n", "") == "3/10장" and "연속 1일" in card.inner_text()
          and "7장만 더" in card.inner_text() and page.locator(".week i.today.on").count() == 1, card.inner_text().replace("\n", " / "))

    # 어제·그제 기록이 있으면 연속이 이어진다
    page.evaluate(f"PROG.act[Dt.add('{today}', -1)] = 4; PROG.act[Dt.add('{today}', -2)] = 11; PROG.act[Dt.add('{today}', -4)] = 2; render()")
    page.wait_for_timeout(200)
    check("오늘·어제·그제 → 연속 3일(나흘 전은 끊김 뒤라 세지 않음)", page.evaluate("streakDays()") == 3 and "연속 3일" in card.inner_text(), card.inner_text().replace("\n", " / "))
    check("최근 7일 점: 학습한 날 4개 칠함", page.locator(".week i.on").count() == 4)

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
    page.evaluate("go('u-home')"); page.wait_for_timeout(250)
    check("홈: 목표 원이 완료 표시, 달성 문구", page.locator(".goal-ring.done").count() == 1 and "달성" in card.inner_text())

    # 새로고침해도 남는다 + 오래된 기록 정리
    page.reload(); page.wait_for_timeout(1200)
    check("새로고침 뒤에도 오늘 활동·연속이 남는다", page.evaluate("actToday()") == 11 and page.evaluate("streakDays()") == 3, str(page.evaluate("PROG.act")))
    page.evaluate(f"PROG.act[Dt.add('{today}', -200)] = 5; bumpAct()")
    check("120일보다 오래된 기록은 지운다", page.evaluate(f"PROG.act[Dt.add('{today}', -200)]") is None)

    check("페이지 JS 오류 없음", not errors, "; ".join(errors[:3]))
    b.close()

print(f"\n{sum(ok for _, ok in results)}/{len(results)} passed")
sys.exit(0 if all(ok for _, ok in results) else 1)
