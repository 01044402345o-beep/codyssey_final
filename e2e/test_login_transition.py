"""로그인 전환 화면 E2E — 구글 창이 닫힌 뒤 로그인 화면에 멈춰 보이지 않는가(사용자 신고 10/19).

`FirebaseAuth`(구글 창·서버 확인)와 `fetch`(/user/state)를 대체해 각 단계에 시간을 준다.
보는 것: 창이 닫히는 순간 로그인 화면을 덮는 전환 화면이 뜨는지, 단계가 실제 순서대로 바뀌는지,
**다음 화면으로 넘어간 뒤에** 완료 안내가 뜨는지, 취소·실패·이메일 경로.

    cd backend && uvicorn app.main:app --port 8768
    python ../e2e/test_login_transition.py http://localhost:8768 [스크린샷 폴더]
"""
import os
import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1]
OUT = sys.argv[2] if len(sys.argv) > 2 else "."
results = []

# Firebase 설정이 있는 배포처럼 켠다(로그인한 계정은 없음) — test_guest_start 와 같은 방식
FB_ON = ("\nFirebaseAuth.start = function () { FirebaseAuth._started = true; FirebaseAuth.enabled = true;"
         " FirebaseAuth.account = null; FirebaseAuth.ready = Promise.resolve(null); return FirebaseAuth.ready; };\n")

STUB = """(cfg) => {
  const wait = ms => new Promise(r => setTimeout(r, ms));
  window.__toasts = [];
  const origToast = window.toast;
  window.toast = msg => { window.__toasts.push({ msg, screen: S.screen, covered: !!S.entering }); origToast(msg); };
  window.fetch = async (url, opt = {}) => {
    const path = String(url).replace(/^https?:\\/\\/[^/]+/, '');
    if (path === '/user/state' && (opt.method || 'GET') === 'GET') { await wait(cfg.pull); return { ok: true, status: 200, json: async () => ({}) }; }
    return { ok: true, status: 200, json: async () => ({}) };
  };
  const fa = window.FirebaseAuth;
  const account = { uid: 'uidL', provider: 'google.com', name: 'L', email: 'l@example.com' };
  fa.idToken = async () => 'tok';
  fa.signInGoogle = async (onPopupDone) => {
    await wait(cfg.popup);                                   // 구글 창
    if (cfg.cancel) { const e = new Error('closed'); e.code = 'auth/popup-closed-by-user'; throw e; }
    onPopupDone && onPopupDone();
    await wait(cfg.me);                                      // getIdToken + /auth/me
    if (cfg.meFail) { const e = new Error('me'); e.code = 'auth/me'; throw e; }
    fa.account = account; return account;
  };
  fa.signInEmail = async (email, password) => {
    await wait(cfg.me);
    if (cfg.badPassword) { const e = new Error('bad'); e.code = 'auth/invalid-credential'; throw e; }
    fa.account = { ...account, provider: 'password', email }; return fa.account;
  };
}"""

STATE = """() => {
  const w = document.querySelector('.modal-wrap.entering');
  if (!w) return { covered: false, scr: S.screen };
  const steps = [...w.querySelectorAll('.wd-steps li')].map(li => ({ cls: li.className, label: li.querySelector('.ic').nextElementSibling.textContent.trim() }));
  const bg = getComputedStyle(w).backgroundColor;
  const r = w.getBoundingClientRect();
  return { covered: true, scr: S.screen, title: w.querySelector('h3').innerText, steps, bg,
           full: r.left <= 0 && r.top <= 0 && r.right >= innerWidth && r.bottom >= innerHeight };
}"""


def check(name, cond, extra=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""))


def fresh(b, w=390):
    ctx = b.new_context(viewport={"width": w, "height": 844})
    def fb_on(route):                        # auth.js 를 한 번만 받아 덧붙인다(예전: 두 번 받아 바쁠 때 첫 로딩이 늦었다)
        resp = route.fetch()
        route.fulfill(response=resp, body=resp.text() + FB_ON)
    ctx.route("**/auth.js*", fb_on)
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE + "/")
    page.wait_for_function("() => typeof S !== 'undefined' && S.screen === 'u-login' && FirebaseAuth.enabled", timeout=30000)
    page.wait_for_timeout(300)
    return ctx, page


def stub(page, **cfg):
    page.evaluate(STUB, {"popup": 400, "me": 1200, "pull": 1200, **cfg})


