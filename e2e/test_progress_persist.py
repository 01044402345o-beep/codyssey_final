"""새로고침해도 학습 진도가 남는지 E2E (사용자 피드백: "refresh 하면 학습 진도가 사라진다").

저장하는 것은 진도뿐이다 — 완료한 날짜와 보던 화면·카드 위치. 여기서는 그 약속만 확인한다.
통과가 '아무것도 안 실렸는데 초록불'이 되지 않도록, 완료 1일과 뒤집은 카드 N장을 먼저 실제
조작으로 만들어 놓고 새로고침한다.

    cd backend && uvicorn app.main:app --port 8769 &
    python ../e2e/test_progress_persist.py http://localhost:8769
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
    errors = []
    page = b.new_page(viewport={"width": 390, "height": 844})
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE + "/?demo=1")
    page.wait_for_timeout(700)

    check("저장소를 쓸 수 있다 (없으면 아래 검사는 아무것도 못 잡는다)", page.evaluate("STORE !== null"))

    page.locator("#demo-fab").click()
    page.wait_for_timeout(300)
    page.locator('.side [data-id="u-sched"]').click()
    page.wait_for_timeout(600)
    check("일정표 도달", page.evaluate("S.screen") == "u-sched")

    # 학습일은 기본 '오늘'(2026-09-22)보다 뒤다. 완료하려면 오늘을 그 날로 옮겨야 한다(데모 날짜 조정과 같은 경로).
    first = page.evaluate("S.sched.filter(r => r.kind !== 'free')[0].date")
    rowN = page.evaluate("S.sched.filter(r => r.kind !== 'free')[0].ids.length")
    page.evaluate(f"S.today = '{first}'")
    page.evaluate("go('u-study')")
    page.wait_for_timeout(500)
    check("학습 화면 도달", page.evaluate("S.screen") == "u-study", f"첫 학습일 {first} · 카드 {rowN}장")

    for _ in range(rowN):                      # 카드 전부 뒤집기 = 완료 조건
        page.locator(".flip").first.click()
        page.wait_for_timeout(120)
        if page.locator('.card-nav [data-act="card-next"]').first.is_enabled():
            page.locator('.card-nav [data-act="card-next"]').first.click()
            page.wait_for_timeout(120)
    flipped = page.evaluate("S.card.flipped.size")
    check("카드를 모두 뒤집었다", flipped == rowN, f"{flipped}/{rowN}")

    page.locator('[data-act="complete"]').first.click()      # 실제 완료 버튼 — 여기서 진도가 기록된다
    page.wait_for_timeout(400)
    done1 = page.evaluate("progress().done")
    i_before = page.evaluate("S.card.i")
    check("완료 버튼으로 1일이 기록됐다", done1 == 1, f"완료 {done1}일")

    page.reload()
    page.wait_for_timeout(900)
    check("새로고침 후 화면이 그대로", page.evaluate("S.screen") == "u-study",
          f"실제 {page.evaluate('S.screen')}")
    check("새로고침 후 완료 기록이 그대로", page.evaluate("progress().done") == done1,
          f"기대 {done1} 실제 {page.evaluate('progress().done')}")
    check("새로고침 후 보던 날짜가 그대로", page.evaluate("pickRow() && pickRow().date") == first,
          f"기대 {first} 실제 {page.evaluate('pickRow() && pickRow().date')}")
    check("새로고침 후 뒤집은 카드가 그대로", page.evaluate("S.card.flipped.size") == rowN,
          f"기대 {rowN} 실제 {page.evaluate('S.card.flipped.size')}")
    live = page.locator("[data-live=flipcount]").first.inner_text()
    check("화면에 뒤집은 카드가 그대로 보인다",
          live.startswith(f"{i_before + 1} / {rowN}") and f"뒤집은 카드 {rowN}" in live, live)

    # 데모 도우미 경로도 같은 저장을 거치는지 (지난 날 채우기)
    page.evaluate("S.today = S.sched.filter(r => r.kind !== 'free')[2].date")
    page.evaluate("ACT['demo-fill']()")
    page.wait_for_timeout(400)
    done2 = page.evaluate("progress().done")
    check("지난 날 채우기도 진도로 기록된다", done2 > done1, f"{done1} → {done2}일")
    page.reload()
    page.wait_for_timeout(900)
    check("그 진도도 새로고침 후 남는다", page.evaluate("progress().done") == done2,
          f"기대 {done2} 실제 {page.evaluate('progress().done')}")

    # 같은 날짜로 예시 여행을 다시 만들어도 이전 완료가 붙지 않는다
    page.evaluate("preset('zero')")
    page.wait_for_timeout(500)
    page.reload()
    page.wait_for_timeout(900)
    check("예시 여행은 이전 완료를 가져오지 않는다",
          page.evaluate("progress().done") == 0,
          f"완료 {page.evaluate('progress().done')}")

    # '처음 상태로' 는 저장분까지 지운다
    page.evaluate("ACT['reset']()")
    page.wait_for_timeout(400)
    page.reload()
    page.wait_for_timeout(900)
    check("'처음 상태로' 뒤에는 저장분이 남지 않는다",
          page.evaluate("progress().done") == 0 and page.evaluate("S.screen") == "u-login",
          f"완료 {page.evaluate('progress().done')} · 화면 {page.evaluate('S.screen')}")

    page.go_back()
    page.wait_for_timeout(600)
    here = page.evaluate("typeof S === 'undefined' ? 'left' : S.screen")
    check("초기화 뒤 뒤로가기가 이전 화면으로 되돌리지 않는다", here in ("left", "u-login"), f"화면 {here}")

    check("자바스크립트 오류 없음", not errors, str(errors[:2]))
    b.close()

bad = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(bad)}/{len(results)} 통과")
if bad:
    print("실패: " + ", ".join(bad))
sys.exit(1 if bad else 0)
