"""다른 표현 E2E (Thesaurus 처럼) — 회화 연습 시트에 '같은 뜻, 다른 표현'.

공통 30문장마다 더 공손하게·짧게·다르게 말하는 검수된 문장 1~2개를 보여 주고, 각 줄의 '듣기'가 그 영어를 읽는다.
예상 답변이 없는 장소 문장에는 이 칸이 없다.

    cd backend && uvicorn app.main:app --port 8768
    python ../e2e/test_alt_expressions.py http://localhost:8768
"""
import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1]
results = []

SPEECH = """
(() => {
  window.__spoken = [];
  const synth = { speaking: false, pending: false, paused: false, onvoiceschanged: null, getVoices: () => [], cancel() {}, pause() {}, resume() {}, addEventListener() {},
    speak(u) { window.__u = u; window.__spoken.push(u.text); if (u.onstart) u.onstart(); } };
  Object.defineProperty(window, 'speechSynthesis', { value: synth, configurable: true });
})();
"""


def check(name, cond, extra=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""))


with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 390, "height": 844})
    ctx.add_init_script(SPEECH)
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE + "/?demo=1"); page.wait_for_timeout(800)
    page.evaluate("S.user = DEMO_USER; ensure('plan'); navFromMenu('u-coll')"); page.wait_for_timeout(300)

    for sit in ("airport", "hotel"):
        page.locator(f'[data-act="drill"][data-v="{sit}"]').click(); page.wait_for_timeout(300)
        page.locator('[data-act="sheet-open"]').click(); page.wait_for_timeout(300)
        alt = page.evaluate("curSent().alt")
        sheet = page.locator(".sheet").inner_text()
        lines = page.locator('.sheet [data-act="say-line"][data-k="a0"], .sheet [data-act="say-line"][data-k="a1"]')
        check(f"{sit}: 시트에 '같은 뜻, 다른 표현' + 데이터대로 {len(alt)}줄", "같은 뜻, 다른 표현" in sheet and lines.count() == len(alt)
              and all(a["en"].replace("[name]", "[your name]").replace("[destination]", "[your destination]") in sheet and a["label"] in sheet for a in alt), str([a["en"] for a in alt]))
        page.evaluate("window.__spoken = []")
        lines.first.click(); page.wait_for_timeout(100)
        check(f"{sit}: 다른 표현 '듣기'가 그 영어를 읽는다", page.evaluate("window.__spoken") == [page.evaluate("ttsText(slotText(curSent().alt[0].en))")], str(page.evaluate("window.__spoken")))
        page.evaluate("window.__u.onboundary({ name: 'word', charIndex: 0 })"); page.wait_for_timeout(50)
        lit = page.evaluate("[...document.querySelectorAll('.sheet .talk-line .w.now')].map(w => w.closest('.talk-line').querySelector('[data-k]').dataset.k)")
        check(f"{sit}: 따라 읽기는 누른 다른 표현 줄에서", lit == ["a0"], str(lit))
        page.evaluate("window.__u.onend && window.__u.onend()")
        page.locator('[data-act="sheet-close"]').click(); page.wait_for_timeout(200)
        page.evaluate("endDrill(); navFromMenu('u-coll')"); page.wait_for_timeout(250)

    # 장소 문장(예상 답변·다른 표현 없음)에는 칸이 없다
    day = page.evaluate("(S.sched.find(r => r.kind !== 'free' && r.ids.some(id => S.smap[id] && !S.smap[id].alt)) || {}).date || null")
    page.evaluate(f"ACT['study-date']({{ dataset: {{ date: '{day}' }} }})"); page.wait_for_timeout(300)
    page.evaluate("S.modal && S.modal.title === '아직 학습일이 아니에요' && ACT['modal-ok']()"); page.wait_for_timeout(300)
    page.evaluate("S.card.i = pickRow().ids.findIndex(id => !S.smap[id].alt); render()"); page.wait_for_timeout(200)
    page.locator('[data-act="sheet-open"]').click(); page.wait_for_timeout(300)
    check("다른 표현이 없는 문장에는 칸이 없다", day and "다른 표현" not in page.locator(".sheet").inner_text())

    check("페이지 JS 오류 없음", not errors, "; ".join(errors[:3]))
    b.close()

print(f"\n{sum(ok for _, ok in results)}/{len(results)} passed")
sys.exit(0 if all(ok for _, ok in results) else 1)
