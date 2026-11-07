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
    page.goto(BASE + "/?demo=1&gate=off", wait_until="domcontentloaded")
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
            if (path === '/account/erase') window.__challengeHeader = (opt.headers || {})['X-Withdraw-Challenge'] || '';
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

    re_case = case(403, "recent_login_required")   # 서버: 마지막 로그인이 RECENT_LOGIN_SECONDS 보다 오래됨(보안 점검 #1c)
    check("403 recent_login_required: 아무것도 지우지 않고 멈춘다(폴백으로 넘어가지 않음)",
          has(re_case["calls"], "POST /account/erase") and no_delete(re_case["calls"]) and "deleteAccount" not in re_case["calls"]
          and re_case["user"] is not None and re_case["local_trip"] is not None, str(re_case))
    check("멈춘 이유가 '다시 로그인 확인'으로 보인다",
          "다시 로그인 확인" in (page.evaluate("S.withdrawing && S.withdrawing.error") or ""), page.evaluate("S.withdrawing && S.withdrawing.error"))
    page.evaluate("ACT['wd-close'] && ACT['wd-close']()")

    # --- 탈퇴 버튼: 마지막 로그인이 오래됐으면 한 번 더 확인(구글 창·비밀번호) 뒤에 지운다(#1c) ---
    def recent(age, prov, reauth_ok=True, password=None):
        page.evaluate("""(cfg) => {
          window.__calls = [];
          window.fetch = async (url, opt = {}) => {
            const path = String(url).replace(/^https?:\\/\\/[^/]+/, '');
            window.__calls.push((opt.method || 'GET') + ' ' + path);
            if (path === '/account/erase') return { ok: true, status: 200, json: async () => ({ erased: true }) };
            return { ok: true, status: 200, json: async () => ({}) };
          };
          const fa = window.FirebaseAuth;
          fa.enabled = true; fa.account = { uid: 'uidR', provider: cfg.prov };
          fa.idToken = async () => 'tok';
          fa.loginAge = async () => cfg.age;
          fa.signInProvider = () => cfg.prov;
          fa.reauth = async (pw) => { window.__calls.push('reauth:' + (pw === undefined ? 'popup' : pw)); return cfg.ok ? { ok: true } : { ok: false, code: 'auth/popup-closed-by-user' }; };
          fa.signOut = async () => { window.__calls.push('signOut'); fa.account = null; };
          S.user = { uid: 'uidR', provider: cfg.prov, name: 'R', email: 'r@example.com' };
          ensure('plan'); go('u-home');
        }""", {"age": age, "prov": prov, "ok": reauth_ok})
        page.wait_for_timeout(150)
        page.evaluate("ACT.withdraw()"); page.wait_for_timeout(150)
        page.evaluate("ACT['modal-ok']()"); page.wait_for_timeout(300)          # '탈퇴하기'
        title = page.evaluate("S.modal ? S.modal.title : ''")
        if title:
            if password is not None:
                page.fill('[data-reauth="pw"]', password)
            page.evaluate("ACT['modal-ok']()"); page.wait_for_timeout(400)      # '확인하고 탈퇴'
        return {"title": title, "calls": page.evaluate("window.__calls"), "user": page.evaluate("S.user")}

    fresh = recent(30, "google.com")
    check("방금 로그인(30초): 다시 확인 없이 바로 지운다",
          fresh["title"] == "" and "reauth:popup" not in fresh["calls"] and has(fresh["calls"], "POST /account/erase"), str(fresh))
    stale = recent(3600, "google.com")
    check("오래된 로그인(1시간)·구글: 다시 확인 창 → 구글 창 → 그다음에 지운다",
          "구글" in stale["title"] and "reauth:popup" in stale["calls"]
          and 0 <= idx(stale["calls"], "reauth:popup") < idx(stale["calls"], "POST /account/erase"), str(stale))
    cancel = recent(3600, "google.com", reauth_ok=False)
    check("다시 확인을 닫으면 지우지 않는다", not has(cancel["calls"], "POST /account/erase") and cancel["user"] is not None, str(cancel))
    pw = recent(3600, "password", password="secret-pw")
    check("오래된 로그인·이메일: 비밀번호 입력 → 그 비밀번호로 다시 확인 → 지운다",
          "비밀번호" in pw["title"] and "reauth:secret-pw" in pw["calls"] and has(pw["calls"], "POST /account/erase"), str(pw))

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
    alive = page.evaluate("({ scr: S.screen, user: S.user, local_trip: localStorage.getItem('cd_trip:uidY'), calls: window.__calls })")
    check("계정이 살아 있으면(흔적만 남은 경우) 지우지 않고 서버에 보고한다: 화면·기록 유지",
          alive["scr"] == "u-home" and alive["user"] is not None and alive["local_trip"] is not None
          and has(alive["calls"], "POST /diagnostics/withdraw"), str(alive))

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

    # --- 탈퇴 증명 카드: 영수증이 있으면 '영수증 받음', 없으면 '상태 불명'을 사용자에게 보여준다 ---
    page.evaluate("""() => {
      S.user = null; S.screen = 'u-login'; render();
      localStorage.setItem('cd_withdraw_proof', JSON.stringify({ challenge: 'ab'.repeat(16), at: Date.now(),
        receipt: { challenge: 'ab'.repeat(16), outcome: 'ok', seq: 7, digest: 'd', created_at: Date.now(), schema: 'SEAL-RECEIPT-v1' } }));
      render();
    }""")
    page.wait_for_timeout(200)
    confirmed = page.evaluate("({ text: document.body.innerText, dl: !!document.querySelector('[data-act=\"proof-download\"]') })")
    check("탈퇴 증명(영수증 있음): '영수증 받음'과 내려받기 버튼을 보여준다",
          "영수증 받음" in confirmed["text"] and confirmed["dl"], str(confirmed["text"])[:200])

    page.evaluate("""() => {
      localStorage.setItem('cd_withdraw_proof', JSON.stringify({ challenge: 'cd'.repeat(16), at: Date.now(), receipt: null }));
      render();
    }""")
    page.wait_for_timeout(200)
    unknown = page.evaluate("({ text: document.body.innerText, rep: !!document.querySelector('[data-act=\"proof-report\"]') })")
    check("탈퇴 증명(영수증 없음): '상태 불명'을 보여주고 서버 보고 버튼을 제공한다",
          "상태 불명" in unknown["text"] and unknown["rep"], str(unknown["text"])[:200])

    # --- 탈퇴 요청: 서버에는 복구 키가 아니라 그 해시(커밋먼트)만 간다. 실제 브라우저의 SHA-256 으로 다시 계산해 본다 ---
    case(200, "", {"erased": True, "receipt": {"seq": 1, "outcome": "ok"}})
    sent_proof = page.evaluate("""async () => {
      const proof = withdrawProof();
      return { header: window.__challengeHeader, key: proof.recovery_key, challenge: proof.challenge,
               recomputed: await ProofCrypto.commitmentOf(proof.recovery_key) };
    }""")
    check("복구 키: 탈퇴 요청 헤더는 커밋먼트이고 복구 키가 아니다",
          sent_proof["header"] == sent_proof["challenge"] == sent_proof["recomputed"] and len(sent_proof["header"]) == 64
          and sent_proof["key"].startswith("wrk1-") and sent_proof["key"][5:] != sent_proof["header"], str(sent_proof["header"]))

    # --- 복구 키: 서버에는 커밋먼트만 가고, 키는 평문 파일에 넣지 않으며, 보낼 때는 봉인한다 ---
    made = page.evaluate("""async () => {
      const m = await ProofCrypto.newRecoveryKey();
      const raw = new Uint8Array(32); crypto.getRandomValues(raw);
      const pair = await crypto.subtle.generateKey({ name: 'X25519' }, true, ['deriveBits']);
      const rawPub = await crypto.subtle.exportKey('raw', pair.publicKey);
      window.__adminKey = 'x25519:' + ProofCrypto.b64e(rawPub);
      window.__realPin = ProofCrypto.ADMIN_KEY_FINGERPRINT;
      ProofCrypto.ADMIN_KEY_FINGERPRINT = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', rawPub)), b => b.toString(16).padStart(2, '0')).join('');
      window.__sent = [];
      window.fetch = async (url, init) => {
        const path = String(url);
        window.__sent.push({ path, body: (init && init.body) || '' });
        if (path.endsWith('/withdraw/recovery-key')) return { ok: true, status: 200, json: async () => ({ public_key: window.__adminKey }) };
        if (path.endsWith('/withdraw/recovery')) return { ok: true, status: window.__recoveryStatus || 200, json: async () => ({}) };
        return { ok: true, status: 200, json: async () => ({}) };
      };
      localStorage.setItem('cd_withdraw_proof', JSON.stringify({ challenge: m.commitment, recovery_key: m.key, at: Date.now(), receipt: null }));
      S.user = null; S.modal = null; S.screen = 'u-login'; render();
      const info = withdrawProofState();
      return { key: m.key, commitment: m.commitment, plain: JSON.stringify(proofPayload(info, false)), locked: JSON.stringify(proofPayload(info, true)) };
    }""")
    check("복구 키: 평문 내보내기에는 키가 없고 암호 파일 내용에만 있다",
          made["key"] not in made["plain"] and made["key"] in made["locked"], "")
    page.wait_for_timeout(150)
    page.click('[data-act="proof-send"]')
    page.wait_for_timeout(500)
    sent = page.evaluate("window.__sent")
    report_body = next((x["body"] for x in sent if x["path"].endswith("/withdraw/recovery")), "")
    check("복구 키: 로그아웃 상태에서도 실제 브라우저가 봉인해 보낸다(요청 어디에도 키 평문 없음)",
          made["commitment"] in report_body and made["key"] not in str(sent) and "관리자만 열 수 있게" in page.inner_text("#toast"), str(sent)[:200])
    page.evaluate("window.__recoveryStatus = 404; render()")
    page.wait_for_timeout(150)
    page.click('[data-act="proof-send"]')
    page.wait_for_timeout(500)
    check("복구 키: 서버 기록에 없으면 보냈다고 하지 않고 파일을 직접 보여 달라고 안내한다",
          "찾지 못했어요" in page.inner_text("#toast"), page.inner_text("#toast"))

    page.evaluate("window.__sent = []; window.__recoveryStatus = 200; ProofCrypto.ADMIN_KEY_FINGERPRINT = window.__realPin; render()")
    page.wait_for_timeout(150)
    page.click('[data-act="proof-send"]')
    page.wait_for_timeout(500)
    swapped = page.evaluate("window.__sent")
    check("복구 키: 서버가 고정 지문과 다른 공개키를 주면(침해 대비) 보내지 않고 파일을 안내한다",
          not any(x["path"].endswith("/withdraw/recovery") for x in swapped) and "예상과 달라" in page.inner_text("#toast"), str(swapped)[:200])

    # --- '서버에 보고'는 실제로 보낸 결과대로 안내한다(예전: 로그아웃이라 안 보내도 늘 '보고했어요') ---
    def report(logged_in, status=200):
        page.evaluate("""(cfg) => {
          window.__diag = 0;
          window.fetch = async (url) => {
            if (String(url).includes('/diagnostics/withdraw')) { window.__diag++; return { ok: cfg.status === 200, status: cfg.status, json: async () => ({}) }; }
            return { ok: true, status: 200, json: async () => ({}) };
          };
          const fa = window.FirebaseAuth; fa.idToken = async () => 'tok';
          wdEnd(); S.modal = null;                 // 앞 검사(탈퇴 실패)가 남긴 진행 창을 닫는다
          S.user = cfg.logged ? { uid: 'uidR', provider: 'google.com', name: 'R', email: 'r@example.com' } : null;
          localStorage.setItem('cd_withdraw_proof', JSON.stringify({ challenge: 'ef'.repeat(16), at: Date.now(), receipt: null }));
          S.screen = 'u-login'; render();
        }""", {"logged": logged_in, "status": status})
        page.wait_for_timeout(150)
        page.click('[data-act="proof-report"]')
        page.wait_for_timeout(400)
        return {"sent": page.evaluate("window.__diag"), "toast": page.inner_text("#toast")}

    r = report(False)
    check("로그아웃 상태 '서버에 보고': 보내지 않았으면 '보고했어요'라고 하지 않고 로그인·증명 파일을 안내",
          r["sent"] == 0 and "보고했어요" not in r["toast"] and "로그인한 뒤에 보고할 수 있어요" in r["toast"], str(r))
    r = report(True)
    check("로그인 상태 '서버에 보고': 실제로 보내고(/diagnostics/withdraw) '관리자에게 보고했어요'",
          r["sent"] == 1 and r["toast"] == "관리자에게 보고했어요.", str(r))
    r = report(True, 500)
    check("서버가 받지 못하면(500) '보고하지 못했어요'", r["sent"] == 1 and "보고하지 못했어요" in r["toast"], str(r))
    page.evaluate("() => { S.user = null; localStorage.removeItem('cd_withdraw_proof'); render(); }")

    check("자바스크립트 오류 없음", not errors, str(errors[:3]))
    b.close()

bad = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(bad)}/{len(results)} 통과")
if bad:
    print("실패: " + ", ".join(bad))
sys.exit(1 if bad else 0)
