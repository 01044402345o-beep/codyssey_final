"""탈퇴 진행 창 E2E — 확인을 누른 뒤 서버를 기다리는 동안 멈춘 것처럼 보이지 않는가(사용자 신고 10/19).

`fetch` 와 `FirebaseAuth` 를 대체해 서버 응답을 일부러 늦춘다(실제 로그인·실제 삭제 없음).
보는 것: 스피너·경과 시간·단계가 실시간으로 바뀌는지, 진행 중에 닫히지 않는지(바깥 클릭·뒤로가기),
성공·실패·폴백·데모 경로가 각각 맞게 끝나는지.

    cd backend && uvicorn app.main:app --port 8768
    python ../e2e/test_withdraw_progress.py http://localhost:8768 [스크린샷 폴더]
"""
import os
import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1]
OUT = sys.argv[2] if len(sys.argv) > 2 else "."
results = []


def check(name, cond, extra=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""))


STUB = """(cfg) => {
  window.__calls = [];
  window.fetch = async (url, opt = {}) => {
    const path = String(url).replace(/^https?:\\/\\/[^/]+/, '');
    window.__calls.push((opt.method || 'GET') + ' ' + path);
    if (path === '/account/erase') {
      await new Promise(r => setTimeout(r, cfg.delay));
      return { ok: cfg.status === 200, status: cfg.status, json: async () => (cfg.status === 200 ? { erased: true, receipt: null } : { detail: cfg.detail }) };
    }
    if (path === '/user/state') { await new Promise(r => setTimeout(r, 400)); return { ok: true, status: 200, json: async () => ({ deleted: true }) }; }
    return { ok: true, status: 200, json: async () => ({}) };
  };
  const fa = window.FirebaseAuth;
  fa.enabled = true; fa.account = { uid: 'uidW', provider: 'google.com' };
  fa.idToken = async () => 'tok';
  fa.signOut = async () => { window.__calls.push('signOut'); fa.account = null; };
  fa.deleteAccount = async () => { await new Promise(r => setTimeout(r, 400)); window.__calls.push('deleteAccount'); fa.account = null; return { ok: true }; };
  S.user = { uid: 'uidW', provider: 'google.com', name: 'W', email: 'w@example.com' };
  ensure('plan'); go('u-home');
}"""

STATE = """() => {
  const m = document.querySelector('.modal.wd');
  if (!m) return { open: false, scr: S.screen };
  // label: 단계 이름만(아이콘·설명 제외), text: 설명까지 포함한 줄 전체
  const steps = [...m.querySelectorAll('.wd-steps li')].map(li => ({ cls: li.className,
    label: li.querySelector('.ic').nextElementSibling.firstChild.textContent.trim(),
    text: li.innerText.replace(/\\s+/g, ' ').trim() }));
  return { open: true, scr: S.screen, title: m.querySelector('h3').innerText, spin: m.querySelector('.wd-spin').className,
           time: m.querySelector('[data-live=wd-elapsed]').innerText, steps, close: !!m.querySelector('[data-act=wd-close]'),
           busy: m.getAttribute('aria-busy'), err: (m.querySelector('.wd-err') || {}).innerText || '' };
}"""


def start(page, status, delay, detail=""):
    page.evaluate(STUB, {"status": status, "delay": delay, "detail": detail})
    page.wait_for_timeout(200)
    page.click('[data-act="withdraw"]')
    page.wait_for_timeout(150)
    page.click('[data-act="modal-ok"]')       # 사용자가 확인을 누른다(실제 클릭)


