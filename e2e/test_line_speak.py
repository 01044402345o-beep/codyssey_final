"""회화 연습 시트: 문장마다 '듣기' 옆에 '말해보기' (사용자 요청 10/20).

- 내 문장 · 상대가 먼저 · 상대의 예상 답변 · 내가 이어서 — 모든 줄에서 듣기와 말해보기가 같은 줄에 나란히 있다.
- 줄의 말해보기를 누르면 그 줄 영어 문장이 /speak-check 의 target 이 되고, 결과는 그 줄 아래에만 보인다.
- 상대 답변·이어서 할 말 연습은 복습 목록에 넣지 않는다(복습 규칙은 내 문장 기준). 한 줄을 녹음하는 동안 다른 줄 말해보기는 막힌다.
- 녹음 고지는 시트에 한 번만.

    python -m http.server 8790 --directory mockup
    python e2e/test_line_speak.py http://localhost:8790
"""
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = sys.argv[1]
results = []
SPY = """(() => { window.__spoken = []; const s = window.speechSynthesis; if (!s) return;
  s.speak = u => { window.__spoken.push(u.text); u.onstart && u.onstart(); setTimeout(() => u.onend && u.onend(), 30); };
  s.cancel = () => {}; s.getVoices = () => []; })();"""


def check(name, cond, extra=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""))


with sync_playwright() as p:
    wav = str(Path(__file__).resolve().parents[1] / "backend" / "tests" / "fixtures" / "good.wav")
    b = p.chromium.launch(args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
                                f"--use-file-for-fake-audio-capture={wav}"])
    ctx = b.new_context(viewport={"width": 390, "height": 844}, permissions=["microphone"])
    ctx.add_init_script(SPY)
    targets = []

    def fake(route):
        body = route.request.post_data_buffer or b""
        t = body.split(b'name="target"\r\n\r\n', 1)[1].split(b"\r\n", 1)[0].decode() if b'name="target"' in body else ""
        targets.append(t)
        route.fulfill(status=200, content_type="application/json", body=json.dumps({
            "usable": True, "mock": False, "score": 40, "score_kind": "word_match",
            "heard": "how long", "fix_one": "fix-line", "tip": "", "cross_validated": True}))

    ctx.route("**/speak-check", fake)
    page = ctx.new_page(); errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE + "/?demo=1", wait_until="domcontentloaded"); page.wait_for_timeout(700)
    page.evaluate("ensure('plan')"); page.evaluate("saveConsentHere(true) || (consentMem = true)")
    page.evaluate("navFromMenu('u-coll')"); page.wait_for_timeout(300)
    page.locator('[data-act="drill"][data-v="immigration"]').click(); page.wait_for_timeout(300)
    page.locator('[data-act="sheet-open"]').click(); page.wait_for_timeout(300)
    s = page.evaluate("(() => { const s = curSent(); return { en: s.en, talk: s.talk }; })()")

    rows = page.locator(".sheet .line-acts")
    want = 1 + len(s["talk"]["replies"]) + 1 + (1 if s["talk"].get("ask") else 0) + len(page.evaluate("(curSent().alt || [])"))   # 내 문장·답변·이어서·질문·같은 뜻 다른 표현
    check("모든 문장 줄에 듣기+말해보기 줄", rows.count() == want, f"{rows.count()}/{want}")
    same_row = page.evaluate("""[...document.querySelectorAll('.sheet .line-acts')].every(r => {
      const a = r.querySelector('.talk-say'), m = r.querySelector('.speak-btn'); if (!a || !m) return false;
      const x = a.getBoundingClientRect(), y = m.getBoundingClientRect();
      return Math.abs(x.top - y.top) < 2 && y.left > x.right; })""")
    check("말해보기는 듣기 바로 오른쪽, 같은 높이(모든 줄)", same_row)
    check("내 문장 말해보기는 기존 speak-rec(복습 규칙 유지)", page.locator('.sheet .talk-me [data-act="speak-rec"]').count() == 1)
    check("녹음 고지는 시트에 한 번", page.locator(".sheet .speak-note").count() == 1)

    r0 = page.locator('.sheet [data-act="speak-line"][data-k="r0"]')
    r0.click(); page.wait_for_timeout(900)
    check("답변 줄 녹음 중: 그 버튼만 '녹음 끝내기'", "녹음 끝내기" in r0.inner_text())
    check("녹음 중 다른 줄 말해보기는 막힘", page.locator('.sheet .talk-me [data-act="speak-rec"]').is_disabled()
          and page.locator('.sheet [data-act="speak-line"][data-k="next"]').is_disabled())
    r0.click(); page.wait_for_timeout(1000)
    check("답변 줄 target = 그 답변 문장", targets[-1:] == [s["talk"]["replies"][0]["en"]], str(targets))
    res_r0 = page.locator('.sheet [data-live="speak-res"][data-k="r0"]').inner_text()
    check("결과는 그 줄 아래에만", "fix-line" in res_r0 and page.locator('.sheet [data-live="speak-res"][data-k="me"]').inner_text().strip() == "", res_r0)
    check("답변 연습은 복습 목록 저장·제안 없음", page.evaluate("weakList().length") == 0 and page.locator('[data-act="weak-save"]').count() == 0)
    check("그 줄에 '내 발음 듣기'", page.locator('.sheet [data-live="speak-res"][data-k="r0"] [data-act="play-mine"]').count() == 1)

    nx = page.locator('.sheet [data-act="speak-line"][data-k="next"]')
    nx.click(); page.wait_for_timeout(900); nx.click(); page.wait_for_timeout(1000)
    check("이어서 할 말 target", targets[-1:] == [s["talk"]["next"]["en"]], str(targets))
    check("새 줄을 녹음하면 이전 줄 결과는 지워짐", page.locator('.sheet [data-live="speak-res"][data-k="r0"]').inner_text().strip() == "")

    ak = page.locator('.sheet [data-act="speak-line"][data-k="ask"]')
    ak.click(); page.wait_for_timeout(900); ak.click(); page.wait_for_timeout(1000)
    check("상대가 먼저 질문도 말해볼 수 있음", targets[-1:] == [s["talk"]["ask"]["en"]], str(targets))

    page.locator('.sheet .talk-me [data-act="speak-rec"]').click(); page.wait_for_timeout(900)
    page.locator('.sheet .talk-me [data-act="speak-rec"]').click(); page.wait_for_timeout(1000)
    check("내 문장 target = 내 문장", targets[-1:] == [s["en"]], str(targets))
    # 복습 규칙은 그대로 AI.weakDecision 이 정한다(공통 문장은 ai:true 가 아니라 'none'). 화면 결과가 그 판정과 같은지 본다.
    dec = page.evaluate("AI.weakDecision(curSent(), { usable: true, mock: false, score: 40, heard: 'how long', cross_validated: true })")
    shown = "auto" if page.evaluate("weakList().length") == 1 else "ask" if page.locator('[data-act="weak-save"]').count() == 1 else "none"
    check("내 문장은 기존 복습 규칙(weakDecision) 그대로", dec == shown, f"{dec} vs {shown}")
    check("내 문장 결과는 내 문장 줄 아래", "fix-line" in page.locator('.sheet [data-live="speak-res"][data-k="me"]').inner_text())

    # 녹음 중 시트를 닫으면 멈춤
    r0.click(); page.wait_for_timeout(700)
    page.locator('[data-act="sheet-close"]').click(); page.wait_for_timeout(300)
    check("녹음 중 시트를 닫으면 녹음도 멈춤", page.evaluate("SPK.state") == "idle")

    check("페이지 오류 없음", not errors, str(errors))
    b.close()

failed = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
