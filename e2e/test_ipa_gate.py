"""발음기호 1회 질문 — 동작 계약.

계약:
  1) 학습 화면에 들어오면 한 번 묻는다. 회화 연습 시트를 열 때는 묻지 않는다.
  2) '기억이 잘 안나요' → 코스 화면. 이후 다시 묻지 않는다(새로고침 후에도).
  3) '네, 알아요' → 이후 다시 묻지 않는다.
  4) 학습·상황별 연습 화면 우측 상단에 항상 [발음기호] 입구가 있다.
"""
import io
import json
import os
import re
import sys
from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8899"
SRC = io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "mockup", "app.js"), encoding="utf-8").read()   # CI 는 backend/ 에서 실행한다
fails = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ((" — " + str(extra)) if (extra and not cond) else ""))
    if not cond:
        fails.append(name)


def fresh_user(page):
    """이 창을 처음 온 사용자로 만든다. 서버는 게스트를 IP 로 기억하는데 테스트 창은 모두 127.0.0.1 이라,
    /ipa/gate 를 창마다 따로 기억하는 가짜로 바꾼다. 실제 서버 경로는 맨 끝 E 와 backend/tests/test_ipa_gate.py 가 본다."""
    store = {}

    def handle(route):
        req = route.request
        if req.method == "POST":
            store["v"] = (json.loads(req.post_data or "{}") or {}).get("value", "known")
            route.fulfill(json={"ok": True, "value": store["v"]})
        else:
            route.fulfill(json={"seen": "v" in store, "value": store.get("v")})
    page.route("**/ipa/gate*", handle)


def to_study(page):
    if page.locator('[data-act="guest"]').count():
        page.locator('[data-act="guest"]').first.click(); page.wait_for_timeout(1200)
    page.evaluate("try{saveConsentHere(true)}catch(e){}; ensure('plan'); navFromMenu('u-study')")
    page.wait_for_timeout(1300)
    # 화면이 먼저 띄우는 다른 창(안내)만 닫는다. 발음기호 질문은 그대로 두고 검사한다.
    page.evaluate("""() => { const m = S.modal; if (m && !/발음기호/.test(m.title || '')) ACT['modal-ok'](); }""")
    page.wait_for_timeout(1100)


def modal_visible(page):
    m = page.locator('.modal').first
    return m.count() > 0 and m.is_visible()


with sync_playwright() as pw:
    br = pw.chromium.launch()

    # ── A: 모른다 → 코스 → 이후 안 물음 ────────────────────────────
    pg = br.new_page(viewport={"width": 390, "height": 844}); fresh_user(pg)
    pg.goto(BASE + "/?demo=1"); pg.wait_for_timeout(2200)
    to_study(pg)
    pg.wait_for_timeout(900)
    check("A1 학습 진입 시 1회 질문", modal_visible(pg))
    txt = pg.locator('.modal').first.inner_text() if modal_visible(pg) else ""
    check("A2 문구가 '발음기호, 기억 나세요?'", "발음기호" in txt and "기억" in txt, txt[:60])
    check("A3 앱바 우측 상단에 발음기호 입구", pg.locator('.appbar .ipa-btn').count() == 1)

    pg.evaluate("() => ACT['modal-cancel']()"); pg.wait_for_timeout(1000)
    check("A4 '기억이 잘 안나요' → 코스 화면", pg.locator(".ipa-card").count() == 1)
    check("A5 코스 1/10", (pg.locator(".ipa-count b").inner_text().strip() == "1") if pg.locator(".ipa-count b").count() else False)
    check("A6 최소대립쌍 2개", pg.locator(".ipa-pair").count() == 2)

    pg.goto(BASE + "/?demo=1"); pg.wait_for_timeout(2000); to_study(pg); pg.wait_for_timeout(1200)
    check("A7 새로고침 후 다시 묻지 않는다", not modal_visible(pg))
    check("A8 학습 화면으로 돌아온다", pg.locator('.appbar .ipa-btn').count() == 1)

    # 시트를 열 때는 묻지 않는다
    if pg.locator('[data-act="flip"]').count():
        pg.locator('[data-act="flip"]').first.click(); pg.wait_for_timeout(400)
    pg.locator('[data-act="sheet-open"]').first.click(); pg.wait_for_timeout(700)
    check("A9 시트를 열 때는 묻지 않는다", not modal_visible(pg))
    check("A10 시트가 바로 열린다", pg.locator(".sheet-wrap").count() > 0)
    pg.close()

    # ── B: 안다 → 즉시 닫히고 이후 안 물음 ──────────────────────────
    pg = br.new_page(viewport={"width": 390, "height": 844}); fresh_user(pg)
    pg.goto(BASE + "/?demo=1"); pg.wait_for_timeout(2200)
    to_study(pg); pg.wait_for_timeout(900)
    check("B1 첫 진입에 질문", modal_visible(pg))
    pg.evaluate("() => ACT['modal-ok']()"); pg.wait_for_timeout(800)
    check("B2 '네' → 창이 닫힌다", not modal_visible(pg))
    check("B3 '네' → 코스 화면으로 가지 않는다", pg.locator(".ipa-card").count() == 0)
    pg.goto(BASE + "/?demo=1"); pg.wait_for_timeout(2000); to_study(pg); pg.wait_for_timeout(1200)
    check("B4 두 번째부터 묻지 않는다", not modal_visible(pg))
    pg.close()
    br.close()

