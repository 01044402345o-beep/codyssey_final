"""로그인 없이 시작 E2E — Firebase 로그인이 켜진 배포에서도 가입 없이 앱을 쓸 수 있어야 한다.

a672c53 이후 첫 화면의 가짜 로그인 문이 진짜 Firebase 로그인이 되어, 가입하지 않으면 다른 화면에 들어갈 수 없었다.
실제 Firebase 는 부르지 않는다 — auth.js 의 start 를 '설정은 있고 로그인한 사람은 없음'으로 대체한다.

    cd backend && uvicorn app.main:app --port 8768
    python ../e2e/test_guest_start.py http://localhost:8768
"""
import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1]
results = []

# Firebase 설정이 있는 배포처럼 켠다. 로그인한 계정은 없다.
FB_ON = ("\nFirebaseAuth.start = function () { FirebaseAuth._started = true; FirebaseAuth.enabled = true;"
         " FirebaseAuth.account = null; FirebaseAuth.ready = Promise.resolve(null); return FirebaseAuth.ready; };\n")


def check(name, cond, extra=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""))


def fb_on(route):
    resp = route.fetch()
    route.fulfill(response=resp, body=resp.text() + FB_ON)


with sync_playwright() as p:
    b = p.chromium.launch()
    errors = []

    # --- Firebase 켜짐: 첫 화면에서 바로 손님으로 시작 ---
    ctx = b.new_context(viewport={"width": 390, "height": 844})
    ctx.route("**/auth.js*", fb_on)
    pushes = []
    ctx.on("request", lambda r: pushes.append(r.url) if "/user/state" in r.url else None)
    page = ctx.new_page(); page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE + "/"); page.wait_for_timeout(900)
    check("Firebase 켜짐: 첫 화면은 로그인 화면", page.evaluate("S.screen") == "u-login" and page.evaluate("FirebaseAuth.enabled"))
    g = page.locator('[data-act="guest"]')
    check("'로그인 없이 시작' 버튼이 보인다", g.count() == 1 and g.is_visible())
    gy, ey = g.bounding_box()["y"], page.locator('[data-auth="email"]').bounding_box()["y"]
    check("버튼이 이메일 입력보다 위(첫 화면 안)", gy < ey and gy + 48 < 844, f"guest y={gy:.0f}, email y={ey:.0f}")
    check("안내 문구: 로그인하지 않아도 쓸 수 있다", "로그인하지 않아도 쓸 수 있어요" in page.locator(".ticket").inner_text()
          and "들어갈 수 없어요" not in page.locator(".ticket").inner_text())

    g.click(); page.wait_for_timeout(400)
    st = page.evaluate("({ scr: S.screen, guest: !!(S.user && S.user.guest), uid: accountUid() })")
    check("누르면 여행 입력으로, 계정 없음(uid 빈 값)", st["scr"] == "u-input" and st["guest"] and st["uid"] == "", str(st))

    page.evaluate("ensure('plan'); go('u-study')"); page.wait_for_timeout(300)
    page.locator(".flip").first.click(); page.wait_for_timeout(150)
    page.evaluate("ACT['card-next']()"); page.wait_for_timeout(150)
    made = page.evaluate("({ i: S.card.i, n: S.card.flipped.size, guest: !!S.user.guest })")
    check("손님도 학습 카드를 쓴다(데모 사용자로 바뀌지 않음)", made["guest"] and made["i"] == 1 and made["n"] == 1, str(made))
    check("손님 기록은 이 브라우저 공용 칸에 저장", page.evaluate("!!localStorage.getItem('cd_session')"))

    page.reload(); page.wait_for_timeout(1200)
    back = page.evaluate("({ scr: S.screen, guest: !!(S.user && S.user.guest), i: S.card.i, n: S.card.flipped.size })")
    check("새로고침해도 로그인 화면으로 튕기지 않고 손님으로 이어서", back["scr"] == "u-study" and back["guest"], str(back))
    check("새로고침해도 카드 위치·뒤집은 카드 유지", back["i"] == 1 and back["n"] == 1, str(back))

    page.evaluate("navFromMenu('u-home')"); page.wait_for_timeout(300)
    acc = page.locator(".account-card").inner_text()
    check("홈 계정 카드: 손님 표시 + 로그인 버튼, 탈퇴 없음",
          "손님" in acc and page.locator('.account-card [data-id="u-login"]').count() == 1 and page.locator('[data-act="withdraw"]').count() == 0, acc.replace("\n", " / "))
    page.locator('.account-card [data-id="u-login"]').click(); page.wait_for_timeout(300)
    check("손님이 로그인 화면으로 가면 로그인 폼이 보인다(로그아웃 카드 아님)",
          page.locator('[data-auth="email"]').count() == 1 and page.locator('[data-act="logout"]').count() == 0)
    check("손님은 계정 서버(/user/state)에 아무것도 보내지 않는다", len(pushes) == 0, str(pushes[:3]))
    ctx.close()

    # --- Firebase 꺼짐(설정 없는 환경): 기존 데모 로그인 그대로 ---
    ctx = b.new_context(viewport={"width": 390, "height": 844})
    page = ctx.new_page(); page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE + "/"); page.wait_for_timeout(900)
    check("Firebase 꺼짐: 손님 버튼 없음, 기존 문구·Google 버튼 그대로",
          page.locator('[data-act="guest"]').count() == 0 and page.locator('[data-act="login"]').count() == 1
          and "들어갈 수 없어요" in page.locator(".ticket").inner_text())
    ctx.close()

    check("페이지 JS 오류 없음", not errors, "; ".join(errors[:3]))
    b.close()

print(f"\n{sum(ok for _, ok in results)}/{len(results)} passed")
sys.exit(0 if all(ok for _, ok in results) else 1)
