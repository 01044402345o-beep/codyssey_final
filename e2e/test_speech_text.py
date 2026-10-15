"""듣기(음성)와 화면 문장의 동일성 E2E.  docs/REPO_STATE.md 불변식.

화면: How do I get to [your destination]?
음성: How do I get to your destination?
→ spoken == shown 에서 대괄호만 뺀 값. 어긋나면 여기서 터진다.

    cd backend && uvicorn app.main:app --port 8769 &
    python ../e2e/test_speech_text.py http://localhost:8769
"""
import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1]
results = []


def check(name, cond, extra=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""))


# ttsState() 가 'ok' 여야 speak() 가 음성을 만든다. 목소리가 없으면 조용히 반환하므로
# 스텁으로 영어 음성 하나를 반드시 넣는다 — 안 그러면 이 테스트가 아무것도 검증하지 못한다.
# speechSynthesis 는 읽기 전용이다. 가짜 voice 객체를 넣으면 utterance.voice 대입이 예외가 되어
# speak() 가 재생 전에 죽는다. 빈 목록이면 ttsState 는 ok 이고 기본 음성으로 읽는다.
STUB = """
  window.__spoken = [];
  const synth = window.speechSynthesis;
  const speak = u => { window.__spoken.push(u.text); if (u.onstart) u.onstart(); if (u.onend) u.onend(); };
  if (synth) {
    synth.getVoices = () => [];
    synth.speak = speak;
    synth.cancel = () => {};
  }
"""

strip = lambda s: s.replace("[", "").replace("]", "")

with sync_playwright() as p:
    b = p.chromium.launch()
    errors = []
    page = b.new_page(viewport={"width": 390, "height": 844})
    page.add_init_script(STUB)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE + "/?demo=1")
    page.wait_for_timeout(700)

    check("TTS 상태가 ok (스텁 음성 인식)",
          page.evaluate("typeof ttsState === 'function' ? ttsState() : 'no-fn'") == "ok",
          str(page.evaluate("typeof ttsState === 'function' ? ttsState() : 'no-fn'")))

    page.locator("#demo-fab").click()
    page.wait_for_timeout(300)
    page.locator('.side [data-id="u-coll"]').click()
    page.wait_for_timeout(600)
    check("문장 모음 도달", page.evaluate("S.screen") == "u-coll")

    n = page.locator(".sent").count()
    check("문장 목록이 있다", n > 0, f"{n}개")

    for i in range(min(6, n)):
        row = page.locator(".sent").nth(i)
        shown = row.locator(".en").inner_text().strip()
        if not shown:
            continue
        row.locator("button.play").click()
        page.wait_for_timeout(250)
        spoken = page.evaluate("window.__spoken.at(-1)")
        check(f"문장 {i + 1}: 음성 == 화면(대괄호 제외)", spoken == strip(shown),
              f"화면={shown!r} 음성={spoken!r}")

    found = False
    for i in range(n):
        row = page.locator(".sent").nth(i)
        shown = row.locator(".en").inner_text().strip()
        if "[" not in shown:
            continue
        row.locator("button.play").click()
        page.wait_for_timeout(250)
        spoken = page.evaluate("window.__spoken.at(-1)")
        check("자리표시자 문장: 음성 == 화면(대괄호 제외)", spoken == strip(shown),
              f"화면={shown!r} 음성={spoken!r}")
        check("자리표시자 화면에 your 가 있다", "your" in shown, shown)
        check("음성에 대괄호가 없다", bool(spoken) and "[" not in spoken and "]" not in spoken, str(spoken))
        found = True
        break
    check("자리표시자 문장을 찾았다", found)

    page.locator('.pnav button[data-id="u-study"]').click()
    page.wait_for_timeout(700)
    if page.evaluate("S.screen") == "u-study" and page.locator('.face.back .en').count():
        page.locator('[data-act="flip"]').first.click()
        page.wait_for_timeout(400)
        shown = page.locator(".face.back .en").first.inner_text().strip()
        page.evaluate("window.__spoken = []")
        page.locator('[data-act="speak-card"]').first.click(force=True)
        page.wait_for_timeout(250)
        fresh = page.evaluate("window.__spoken.slice()")
        check("학습 카드: 음성 == 화면(대괄호 제외)", fresh == [strip(shown)],
              f"화면={shown!r} 음성={fresh!r}")
    else:
        check("학습 카드 도달", False, str(page.evaluate("S.screen")))

    check("JS 오류 없음", not errors, "; ".join(errors[:3]))
    b.close()

bad = [n for n, c in results if not c]
print(f"\n{len(results) - len(bad)}/{len(results)} 통과")
if bad:
    print("실패: " + ", ".join(bad))
    sys.exit(1)
