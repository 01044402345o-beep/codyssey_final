"""따라 읽기 E2E — '듣기'를 누르면 지금 읽는 영어 단어를 칠한다(NaturalReaders 처럼).

브라우저 음성을 가짜로 바꿔, 단어 경계(boundary) 이벤트를 테스트가 직접 보낸다.
- 경계 이벤트가 오면: 그 글자 위치의 단어를 칠한다. 대괄호 자리표시자([your name])는 빼고 읽으므로 위치를 당겨 센다.
- 경계 이벤트가 안 오면(Android 의 일부 음성): 글자 수로 시간을 어림해 단어를 따라간다.
- 다 읽으면 칠한 표시를 지운다.

    cd backend && uvicorn app.main:app --port 8768
    python ../e2e/test_read_along.py http://localhost:8768
"""
import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1]
results = []

# 가짜 음성: speak 하면 onstart 만 부르고, 끝내기·경계 이벤트는 테스트가 window.__u 로 직접 낸다.
SPEECH = """
(() => {
  window.__spoken = [];
  const synth = {
    speaking: false, pending: false, paused: false, onvoiceschanged: null,
    getVoices: () => [], cancel() {}, pause() {}, resume() {}, addEventListener() {},
    speak(u) { window.__u = u; window.__spoken.push(u.text); if (u.onstart) u.onstart(); },
  };
  Object.defineProperty(window, 'speechSynthesis', { value: synth, configurable: true });
  window.__boundary = (i) => window.__u.onboundary && window.__u.onboundary({ name: 'word', charIndex: i });
  window.__end = () => window.__u.onend && window.__u.onend();
})();
"""


def check(name, cond, extra=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""))


NOW = "[...document.querySelectorAll('.w.now')].map(w => w.textContent)"

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 390, "height": 844})
    ctx.add_init_script(SPEECH)
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE + "/?demo=1"); page.wait_for_timeout(800)
    page.evaluate("S.user = DEMO_USER; ensure('plan'); navFromMenu('u-coll')"); page.wait_for_timeout(300)
    page.locator('[data-act="drill"][data-v="airport"]').click(); page.wait_for_timeout(300)
    page.locator(".flip").first.click(); page.wait_for_timeout(700)

    en = page.locator(".face.back .en")
    words = en.locator(".w")
    check("카드 뒷면 영어가 단어 단위로 그려진다", words.count() >= 4 and en.inner_text().strip() == page.evaluate("slotText(curSent().en)"),
          f"{words.count()}개: {en.inner_text()}")

    # --- 경계 이벤트가 오는 브라우저 ---
    page.locator('.face.back [data-act="speak-card"]').click(); page.wait_for_timeout(100)
    spoken = page.evaluate("window.__spoken[window.__spoken.length - 1]")
    starts = page.evaluate("[...document.querySelectorAll('.face.back .en .w')].map(w => +w.dataset.c)")
    page.evaluate(f"window.__boundary({starts[0]})"); page.wait_for_timeout(50)
    first = page.evaluate(NOW)
    page.evaluate(f"window.__boundary({starts[2]})"); page.wait_for_timeout(50)
    third = page.evaluate(NOW)
    texts = page.evaluate("[...document.querySelectorAll('.face.back .en .w')].map(w => w.textContent)")
    check("경계 이벤트 위치의 단어를 칠한다(한 번에 한 단어)", first == [texts[0]] and third == [texts[2]], f"{first} → {third}")
    check("칠하는 위치가 실제로 읽는 문장과 맞는다", all(spoken[c:c + 1].strip() for c in starts), spoken)
    page.evaluate("window.__end()"); page.wait_for_timeout(50)
    check("다 읽으면 표시가 지워진다", page.evaluate(NOW) == [])

    # --- 경계 이벤트가 안 오는 브라우저: 어림으로 따라간다 ---
    page.locator('.face.back [data-act="speak-card"]').click()
    seen = []
    for _ in range(25):
        page.wait_for_timeout(120)
        cur = page.evaluate(NOW)
        if cur and (not seen or seen[-1] != cur[0]):
            seen.append(cur[0])
    check("경계 이벤트가 없어도 단어를 차례로 따라간다(어림)", len(seen) >= 3 and seen[0] == texts[0], str(seen))
    page.evaluate("window.__end()"); page.wait_for_timeout(50)

    # --- 자리표시자: [your name] 은 대괄호 없이 읽으므로 위치를 당겨 센다 ---
    pos = page.evaluate("""(() => { const d = document.createElement('div'); d.innerHTML = enHtml('I have a reservation under [name].');
      return [...d.querySelectorAll('.w')].map(w => [w.textContent, +w.dataset.c, w.classList.contains('ph')]); })()""")
    spoken2 = page.evaluate("ttsText(slotText('I have a reservation under [name].'))")
    ok = all(spoken2[c:c + len(t.replace('[', '').replace(']', ''))] == t.replace('[', '').replace(']', '') for t, c, _ in pos)
    check("자리표시자 문장도 단어 위치가 읽는 문장과 맞고, 자리표시자 단어는 강조 유지", ok and [t for t, _, ph in pos if ph] == ["[your", "name]."], str(pos))

    # --- 회화 연습 시트의 예상 답변도 따라 읽는다 ---
    page.locator('[data-act="sheet-open"]').click(); page.wait_for_timeout(300)
    page.locator('.sheet [data-act="say-line"][data-k="r0"]').click(); page.wait_for_timeout(100)
    rstarts = page.evaluate("[...document.querySelectorAll('.sheet .talk-line')][0].querySelectorAll('.w').length")
    page.evaluate("window.__boundary(0)"); page.wait_for_timeout(50)
    lit = page.evaluate("[...document.querySelectorAll('.sheet .talk-line .w.now')].length")
    other = page.evaluate("[...document.querySelectorAll('.face .w.now, .talk-me .w.now')].length")
    check("시트: 누른 답변 줄만 칠한다", rstarts >= 2 and lit == 1 and other == 0, f"lit={lit} other={other}")
    page.evaluate("window.__end()")

    check("페이지 JS 오류 없음", not errors, "; ".join(errors[:3]))
    b.close()

print(f"\n{sum(ok for _, ok in results)}/{len(results)} passed")
sys.exit(0 if all(ok for _, ok in results) else 1)