with sync_playwright() as p:
    b = p.chromium.launch()
    errors = []

    # --- 구글: 창(0.4초) → 서버 확인(1.2초) → 기록 불러오기(1.2초) ---
    ctx, page = fresh(b)
    stub(page)
    page.click('[data-act="login"]')
    page.wait_for_timeout(200)
    check("구글 창이 열려 있는 동안은 덮지 않는다(창을 닫아 취소할 수 있게)", not page.evaluate(STATE)["covered"])
    page.wait_for_timeout(450)                    # 창이 닫히고 서버 확인 중
    s = page.evaluate(STATE)
    check("창이 닫히는 순간 로그인 화면을 덮는 전환 화면이 뜬다", s["covered"] and s["full"] and s["title"] == "로그인하는 중이에요", str(s))
    check("덮개는 불투명하다(로그인 폼이 비치지 않는다)", s["covered"] and "rgba" not in s["bg"] and s["bg"] != "transparent", s.get("bg"))
    check("단계: 구글 로그인 ✓ → 지금 '계정 확인'",
          [x["label"] for x in s["steps"]] == ["구글 로그인", "계정 확인", "저장된 기록 불러오기", "화면 준비"]
          and [x["cls"] for x in s["steps"]] == ["done", "now", "", ""], str(s["steps"]))
    page.screenshot(path=os.path.join(OUT, "login_transition_390.png"))
    page.evaluate("history.back()")
    page.wait_for_timeout(200)
    check("전환 중 뒤로가기로 덮개가 걷히지 않는다", page.evaluate(STATE)["covered"])
    page.wait_for_timeout(1200)                   # 서버 확인 끝 → 기록 불러오기 중
    s = page.evaluate(STATE)
    check("다음 단계: 지금 '저장된 기록 불러오기'", s["covered"] and [x["cls"] for x in s["steps"]][:3] == ["done", "done", "now"], str(s.get("steps")))
    page.wait_for_timeout(1500)                   # 끝
    s = page.evaluate(STATE)
    toasts = page.evaluate("window.__toasts")
    check("끝나면 덮개가 걷히고 다음 화면(여행 입력)", not s["covered"] and s["scr"] == "u-input", str(s))
    check("완료 안내는 다음 화면으로 넘어간 **뒤에**, 덮개가 걷힌 뒤 뜬다",
          toasts and toasts[-1]["msg"] == "구글 로그인을 완료했어요." and toasts[-1]["screen"] == "u-input" and not toasts[-1]["covered"], str(toasts))
    ctx.close()

    # --- 구글 창을 닫아 취소: 덮지 않고, 안내도 없다 ---
    ctx, page = fresh(b)
    stub(page, cancel=True)
    page.click('[data-act="login"]')
    page.wait_for_timeout(700)
    s = page.evaluate(STATE)
    check("구글 창 취소: 덮개 없이 로그인 화면 그대로, 안내 없음", not s["covered"] and s["scr"] == "u-login" and page.evaluate("window.__toasts.length") == 0, str(s))
    ctx.close()

    # --- 창은 닫혔는데 서버 확인 실패: 덮개를 걷고 로그인 화면에서 이유 ---
    ctx, page = fresh(b)
    stub(page, meFail=True, me=500)
    page.click('[data-act="login"]')
    page.wait_for_timeout(1200)
    s = page.evaluate(STATE)
    toasts = page.evaluate("window.__toasts")
    check("서버 확인 실패: 덮개가 걷히고 로그인 화면 + 이유 안내", not s["covered"] and s["scr"] == "u-login" and toasts and "로그인에 실패" in toasts[-1]["msg"], str(toasts))
    ctx.close()

    # --- 이메일: 누르자마자 덮는다 → 끝나면 이동 뒤 안내 ---
    ctx, page = fresh(b)
    stub(page)
    page.click('[data-act="auth-open"]'); page.click('[data-act="auth-pick"][data-v="login"]'); page.wait_for_timeout(150)   # 로그인 → 이미 계정이 있어요
    page.fill('[data-auth="email"]', "me@example.com"); page.fill('[data-auth="password"]', "secret12")
    page.click('[data-act="login-email"]')
    page.wait_for_timeout(200)
    s = page.evaluate(STATE)
    check("이메일: 누르자마자 덮고 '이메일·비밀번호 확인' 진행 중",
          s["covered"] and [x["label"] for x in s["steps"]] == ["이메일·비밀번호 확인", "저장된 기록 불러오기", "화면 준비"] and s["steps"][0]["cls"] == "now", str(s))
    page.wait_for_timeout(2800)
    s = page.evaluate(STATE); toasts = page.evaluate("window.__toasts")
    check("이메일: 다음 화면으로 넘어간 뒤 '로그인했어요.'",
          not s["covered"] and s["scr"] == "u-input" and toasts and toasts[-1]["msg"] == "로그인했어요." and toasts[-1]["screen"] == "u-input", str(toasts))
    ctx.close()

    # --- 비밀번호 틀림: 덮개를 걷고 폼 그대로(입력한 이메일 유지) ---
    ctx, page = fresh(b)
    stub(page, badPassword=True, me=400)
    page.click('[data-act="auth-open"]'); page.click('[data-act="auth-pick"][data-v="login"]'); page.wait_for_timeout(150)   # 로그인 → 이미 계정이 있어요
    page.fill('[data-auth="email"]', "me@example.com"); page.fill('[data-auth="password"]', "wrong")
    page.click('[data-act="login-email"]')
    page.wait_for_timeout(800)
    s = page.evaluate(STATE); toasts = page.evaluate("window.__toasts")
    check("비밀번호 틀림: 덮개가 걷히고 이유 안내, 입력한 이메일 그대로(이메일 화면에 남는다)",
          not s["covered"] and s["scr"] == "u-auth" and toasts and "비밀번호가 맞지 않아요" in toasts[-1]["msg"]
          and page.input_value('[data-auth="email"]') == "me@example.com", str(toasts))
    ctx.close()

    # --- 넓은 화면 ---
    ctx, page = fresh(b, 1280)
    stub(page)
    page.click('[data-act="login"]'); page.wait_for_timeout(700)
    s = page.evaluate(STATE)
    box = page.locator(".modal.en").bounding_box()
    check("1280px: 화면 전체를 덮고 카드는 가운데", s["covered"] and s["full"] and box and abs((box["x"] + box["width"] / 2) - 640) < 4, str(box))
    page.screenshot(path=os.path.join(OUT, "login_transition_1280.png"))
    page.wait_for_timeout(2800)
    ctx.close()

    check("페이지 JS 오류 없음", not errors, "; ".join(errors[:3]))
    b.close()

print(f"\n{sum(ok for _, ok in results)}/{len(results)} passed")
sys.exit(0 if all(ok for _, ok in results) else 1)
