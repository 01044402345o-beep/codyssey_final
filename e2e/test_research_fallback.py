"""보고서 화면 — 장소 대체 체인의 화면 폴백 E2E (/research 는 Playwright 가짜).

도쿄: 대체 소스(Wikidata) 장소 + 소스 장애로 지난 결과(stale). 나라: 장소 0곳(소스 장애).
확인: 이유별 안내(예시로 안 채움) · 0곳 도시에 도시 브리프 + '다시 조사하기' + '장소 직접 추가'(검증·중복·선택) ·
provider 별 출처 이름·라이선스 · stale 안내 · 직접 추가한 장소로 방문 순서까지 · 다시 조사는 /research 를 다시 부름 · 넘침 없음.

    cd backend && uvicorn app.main:app --port 8768
    python ../e2e/test_research_fallback.py http://localhost:8768
"""
import json
import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8768"
results = []


def check(name, cond, extra=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))


def wd_place(i, name, kind="attraction"):
    return {"id": f"wd:JP_1850147:Q{i}", "name": name, "kind": kind, "lat": 35.68, "lon": 139.75, "area": "",
            "desc_en": f"{name} is a landmark.", "provider": "wikidata", "wikidata": f"Q{i}",
            "sources": [{"provider": "wikidata", "url": f"https://www.wikidata.org/wiki/Q{i}", "title": name, "license": "CC0"},
                        {"provider": "wikipedia", "url": f"https://en.wikipedia.org/wiki/X{i}", "title": name, "license": "CC BY-SA 4.0"}]}


REPORT = {
    "schema": "research.v1", "status": "done", "quality": "reduced",
    "countries": {"JP": {"iso2": "JP", "currency": {"code": "JPY"}, "emergency": ["110"], "plugs": [], "voltage": "",
                         "driving_side": "left", "languages": [], "advisory": None}},
    "cities": [
        {"key": "JP_1850147", "idx": 0, "name": "Tokyo", "iso2": "JP", "resolved": True, "status": "ok",
         "place_status": "ok", "none_reason": "", "stale": True,
         "wikivoyage": {"title": "", "url": ""},
         "places": [wd_place(1, "Sensō-ji"), wd_place(2, "Meiji Shrine"), wd_place(3, "Ueno Park"), wd_place(4, "Tokyo Tower"),
                    wd_place(5, "Sushi Dai", "restaurant"), wd_place(6, "Blue Bottle", "cafe"), wd_place(7, "Afuri", "restaurant")],
         "practical": [], "climate": None, "days": [], "sources": []},
        {"key": "JP_1855612", "idx": 1, "name": "Nara", "iso2": "JP", "resolved": True, "status": "empty",
         "place_status": "none", "none_reason": "outage", "stale": False,
         "wikivoyage": {"title": "", "url": ""}, "places": [], "practical": [], "climate": None, "days": [], "sources": []},
    ],
    "attributions": [{"provider": "wikidata", "text": "Wikidata (CC0)"}, {"provider": "wikipedia", "text": "Wikipedia contributors (CC BY-SA 4.0)"}],
}
COUNTRIES = [{"iso2": "JP", "name": "Japan", "ko": "일본", "capital": "Tokyo", "population": 1, "continent": "AS"}]
BRIEF = {"ok": True, "confidence": "verified", "city": "나라", "gaps": [],
         "sections": [{"kind": "overview", "title": "도시 소개", "text": "나라는 일본 나라현의 도시이다.", "source": "wikipedia:ko",
                       "url": "https://ko.wikipedia.org/wiki/나라시"}],
         "attribution": "위키백과 CC BY-SA 4.0"}
seen = {"post": 0}
brief_calls = []


def research_route(route):
    if route.request.method == "POST":
        seen["post"] += 1
        return route.fulfill(status=200, content_type="application/json",
                             body=json.dumps({"status": "done", "report": REPORT, "cached": True}, ensure_ascii=False))
    route.fulfill(status=404, content_type="application/json", body="{}")


def brief_route(route):
    brief_calls.append(route.request.url)
    route.fulfill(status=200, content_type="application/json", body=json.dumps(BRIEF, ensure_ascii=False))


