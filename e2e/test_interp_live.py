"""실시간 통역 E2E — 마이크 → 서버 WebSocket → 자막 → 종료 (시험 모드 제공자).

실제 번역 품질은 키가 있어야 확인된다. 여기서는 파이프가 실제로 도는지만 본다:
마이크 PCM 이 서버로 올라가고, 서버가 보낸 자막이 화면에 붙고, 끝내면 마이크가 꺼진다.
시험 모드는 INTERP_ALLOW_FAKE=1 · INTERP_PROVIDER=fake 로 띄운 서버에서만 켜진다.

    INTERP_ALLOW_FAKE=1 INTERP_PROVIDER=fake uvicorn app.main:app --port 8770
    python e2e/test_interp_live.py http://localhost:8770
"""
import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1]
results = []


def check(name, cond, extra=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""))


with sync_playwright() as p:
    b = p.chromium.launch(args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"])
    ctx = b.new_context(viewport={"width": 390, "height": 844}, permissions=["microphone"])
    page = ctx.new_page(); errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE + "/?demo=1"); page.wait_for_timeout(800)
    page.evaluate("S.user = DEMO_USER; ensure('plan'); S.today = S.trip.tripStart; go('u-interp')"); page.wait_for_timeout(500)

    check("통역 화면에 '실시간 통역' 카드", page.locator('.live-card [data-act="live-start"]').count() == 1)
    check("시작 전에는 자막 칸이 없다", page.locator(".live-cols").count() == 0)

    page.locator('[data-act="live-start"]').click(); page.wait_for_timeout(300)
    modal = page.locator(".modal")
    check("처음 시작할 때 동의 창", modal.count() == 1 and "실시간 통역 전에" in modal.inner_text())
    check("동의 창에 제공자·저장 안 함·국외 이전 고지",
          all(k in modal.inner_text() for k in ["Soniox", "저장하지 않아요", "국외"]))
    page.locator('[data-act="modal-ok"]').click()
    for _ in range(20):                      # 연결은 첫 요청이 느릴 수 있다(최대 6초)
        page.wait_for_timeout(300)
        if page.evaluate("LIVE.status") == "live":
            break

    check("동의 뒤 연결되어 '듣는 중'", page.evaluate("LIVE.on && LIVE.status") == "live", page.evaluate("LIVE.status"))
    check("시험 모드 표시", page.locator(".live-badge.test").count() == 1)
    check("자막 두 칸이 보인다", page.locator(".live-cols .live-col").count() == 2)
    # 시험 제공자는 100 ms 프레임 12개(≈1초)마다 한 줄을 보낸다. CI 러너는 오디오 콜백이 느려 고정 대기 대신 최대 8초 기다린다.
    for _ in range(40):
        page.wait_for_timeout(200)
        if page.evaluate("LIVE.cap.source && LIVE.cap.target && (LIVE.sent || 0) > 16000"):
            break
    src = page.locator(".live-cols .live-col").nth(0).inner_text()
    tgt = page.locator(".live-cols .live-col").nth(1).inner_text()
    # 시험 제공자는 오디오 1초마다 두 문장을 번갈아 보낸다 — 어느 쪽이 떠 있어도 된다
    check("마이크 소리가 올라가 자막이 붙는다", any(k in src for k in ("기차역", "걸어서 5분")), src[:60])
    check("번역 자막이 상대 칸에 나온다", any(k in tgt for k in ("train station", "five minutes")), tgt[:60])
    check("마이크 트랙이 살아 있다", page.evaluate("!!(LIVE.stream && LIVE.stream.getAudioTracks()[0].readyState === 'live')"))
    check("브라우저가 보낸 오디오 샘플이 있다", page.evaluate("LIVE.sent || 0") > 16000, str(page.evaluate("LIVE.sent")))

    page.locator('[data-act="live-play"]').click(); page.wait_for_timeout(200)
    check("'번역 들려주기'가 번역문을 읽는다", page.evaluate("LIVE.cap.target.length") > 0)

    page.locator('[data-act="live-stop"]').click(); page.wait_for_timeout(400)
    check("끝내면 마이크·연결이 닫힌다", page.evaluate("!LIVE.on && !LIVE.ws && !LIVE.stream"))
    check("끝낸 뒤 시작 버튼으로 돌아온다", page.locator('[data-act="live-start"]').count() == 1)

    # 다른 화면으로 가면 통역도 멈춘다
    page.locator('[data-act="live-start"]').click(); page.wait_for_timeout(1200)
    page.evaluate("go('u-home')"); page.wait_for_timeout(400)
    check("화면을 옮기면 통역이 멈춘다", page.evaluate("!LIVE.on"))

    # 처리방침: 홈 'AI · 개인정보' 카드에 통역 동의 상태·받는 곳, 따로 철회
    card = page.locator(".card", has_text="실시간 통역 동의")
    check("개인정보 카드에 통역 동의 상태와 받는 곳(Soniox)", card.count() == 1 and "동의함" in card.inner_text() and "Soniox" in card.inner_text())
    card.locator('[data-act="interp-consent-withdraw"]').click(); page.wait_for_timeout(300)
    check("통역 동의 철회 → 동의 기록이 지워진다", page.evaluate("interpConsent()") is None and "동의하지 않음" in page.locator(".card", has_text="실시간 통역 동의").inner_text())
    page.evaluate("localStorage.setItem(INTERP_CONSENT_KEY, JSON.stringify({voice: true, at: Date.now()}))")
    check("동의 문구 버전이 다르면(옛 동의) 다시 묻는다", page.evaluate("interpConsent()") is None)
    check("페이지 오류 없음", not errors, str(errors)[:200])
    b.close()

failed = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
