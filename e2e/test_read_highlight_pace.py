#!/usr/bin/env python3
"""따라 읽기 속도 E2E — 경계 이벤트가 고유명사에서 끊겨도 멈추지 않는가.

iOS Safari(실기기 녹화 02:51 "Statue of Liberty", 02:53 "Brooklyn Bridge")는 단어 경계 이벤트를
고유명사 앞에서 끊는다. 예전 구현은 경계 이벤트가 올 때마다 '다음 이벤트까지 gap×2'를 기다렸으므로
그 지점에서 강조가 1초 넘게 멈췄고, 마지막 단어는 칠해지지도 못한 채 발화가 끝나 사라졌다.

  python3 test_read_highlight_pace.py http://127.0.0.1:8772
"""
import sys
from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8772"
passed = failed = 0


def check(name, ok, note=""):
    global passed, failed
    if ok:
        passed += 1; print("PASS " + name)
    else:
        failed += 1; print("FAIL " + name + (f"  [{note}]" if note else ""))


SPEECH = """
(() => {
  window.__spoken = [];
  const synth = { speaking: true, pending: false, paused: false, onvoiceschanged: null,
    getVoices: () => [], cancel() {}, pause() {}, resume() {}, addEventListener() {},
    speak(u) { window.__u = u; window.__spoken.push(u.text); if (u.onstart) u.onstart(); } };
  Object.defineProperty(window, 'speechSynthesis', { value: synth, configurable: true });
  window.__boundary = (i) => window.__u.onboundary({ name: 'word', charIndex: i });
  window.__end = () => window.__u.onend && window.__u.onend();
})();
"""
# 카드 뒷면의 '지금 칠해진 단어'를 배열로. 없으면 빈 배열.
NOW = "[...document.querySelectorAll('.face.back .en .w.now')].map(w => w.textContent)"

SENT = "How do I get to the Statue of Liberty?"

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True)
    ctx.add_init_script(SPEECH)
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(BASE + "/?demo=1"); pg.wait_for_timeout(820)
    pg.evaluate("S.user = DEMO_USER; ensure('plan'); navFromMenu('u-coll')"); pg.wait_for_timeout(320)
    pg.locator('[data-act="drill"][data-v="airport"]').click(); pg.wait_for_timeout(320)
    pg.locator(".flip").first.click(); pg.wait_for_timeout(650)

    # 카드 문장을 '고유명사가 든 긴 문장'으로 바꿔 끼운다(실기기와 같은 모양).
    pg.evaluate("""(t) => { const cur = curSent(); cur.en = t; render(); }""", SENT)
    pg.wait_for_timeout(320)
    pg.evaluate("() => { const f = document.querySelector('.flip'); if (f && !f.classList.contains('flipped')) f.click(); }")
    pg.wait_for_timeout(650)
    starts = pg.evaluate("[...document.querySelectorAll('.face.back .en .w')].map(w => +w.dataset.c)")
    texts = pg.evaluate("[...document.querySelectorAll('.face.back .en .w')].map(w => w.textContent)")
    check("긴 고유명사 문장이 단어 단위로 그려진다", len(texts) >= 8, str(texts))

    # ── 1. onstart 즉시 첫 단어를 칠하는가(예전: 350ms 지연) ──
    pg.locator('.face.back [data-act="speak-card"]').click()
    pg.wait_for_timeout(120)
    first = pg.evaluate(NOW)
    check("듣기를 누르면 곧바로 첫 단어가 칠해진다(350ms 공백 없음)", first == [texts[0]], str(first))

    # ── 2. iOS 처럼 'Statue' 에서 경계 이벤트가 끊긴다 ──
    stop_i = texts.index("Statue")
    for i in range(stop_i + 1):
        pg.evaluate(f"window.__boundary({starts[i]})"); pg.wait_for_timeout(30)
    at_stop = pg.evaluate(NOW)
    check("끊기기 직전 단어까지 경계 이벤트대로 칠한다", at_stop == [texts[stop_i]], str(at_stop))
    pg.wait_for_timeout(900)          # 예전 구현은 여기서 gap×2 를 기다리며 멈춰 있었다
    after = pg.evaluate(NOW)
    check("경계 이벤트가 끊긴 뒤 0.9초 안에 다음 단어로 넘어간다(멈춤 없음)",
          after != at_stop and after != [], f"{at_stop} → {after}")

    # ── 3. 마지막 단어까지 도달하는가 ──
    reached = []
    for _ in range(40):               # 최대 4.8초
        pg.wait_for_timeout(120)
        cur = pg.evaluate(NOW)
        if cur and (not reached or reached[-1] != cur[0]): reached.append(cur[0])
        if cur == [texts[-1]]: break
    check("마지막 단어까지 칠해진다", reached[-1:] == [texts[-1]], str(reached))
    check("칠이 뒤로 가지 않는다(단조 증가)",
          all(texts.index(a) <= texts.index(b) for a, b in zip(reached, reached[1:])), str(reached))
    check("발화가 끝나기 전에는 강조가 사라지지 않는다", pg.evaluate(NOW) != [])

    # ── 4. 다 읽으면 지운다 ──
    pg.evaluate("window.__end()"); pg.wait_for_timeout(90)
    check("다 읽으면 강조를 지운다", pg.evaluate(NOW) == [], str(pg.evaluate(NOW)))

    # ── 5. 실측 보정: 발화가 끝나면 글자당 시간이 실제 값 쪽으로 움직인다 ──
    before = pg.evaluate("TTS.perChar")
    # 보정은 '끝까지 읽은' 발화만 믿는다. 그래서 발화 길이를 현실적으로 흉내 낸다(짧게 끊으면 보정하지 않는 게 맞다).
    pg.evaluate("""async () => { speak('This is a measurement sentence.', null, null);
      await new Promise(r => setTimeout(r, 1600)); window.__end(); }""")
    pg.wait_for_timeout(300)
    after5 = pg.evaluate("TTS.perChar")
    check("끝까지 읽은 발화의 길이로 글자당 시간을 보정한다", after5 != before and 45 <= after5 <= 170, f"{before} → {after5}")
    # 중간에 끊긴 발화는 보정에 쓰지 않는다(쓰면 글자당 시간이 바닥까지 떨어져 이후 문장이 두 배로 빨라진다)
    pg.evaluate("""async () => { speak('This sentence will be cut off almost immediately by the caller.', null, null);
      await new Promise(r => setTimeout(r, 500)); window.__end(); }""")
    pg.wait_for_timeout(300)
    check("중간에 끊긴 발화로는 보정하지 않는다", pg.evaluate("TTS.perChar") == after5,
          f'{after5} → {pg.evaluate("TTS.perChar")}')

    check("JS 오류 없음", not errs, str(errs[:2]))
    b.close()

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
