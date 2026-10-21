"""큰 화면에서 앱이 보이는지 — 화면을 통째로 덮는 불투명 고정 요소가 없어야 한다.

10/22 운영: 컴퓨터(폭 900px 이상)에서 앱이 전혀 안 보였다. 통역 전체화면의 빈 슬롯(.il-slot, fixed·z 290·
pointer-events:none)에 데스크톱용 캔버스 배경을 칠해, 통역을 안 할 때도 화면 전체를 덮었다(클릭은 통과해서
elementFromPoint 로는 안 보이는 덮개). 폭 390·768·900·1280·1920, 로그인·홈에서 확인하고,
통역을 켰을 때만 캔버스가 깔리고 끄면 사라지는지 본다.

    INTERP_ALLOW_FAKE=1 INTERP_PROVIDER=fake uvicorn app.main:app --port 8768
    python e2e/test_desktop_visible.py http://localhost:8768
"""
import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1]
results = []

COVERS = """() => [...document.querySelectorAll('body *')].filter(e => {
    const s = getComputedStyle(e); if (s.position !== 'fixed' || s.visibility === 'hidden' || s.display === 'none' || +s.opacity === 0) return false;
    const r = e.getBoundingClientRect();   // 화면 안에 실제로 걸친 넓이(밖으로 밀어 둔 서랍은 제외)
    const vis = Math.max(0, Math.min(r.right, innerWidth) - Math.max(r.left, 0)) * Math.max(0, Math.min(r.bottom, innerHeight) - Math.max(r.top, 0));
    if (vis < innerWidth * innerHeight * 0.6) return false;
    const bg = s.backgroundColor; return !(bg === 'transparent' || /rgba\\(.*,\\s*0\\)$/.test(bg));
  }).map(e => e.tagName.toLowerCase() + '.' + String(e.className).trim().split(/\\s+/).slice(0, 2).join('.'))"""


def check(name, cond, extra=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""))


with sync_playwright() as p:
    b = p.chromium.launch(args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"])
    for w, h in [(390, 844), (768, 1024), (900, 800), (1280, 800), (1920, 1080)]:
        ctx = b.new_context(viewport={"width": w, "height": h}, permissions=["microphone"])
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(BASE + "/"); page.wait_for_timeout(900)
        covers = page.evaluate(COVERS)
        check(f"{w}px 로그인 화면: 화면을 덮는 불투명 고정 요소 없음", covers == [], str(covers))
        check(f"{w}px 로그인 화면: 제목이 보인다", page.locator(".login h1, .login .title-lg").first.is_visible())
        page.goto(BASE + "/?demo=1"); page.wait_for_timeout(900)
        page.evaluate("S.user = DEMO_USER; ensure('plan'); S.today = S.trip.tripStart; go('u-interp')"); page.wait_for_timeout(500)
        covers = page.evaluate(COVERS)
        check(f"{w}px 통역 탭(통역 안 함): 덮는 요소 없음", covers == [], str(covers))
        if w >= 900:   # 데스크톱: 통역을 켜면 캔버스가 깔리고, 끄면 사라진다
            page.evaluate("localStorage.setItem(INTERP_CONSENT_KEY, JSON.stringify({voice: true, at: Date.now(), v: INTERP_CONSENT_VERSION}))")
            page.locator('[data-act="live-start"]').click()
            for _ in range(25):
                page.wait_for_timeout(200)
                if page.evaluate("LIVE.on && !!document.querySelector('.interp-live')"):
                    break
            bg_on = page.evaluate("getComputedStyle(document.querySelector('.il-slot')).backgroundColor")
            check(f"{w}px 통역 중: 뒤에 캔버스 배경", not bg_on.endswith(", 0)") and bg_on != "transparent", bg_on)
            page.locator('.il-acts [data-act="live-stop"]').click(); page.wait_for_timeout(400)
            covers = page.evaluate(COVERS)
            check(f"{w}px 통역 끝낸 뒤: 덮는 요소 없음", covers == [] and not page.evaluate("LIVE.on"), str(covers))
        check(f"{w}px 페이지 오류 없음", not errors, str(errors)[:200])
        ctx.close()
    b.close()

print(f"\n{sum(ok for _, ok in results)}/{len(results)} passed")
sys.exit(0 if all(ok for _, ok in results) else 1)
