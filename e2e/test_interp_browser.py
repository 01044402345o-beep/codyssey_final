"""통역 브라우저 엔진(데스크톱 Chrome·Edge) E2E — 가짜 SpeechRecognition·Translator 로 확인한다.

- 기기 안 인식(processLocally)·번역이 되면 '이 기기(브라우저)' 엔진이 맨 앞(기본). 음성이 서버로 가지 않는다(WebSocket 없음).
- 내 차례 ↔ 상대 차례: 인식 언어가 ko-KR ↔ en-US 로 바뀐다.
- 브라우저 엔진이 실패하면 그 자리에서 서버 엔진으로 넘어간다.
- 모바일, processLocally 없음(=Chrome 기본 인식은 서버로 보냄), 언어 팩 없음이면 브라우저 엔진을 보이지 않는다.
서버는 시험 모드로 띄운다: INTERP_PROVIDER=fake INTERP_ALLOW_FAKE=1
"""
import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1]
results = []

MOCK = """
(() => {
  window.__srLog = [];
  const mode = window.__srMode || 'ok';
  class FakeSR {
    constructor() { this.lang = ''; this.continuous = false; this.interimResults = false; window.__sr = this; }
    static async available(o) { window.__srLog.push(['available', o.langs.join(','), o.processLocally]); return mode === 'none' ? 'unavailable' : 'available'; }
    static async install() { return true; }
    start() {
      window.__srLog.push(['start', this.lang, this.processLocally]);
      if (mode === 'fail') { setTimeout(() => this.onerror && this.onerror({ error: 'network' }), 60); return; }
      setTimeout(() => {
        const said = this.lang === 'ko-KR' ? '기차역이 어디예요?' : 'It is five minutes on foot.';
        const res = [[{ transcript: said }]]; res[0].isFinal = true;
        this.onresult && this.onresult({ resultIndex: 0, results: res });
      }, 150);
    }
    abort() { window.__srLog.push(['abort']); }
    stop() {}
  }
  if (mode !== 'cloud-only') FakeSR.prototype.processLocally = false;   // cloud-only: 기기 안 인식 기능이 없는 브라우저
  Object.defineProperty(window, 'SpeechRecognition', { value: FakeSR, configurable: true });
  window.Translator = { availability: async () => 'available',
    create: async o => ({ translate: async t => `[${o.sourceLanguage}->${o.targetLanguage}] ${t}`, destroy() {} }) };
})();
"""


def check(name, cond, extra=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""))


def open_interp(b, mode="ok", ua=None):
    kw = {"viewport": {"width": 1280, "height": 900}, "permissions": ["microphone"]}
    if ua:
        kw["user_agent"] = ua
    ctx = b.new_context(**kw)
    ctx.add_init_script(f"window.__srMode = '{mode}'; window.__browserEngineTest = true;")   # 자동화 브라우저에서도 브라우저 엔진 판단을 켠다(가짜 API)
    ctx.add_init_script(MOCK)
    page = ctx.new_page()
    errors, sockets = [], []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("websocket", lambda ws: sockets.append(ws.url))
    page.goto(BASE + "/?demo=1"); page.wait_for_timeout(800)
    page.evaluate("S.user = DEMO_USER; ensure('plan'); S.today = S.trip.tripStart; go('u-interp')")
    for _ in range(20):
        page.wait_for_timeout(200)
        if page.evaluate("Array.isArray(LIVE.providers)"):
            break
    page.wait_for_timeout(200)
    return ctx, page, errors, sockets


def chips(page):
    return page.evaluate("[...document.querySelectorAll('.live-engines .chip')].map(c => [c.textContent.trim(), c.classList.contains('on')])")


def start(page):
    page.locator('[data-act="live-start"]').click(); page.wait_for_timeout(300)
    if page.locator('.modal [data-act="modal-ok"]').count():
        page.locator('.modal [data-act="modal-ok"]').click()