with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 390, "height": 844})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.route("https://*.wikipedia.org/**", lambda r: r.abort())
    page.route("https://www.wikidata.org/**", lambda r: r.abort())
    page.route("**/geo/countries", lambda r: r.fulfill(status=200, content_type="application/json",
                                                     body=json.dumps({"countries": COUNTRIES, "attribution": "GeoNames"})))
    page.route("**/generate", lambda r: r.fulfill(status=503, content_type="application/json", body='{"detail":"busy"}'))
    page.route("**/city-brief**", brief_route)
    page.route("**/research**", research_route)
    page.goto(BASE + "/?demo=1", wait_until="domcontentloaded")
    page.wait_for_timeout(800)
    page.evaluate("""() => { S.user = DEMO_USER;
      const s = Dt.add(S.today, 50), m = Dt.add(S.today, 53), e = Dt.add(S.today, 55);
      createTrip({ countries: ['일본'], country: '일본', cities: [{ name: '도쿄', gid: 1850147, ci: 0, start: s, end: m },
                                                                 { name: '나라', gid: 1855612, ci: 0, start: m, end: e }],
                   studyStart: Dt.add(S.today, 5) });
      request('report'); }""")
    page.wait_for_function("() => S.screen === 'u-report'", timeout=30000)
    page.wait_for_timeout(300)

    check("조사 모드(한 도시가 0곳이어도 여행 전체는 조사 결과)", page.evaluate("S.reportMode") == "research")
    text = page.inner_text(".app")
    check("도쿄: 소스 장애로 지난 결과 안내", "지난번에 조사한 장소" in text, text[:300])
    card = page.locator(".place", has_text="Sensō-ji").first.inner_text()
    check("도쿄: 대체 소스 출처 이름·라이선스(Wikidata·Wikipedia)", "Wikidata · Sensō-ji" in card and "Wikipedia · Sensō-ji" in card
          and "Wikidata (CC0)" in card and "Wikipedia (CC BY-SA 4.0)" in card, card)
    check("도쿄: 직접 추가 칸은 없다(장소가 있는 도시)", page.locator(".add-place").count() == 0)
    check("출처 표기에 대체 소스", "Wikidata (CC0)" in page.inner_text(".rinfo-credits"))

    page.locator(".city-tabs button", has_text="나라").click()
    page.wait_for_timeout(300)
    text = page.inner_text(".app")
    check("나라: 소스 장애 안내(예시로 채우지 않음)", "자료 서버가 지금 응답하지 않아" in text and "미리 준비한 예시 데이터" not in text, text[:400])
    check("나라: 예시 장소 0곳", page.evaluate("S.places.filter(p => p.city === '나라').length") == 0)
    page.wait_for_function("() => document.querySelector('.brief-card:not(.loading)')", timeout=10000)
    check("나라: 도시 브리프 카드(백업 경로)", "나라는 일본 나라현의 도시" in page.inner_text(".brief-card") and len(brief_calls) == 1)
    check("나라: 다시 조사하기 버튼", page.locator("[data-act=research-retry]").count() == 1)

    page.fill("#add-place-name", "  Tōdai-ji  ")
    page.select_option("#add-place-kind", "attraction")
    page.click("[data-act=add-place]")
    page.wait_for_timeout(200)
    added = page.evaluate("S.places.filter(p => p.city === '나라').map(p => [p.name, p.kind, p.selected, p.attribution, p.research])")
    check("직접 추가: 이름 정리·종류·선택됨·출처 '직접 추가'", added == [["Tōdai-ji", "attraction", True, "직접 추가", True]], str(added))
    check("직접 추가한 장소 카드가 그려진다", "직접 추가" in page.locator(".place", has_text="Tōdai-ji").first.inner_text())
    page.fill("#add-place-name", "tōdai-ji")
    page.click("[data-act=add-place]")
    page.fill("#add-place-name", "<b>x</b>")
    page.click("[data-act=add-place]")
    page.fill("#add-place-name", "Kakinoha Sushi")
    page.select_option("#add-place-kind", "restaurant")
    page.click("[data-act=add-place]")
    names = page.evaluate("S.places.filter(p => p.city === '나라').map(p => p.name)")
    check("중복·위험한 이름은 막고 정상 이름은 추가", names == ["Tōdai-ji", "Kakinoha Sushi"], str(names))
    for w in (320, 390):
        page.set_viewport_size({"width": w, "height": 800}); page.wait_for_timeout(150)
        check(f"{w}px: 가로 넘침 없음", page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"))

    before = seen["post"]
    page.click("[data-act=research-retry]")
    page.wait_for_function("() => S.screen === 'u-report'", timeout=30000)
    page.wait_for_timeout(300)
    check("다시 조사하기 → /research 를 다시 부른다", seen["post"] == before + 1, f"{before} → {seen['post']}")

    page.locator(".city-tabs button", has_text="나라").click()
    page.fill("#add-place-name", "Nara Park")
    page.click("[data-act=add-place]")
    page.evaluate("() => { S.modal = null; S.trip.status = 'route_requested'; request('route'); }")
    page.wait_for_function("() => S.screen === 'u-route'", timeout=40000)
    nara_ids = page.evaluate("S.places.filter(p => p.city === '나라' && p.selected).map(p => p.id)")
    check("직접 추가한 장소로 방문 순서까지", bool(nara_ids) and page.evaluate(
        "ids => S.days.some(d => d.placeIds.some(id => ids.includes(id)))", nara_ids), str(nara_ids))
    check("JS 오류 없음", not errors, "; ".join(errors[:3]))
    b.close()

print(f"{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
