"""복원 시 AI 문장 채우기 E2E.

새로고침·재방문으로 계획을 규칙으로 다시 만들면 /generate 로 만든 AI 문장이 사라진다.
저장된 여행을 되살린 경우에만 백그라운드로 한 번 더 생성해 AI 문장을 채우는지 확인한다.
서버는 키 없이(목업 = sample) 띄운다.

    cd backend && uvicorn app.main:app --port 8768
    python ../e2e/test_ai_restore.py http://localhost:8768
"""
import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1]
results = []


def check(name, cond, extra=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""))


def gen_tracker(page):
    box = {"urls": []}
    page.on("request", lambda r: box["urls"].append(r.url) if "/generate" in r.url else None)
    return box


with sync_playwright() as p:
    b = p.chromium.launch()
    errors = []

    # --- 여행이 없으면 부르지 않는다 ---
    ctx = b.new_context(viewport={"width": 390, "height": 844})
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    gen = gen_tracker(page)
    page.goto(BASE + "/", wait_until="domcontentloaded")
    page.wait_for_timeout(1800)
    check("여행이 없으면 /generate 를 부르지 않는다", len(gen["urls"]) == 0, str(gen["urls"]))
    ctx.close()

    # --- 저장된 여행을 복원하면 백그라운드로 한 번 더 생성한다 ---
    ctx = b.new_context(viewport={"width": 390, "height": 844})
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE + "/?demo=1", wait_until="domcontentloaded")
    page.wait_for_timeout(700)
    page.evaluate("ensure('plan'); go('u-home')")           # 여행 입력 저장 + 세션(화면) 기록
    check("여행 입력·세션이 저장됐다",
          page.evaluate("!localStorage.getItem('cd_trip')") is False and page.evaluate("!localStorage.getItem('cd_session')") is False)
    blank = page.evaluate("({ ai: S.sents.some(s => s.sample || s.ai), pools: Object.keys(S.aiPools).length })")
    check("복원 전에는 AI 문장이 없다(틀 문장)", blank["ai"] is False and blank["pools"] == 0, str(blank))

    gen = gen_tracker(page)
    page.goto(BASE + "/", wait_until="domcontentloaded")     # 새로 열기 = 복원
    page.wait_for_timeout(3500)
    st = page.evaluate("({ scr: S.screen, ai: S.sents.some(s => s.sample || s.ai), pools: Object.keys(S.aiPools).length })")
    check("복원하면 백그라운드 /generate 를 부른다", len(gen["urls"]) >= 1, str(gen["urls"]))
    check("복원 뒤 AI(샘플) 문장이 채워진다", st["ai"] and st["pools"] > 0, str(st))
    check("화면은 홈(계획 복원)", st["scr"] == "u-home", st["scr"])

    # --- 같은 여행을 또 열어도 중복 호출하지 않는다(로드마다 1회) ---
    gen2 = gen_tracker(page)
    page.goto(BASE + "/", wait_until="domcontentloaded")
    page.wait_for_timeout(2500)
    check("다시 열면 또 1회 생성(세션당 여행 1회)", len(gen2["urls"]) >= 1, str(gen2["urls"]))

    check("자바스크립트 오류 없음", not errors, str(errors[:3]))
    b.close()

bad = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(bad)}/{len(results)} 통과")
if bad:
    print("실패: " + ", ".join(bad))
sys.exit(1 if bad else 0)
