"""단순해진 로그인 첫 화면 E2E (10/20 피드백: "지금 로그인 화면이 너무 복잡하다").

- 첫 화면: '로그인' → Google로 계속하기 → 그 아래 작은 회색 '로그인 없이 시작'. 이메일 입력은 없다.
- '로그인'을 누르면 별도 화면(u-auth): '이미 계정이 있어요' / '아직 계정이 없어요' 두 갈래만.
  고른 쪽의 폼만 보이고, 뒤로가기는 폼 → 고르기 → 로그인 화면 순서로 돌아간다.
실제 Firebase 는 부르지 않는다(test_guest_start 와 같은 방식으로 '설정 있음, 로그인 안 함').

    cd backend && uvicorn app.main:app --port 8768
    python ../e2e/test_login_simple.py http://localhost:8768
"""
import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1]
results = []

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
    ctx = b.new_context(viewport={"width": 390, "height": 844})
    ctx.route("**/auth.js*", fb_on)
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE + "/"); page.wait_for_timeout(900)
    scr = lambda: page.evaluate("S.screen")

    # --- 첫 화면: 고르기만 ---
    t = page.locator(".ticket")
    btn = lambda act: page.locator(f'.ticket [data-act="{act}"]')
    check("첫 화면에 이메일·비밀번호 입력이 없다", page.locator("[data-auth]").count() == 0)
    check("버튼은 로그인·Google·로그인 없이 시작 세 개", btn("auth-open").count() == 1 and btn("login").count() == 1 and btn("guest").count() == 1
          and t.locator("button").count() == 3, str(t.locator("button").all_inner_texts()))
    y = {a: btn(a).bounding_box() for a in ("auth-open", "login", "guest")}
    check("순서: 로그인 → Google → 로그인 없이 시작", y["auth-open"]["y"] < y["login"]["y"] < y["guest"]["y"], str({k: round(v["y"]) for k, v in y.items()}))
    check("'로그인 없이 시작'은 작은 버튼(폭이 좁고 높이 44~48)", y["guest"]["width"] < y["login"]["width"] * 0.7 and 44 <= y["guest"]["height"] <= 48,
          f'{y["guest"]["width"]:.0f}x{y["guest"]["height"]:.0f} vs {y["login"]["width"]:.0f}')
    gc, lc = page.evaluate("""() => { const g = getComputedStyle(document.querySelector('[data-act="guest"]')), l = getComputedStyle(document.querySelector('[data-act="auth-open"]'));
      return [g.backgroundColor, l.backgroundColor]; }""")
    check("'로그인 없이 시작'은 회색(강조색·기본 버튼 색이 아님)", gc != lc and gc not in ("rgb(226, 85, 47)",), f"{gc} / {lc}")
    check("세 버튼이 첫 화면(844) 안에 보인다", y["guest"]["y"] + y["guest"]["height"] <= 844, f'{y["guest"]["y"] + y["guest"]["height"]:.0f}')

    # --- 로그인 → 이메일 화면: 두 갈래만 ---
    btn("auth-open").click(); page.wait_for_timeout(300)
    pick = page.locator('[data-act="auth-pick"]')
    check("'로그인' → 로그인 화면을 벗어나 새 화면", scr() == "u-auth" and page.locator(".login").count() == 0, scr())
    check("두 갈래만: '이미 계정이 있어요' / '아직 계정이 없어요', 입력 없음",
          pick.count() == 2 and "이미 계정이 있어요" in pick.nth(0).inner_text() and "아직 계정이 없어요" in pick.nth(1).inner_text()
          and page.locator("[data-auth]").count() == 0, str(pick.all_inner_texts()))

    pick.nth(0).click(); page.wait_for_timeout(250)
    check("'이미 계정이 있어요' → 이메일·비밀번호 폼(이름 없음)", page.locator('[data-auth="email"]').count() == 1 and page.locator('[data-auth="password"]').count() == 1
          and page.locator('[data-auth="name"]').count() == 0 and page.locator('[data-act="login-email"]').inner_text().strip() == "로그인")
    page.go_back(); page.wait_for_timeout(300)
    check("뒤로가기: 폼 → 두 갈래 고르기(같은 화면)", scr() == "u-auth" and page.locator('[data-act="auth-pick"]').count() == 2 and page.locator("[data-auth]").count() == 0, scr())

    page.locator('[data-act="auth-pick"][data-v="signup"]').click(); page.wait_for_timeout(250)
    check("'아직 계정이 없어요' → 이름까지 있는 가입 폼", page.locator('[data-auth="name"]').count() == 1 and page.locator('[data-act="login-email"]').inner_text().strip() == "가입하기")
    page.locator('[data-act="auth-pick"][data-v="login"]').click(); page.wait_for_timeout(250)
    check("폼 아래 '이미 계정이 있어요 · 로그인' → 바로 로그인 폼", page.locator('[data-auth="name"]').count() == 0
          and page.locator('[data-act="login-email"]').inner_text().strip() == "로그인")
    page.go_back(); page.wait_for_timeout(300)
    check("폼끼리 바꿔도 뒤로가기 한 번이면 두 갈래 고르기", page.locator('[data-act="auth-pick"]').count() == 2 and page.locator("[data-auth]").count() == 0)

    page.locator(".appbar .back").click(); page.wait_for_timeout(300)
    check("위쪽 뒤로 → 로그인 첫 화면", scr() == "u-login" and btn("auth-open").count() == 1, scr())

    # 새로고침하면 로그인 단계는 되살리지 않는다(손님으로 이메일 화면이 열리지 않게)
    btn("auth-open").click(); page.wait_for_timeout(300)
    page.reload(); page.wait_for_timeout(1200)
    check("이메일 화면에서 새로고침 → 로그인 첫 화면, 손님으로 바뀌지 않음", scr() == "u-login" and not page.evaluate("!!S.user"), f"{scr()} user={page.evaluate('S.user')}")

    check("페이지 JS 오류 없음", not errors, "; ".join(errors[:3]))
    ctx.close()

    # --- Firebase 꺼짐: 기존처럼 Google 버튼만(이메일 로그인은 쓸 수 없다) ---
    ctx = b.new_context(viewport={"width": 390, "height": 844})
    page = ctx.new_page(); page.goto(BASE + "/"); page.wait_for_timeout(900)
    check("Firebase 꺼짐: Google 버튼만, 로그인·손님 버튼 없음",
          page.locator('.ticket [data-act="login"]').count() == 1 and page.locator('[data-act="auth-open"]').count() == 0 and page.locator('[data-act="guest"]').count() == 0)
    ctx.close()
    b.close()

print(f"\n{sum(ok for _, ok in results)}/{len(results)} passed")
sys.exit(0 if all(ok for _, ok in results) else 1)
