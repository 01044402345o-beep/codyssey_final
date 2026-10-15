"""하단 뒤로가기 = 이전 화면 E2E.  mockup/app.js 의 화면 히스토리.

예전에는 pushState·popstate 가 없어서 뒤로가기가 앱을 닫았다(2차 사용자 피드백).
이 검사는 뒤로가기가 (1) 앱을 닫지 않고 (2) 이전 화면으로 가고
(3) 오버레이가 열려 있으면 그것만 먼저 닫고 (4) 깊이가 상한을 넘지 않는지 본다.

    cd backend && uvicorn app.main:app --port 8769 &
    python ../e2e/test_back_nav.py http://localhost:8769
"""
import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1]
OUT = sys.argv[2] if len(sys.argv) > 2 else "."   # CI 호환용(쓰지 않음)
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

    url0 = page.url.split("#")[0]
    scr = lambda: page.evaluate("typeof S === 'undefined' ? null : S.screen")

    # 일정표 → 학습 (서랍으로 한 번, 탭으로 한 번)
    page.locator("#demo-fab").click()
    page.wait_for_timeout(300)
    page.locator('.side [data-id="u-sched"]').click()
    page.wait_for_timeout(600)
    check("일정표 도달", scr() == "u-sched", str(scr()))

    page.locator('.pnav button[data-id="u-study"]').click()
    page.wait_for_timeout(700)
    check("학습 도달", scr() == "u-study", str(scr()))

    # ★ 본 검사: 뒤로가기가 앱을 닫지 않는다
    page.go_back()
    page.wait_for_timeout(700)
    check("뒤로가기 → 앱이 닫히지 않았다 (URL 그대로)",
          page.url.split("#")[0] == url0, page.url)
    check("뒤로가기 → 일정표(이전 화면)", scr() == "u-sched", str(scr()))

    # 오버레이: 뒤로가기가 그것만 먼저 닫는다
    page.evaluate("confirmBox('확인', '내용', '확인', () => {})")
    page.wait_for_timeout(300)
    check("확인 상자가 열렸다", page.evaluate("!!S.modal"))
    page.go_back()
    page.wait_for_timeout(600)
    check("뒤로가기 → 상자만 닫히고 화면은 그대로",
          page.evaluate("!S.modal") and scr() == "u-sched", f"modal={page.evaluate('!!S.modal')} screen={scr()}")

    # 깊이 상한: 화면을 여러 번 옮겨도 뒤로가기가 무한히 깊어지지 않는다.
    # 학습 화면에는 탭바(.pnav)가 없으므로 UI 클릭 대신 앱의 go() 를 직접 부른다(같은 경로).
    for _ in range(10):
        page.evaluate("go('u-study')")
        page.wait_for_timeout(90)
        page.evaluate("go('u-sched')")
        page.wait_for_timeout(90)
    depth = 0
    seen = set()
    for _ in range(12):
        before = scr()
        page.go_back()
        page.wait_for_timeout(350)
        after = scr()
        if after == before or page.url.split("#")[0] != url0:
            break
        depth += 1
        if after in seen:
            break
        seen.add(after)
    check("뒤로가기 깊이가 상한(6)을 넘지 않는다", depth <= 6, f"{depth}회")
    check("깊이 상한 안에서 앱이 닫히지 않았다", page.url.split("#")[0] == url0, page.url)
    check("JS 오류 없음", not errors, "; ".join(errors[:2]))
    b.close()

bad = [n for n, c in results if not c]
print(f"\n{len(results) - len(bad)}/{len(results)} 통과")
if bad:
    print("실패: " + ", ".join(bad))
    sys.exit(1)
