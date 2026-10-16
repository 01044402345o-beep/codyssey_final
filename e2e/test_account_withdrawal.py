"""탈퇴 E2E — 브라우저 기록 폐기 경로와 '탈퇴한 계정' 감지.

실제 로그인·실제 `deleteUser`·실제 서비스 계정 호출은 여기서 다루지 않는다 — `fetch` 와
`FirebaseAuth` 를 대체해 **호출 순서·계약(본문 erased/deleted)·분기**를 본다(서버 쪽은
tests/test_user_state.py·tests/test_firebase_admin.py 가 지킨다).
이 검사는 버튼 위치·확인 창·브라우저 기록 폐기·로그인 화면 복귀·403 계정 감지를 본다.

    cd backend && uvicorn app.main:app --port 8768
    python ../e2e/test_account_withdrawal.py http://localhost:8768
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
    page.goto(BASE + "/?demo=1", wait_until="domcontentloaded")
    page.wait_for_timeout(700)
    page.evaluate("ensure('plan'); go('u-home')")
    page.wait_for_timeout(300)

    # --- 버튼 위치: 계정 카드 '패딩 밖' 아래, 작고 연한 글씨 ---
    ui = page.evaluate("""() => {
      const w = document.querySelector('.withdraw');
      const acc = document.querySelector('.account-card');
      const cs = w ? getComputedStyle(w) : null;
      return {
        exists: !!w, act: w && w.dataset.act,
        inside_card: !!document.querySelector('.card.account-card .withdraw'),
        after_card: !!w && !!acc && (acc.compareDocumentPosition(w) & Node.DOCUMENT_POSITION_FOLLOWING) > 0,
        font: cs && parseFloat(cs.fontSize),
      };
    }""")
    check("탈퇴 버튼이 계정 카드 '패딩 밖' 아래에 있다", ui["exists"] and ui["act"] == "withdraw" and not ui["inside_card"] and ui["after_card"], str(ui))
    check("탈퇴 버튼은 작은(캡션) 글씨", ui["font"] is not None and ui["font"] <= 12, str(ui["font"]))

    # --- 취소하면 아무것도 지워지지 않는다 ---
    before = page.evaluate("({ trip: !!localStorage.getItem('cd_trip'), sess: !!localStorage.getItem('cd_session'), scr: S.screen })")
    page.click('[data-act="withdraw"]')
    page.wait_for_timeout(200)
    check("탈퇴는 확인 창을 띄운다", page.evaluate("!!S.modal") and "탈퇴" in page.locator(".modal").inner_text())
    page.click('[data-act="modal-cancel"]')
    page.wait_for_timeout(200)
    cancel = page.evaluate("({ trip: !!localStorage.getItem('cd_trip'), sess: !!localStorage.getItem('cd_session'), scr: S.screen })")
    check("취소하면 기록이 그대로", cancel["trip"] == before["trip"] and cancel["sess"] == before["sess"] and cancel["scr"] == before["scr"], f'{before} -> {cancel}')

    # --- 확정하면 브라우저 기록 폐기 + 로그인 화면 ---
    page.click('[data-act="withdraw"]')
    page.wait_for_timeout(200)
    page.click('[data-act="modal-ok"]')
    page.wait_for_timeout(700)
    after = page.evaluate("""() => {
      const sess = (() => { try { return JSON.parse(localStorage.getItem('cd_session') || 'null'); } catch (e) { return null; } })();
      return {
        scr: S.screen, user: S.user,
        trip: localStorage.getItem('cd_trip'), weak: localStorage.getItem('cd_weak'), consent: localStorage.getItem('cd_consent'),
        sess_done: sess ? Object.keys(sess.done || {}).length : -1, sess_screen: sess && sess.screen,
      };
    }""")
    check("여행 입력·복습·말하기 동의가 폐기된다", after["trip"] is None and after["weak"] is None and after["consent"] is None, str(after))
    check("진도 기록이 비워진다(로그인 화면만 남음)", after["sess_done"] == 0 and after["sess_screen"] == "u-login", str(after))
    check("로그인 화면으로 돌아가고 사용자 정보가 비워진다", after["scr"] == "u-login" and after["user"] is None, str(after))

    # --- 계정 칸(:uid)과, 로그인 전에 남은 공용 칸의 같은 기록을 함께 지운다 ---
    page.evaluate("""() => {
      ensure('plan');                       // 계획 준비(데모)
      S.user = { uid: 'uidX', provider: 'google.com', name: 'X', email: 'x@example.com' };
      const weak = [{ category_id: 'restaurant', id: 'order_menu', situation: 'x', en: 'Water', ko: '물' }];
      const trip = { country: '미국', cities: [{ name: '뉴욕', start: '2026-11-10', end: '2026-11-13' }], studyStart: '2026-10-01' };
      localStorage.setItem('cd_weak:uidX', JSON.stringify(weak));
      localStorage.setItem('cd_trip:uidX', JSON.stringify(trip));
      localStorage.setItem('cd_weak', JSON.stringify(weak));
      localStorage.setItem('cd_trip', JSON.stringify(trip));
      go('u-home');
    }""")
    page.wait_for_timeout(250)
    seeded = page.evaluate("({ sw: !!localStorage.getItem('cd_weak:uidX'), st: !!localStorage.getItem('cd_trip:uidX'), w: !!localStorage.getItem('cd_weak'), t: !!localStorage.getItem('cd_trip') })")
    check("계정 칸과 공용 칸에 같은 이름의 기록을 심었다", all(seeded.values()), str(seeded))
    page.click('[data-act="withdraw"]')
    page.wait_for_timeout(200)
    page.click('[data-act="modal-ok"]')
    page.wait_for_timeout(600)
    twin = page.evaluate("""() => ({
      scoped_weak: localStorage.getItem('cd_weak:uidX'), scoped_trip: localStorage.getItem('cd_trip:uidX'),
      shared_weak: localStorage.getItem('cd_weak'), shared_trip: localStorage.getItem('cd_trip'), scr: S.screen,
    })""")
    check("계정 칸(:uid)과 공용 칸의 같은 기록을 함께 지운다",
          twin["scoped_weak"] is None and twin["scoped_trip"] is None and twin["shared_weak"] is None and twin["shared_trip"] is None,
          str(twin))

    # --- 관리자 경로 / 폴백 분기 (fetch·FirebaseAuth 를 대체해 실제 로그인 없이 검증) ---
    def case(status, detail, body=None):
        page.evaluate("""(cfg) => {
          window.__calls = [];
          window.fetch = async (url, opt = {}) => {
            const path = String(url).replace(/^https?:\\/\\/[^/]+/, '');
            const auth = (opt.headers && (opt.headers.Authorization || opt.headers.authorization)) || '';
            window.__calls.push((opt.method || 'GET') + ' ' + path + ' ' + auth);
            if (path === '/account/erase') return { ok: cfg.status === 200, status: cfg.status, json: async () => (cfg.body || { detail: cfg.detail }) };
            if (path === '/user/state') return { ok: true, status: 200, json: async () => ({ deleted: true }) };
            return { ok: true, status: 200, json: async () => ({}) };
          };
          const fa = window.FirebaseAuth;
          fa.enabled = true;
          fa.account = { uid: 'uidZ', provider: 'google.com' };
          fa.idToken = async () => 'tok';
          fa.signOut = async () => { window.__calls.push('signOut'); fa.account = null; };
          fa.deleteAccount = async () => { window.__calls.push('deleteAccount'); fa.account = null; return { ok: true }; };
          S.user = { uid: 'uidZ', provider: 'google.com', name: 'Z', email: 'z@example.com' };
          ensure('plan'); go('u-home');
        }""", {"status": status, "detail": detail, "body": body})
        page.wait_for_timeout(150)
        page.evaluate("doWithdraw()")
        page.wait_for_timeout(300)
        return page.evaluate("({ calls: window.__calls, user: S.user, scr: S.screen, local_trip: localStorage.getItem('cd_trip:uidZ') })")

    def has(calls, prefix):
        return any(c.startswith(prefix) for c in calls)

    def idx(calls, prefix):
        return next((i for i, c in enumerate(calls) if c.startswith(prefix)), -1)

    def no_delete(calls):
        return not any(c.startswith("DELETE ") for c in calls)

    ok_case = case(200, "", {"erased": True})
    check("관리자 경로 성공: 토큰을 실어 보내고 규칙 삭제·deleteUser 없이 끝난다",
          has(ok_case["calls"], "POST /account/erase Bearer tok") and no_delete(ok_case["calls"])
          and "deleteAccount" not in ok_case["calls"] and "signOut" in ok_case["calls"], str(ok_case["calls"]))
    check("서버 탈퇴가 signOut 보다 먼저 일어난다",
          0 <= idx(ok_case["calls"], "POST /account/erase") < idx(ok_case["calls"], "signOut"), str(ok_case["calls"]))
    check("관리자 경로 성공 뒤 로그인 화면·로컬 폐기", ok_case["user"] is None and ok_case["scr"] == "u-login" and ok_case["local_trip"] is None, str(ok_case))

    nf_case = case(404, "not_found")   # 아직 이 경로가 없는(옛) 서버
    check("404(경로 없음): 폴백으로 되돌아간다",
          has(nf_case["calls"], "POST /account/erase") and has(nf_case["calls"], "DELETE /user/state") and "deleteAccount" in nf_case["calls"], str(nf_case["calls"]))
    check("404 폴백도 로그인 화면으로 끝난다", nf_case["user"] is None and nf_case["scr"] == "u-login", str(nf_case))

    fb_case = case(503, "admin_unavailable")
    check("키 없음(503 admin_unavailable): 규칙 삭제(토큰 포함) + deleteUser 로 되돌아간다",
          has(fb_case["calls"], "POST /account/erase") and has(fb_case["calls"], "DELETE /user/state Bearer tok") and "deleteAccount" in fb_case["calls"], str(fb_case["calls"]))
    check("폴백 경로도 로그인 화면으로 끝난다", fb_case["user"] is None and fb_case["scr"] == "u-login", str(fb_case))

    fail_case = case(500, "admin_failed")
    check("관리자 경로 실패(500): 계정을 지우지 않고 멈춘다",
          has(fail_case["calls"], "POST /account/erase") and no_delete(fail_case["calls"]) and "deleteAccount" not in fail_case["calls"], str(fail_case["calls"]))
    check("실패 시 화면·사용자·로컬 기록 유지", fail_case["user"] is not None and fail_case["scr"] == "u-home" and fail_case["local_trip"] is not None, str(fail_case))

    blank_case = case(200, "", {})    # 본문 계약(erased:true) 없는 200 — 프록시/CDN 오인 방지
    check("2xx 라도 본문 계약이 없으면 성공으로 보지 않는다",
          has(blank_case["calls"], "POST /account/erase") and no_delete(blank_case["calls"]) and blank_case["user"] is not None and blank_case["local_trip"] is not None,
          str(blank_case))

    # --- 다른 기기에서 탈퇴된 계정: 서버가 403 account_deleted 로 거부하면 이 기기도 정리한다 ---
    page.evaluate("""() => {
      window.__calls = [];
      window.fetch = async (url, opt = {}) => {
        window.__calls.push((opt.method || 'GET') + ' ' + String(url).replace(/^https?:\\/\\/[^/]+/, ''));
        return { ok: false, status: 403, json: async () => ({ detail: 'account_deleted' }) };
      };
      const fa = window.FirebaseAuth;
      fa.enabled = true; fa.account = { uid: 'uidZ', provider: 'google.com' };
      fa.idToken = async () => 'tok';
      fa.signOut = async () => { fa.account = null; };
      delete fa.stillAlive;                       // 확인 수단이 없으면 그대로 탈퇴로 본다
      S.user = { uid: 'uidZ', provider: 'google.com', name: 'Z', email: 'z@example.com' };
      ensure('plan'); go('u-home');
      accountClosed = false;
    }""")
    page.wait_for_timeout(150)
    page.evaluate("scheduleStatePush()")            # 실제 배선: 예약 업로드 → pushPayload → 감지
    page.wait_for_timeout(1200)
    gone = page.evaluate("({ scr: S.screen, user: S.user, local_trip: localStorage.getItem('cd_trip:uidZ'), calls: window.__calls })")
    check("다른 기기 탈퇴 감지(403 account_deleted): 예약 업로드 경로에서도 로컬 정리 후 로그인 화면",
          gone["scr"] == "u-login" and gone["user"] is None and gone["local_trip"] is None and has(gone["calls"], "PUT /user/state"),
          str(gone))

    # --- 흔적만 남고 계정이 살아 있는 드문 경우(관리자 경로가 도중 실패): 지우지 않고 알린다 ---
    page.evaluate("""() => {
      window.__calls = [];
      window.fetch = async (url, opt = {}) => {
        window.__calls.push((opt.method || 'GET') + ' ' + String(url).replace(/^https?:\\/\\/[^/]+/, ''));
        return { ok: false, status: 403, json: async () => ({ detail: 'account_deleted' }) };
      };
      const fa = window.FirebaseAuth;
      fa.enabled = true; fa.account = { uid: 'uidY', provider: 'google.com' };
      fa.idToken = async () => 'tok';
      fa.signOut = async () => { fa.account = null; };
      fa.stillAlive = async () => true;            // 계정은 살아 있다(강제 갱신이 성공)
      S.user = { uid: 'uidY', provider: 'google.com', name: 'Y', email: 'y@example.com' };
      ensure('plan'); go('u-home');
      accountClosed = false;
    }""")
    page.wait_for_timeout(150)
    page.evaluate("pushPayload('uidY', { session: null, weak: [], consent: null, trip: null })")
    page.wait_for_timeout(500)
    alive = page.evaluate("({ scr: S.screen, user: S.user, local_trip: localStorage.getItem('cd_trip:uidY') })")
    check("계정이 살아 있으면(흔적만 남은 경우) 지우지 않는다: 화면·기록 유지",
          alive["scr"] == "u-home" and alive["user"] is not None and alive["local_trip"] is not None, str(alive))

    # --- 늦게 도착한 403 이 다른 계정을 지우지 않는다(계정을 갈아 끼운 뒤 도착) ---
    page.evaluate("""() => {
      window.__calls = [];
      window.fetch = async () => ({ ok: false, status: 403, json: async () => ({ detail: 'account_deleted' }) });
      const fa = window.FirebaseAuth;
      fa.enabled = true; fa.account = { uid: 'uidB', provider: 'google.com' };
      fa.idToken = async () => 'tok';
      fa.signOut = async () => { fa.account = null; };
      delete fa.stillAlive;
      S.user = { uid: 'uidB', provider: 'google.com', name: 'B', email: 'b@example.com' };
      S.trip = null; resetDerived();              // 앞 사건의 여행을 들고 가지 않게(ensure 가 실제로 기록을 만들도록)
      ensure('plan'); go('u-home');
      accountClosed = false;
    }""")
    page.wait_for_timeout(150)
    page.evaluate("handleAccountDeleted('uidA', 0)")   # 지난 계정(uidA)에 대한 늦은 응답
    page.wait_for_timeout(300)
    other = page.evaluate("({ scr: S.screen, user: S.user, local_trip: localStorage.getItem('cd_trip:uidB') })")
    check("늦게 도착한 다른 계정의 탈퇴 응답은 무시한다",
          other["scr"] == "u-home" and other["user"] is not None and other["local_trip"] is not None, str(other))

    check("자바스크립트 오류 없음", not errors, str(errors[:3]))
    b.close()

bad = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(bad)}/{len(results)} 통과")
if bad:
    print("실패: " + ", ".join(bad))
sys.exit(1 if bad else 0)