# ── C: 소스 계약 — 두 화면 모두 앱바에 입구를 단다 ──────────────────
study_bar = re.search(r"appbar\('학습', \{ back: 'u-sched'(.*?)\}\)", SRC)
drill_bar = re.search(r"appbar\('상황별 연습', \{ back: 'u-coll'(.*?)\}\)", SRC)
check("C1 학습 앱바에 입구", bool(study_bar) and "ipaEntryBtn()" in study_bar.group(1), study_bar.group(1) if study_bar else "없음")
check("C2 상황별 연습 앱바에 입구", bool(drill_bar) and "ipaEntryBtn()" in drill_bar.group(1), drill_bar.group(1) if drill_bar else "없음")
check("C3 시트 진입에는 질문이 없다", "confirmBox('발음기호" not in SRC.split("'sheet-open':")[1].split("'ipa-open'")[0])


# ── D: 어떤 답을 하든 입구는 남는다 (좁은 화면·와이드 화면·질문 중) ──────
with sync_playwright() as pw:
    br = pw.chromium.launch()
    for w, label in ((390, "좁은"), (1280, "와이드")):
        for act, ans in (("modal-ok", "네"), ("modal-cancel", "기억이 잘 안나요")):
            pg = br.new_page(viewport={"width": w, "height": 900}); fresh_user(pg)
            pg.goto(BASE + "/?demo=1"); pg.wait_for_timeout(2200)
            to_study(pg); pg.wait_for_timeout(900)
            during = pg.locator('.appbar .ipa-btn').count()
            check(f"D {label}·{ans}: 질문이 떠 있는 동안에도 입구가 있다", during == 1, during)
            pg.evaluate(f"() => ACT['{act}']()"); pg.wait_for_timeout(900)
            if act == "modal-cancel":
                pg.evaluate("() => go('u-study')"); pg.wait_for_timeout(900)
            after = pg.locator('.appbar .ipa-btn').count()
            check(f"D {label}·{ans}: 답한 뒤에도 입구가 있다", after == 1, after)
            # 눌러서 실제로 코스가 열리는지
            if after == 1:
                pg.locator('.appbar .ipa-btn').first.click(); pg.wait_for_timeout(700)
                check(f"D {label}·{ans}: 눌러서 코스가 열린다", pg.locator(".ipa-card").count() == 1)
            pg.close()
    br.close()

check("C4 일정이 없을 때도 입구가 있다", "appbar('학습', { back: 'u-sched', act: ipaEntryBtn() }), tabbar: true, tab: 'u-study' });" in SRC)
check("C5 와이드 학습 앱바에도 입구", "tab === 'u-study' ? ipaEntryBtn() : pastEntryBtn()" in SRC)

# ── E: 실제 서버 — 한 브라우저에서 답하면 새 브라우저(같은 사용자)에서는 다시 묻지 않는다 ──────
# (게스트는 IP 기준. 이전 실행이 이미 답했으면 첫 창도 안 물을 수 있어, 두 번째 창만 검사한다)
with sync_playwright() as pw:
    br = pw.chromium.launch()
    pg = br.new_page(viewport={"width": 390, "height": 844})
    pg.goto(BASE + "/?demo=1"); pg.wait_for_timeout(2200)
    to_study(pg); pg.wait_for_timeout(900)
    if modal_visible(pg):
        pg.evaluate("() => ACT['modal-ok']()"); pg.wait_for_timeout(1200)
    r = pg.evaluate("async () => (await fetch('/ipa/gate', {cache: 'no-store'})).json()")
    check("E1 서버가 답을 기억한다(GET /ipa/gate)", r.get("seen") is True, r)
    pg.close()
    pg = br.new_context(viewport={"width": 390, "height": 844}).new_page()   # 저장소가 빈 새 브라우저
    pg.goto(BASE + "/?demo=1"); pg.wait_for_timeout(2200)
    to_study(pg); pg.wait_for_timeout(1200)
    check("E2 새 브라우저에서도 다시 묻지 않는다", not modal_visible(pg))
    br.close()

print("---")
print("ALL PASS" if not fails else "FAILED: " + ", ".join(fails))
sys.exit(1 if fails else 0)
