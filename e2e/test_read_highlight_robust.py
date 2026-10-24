#!/usr/bin/env python3
"""따라 읽기 견고성 E2E — '다시 그려져도' 강조가 살아 있는가.

실기기(iPhone 14 Pro) 신고: 생성된 문장·관리 안 된 새 문장에서 강조가 끊기거나 한 단어에서 멈추거나 사라진다.
원인은 문장이 아니라 화면 교체다. 이 앱은 render() 로 #stage 를 통째로 갈아 끼우므로(생성 응답 도착,
음성 목록 로드, 진행 저장, 탭 이동), speak() 가 붙잡은 노드는 곧 detached 가 되고 타이머만 홀로 돈다.

  python3 test_read_highlight_robust.py http://127.0.0.1:8772
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
  const synth = { speaking: false, pending: false, paused: false, onvoiceschanged: null,
    getVoices: () => [], cancel() {}, pause() {}, resume() {}, addEventListener() {},
    speak(u) { window.__u = u; window.__spoken.push(u.text); if (u.onstart) u.onstart(); } };
  Object.defineProperty(window, 'speechSynthesis', { value: synth, configurable: true });
  window.__boundary = (i) => window.__u.onboundary && window.__u.onboundary({ name: 'word', charIndex: i });
  window.__end = () => window.__u.onend && window.__u.onend();
})();
"""
NOW = "[...document.querySelectorAll('.face.back .en .w.now')].map(w => w.textContent)"

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
    starts = pg.evaluate("[...document.querySelectorAll('.face.back .en .w')].map(w => +w.dataset.c)")
    texts = pg.evaluate("[...document.querySelectorAll('.face.back .en .w')].map(w => w.textContent)")

    # ── 1. 말하는 도중에 화면이 다시 그려져도 강조가 이어지는가 ──
    pg.locator('.face.back [data-act="speak-card"]').click(); pg.wait_for_timeout(120)
    pg.evaluate(f"window.__boundary({starts[0]})"); pg.wait_for_timeout(60)
    before = pg.evaluate(NOW)
    pg.evaluate("render()"); pg.wait_for_timeout(120)          # 생성 응답 도착·음성 목록 로드와 같은 경로
    after = pg.evaluate(NOW)
    check("다시 그려진 직후에도 강조가 살아 있다", before == [texts[0]] and after == [texts[0]],
          f"{before} → {after}")
    check("다시 그려져도 강조 대상이 새 DOM 노드다",
          pg.evaluate("[...document.querySelectorAll('.face.back .en .w.now')].every(w => w.isConnected)"))
    advanced = []
    for _ in range(14):
        pg.wait_for_timeout(120)
        cur = pg.evaluate(NOW)
        if cur and (not advanced or advanced[-1] != cur[0]): advanced.append(cur[0])
    check("다시 그려진 뒤에도 어림 시간표가 다음 단어로 계속 간다", len(advanced) >= 3, str(advanced))
    pg.evaluate("render()"); pg.wait_for_timeout(120)          # 한 번 더 갈아 끼워도
    # 시계가 이미 앞으로 갔을 수 있다. 경계 이벤트는 '앞으로'만 붙는 것이므로, 늦게 도착한
    # 뒤쪽 경계(단어 0)는 강조를 되감지 않아야 한다 — 되감으면 읽는 중에 칠이 튄다.
    rw = pg.evaluate(f"""() => {{ const q = '.face.back .en .w.now';
      const b = [...document.querySelectorAll(q)].map(w => w.textContent);
      window.__boundary({starts[0]});
      const a = [...document.querySelectorAll(q)].map(w => w.textContent);
      return {{ b, a }}; }}""")
    check("늦게 온 뒤쪽 경계 이벤트가 강조를 되감지 않는다", rw["b"] == rw["a"] and rw["b"] != [], str(rw))
    pg.evaluate("window.__end()"); pg.wait_for_timeout(80)

    # ── 2. 취소된 발화의 늦은 콜백이 새 문장을 망치지 않는가 ──
    pg.locator('.face.back [data-act="speak-card"]').click(); pg.wait_for_timeout(100)
    pg.evaluate("window.__u1 = window.__u")
    pg.locator('.face.back [data-act="speak-card"]').click(); pg.wait_for_timeout(100)
    pg.evaluate(f"window.__boundary({starts[0]})"); pg.wait_for_timeout(60)
    ok_before = pg.evaluate(NOW)
    pg.evaluate(f"window.__u1.onboundary({{ name: 'word', charIndex: {starts[3]} }})"); pg.wait_for_timeout(60)
    check("취소된 발화의 늦은 경계 이벤트를 무시한다", pg.evaluate(NOW) == ok_before, str(pg.evaluate(NOW)))
    pg.evaluate("window.__u1.onstart()"); pg.wait_for_timeout(80)   # 늦은 onstart 도 타이머를 훔치면 안 된다
    pg.evaluate(f"window.__boundary({starts[2]})"); pg.wait_for_timeout(60)
    check("늦은 onstart 가 새 문장의 강조를 가로채지 않는다", pg.evaluate(NOW) == [texts[2]],
          str(pg.evaluate(NOW)))
    pg.evaluate("window.__end()"); pg.wait_for_timeout(80)

    # ── 3. 문장이 화면에서 사라지면 강조도 남지 않는다 ──
    pg.locator('.face.back [data-act="speak-card"]').click(); pg.wait_for_timeout(100)
    pg.evaluate(f"window.__boundary({starts[1]})"); pg.wait_for_timeout(60)
    had = pg.evaluate(NOW)
    pg.evaluate("navFromMenu('u-home')"); pg.wait_for_timeout(500)
    left = pg.evaluate("document.querySelectorAll('.w.now').length")
    check("다른 화면으로 떠나면 강조가 남지 않는다", had != [] and left == 0, f"{had} / 남은 {left}개")
    pg.evaluate("window.__end()"); pg.wait_for_timeout(60)

    # ── 4. 생성형 문장(둥근 따옴표·줄표·긴 길이)에서 위치가 어긋나지 않는가 ──
    GEN = "Could I get a table for two, please? We\u2019d like the chef\u2019s special \u2014 if it\u2019s not too spicy."
    align = pg.evaluate("""(t) => { const d = document.createElement('div'); d.innerHTML = enHtml(t);
      const ws = [...d.querySelectorAll('.w')];
      const spoken = ttsText(slotText(t));
      return { n: ws.length, ok: ws.every(w => spoken.slice(+w.dataset.c).startsWith(w.textContent)) }; }""", GEN)
    check("생성형 문장도 단어 위치가 읽는 문장과 맞는다", align["ok"] and align["n"] >= 15, str(align))
    live = pg.evaluate("""(t) => { const d = document.createElement('div'); d.innerHTML = enHtml(t);
      document.body.appendChild(d); speak(t, null, d); return d.querySelectorAll('.w').length; }""", GEN)
    pg.evaluate("window.__boundary(84)"); pg.wait_for_timeout(60)
    check("생성형 문장의 마지막 단어까지 칠해진다",
          pg.evaluate("document.body.lastElementChild.querySelectorAll('.w.now').length") == 1,
          str(live))
    pg.evaluate("window.__end(); document.body.lastElementChild.remove()"); pg.wait_for_timeout(60)

    check("JS 오류 없음", not errs, str(errs[:2]))
    b.close()

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
