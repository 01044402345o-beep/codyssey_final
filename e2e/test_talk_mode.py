"""회화 연습 시트의 '대화하기' E2E (실시간 회화 1a — 스크립트, AI 호출 0회).

근거: docs/research/realtime-agent/README.md 3절 Must · 4절 1a.
- 상대가 먼저(입국심사 '방문 목적') 영어로 말하고 자막이 보인다. 소리가 끝나면 내 차례.
- 힌트는 누를 때만 한 단계씩(질문의 한국어 뜻 → 첫 단어 → 예시 답 전체).
- 내 답을 녹음하면 /speak-check 의 target 이 그 턴의 문장이다(내 문장 → 이어서). 대화 중에는 점수가 안 보인다.
- 끝나면 요약: 고칠 점 한 가지만. 시트를 닫으면 대화도 멈춘다. 서버 응답은 가로채서 고정한다(외부 AI 호출 없음).

    /speak-check 는 가로채므로 정적 서버면 된다(백엔드도 됨):
    python -m http.server 8790 --directory mockup
    python e2e/test_talk_mode.py http://localhost:8790
"""
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = sys.argv[1]
results = []

SPEECH_SPY = """
(() => {
  window.__spoken = [];
  const synth = window.speechSynthesis;
  if (!synth) return;
  synth.speak = u => { window.__spoken.push({ text: u.text, rate: u.rate }); if (u.onstart) u.onstart(); setTimeout(() => u.onend && u.onend(), 30); };
  synth.cancel = () => {};
  synth.getVoices = () => [];
})();
"""


def check(name, cond, extra=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""))


