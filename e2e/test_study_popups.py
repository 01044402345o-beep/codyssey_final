"""학습 완료·미래 날짜 팝업 E2E (팀 요청 10/18~19).

- 미래 날짜를 열면 카드보다 먼저 확인 창(한재정 님 제안). '일정표로' / '미리 학습하기'.
- 모든 카드를 뒤집으면 버튼 없이 자동 완료 + 축하 창(학습 완료 / 미리 학습을 마쳤어요 / 상황별 연습).
- 미리 학습한 날은 그날이 오면 자동으로 완료로 옮겨진다(예전 안내 "미리 학습해 두면 그날 바로 완료돼요"는
  기록을 남기지 않아 지켜지지 않았다). 새로고침해도 미리 학습 기록이 남는다.

    cd backend && uvicorn app.main:app --port 8768
    python ../e2e/test_study_popups.py http://localhost:8768
"""
import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1]
results = []


def check(name, cond, extra=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""))


def modal(page):
    return page.evaluate("S.modal ? { title: S.modal.title, ok: S.modal.ok, cancel: S.modal.cancel } : null")


def flip_all(page):
    n = page.evaluate("pickRow().ids.length")
    for _ in range(n):
        if page.evaluate("S.modal") is not None:
            break
        page.locator(".flip").first.click(); page.wait_for_timeout(120)
        if page.evaluate("S.modal") is None and page.locator('.card-nav [data-act="card-next"]').first.is_enabled():
            page.locator('.card-nav [data-act="card-next"]').first.click(); page.wait_for_timeout(120)
    return n


with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 390, "height": 844})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE + "/?demo=1", wait_until="domcontentloaded")
    page.wait_for_timeout(700)
    page.evaluate("ensure('plan'); go('u-sched')")
    page.wait_for_timeout(300)
    rows = page.evaluate("S.sched.filter(r => r.kind !== 'free').map(r => r.date)")
    d1, d2 = rows[0], rows[1]
    page.evaluate(f"S.today = '{d1}'; render()")   # 오늘 = 첫 학습일 → 둘째 날은 미래

    # --- 미래 날짜: 카드보다 먼저 확인 창 ---
    page.evaluate(f"ACT['study-date']({{ dataset: {{ date: '{d2}' }} }})")
    page.wait_for_timeout(300)
    m = modal(page)
    check("미래 날짜를 열면 카드보다 먼저 확인 창", m and m["title"] == "아직 학습일이 아니에요" and page.locator(".flip").count() == 0, str(m))
    check("확인 창 버튼: 미리 학습하기 / 일정표로", m and m["ok"] == "미리 학습하기" and m["cancel"] == "일정표로", str(m))
    page.locator('[data-act="modal-cancel"]').click(); page.wait_for_timeout(300)
    check("'일정표로' → 일정표, 창 닫힘", page.evaluate("S.screen") == "u-sched" and modal(page) is None, page.evaluate("S.screen"))
    page.evaluate(f"ACT['study-date']({{ dataset: {{ date: '{d2}' }} }})"); page.wait_for_timeout(300)
    page.locator('[data-act="modal-ok"]').click(); page.wait_for_timeout(300)
    check("'미리 학습하기' → 카드가 열림", page.locator(".flip").count() == 1 and modal(page) is None)
    check("하단: 미리 학습 중 안내(완료 버튼 없음)", "미리 학습 중" in page.inner_text(".bottombar") and page.locator('[data-act="complete"]').count() == 0,
          page.inner_text(".bottombar"))

    # --- 미래 날짜를 다 뒤집기: 미리 학습 기록 + 축하 창, 완료율은 그대로 ---
    done0 = page.evaluate("progress().done")
    flip_all(page)
    m = modal(page)
    check("다 뒤집으면 '미리 학습을 마쳤어요' 창", m and m["title"] == "미리 학습을 마쳤어요", str(m))
    check("미리 학습 기록이 남고 완료율은 그대로", page.evaluate(f"!!PROG.pre['{d2}']") and page.evaluate("progress().done") == done0)
    page.locator('[data-act="modal-cancel"]').click(); page.wait_for_timeout(300)
    check("하단: '미리 학습 완료 · 그날 자동 완료'", "미리 학습 완료" in page.inner_text(".bottombar"), page.inner_text(".bottombar"))

    page.reload(); page.wait_for_timeout(1200)
    check("새로고침해도 미리 학습 기록이 남는다", page.evaluate(f"!!PROG.pre['{d2}']"))

    # --- 그날이 오면 자동으로 완료 ---
    page.evaluate(f"S.today = '{d2}'; render()"); page.wait_for_timeout(300)
    check("그날이 되면 미리 학습한 날이 자동으로 완료", page.evaluate(f"!!PROG.done['{d2}']") and not page.evaluate(f"!!PROG.pre['{d2}']")
          and page.evaluate(f"S.sched.find(r => r.date === '{d2}').completed"))

    # --- 오늘(첫 학습일) 다 뒤집기: 자동 완료 + 축하 창 ---
    page.evaluate(f"S.today = '{d1}'; ACT['study-date']({{ dataset: {{ date: '{d1}' }} }})"); page.wait_for_timeout(300)
    check("오늘 날짜는 확인 창 없이 바로 카드", modal(page) is None and page.locator(".flip").count() == 1)
    before = page.evaluate("progress().done")
    flip_all(page)
    m = modal(page)
    check("오늘 다 뒤집으면 '학습 완료! 🎉' 창(버튼 누를 필요 없음)", m and m["title"].startswith("학습 완료") and m["ok"] == "홈으로", str(m))
    check("완료가 바로 기록된다", page.evaluate("progress().done") == before + 1 and page.evaluate(f"!!PROG.done['{d1}']"))
    page.locator('[data-act="modal-ok"]').click(); page.wait_for_timeout(300)
    check("'홈으로' → 홈", page.evaluate("S.screen") == "u-home")

    # --- 상황별 연습: 다 뒤집으면 연습 축하 창(완료율 무관) ---
    page.evaluate("navFromMenu('u-coll')"); page.wait_for_timeout(300)
    page.locator('[data-act="drill"][data-v="airport"]').click(); page.wait_for_timeout(300)
    done_before = page.evaluate("progress().done")
    flip_all(page)
    m = modal(page)
    check("상황별 연습을 다 보면 '이 상황을 다 봤어요' 창", m and m["title"] == "이 상황을 다 봤어요", str(m))
    check("상황별 연습은 완료율을 바꾸지 않는다", page.evaluate("progress().done") == done_before)
    page.locator('[data-act="modal-ok"]').click(); page.wait_for_timeout(300)
    check("'다른 상황 고르기' → 문장 모음", page.evaluate("S.screen") == "u-coll" and page.evaluate("S.drill") is None)

    check("페이지 JS 오류 없음", not errors, "; ".join(errors[:3]))
    b.close()

print(f"\n{sum(ok for _, ok in results)}/{len(results)} passed")
sys.exit(0 if all(ok for _, ok in results) else 1)
