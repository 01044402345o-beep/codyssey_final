"""통역 탭 E2E — 여행 중에는 하단 '학습' 자리에 '통역'.

- 여행 전·여행 끝난 뒤는 '학습', 여행 중(tripStart ≤ 오늘 ≤ tripEnd)만 '통역'.
- 통역 화면: 오늘 장소 문장 → 상황 칩(도움 요청·공항·입국…) → 한국어/영어 낱말로 찾기.
- 문장마다 '들려주기'(영어 음성)·'크게 보여주기'(화면 가득 영어 + 상대의 예상 답변과 한국어 뜻).
- 검수된 문장만 쓴다: 통역 화면을 쓰는 동안 서버로 보내는 요청(POST)이 없다.

    cd backend && uvicorn app.main:app --port 8768
    python ../e2e/test_interpret.py http://localhost:8768
"""
import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1]
results = []

SPEECH = """
(() => {
  window.__spoken = [];
  const synth = { speaking: false, pending: false, paused: false, onvoiceschanged: null, getVoices: () => [], cancel() {}, pause() {}, resume() {}, addEventListener() {},
    speak(u) { window.__spoken.push(u.text); if (u.onstart) u.onstart(); setTimeout(() => u.onend && u.onend(), 30); } };
  Object.defineProperty(window, 'speechSynthesis', { value: synth, configurable: true });
})();
"""


def check(name, cond, extra=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""))


TABS = "[...document.querySelectorAll('.pnav button span')].map(s => s.textContent)"

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 390, "height": 844})
    ctx.add_init_script(SPEECH)
    page = ctx.new_page()
    errors, posts = [], []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("request", lambda r: posts.append(r.url) if r.method != "GET" else None)
    page.goto(BASE + "/?demo=1"); page.wait_for_timeout(800)
    page.evaluate("S.user = DEMO_USER; ensure('plan'); go('u-home')"); page.wait_for_timeout(300)

    # --- 여행 전: 학습 ---
    check("여행 전: 하단 탭은 홈·일정표·학습·문장 모음", page.evaluate(TABS) == ["홈", "일정표", "학습", "문장 모음"], str(page.evaluate(TABS)))

    # --- 여행 중: 통역 ---
    page.evaluate("S.today = S.trip.tripStart; go('u-home')"); page.wait_for_timeout(300)
    check("여행 중: '학습' 자리에 '통역'", page.evaluate(TABS) == ["홈", "일정표", "통역", "문장 모음"], str(page.evaluate(TABS)))
    page.locator('.pnav button[data-id="u-interp"]').click(); page.wait_for_timeout(300)
    check("통역 탭 → 통역 화면, 탭이 켜짐", page.evaluate("S.screen") == "u-interp" and page.locator('.pnav button.on[data-id="u-interp"]').count() == 1)

    today_ids = page.evaluate("(S.sched.find(r => r.date === S.today && r.kind !== 'free') || {ids: []}).ids")
    items = page.locator(".interp-item")
    check("처음엔 오늘 장소 문장(오늘 일정과 같은 수)", len(today_ids) > 0 and items.count() == len(today_ids), f"{items.count()} / {len(today_ids)}")

    # 들려주기
    page.evaluate("window.__spoken = []")
    first_en = page.evaluate(f"ttsText(slotText(S.smap['{today_ids[0]}'].en))")
    items.first.locator('[data-act="interp-say"]').click(); page.wait_for_timeout(150)
    check("'들려주기'가 그 영어 문장을 읽는다", page.evaluate("window.__spoken") == [first_en], str(page.evaluate("window.__spoken")))

    # 찾기(한국어·영어) — 입력하는 동안 입력칸이 다시 그려지지 않는다
    box = page.locator('[data-interp="q"]')
    box.fill("영수증"); page.wait_for_timeout(200)
    txt = page.locator("[data-live=interp-list]").inner_text()
    check("한국어로 찾기: '영수증' → Can I get a receipt", "receipt" in txt.lower() and page.evaluate("document.activeElement && document.activeElement.dataset.interp") == "q", txt[:80])
    box.fill("passport"); page.wait_for_timeout(200)
    check("영어로 찾기: 'passport'", "passport" in page.locator("[data-live=interp-list]").inner_text().lower())
    box.fill("zzqq"); page.wait_for_timeout(200)
    check("없으면 안내", "찾는 문장이 없어요" in page.locator("[data-live=interp-list]").inner_text())
    box.fill(""); page.wait_for_timeout(150)

    # 도움 요청 칩: 돌발 + 응급 전화(참고 묶음)
    page.locator('[data-act="interp-sit"][data-v="help"]').click(); page.wait_for_timeout(250)
    ids = page.evaluate("interpList().map(s => s.id)")
    check("'도움 요청' 칩: 돌발 상황 + 응급 전화 문장", any(i.startswith("c-emergency") for i in ids) and any(i.startswith("r-") for i in ids), str(ids[:6]))

    # 크게 보여주기 — 입국심사(상대 답변이 있는 문장)
    page.locator('[data-act="interp-sit"][data-v="immigration"]').click(); page.wait_for_timeout(250)
    page.locator('.interp-item [data-act="interp-show"]').first.click(); page.wait_for_timeout(250)
    show = page.locator(".interp-show")
    sid = page.evaluate("S.interp.show")
    check("크게 보여주기: 화면 가득 영어 문장 + 한국어 뜻", show.count() == 1 and page.evaluate(f"slotText(S.smap['{sid}'].en)") in show.inner_text()
          and page.evaluate("parseFloat(getComputedStyle(document.querySelector('.interp-show-en')).fontSize)") >= 30)
    nrep = page.evaluate(f"(S.smap['{sid}'].talk || {{replies: []}}).replies.length")
    check("상대가 이렇게 답할 수 있어요 — 예상 답변과 한국어 뜻", nrep > 0 and "상대가 이렇게 답할 수 있어요" in show.inner_text()
          and show.locator(".talk-line").count() == nrep, f"{nrep}개")
    page.evaluate("window.__spoken = []")
    show.locator('[data-act="interp-say-reply"]').first.click(); page.wait_for_timeout(150)
    check("예상 답변 '듣기'", page.evaluate("window.__spoken") == [page.evaluate(f"S.smap['{sid}'].talk.replies[0].en")])
    page.go_back(); page.wait_for_timeout(300)
    check("뒤로가기: 크게 보여주기만 닫고 통역 화면에 남는다", show.count() == 0 and page.evaluate("S.screen") == "u-interp")

    # 여행이 끝나면 다시 학습
    page.evaluate("S.today = Dt.add(S.trip.tripEnd, 1); go('u-home')"); page.wait_for_timeout(300)
    tabs_end = page.evaluate("[...document.querySelectorAll('.pnav button span')].map(s => s.textContent)")
    check("여행이 끝나면 '통역' 대신 '학습'(종료 화면은 탭 없음이면 통과)", tabs_end in ([], ["홈", "일정표", "학습", "문장 모음"]), str(tabs_end))

    check("통역을 쓰는 동안 서버로 보낸 요청 없음(검수 문장만, AI 호출 없음)", not [u for u in posts if "/user/state" not in u], str(posts[:3]))
    check("페이지 JS 오류 없음", not errors, "; ".join(errors[:3]))
    b.close()

print(f"\n{sum(ok for _, ok in results)}/{len(results)} passed")
sys.exit(0 if all(ok for _, ok in results) else 1)