with sync_playwright() as p:
    wav = str(Path(__file__).resolve().parents[1] / "backend" / "tests" / "fixtures" / "good.wav")
    b = p.chromium.launch(args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
                                f"--use-file-for-fake-audio-capture={wav}"])
    ctx = b.new_context(viewport={"width": 390, "height": 844}, permissions=["microphone"])
    ctx.add_init_script(SPEECH_SPY)
    targets = []
    scores = iter([88, 52])

    def fake_check(route):
        body = route.request.post_data_buffer or b""
        t = body.split(b'name="target"\r\n\r\n', 1)[1].split(b"\r\n", 1)[0].decode() if b'name="target"' in body else ""
        targets.append(t)
        sc = next(scores, 70)
        route.fulfill(status=200, content_type="application/json", body=json.dumps({
            "usable": True, "mock": False, "score": sc, "score_kind": "word_match_consensus",
            "heard": t.lower().rstrip("."), "fix_one": f"fix-{sc}", "tip": "", "cross_validated": True}))

    ctx.route("**/speak-check", fake_check)
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE + "/?demo=1", wait_until="domcontentloaded")
    page.wait_for_timeout(700)
    page.evaluate("ensure('plan')")
    page.evaluate("saveConsentHere(true) || (consentMem = true)")   # 동의 흐름은 test_consent 가 본다

    page.evaluate("navFromMenu('u-coll')"); page.wait_for_timeout(300)
    page.locator('[data-act="drill"][data-v="immigration"]').click(); page.wait_for_timeout(300)
    page.locator('[data-act="sheet-open"]').click(); page.wait_for_timeout(300)
    check("시트에 '대화하기' 버튼", page.locator('[data-act="talk-start"]').count() == 1)

    page.locator('[data-act="talk-start"]').click(); page.wait_for_timeout(150)
    check("상대가 먼저: 입국 질문 자막", "What's the purpose of your visit?" in page.locator(".talk-log").inner_text())
    page.wait_for_timeout(500)
    spoken = page.evaluate("window.__spoken.map(x => x.text)")
    check("상대 대사를 TTS 로 읽었다", "What's the purpose of your visit?" in spoken, str(spoken))
    check("소리가 끝나면 내 차례", "내 차례" in page.locator(".talk-state").inner_text(), page.locator(".talk-state").inner_text())
    check("대화 중 점수 문구 없음", "%" not in page.locator(".sheet.talk").inner_text())
    check("큰 마이크 버튼(≥56px)", page.locator('[data-act="talk-rec"]').bounding_box()["height"] >= 56)

    # 재디자인: 시트 높이 고정(턴마다 출렁이지 않음) · 조작부는 시트 바닥 · 진행 점 · 기록 칸만 스크롤
    h0 = page.locator(".sheet.talk").bounding_box()["height"]
    dock = page.locator(".talk-dock").bounding_box(); sh = page.locator(".sheet.talk").bounding_box()
    check("조작부가 시트 바닥에 붙음", abs((dock["y"] + dock["height"]) - (sh["y"] + sh["height"])) < 2, f"{dock} {sh}")
    check("진행 점 = 내 차례 수(2), 지금 1개", page.locator(".talk-prog i").count() == 2 and page.locator(".talk-prog i.now").count() == 1)
    check("상태 띠에 단계 표시(me)", page.locator(".talk-state").get_attribute("data-phase") == "me")
    check("시트 자체는 스크롤하지 않음(기록 칸만)", page.evaluate("getComputedStyle(document.querySelector('.sheet.talk')).overflowY") == "hidden"
          and page.evaluate("getComputedStyle(document.querySelector('.talk-scroll')).overflowY") == "auto")
    hint = page.locator('[data-act="talk-hint"]')
    check("힌트는 처음엔 숨김", page.locator(".talk-hint").count() == 0)
    hint.click(); page.wait_for_timeout(100)
    check("힌트 1: 질문의 한국어 뜻", page.locator(".talk-hint.ask-ko").inner_text() == "방문 목적이 무엇인가요?")
    hint.click(); page.wait_for_timeout(100)
    check("힌트 2: 첫 단어", page.locator(".talk-hint.first").inner_text().startswith("I'm"))
    hint.click(); page.wait_for_timeout(100)
    check("힌트 3: 예시 답 전체", page.locator(".talk-hint.en").inner_text() == "I'm here for sightseeing.")
    check("힌트 3단계에서 멈춤", hint.is_disabled())
    check("힌트에 단계 이름표(질문 뜻·예시 답)", "질문 뜻" in page.locator(".talk-hints").inner_text() and "예시 답" in page.locator(".talk-hints").inner_text())
    check("힌트를 펼쳐도 시트 높이 그대로", abs(page.locator(".sheet.talk").bounding_box()["height"] - h0) < 2)

    # 내 답 녹음 → 서버(가로챔) → 들린 말 되받기 → 상대 차례 자동
    page.locator('[data-act="talk-rec"]').click(); page.wait_for_timeout(1200)
    check("녹음 중: 상태 띠 rec · 힌트 비활성", page.locator(".talk-state").get_attribute("data-phase") == "rec" and hint.is_disabled())
    page.locator('[data-act="talk-rec"]').click(); page.wait_for_timeout(600)
    check("첫 녹음 target = 내 문장", targets[:1] == ["I'm here for sightseeing."], str(targets))
    check("들린 말을 되받고 점수는 숨김", "들렸어요" in page.locator(".talk-note").inner_text()
          and "88" not in page.locator(".sheet.talk").inner_text())
    page.wait_for_timeout(1700)
    check("상대 갈래(nextFor) 대사로 넘어감", "How long will you be staying?" in page.locator(".talk-log").inner_text())

    # Sorry? → 더 천천히
    page.wait_for_timeout(300)
    before = page.evaluate("window.__spoken.length")
    page.locator('[data-act="talk-sorry"]').first.click(); page.wait_for_timeout(200)
    sp = page.evaluate("window.__spoken")
    check("Sorry? 는 같은 대사를 더 느리게", len(sp) > before and sp[-1]["text"] == "How long will you be staying?" and sp[-1]["rate"] < sp[0]["rate"], str(sp[-2:]))
    page.wait_for_timeout(300)

    page.locator('[data-act="talk-rec"]').click(); page.wait_for_timeout(1200)
    page.locator('[data-act="talk-rec"]').click(); page.wait_for_timeout(2600)
    check("둘째 녹음 target = 이어서 문장", targets[1:2] == ["About a week."], str(targets))
    done = page.locator(".talk-done")
    check("끝난 뒤 요약", done.count() == 1)
    txt = done.inner_text() if done.count() else ""
    check("요약: 단어 일치(발음 점수 아님) 표기", "단어 일치 88%" in txt and "발음 점수 아님" in txt, txt[:200])
    check("고칠 점은 한 가지(가장 낮은 턴)", page.locator(".talk-fix").count() == 1 and "fix-52" in txt and "fix-88" not in txt)
    check("자동 복습 저장 없음(대화 중)", page.evaluate("weakList().length") == 0)
    check("요약: 다시 해보기·돌아가기는 바닥 고정 칸", page.locator(".talk-done .talk-dock [data-act=talk-exit]").count() == 1)
    check("요약 상태 띠 done", page.locator(".talk-state").get_attribute("data-phase") == "done")

    # 다시 해보기 → 닫기로 대화 정지
    page.locator('.talk-done [data-act="talk-start"]').click(); page.wait_for_timeout(200)
    check("다시 해보기: 처음부터", page.evaluate("TALK.on && TALK.i") in (0, 1))
    page.evaluate("closeSheet()")
    page.wait_for_timeout(200)
    check("시트를 닫으면 대화도 멈춤", page.evaluate("TALK.on") is False and page.locator(".sheet").count() == 0)

    # 상대가 먼저 없는 상황(공항 좌석): 내가 먼저, 힌트 1 = 내 문장 뜻
    page.evaluate("navFromMenu('u-coll')"); page.wait_for_timeout(300)
    page.locator('[data-act="drill"][data-v="airport"]').click(); page.wait_for_timeout(300)
    page.locator('[data-act="sheet-open"]').click(); page.wait_for_timeout(200)
    page.locator('[data-act="talk-start"]').click(); page.wait_for_timeout(200)
    check("ask 없으면 내가 먼저", "내 차례" in page.locator(".talk-state").inner_text())
    page.locator('[data-act="talk-hint"]').click(); page.wait_for_timeout(100)
    check("내가 먼저일 때 힌트 1 = 내 문장 뜻", page.locator(".talk-hint.me-ko").count() == 1)
    page.locator('[data-act="talk-next"]').click(); page.wait_for_timeout(500)
    check("넘어가기 → 상대 대사(nextFor 갈래)", "Sorry, all the window seats are taken." in page.locator(".talk-log").inner_text())


    # --- 동의 전 · 마이크 거부 · 3초 안내 · 뒤로가기 (별도 컨텍스트) ---
    ctx2 = b.new_context(viewport={"width": 390, "height": 844}, permissions=["microphone"])
    ctx2.add_init_script(SPEECH_SPY)
    ctx2.add_init_script("window.__gum = 0; window.__deny = false; const o = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);"
                         "navigator.mediaDevices.getUserMedia = c => { window.__gum++; return window.__deny ? Promise.reject(new Error('denied')) : o(c); };")

    # 응답 지연은 브라우저 쪽 fetch 에서 만든다(동기 Playwright 핸들러에서 sleep 하면 테스트 시계가 같이 멈춘다)
    ctx2.add_init_script("""(() => { const f = window.fetch; window.fetch = (u, o) => String(u).includes('/speak-check')
      ? new Promise(r => setTimeout(() => r(new Response(JSON.stringify({ usable: true, mock: false, score: 80, heard: "i'm here for sightseeing", cross_validated: true }), { headers: { 'Content-Type': 'application/json' } })), 4500))
      : f(u, o); })();""")
    pg = ctx2.new_page(); pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(BASE + "/?demo=1", wait_until="domcontentloaded"); pg.wait_for_timeout(700); pg.evaluate("ensure('plan')")
    pg.evaluate("navFromMenu('u-coll')"); pg.wait_for_timeout(300)
    pg.locator('[data-act="drill"][data-v="immigration"]').click(); pg.wait_for_timeout(300)
    pg.locator('[data-act="sheet-open"]').click(); pg.wait_for_timeout(200)
    pg.locator('[data-act="talk-start"]').click(); pg.wait_for_timeout(600)
    pg.locator('[data-act="talk-rec"]').click(); pg.wait_for_timeout(300)
    check("동의 전: 동의 창이 뜨고 마이크는 안 열림", pg.locator(".modal").count() == 1 and pg.evaluate("window.__gum") == 0)
    pg.evaluate("window.__deny = true")
    pg.locator('.modal [data-act="modal-ok"]').click(); pg.wait_for_timeout(500)
    check("동의 뒤에도 대화는 유지", pg.evaluate("TALK.on") is True)
    check("마이크 거부: 대화 화면에 한국어 안내", "마이크를 사용할 수 없어요" in pg.locator(".talk-note").inner_text())
    pg.evaluate("window.__deny = false")
    pg.locator('[data-act="talk-rec"]').click(); pg.wait_for_timeout(4200)   # 오래 녹음
    pg.locator('[data-act="talk-rec"]').click(); pg.wait_for_timeout(1500)
    check("말을 마친 직후(1.5초)에는 3초 안내 없음", "서버가 깨어나는" not in pg.locator(".talk-state").inner_text(), pg.locator(".talk-state").inner_text())
    check("녹음/채점 중 Sorry? 비활성", pg.locator('[data-act="talk-sorry"]').first.is_disabled())
    pg.wait_for_timeout(2000)
    check("말을 마친 뒤 3초가 넘으면 한국어 안내", "서버가 깨어나는" in pg.locator(".talk-state").inner_text(), pg.locator(".talk-state").inner_text())
    pg.wait_for_timeout(1500)
    pg.go_back(); pg.wait_for_timeout(400)
    check("뒤로가기: 시트와 대화가 함께 닫힘", pg.evaluate("TALK.on") is False and pg.locator(".sheet").count() == 0)
    ctx2.close()

    check("페이지 오류 없음", not errors, str(errors))
    b.close()

failed = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
