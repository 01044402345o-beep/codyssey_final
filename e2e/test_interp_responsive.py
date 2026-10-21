"""통역 전체화면 반응형 — 폭·높이를 바꿔도 깨지지 않는지 본다.

깨졌던 두 가지를 고정한다:
  ① 조작 버튼이 동그라미가 되고 글자가 밖으로 나가던 문제(아이콘 SVG 기본 크기 300×150)
  ② 번역문이 칸을 넘쳐 'AI 번역' 표시와 겹치던 문제
그리고 좁은 폰·가로 폰·데스크톱에서 배치가 바뀌는지 확인한다.

    INTERP_ALLOW_FAKE=1 INTERP_PROVIDER=fake uvicorn app.main:app --port 8770
    python e2e/test_interp_responsive.py http://localhost:8770
"""
import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1]
results = []


def check(name, cond, extra=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""))


GEOM = """(() => {
  const r = e => { const b = e.getBoundingClientRect(); return {x: b.x, y: b.y, w: b.width, h: b.height, b: b.y + b.height, r: b.x + b.width}; };
  const acts = [...document.querySelectorAll('.il-act')].map(e => ({box: r(e), sw: e.scrollWidth, cw: e.clientWidth,
      svg: e.querySelector('svg') ? r(e.querySelector('svg')) : null, txt: e.textContent.trim()}));
  const big = document.querySelector('.il-side-far .conv-big') || document.querySelector('.conv-big');
  const ai = document.querySelector('.il-side-far .conv-ai') || document.querySelector('.conv-ai');
  const dock = document.querySelector('.il-dock');
  return {acts, big: big && r(big), ai: ai && r(ai), dock: dock && r(dock),
          mic: r(document.querySelector('.il-mic')),
          vw: innerWidth, vh: innerHeight,
          docW: document.documentElement.scrollWidth, docH: document.documentElement.scrollHeight,
          fit: big && big.dataset.fit, base: big && big.dataset.base};
})()"""

START = """(() => {
  S.user = DEMO_USER; ensure('plan'); S.today = S.trip.tripStart; go('u-interp');
  localStorage.setItem(INTERP_CONSENT_KEY, JSON.stringify({voice: true, at: Date.now(), v: INTERP_CONSENT_VERSION}));
})()"""

