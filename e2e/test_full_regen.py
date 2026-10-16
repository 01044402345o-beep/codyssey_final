"""여행 설정 화면에서 보고서·문장 완전 재생성 E2E.

날짜만 바꾸면 기본 '저장'은 계획만 다시 계산한다(도시·문장 유지).
'보고서·문장까지 새로 만들기'는 도시가 같아도 보고서와 문장을 처음부터 다시 만든다.
서버는 키 없이(목업 = sample) 띄운다.

    cd backend && uvicorn app.main:app --port 8768
    python ../e2e/test_full_regen.py http://localhost:8768
"""
import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1]
results = []


def check(name, cond, extra=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""))


with sync_playwright() as p:
    b = p.chromium.launch()
    errors = []
    page = b.new_page(viewport={"width": 390, "height": 844})
    page.on("pageerror", lambda e: errors.append(str(e)))
    gens = {"urls": []}
    page.on("request", lambda r: gens["urls"].append(r.url) if "/generate" in r.url else None)

    page.goto(BASE + "/?demo=1", wait_until="domcontentloaded")
    page.wait_for_timeout(700)
    page.evaluate("ensure('plan'); go('u-home')")
    before = page.evaluate("({ places: S.places.length, sents: S.sents.length, id: S.trip.id })")

    # --- 수정 화면에 두 버튼이 있다 ---
    page.evaluate("navFromMenu('u-edit')")
    page.wait_for_timeout(250)
    has = page.evaluate("({ save: !!document.querySelector('[data-act=\"save-trip\"]'), regen: !!document.querySelector('[data-act=\"save-trip-regen\"]') })")
    check("수정 화면에 저장·새로 만들기 버튼", has["save"] and has["regen"], str(has))

    # --- 날짜만 바꿔 기본 '저장' 은 전체 재생성하지 않는다(장소 유지) ---
    page.fill('[data-bind="studyStart"]', page.evaluate("Dt.add(S.trip.tripStart, -20)"))
    page.wait_for_timeout(120)
    page.click('[data-act="save-trip"]')
    page.wait_for_timeout(500)
    light = page.evaluate("({ scr: S.screen, status: S.trip.status, id: S.trip.id, places: S.places.length })")
    check("기본 저장은 계획만 다시 계산(장소·여행 그대로)",
          light["scr"] == "u-home" and light["status"] == "studying" and light["id"] == before["id"] and light["places"] == before["places"],
          str(light))
    check("기본 저장 경로에서는 /generate 를 부르지 않는다", len(gens["urls"]) == 0, str(gens["urls"]))

    # --- '보고서·문장까지 새로 만들기' → 확인 → 보고서 생성부터 다시 ---
    page.evaluate("navFromMenu('u-edit')")
    page.wait_for_timeout(250)
    page.click('[data-act="save-trip-regen"]')
    page.wait_for_timeout(200)
    check("재생성은 먼저 확인 창을 띄운다", page.evaluate("!!S.modal") and "새로 만들" in page.locator(".modal").inner_text())
    page.click('[data-act="modal-ok"]')
    page.wait_for_timeout(600)
    entered = page.evaluate("({ scr: S.screen, status: S.trip.status })")
    check("확정하면 보고서 생성 흐름으로 간다", entered["status"].startswith("report_") or entered["scr"] == "u-gen", str(entered))

    # --- 흐름 완주: 보고서 → 장소 확정 → 방문 순서 → 문장 생성 ---
    page.wait_for_function("() => S.trip && S.trip.status === 'report_done'", timeout=40000)
    page.click('[data-act="confirm-places"]')
    page.wait_for_timeout(200)
    page.click('[data-act="modal-ok"]')
    page.wait_for_function("() => S.trip && S.trip.status === 'studying'", timeout=60000)
    after = page.evaluate("({ scr: S.screen, plan: !!S.plan, ai: S.sents.some(s => s.sample || s.ai), places: S.places.length, study: S.trip.studyStart })")
    check("문장·일정표가 다시 만들어진다(홈/방문순서 도달)", after["plan"] and after["ai"], str(after))
    check("보고서·문장 재생성으로 /generate 를 부른다", len(gens["urls"]) >= 1, str(gens["urls"]))
    check("새 학습 시작일이 저장된다", after["study"] == page.evaluate("Dt.add(S.trip.tripStart, -20)"), after["study"])

    check("자바스크립트 오류 없음", not errors, str(errors[:3]))
    b.close()

bad = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(bad)}/{len(results)} 통과")
if bad:
    print("실패: " + ", ".join(bad))
sys.exit(1 if bad else 0)