with sync_playwright() as p:
    b = p.chromium.launch()
    errors = []
    page = b.new_page(viewport={"width": 390, "height": 844})
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE + "/?demo=1", wait_until="domcontentloaded")
    page.wait_for_timeout(700)

    # --- 성공(관리자 경로): 서버 응답 2.5초 ---
    start(page, 200, 2500)
    page.wait_for_timeout(250)
    s = page.evaluate(STATE)
    check("확인 직후 같은 자리에 진행 창이 뜬다(빈 대기 없음)", s["open"] and s["title"] == "탈퇴하는 중이에요" and s["busy"] == "true", str(s.get("title")))
    check("스피너가 돈다", s["open"] and "run" in s["spin"], s.get("spin"))
    labels = [x["label"] for x in s.get("steps", [])]
    check("단계 목록: 로그인 확인 → 증명 준비 → 서버 삭제 → 기기 정리 → 로그아웃",
          labels == ["로그인 정보 확인", "탈퇴 증명(챌린지) 준비", "서버에서 계정·기록 삭제", "이 기기의 기록 정리", "로그아웃"], str(labels))
    cls = [x["cls"] for x in s["steps"]]
    check("앞 두 단계는 완료, 지금은 '서버 삭제'(진행 중)", cls[:3] == ["done", "done", "now"] and cls[3:] == ["", ""], str(cls))
    check("서버 단계에 서버가 하는 일을 함께 보여 준다", "토큰 취소" in s["steps"][2]["text"], s["steps"][2]["text"])
    page.screenshot(path=os.path.join(OUT, "withdraw_progress_390.png"))
    t1 = s["time"]
    page.wait_for_timeout(1300)
    t2 = page.evaluate(STATE)["time"]
    check("경과 시간이 실시간으로 늘어난다", int(t2.rstrip("초")) > int(t1.rstrip("초")), f"{t1} -> {t2}")
    page.mouse.click(10, 10)                   # 바깥(어두운 배경)을 누른다
    page.wait_for_timeout(150)
    check("진행 중 바깥을 눌러도 닫히지 않는다", page.evaluate(STATE)["open"])
    page.evaluate("history.back()")
    page.wait_for_timeout(300)
    s = page.evaluate(STATE)
    check("진행 중 뒤로가기로도 닫히거나 화면이 바뀌지 않는다", s["open"] and s["scr"] == "u-home", str(s.get("scr")))
    page.wait_for_timeout(1400)                # 서버 응답 도착
    s = page.evaluate(STATE)
    check("끝나면 모든 단계가 완료, '탈퇴를 마쳤어요', 뒤에는 로그인 화면",
          s["open"] and s["title"] == "탈퇴를 마쳤어요" and all(x["cls"] == "done" for x in s["steps"]) and "done" in s["spin"] and s["scr"] == "u-login", str(s))
    page.wait_for_timeout(1400)
    s = page.evaluate(STATE)
    check("잠시 뒤 창이 닫히고 안내가 뜬다", not s["open"] and s["scr"] == "u-login" and "탈퇴했어요" in page.inner_text("#toast"), page.inner_text("#toast"))
    calls = page.evaluate("window.__calls")
    check("실제 처리 순서: 서버 삭제 → signOut", calls.index("POST /account/erase") < calls.index("signOut"), str(calls))

    # --- 실패(500): 멈춘 단계와 이유, 닫기 ---
    start(page, 500, 800, "admin_failed")
    page.wait_for_timeout(1200)
    s = page.evaluate(STATE)
    check("실패: '탈퇴를 멈췄어요' + 서버 단계에 실패 표시 + 이유 + 닫기",
          s["open"] and s["title"] == "탈퇴를 멈췄어요" and s["steps"][2]["cls"] == "fail" and "탈퇴를 완료하지 못했어요" in s["err"] and s["close"], str(s))
    page.screenshot(path=os.path.join(OUT, "withdraw_progress_fail_390.png"))
    page.click('[data-act="wd-close"]')
    page.wait_for_timeout(200)
    s = page.evaluate(STATE)
    check("닫기 → 창이 닫히고 홈·계정 그대로", not s["open"] and s["scr"] == "u-home" and page.evaluate("!!S.user"), str(s))

    # --- 폴백(503 admin_unavailable): 단계 이름이 실제 경로로 바뀐다 ---
    start(page, 503, 500, "admin_unavailable")
    page.wait_for_timeout(900)
    s = page.evaluate(STATE)
    labels = [x["label"] for x in s.get("steps", [])]
    check("폴백: '서버의 저장 기록 삭제'·'계정 삭제' 단계로 바뀐다", labels[2] == "서버의 저장 기록 삭제" and labels[4] == "계정 삭제", str(labels))
    page.wait_for_timeout(1400)
    check("폴백도 마치면 로그인 화면", page.evaluate(STATE)["scr"] == "u-login")
    page.wait_for_timeout(1400)

    # --- 데모(서버 없음): 한 단계로 바로 끝난다 ---
    page.evaluate("FirebaseAuth.enabled = false; S.user = { name: 'D' }; ensure('plan'); go('u-home')")
    page.wait_for_timeout(200)
    page.click('[data-act="withdraw"]'); page.wait_for_timeout(150); page.click('[data-act="modal-ok"]')
    page.wait_for_timeout(200)
    s = page.evaluate(STATE)
    check("데모 경로: '이 기기의 기록 정리' 한 단계로 마친다", s["open"] and [x["label"] for x in s["steps"]] == ["이 기기의 기록 정리"] and s["title"] == "탈퇴를 마쳤어요", str(s))
    page.wait_for_timeout(1400)

    # --- 넓은 화면·좁은 화면 배치 ---
    for w in (360, 1280):
        page.set_viewport_size({"width": w, "height": 800})
        start(page, 200, 1500)
        page.wait_for_timeout(300)
        over = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
        box = page.locator(".modal.wd").bounding_box()
        check(f"{w}px: 가로 넘침 없음, 창이 화면 안", over <= 0 and box and box["x"] >= 0 and box["x"] + box["width"] <= w, f"over={over} box={box}")
        page.screenshot(path=os.path.join(OUT, f"withdraw_progress_{w}.png"))
        page.wait_for_timeout(3000)

    check("페이지 JS 오류 없음", not errors, "; ".join(errors[:3]))
    b.close()

print(f"\n{sum(ok for _, ok in results)}/{len(results)} passed")
sys.exit(0 if all(ok for _, ok in results) else 1)
