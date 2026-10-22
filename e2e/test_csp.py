"""보안 헤더·CSP 가 실제 브라우저에서 앱을 깨지 않는지 E2E (ZAP 2026-10-16 스캔 대응).

서버가 CSP 를 강제(enforce, 기본)로 보낸 상태에서 주요 화면을 돌며 CSP 위반(securitypolicyviolation·콘솔)을 모은다.
위반이 0건이어야 하고, 인라인 스크립트였던 부팅 코드(boot.js)가 여전히 테마·화면 모드를 정해야 한다.
나머지 e2e 전체도 같은 서버(CSP 강제)에서 돈다 — 화면 기능이 막히면 그쪽에서도 깨진다.

구글 팝업 로그인 경로(Firebase SDK·gapi·authDomain iframe)는 실제 Firebase 설정이 있어야 해서 CI 에서는 건너뛴다.
로컬에서 확인: 서버를 FIREBASE_AUTH_DOMAIN 등과 함께 띄우고 CSP_FIREBASE=1 로 실행.

    cd backend && uvicorn app.main:app --port 8768
    python ../e2e/test_csp.py http://localhost:8768
"""
import os
import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8768"
results = []


def check(name, cond, extra=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))


COLLECT = """window.__csp = [];
document.addEventListener('securitypolicyviolation', e => window.__csp.push(e.violatedDirective + ' ← ' + (e.blockedURI || 'inline')));"""


def watch(page):
    console = []
    page.on("console", lambda m: console.append(m.text) if "Content Security Policy" in m.text else None)
    page.add_init_script(COLLECT)
    return console


def violations(page, console):
    v = page.evaluate("window.__csp || []")
    return [x for x in v + console if "chrome-extension" not in x]


with sync_playwright() as p:
    b = p.chromium.launch(args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"])
    ctx = b.new_context(viewport={"width": 390, "height": 844}, permissions=["microphone"])
    page = ctx.new_page()
    console = watch(page)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    resp = page.goto(BASE + "/?demo=1"); page.wait_for_timeout(900)
    h = resp.headers
    check("첫 화면에 CSP 강제 헤더", "content-security-policy" in h and "script-src 'self'" in h["content-security-policy"], str(h.get("content-security-policy"))[:80])
    check("클릭재킹 방지(X-Frame-Options DENY + frame-ancestors 'none')",
          h.get("x-frame-options") == "DENY" and "frame-ancestors 'none'" in h.get("content-security-policy", ""))
    check("nosniff·HSTS·Referrer-Policy", h.get("x-content-type-options") == "nosniff" and "max-age" in h.get("strict-transport-security", "")
          and h.get("referrer-policy") == "strict-origin-when-cross-origin")
    check("boot.js 가 화면 모드를 정했다(demo)", page.evaluate("document.documentElement.dataset.mode") == "demo")
    check("외부 폰트 CSS(SRI 포함)가 막히지 않았다", page.evaluate(
        "[...document.styleSheets].some(s => (s.href || '').includes('pretendard'))"))

    # 주요 화면 순회
    page.evaluate("S.user = DEMO_USER; ensure('plan'); S.today = S.trip.studyStart; go('u-home')"); page.wait_for_timeout(400)
    for scr in ("u-sched", "u-coll", "u-home"):
        page.evaluate(f"go('{scr}')"); page.wait_for_timeout(300)
    page.evaluate("ACT.tab({ dataset: { id: 'u-study' } })"); page.wait_for_timeout(300)
    page.evaluate("ACT['card-next']()"); page.wait_for_timeout(200)
    if page.locator(".flip").count():
        page.locator(".flip").first.click(); page.wait_for_timeout(200)
    page.evaluate("toast('확인')"); page.wait_for_timeout(200)
    # 녹음 다시 듣기 경로(blob: 미디어) — 가짜 마이크로 녹음 blob 을 만들어 재생해 본다
    blob_ok = page.evaluate("""async () => {
        const s = await navigator.mediaDevices.getUserMedia({ audio: true });
        const r = new MediaRecorder(s); const parts = [];
        r.ondataavailable = e => parts.push(e.data);
        const done = new Promise(res => r.onstop = res);
        r.start(); await new Promise(res => setTimeout(res, 400)); r.stop(); await done;
        s.getTracks().forEach(t => t.stop());
        const a = new Audio(URL.createObjectURL(new Blob(parts, { type: r.mimeType })));
        a.muted = true;
        try { await a.play(); return true; } catch (e) { return String(e); } }""")
    check("녹음 blob 재생이 CSP 에 막히지 않는다(media-src blob:)", blob_ok is True, str(blob_ok))
    check("주요 화면 순회: CSP 위반 0건", violations(page, console) == [], "; ".join(violations(page, console)[:4]))
    check("페이지 JS 오류 없음", not errors, "; ".join(errors[:3]))

    # 예전 데모 레이아웃 + 다크 테마: boot.js 가 data-mode=legacy, data-theme=dark 를 정한다
    p2 = ctx.new_page(); c2 = watch(p2)
    p2.add_init_script("try { localStorage.setItem('cd_theme', 'dark') } catch (e) {}")
    p2.goto(BASE + "/?demo=1&frame=1"); p2.wait_for_timeout(800)
    check("boot.js: legacy 모드 + 저장된 다크 테마", p2.evaluate("[document.documentElement.dataset.mode, document.documentElement.dataset.theme]") == ["legacy", "dark"],
          str(p2.evaluate("[document.documentElement.dataset.mode, document.documentElement.dataset.theme]")))
    check("boot.js: 주소창 색도 다크", p2.evaluate("document.getElementById('theme-color').content") == "#12151c")
    check("legacy·다크: CSP 위반 0건", violations(p2, c2) == [], "; ".join(violations(p2, c2)[:4]))

    # CSP 가 실제로 막는지(정책이 장식이 아님): 인라인 스크립트를 넣으면 실행되지 않는다
    blocked = p2.evaluate("""() => { window.__ran = false; const s = document.createElement('script');
        s.textContent = 'window.__ran = true'; document.head.appendChild(s); return window.__ran; }""")
    check("인라인 스크립트 주입은 실행되지 않는다", blocked is False, str(blocked))

    # 구글 팝업 로그인 경로 — 실제 Firebase 설정이 있을 때만(로컬 확인용)
    if os.getenv("CSP_FIREBASE") == "1":
        p3 = ctx.new_page(); c3 = watch(p3)
        p3.goto(BASE + "/"); p3.wait_for_timeout(2500)
        check("Firebase SDK(gstatic 동적 import)가 CSP 를 통과", p3.evaluate("typeof FirebaseAuth !== 'undefined' && FirebaseAuth.enabled === true"))
        try:
            with ctx.expect_page(timeout=8000) as pop:
                p3.evaluate("void FirebaseAuth.signInGoogle(() => {}).catch(() => {})")   # 팝업이 닫힐 때까지 기다리지 않는다
            pop.value.wait_for_timeout(2500)
            check("구글 로그인 팝업이 열린다", "accounts.google.com" in pop.value.url or "/__/auth/handler" in pop.value.url, pop.value.url[:60])
            pop.value.close()
        except Exception as exc:   # noqa: BLE001
            check("구글 로그인 팝업이 열린다", False, str(exc)[:120])
        p3.wait_for_timeout(1500)
        check("로그인 경로: CSP 위반 0건(gapi·authDomain iframe·identitytoolkit)", violations(p3, c3) == [], "; ".join(violations(p3, c3)[:4]))
    b.close()

print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