with sync_playwright() as p:
    b = p.chromium.launch(args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"])

    # --- 쓸 수 있는 데스크톱 브라우저 ---
    ctx, page, errors, sockets = open_interp(b)
    c = chips(page)
    check("기기 안에서 되면 '이 기기(브라우저)'가 맨 앞이고 기본 선택", bool(c) and c[0] == ["이 기기(브라우저)", True], str(c))
    start(page)
    for _ in range(20):
        page.wait_for_timeout(200)
        if page.evaluate("LIVE.cap.target"):
            break
    check("브라우저 엔진으로 통역: 인식 → 기기 안 번역 → 상대 칸", page.evaluate("LIVE.provider") == "browser"
          and page.evaluate("LIVE.cap.target") == "[ko->en] 기차역이 어디예요?", page.evaluate("LIVE.cap.target"))
    log = page.evaluate("window.__srLog")
    check("음성 인식은 기기 안 처리(processLocally=true)·ko-KR", ["start", "ko-KR", True] in log, str(log))
    check("음성이 서버로 가지 않는다(WebSocket 없음)", sockets == [], str(sockets))
    check("상대 칸에 상대 언어 'AI 번역' 표시", "AI translation" in page.locator(".conv-partner").inner_text())
    page.locator('[data-act="live-turn"]').click()
    for _ in range(20):
        page.wait_for_timeout(200)
        if "en->ko" in (page.evaluate("LIVE.cap.target") or ""):
            break
    check("상대 차례로 바꾸면 en-US 로 듣고 한국어로 번역", page.evaluate("LIVE.speaker") == "partner"
          and page.evaluate("LIVE.cap.target") == "[en->ko] It is five minutes on foot.", page.evaluate("LIVE.cap.target"))
    page.locator('[data-act="live-stop"]').click(); page.wait_for_timeout(300)
    check("끝내면 인식·번역기를 정리", page.evaluate("!LIVE.on && LIVE.rec === null && LIVE.tr === null"))
    check("페이지 오류 없음", not errors, str(errors)[:200])
    ctx.close()

    # --- 브라우저 엔진이 실패하면 서버 엔진으로 ---
    ctx, page, errors, sockets = open_interp(b, mode="fail")
    start(page)
    for _ in range(40):
        page.wait_for_timeout(200)
        if page.evaluate("LIVE.provider") == "fake" and page.evaluate("LIVE.status") == "live":
            break
    check("브라우저 엔진 실패 → 자동으로 서버 엔진(시험 모드)으로 연결", page.evaluate("LIVE.provider") == "fake"
          and page.evaluate("LIVE.exclude.includes('browser')") and len(sockets) >= 1 and "서버 통역" in page.evaluate("LIVE.note"),
          f"{page.evaluate('LIVE.provider')} / {page.evaluate('LIVE.note')} / {sockets}")
    page.locator('[data-act="live-stop"]').click(); page.wait_for_timeout(200)
    check("페이지 오류 없음(실패 전환)", not errors, str(errors)[:200])
    ctx.close()

    # --- 브라우저 엔진을 보이지 않는 경우 ---
    for mode, ua, why in [("none", None, "언어 팩을 기기 안에서 쓸 수 없음"),
                          ("cloud-only", None, "processLocally 없음(인식이 서버로 감)"),
                          ("ok", "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148", "모바일")]:
        ctx, page, errors, sockets = open_interp(b, mode=mode, ua=ua)
        names = [n for n, _ in chips(page)]
        ids = page.evaluate("(LIVE.providers || []).map(p => p.id)")
        check(f"브라우저 엔진 없음: {why}", "browser" not in ids and "이 기기(브라우저)" not in names, str(ids))
        ctx.close()
    b.close()

print(f"\n{sum(ok for _, ok in results)}/{len(results)} passed")
sys.exit(0 if all(ok for _, ok in results) else 1)