with sync_playwright() as p:
    b = p.chromium.launch(args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"])
    for (w, h, ui, label) in [(320, 568, "card", "작은 폰"), (390, 844, "split", "기본 폰"),
                              (430, 932, "split", "큰 폰"), (844, 390, "split", "가로 폰"),
                              (768, 1024, "card", "태블릿"), (1280, 800, "card", "데스크톱")]:
        ctx = b.new_context(viewport={"width": w, "height": h}, permissions=["microphone"])
        page = ctx.new_page(); errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(BASE + "/?demo=1"); page.wait_for_timeout(600)
        page.evaluate(START); page.wait_for_timeout(300)
        page.locator('[data-act="live-start"]').click()
        for _ in range(30):
            page.wait_for_timeout(250)
            if page.evaluate("LIVE.status") == "live" and page.evaluate("LIVE.cap.target"):
                break
        page.evaluate(f"setInterpUi('{ui}'); updateLiveUi()"); page.wait_for_timeout(600)
        g = page.evaluate(GEOM); tag = f"{label} {w}x{h}"

        # ① 버튼: 알약이지 동그라미가 아니고, 높이가 고정이며, 글자가 잘리지 않는다
        ok_btn = all(40 <= a["box"]["h"] <= 48 for a in g["acts"])
        check(f"[{tag}] 조작 버튼 높이 44 고정", ok_btn, str([round(a['box']['h']) for a in g['acts']]))
        icon_mode = w <= 340 or h <= 620 or (w > h and h <= 560)
        if not icon_mode:
            check(f"[{tag}] 버튼이 동그라미가 아니다(가로가 세로보다 넓다)",
                  all(a["box"]["w"] > a["box"]["h"] + 8 for a in g["acts"]), str([[round(a['box']['w']), round(a['box']['h'])] for a in g['acts']]))
            check(f"[{tag}] 버튼 글자가 밖으로 나가지 않는다", all(a["sw"] <= a["cw"] + 1 for a in g["acts"]),
                  str([[a['sw'], a['cw']] for a in g['acts']]))
        else:
            check(f"[{tag}] 낮은 화면: 조작은 아이콘만", all(38 <= a["box"]["w"] <= 50 for a in g["acts"]), str([round(a['box']['w']) for a in g['acts']]))
        check(f"[{tag}] 버튼 안 아이콘은 20px 이하", all(a["svg"] and a["svg"]["w"] <= 22 for a in g["acts"] if a["svg"]),
              str([round(a['svg']['w']) if a['svg'] else None for a in g['acts']]))

        # ② 번역문이 'AI 번역' 표시를 덮지 않는다
        if g["big"] and g["ai"]:
            # 마주 보기는 상대 칸을 180° 돌리므로 위/아래 비교가 뒤집힌다 — 사각형 교차로만 판정한다
            A, B = g["big"], g["ai"]
            overlap = not (A["r"] <= B["x"] or B["r"] <= A["x"] or A["b"] <= B["y"] or B["b"] <= A["y"])
            check(f"[{tag}] 번역문이 AI 표시와 겹치지 않는다", not overlap, f"big.b={g['big']['b']:.0f} ai.y={g['ai']['y']:.0f}")
            check(f"[{tag}] 번역문이 칸 안에 들어간다(넘치면 글자를 줄인다)",
                  g["big"]["h"] > 0 and float(g["fit"]) <= float(g["base"]) + 1, f"fit={g['fit']} base={g['base']}")

        # ③ 화면 밖으로 나가지 않는다(가로 스크롤·바닥 잘림 없음)
        check(f"[{tag}] 가로 스크롤이 없다", g["docW"] <= g["vw"] + 1, f"{g['docW']} vs {g['vw']}")
        check(f"[{tag}] 바닥 조작이 화면 안에 있다", g["dock"]["b"] <= g["vh"] + 1, f"{g['dock']['b']:.0f}/{g['vh']}")

        # ④ 배치가 화면에 맞게 바뀐다
        if h <= 620:   # 낮은 화면(가로 폰·작은 폰): 마이크와 조작이 같은 줄
            check(f"[{tag}] 가로에서는 마이크·조작이 한 줄", abs(g["mic"]["y"] - g["acts"][0]["box"]["y"]) < 20,
                  f"mic.y={g['mic']['y']:.0f} act.y={g['acts'][0]['box']['y']:.0f}")
        if w >= 900:   # 데스크톱: 앱 컬럼 폭으로 모인다
            box = page.locator("#interp-live").bounding_box()
            check(f"[{tag}] 데스크톱은 컬럼 폭(≤820)으로 가운데", box and box["width"] <= 821 and abs((box["x"] + box["width"] / 2) - w / 2) < 2,
                  str(box and [round(box["width"]), round(box["x"])]))
        if ui == "split":
            check(f"[{tag}] 마주 보기: 상대 칸은 번역문과 AI 표시만",
                  page.locator(".il-side-far .conv-who").count() == 0 or not page.locator(".il-side-far .conv-who").is_visible())
            rot = page.evaluate("(() => { const m = new DOMMatrix(getComputedStyle(document.querySelector('.il-side-far')).transform); return [m.a, m.d]; })()")
            if w > h:
                check(f"[{tag}] 가로 마주 보기는 회전을 푼다", abs(rot[0] - 1) < .01, str(rot))
            else:
                check(f"[{tag}] 세로 마주 보기는 180°", rot[0] < -0.99, str(rot))

        check(f"[{tag}] 페이지 오류 없음", not errors, str(errors)[:160])
        ctx.close()

    # 화면을 눕혀도 다시 맞춘다(회전)
    ctx = b.new_context(viewport={"width": 390, "height": 844}, permissions=["microphone"])
    page = ctx.new_page(); errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE + "/?demo=1"); page.wait_for_timeout(600)
    page.evaluate(START); page.locator('[data-act="live-start"]').click()
    for _ in range(30):
        page.wait_for_timeout(250)
        if page.evaluate("LIVE.status") == "live" and page.evaluate("LIVE.cap.target"):
            break
    page.evaluate("setInterpUi('split'); updateLiveUi()"); page.wait_for_timeout(500)
    page.set_viewport_size({"width": 844, "height": 390}); page.wait_for_timeout(700)
    g = page.evaluate(GEOM)
    check("[회전] 눕히면 마이크·조작이 한 줄로 바뀐다", abs(g["mic"]["y"] - g["acts"][0]["box"]["y"]) < 20)
    A, B = g["big"], g["ai"]
    check("[회전] 눕혀도 번역문이 AI 표시를 덮지 않는다",
          not (not (A["r"] <= B["x"] or B["r"] <= A["x"] or A["b"] <= B["y"] or B["b"] <= A["y"])))
    check("[회전] 눕혀도 화면 밖으로 안 나간다", g["docW"] <= g["vw"] + 1 and g["dock"]["b"] <= g["vh"] + 1)
    ctx.close()
    b.close()

failed = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
