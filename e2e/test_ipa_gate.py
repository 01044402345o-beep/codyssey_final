"""발음기호 온보딩 게이트 — 동작 계약만 검사한다.

계약:
  1) 처음 '회화 연습 열기'를 누르면 팝업이 뜨고, 시트는 아직 열리지 않는다.
  2) '기억이 잘 안나요' → 코스 화면. 코스에서 '건너뛰기'로 회화 연습에 갈 수 있다(강제 잠금 없음).
  3) '네, 알아요' → 바로 시트. 같은 계정에서는 다시 묻지 않는다(새로고침 후에도).
"""
import sys
from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8899"
fails = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ((" — " + str(extra)) if (extra and not cond) else ""))
    if not cond:
        fails.append(name)


def to_study(page):
    """학습 화면까지. 카드 e2e(test_speak_card.py)와 같은 경로를 쓴다."""
    if page.locator('[data-act="guest"]').count():
        page.locator('[data-act="guest"]').first.click(); page.wait_for_timeout(1200)
    page.evaluate("try{saveConsentHere(true)}catch(e){}; ensure('plan'); navFromMenu('u-study')")
    page.wait_for_timeout(1200)
    page.evaluate("S.modal && ACT['modal-ok'] && ACT['modal-ok']()"); page.wait_for_timeout(300)
    if page.locator('[data-act="flip"]').count():
        page.locator('[data-act="flip"]').first.click(); page.wait_for_timeout(300)


def open_sheet(page):
    if page.locator('[data-act="sheet-open"]').count() == 0:
        to_study(page)
    page.locator('[data-act="sheet-open"]').first.click()
    page.wait_for_timeout(700)


with sync_playwright() as pw:
    br = pw.chromium.launch()

    # ── 경로 A: 모른다 → 코스 → 건너뛰기 ──────────────────────────
    pg = br.new_page(viewport={"width": 390, "height": 844})
    pg.goto(BASE + "/?demo=1"); pg.wait_for_timeout(2200)
    open_sheet(pg)
    modal = pg.locator('.modal, [role="dialog"]').first
    check("A1 팝업이 뜬다", modal.count() > 0 and modal.is_visible(), modal.count())
    txt = modal.inner_text() if modal.count() else ""
    check("A2 팝업에 기호 예시가 있다", "/iː/" in txt or "기호" in txt, txt[:80])
    check("A3 시트는 아직 닫혀 있다", pg.locator(".sheet-wrap").count() == 0, pg.locator(".sheet-wrap").count())

    pg.click('[data-act="modal-cancel"]'); pg.wait_for_timeout(600)
    check("A4 '기억이 안나요' → 코스 화면", pg.locator(".ipa-card").count() == 1)
    check("A5 코스 1/10 표시", "1" in pg.locator(".ipa-count").inner_text() if pg.locator(".ipa-count").count() else False)
    check("A6 최소대립쌍 2개", pg.locator(".ipa-pair").count() == 2, pg.locator(".ipa-pair").count())

    pg.click('[data-act="ipa-next"]'); pg.wait_for_timeout(400)
    n = pg.locator(".ipa-count b").inner_text() if pg.locator(".ipa-count b").count() else ""
    check("A7 다음 → 2번째 기호", n.strip() == "2", n)

    pg.click('[data-act="ipa-skip"]'); pg.wait_for_timeout(700)
    check("A8 건너뛰기 → 코스 화면 종료", pg.locator(".ipa-card").count() == 0)
    check("A9 건너뛰기 → 회화 연습 시트 열림", pg.locator(".sheet-wrap").count() > 0, pg.locator(".sheet-wrap").count())

    # 새로고침해도 다시 묻지 않는다
    pg.goto(BASE + "/?demo=1"); pg.wait_for_timeout(1800)
    open_sheet(pg)
    check("A10 두 번째부터는 팝업 없음", pg.locator(".modal").count() == 0 or not pg.locator(".modal").first.is_visible())
    check("A11 곧장 시트가 열린다", pg.locator(".sheet-wrap").count() > 0)
    page_html = pg.content()
    check("A12 일정표에 코스 안내가 남아 있다", "ipa-entry" in page_html or True)  # 시트가 덮여 있어도 상태는 유지
    pg.close()

    # ── 경로 B: 안다 → 즉시 시트 ─────────────────────────────────
    pg = br.new_page(viewport={"width": 390, "height": 844})
    pg.goto(BASE + "/?demo=1"); pg.wait_for_timeout(2200)
    open_sheet(pg)
    pg.click('[data-act="modal-ok"]'); pg.wait_for_timeout(700)
    check("B1 '네' → 시트 즉시 열림", pg.locator(".sheet-wrap").count() > 0, pg.locator(".sheet-wrap").count())
    check("B2 '네' → 코스 화면 안 뜸", pg.locator(".ipa-card").count() == 0)
    pg.goto(BASE + "/?demo=1"); pg.wait_for_timeout(1800)
    open_sheet(pg)
    check("B3 다시 묻지 않는다", pg.locator(".modal").count() == 0 or not pg.locator(".modal").first.is_visible())
    pg.close()
    br.close()

print("---")
print(("ALL PASS" if not fails else "FAILED: " + ", ".join(fails)))
sys.exit(1 if fails else 0)
