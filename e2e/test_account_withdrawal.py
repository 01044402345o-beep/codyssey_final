"""탈퇴 E2E — 브라우저 기록 폐기 경로.

Firebase 계정 삭제(deleteUser)와 서버 기록 삭제(DELETE /user/state)는 실제 로그인이 필요해
여기서는 다루지 않는다(서버는 tests/test_user_state.py, 계정 삭제는 실제 로그인 환경에서 확인).
이 검사는 버튼 위치·확인 창·브라우저 기록 폐기·로그인 화면 복귀를 본다.

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

    check("자바스크립트 오류 없음", not errors, str(errors[:3]))
    b.close()

bad = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(bad)}/{len(results)} 통과")
if bad:
    print("실패: " + ", ".join(bad))
sys.exit(1 if bad else 0)
