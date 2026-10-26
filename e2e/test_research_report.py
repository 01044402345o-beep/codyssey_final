"""보고서 화면 ← 도시 조사(POST /research → GET /research/{id}) 연결 E2E.

/research 는 Playwright 로 가짜를 준다(CI 서버는 조사 플래그가 꺼져 있고 외부로 나가지 않는다).
확인: 요청 본문(나라 ISO2·도시 gid·날짜·장소 수, 사용자 정보 없음) · 폴링 · 조사 장소 카드(영어 원문·출처·홈페이지) ·
'현지 정보' 카드(날씨·통화·긴급번호·전기·권고·교통) · 출처 표기 · 장소 확정 → 방문 순서까지 · 꺼짐이면 예시 그대로 · 좁은 화면 넘침 없음.

    cd backend && uvicorn app.main:app --port 8768
    python ../e2e/test_research_report.py http://localhost:8768
"""
import json
import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8768"
results = []


def check(name, cond, extra=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))


def place(i, name, kind, area="Chiyoda"):
    return {"id": f"wv:JP_1850147:{i}", "name": name, "kind": kind, "lat": 35.68, "lon": 139.75, "area": area,
            "desc_en": f"{name} is worth a visit.", "homepage": "https://example.jp/" if i == 0 else "javascript:alert(1)",
            "sources": [{"provider": "wikivoyage", "url": "https://en.wikivoyage.org/wiki/Tokyo/Chiyoda", "title": "Tokyo/Chiyoda",
                         "license": "CC BY-SA 4.0"}]}


REPORT = {
    "schema": "research.v1", "status": "done", "quality": "full",
    "countries": {"JP": {"iso2": "JP", "currency": {"code": "JPY", "krw_per_unit": 8.43, "as_of": "2026-10-25"},
                         "emergency": ["110", "119"], "plugs": ["Type A"], "voltage": "100", "driving_side": "left",
                         "languages": ["Japanese"],
                         "advisory": {"updated_at": "2026-10-19", "basis": "UK FCDO",
                                      "parts": [{"slug": "safety-and-security", "title": "Safety and security",
                                                 "url": "https://www.gov.uk/foreign-travel-advice/japan/safety-and-security", "text_en": "Low crime."}]}}},
    "cities": [{"key": "JP_1850147", "idx": 0, "name": "Tokyo", "iso2": "JP", "resolved": True, "status": "ok",
                "wikivoyage": {"title": "Tokyo", "url": "https://en.wikivoyage.org/wiki/Tokyo"},
                "places": [place(0, "Imperial Palace", "attraction"), place(1, "Tokyo Tower", "attraction", ""),
                           place(2, "Senso-ji", "attraction"), place(3, "Meiji Shrine", "attraction"),
                           place(4, "Ueno Park", "attraction"), place(5, "Sushi Dai", "restaurant"),
                           place(6, "Blue Bottle Coffee", "cafe"), place(7, "Ichiran Ramen", "restaurant"),
                           place(8, "Tsukiji Outer Market", "restaurant"), place(9, "Afuri", "restaurant")]
                + [place(10 + i, f"Sight {i}", "attraction") for i in range(4)]
                + [place(20 + i, f"Diner {i}", "restaurant") for i in range(4)],
                "practical": [{"topic": "transport_airport", "text_en": "Narita and Haneda serve Tokyo.",
                               "source": {"provider": "wikivoyage", "url": "https://en.wikivoyage.org/wiki/Tokyo#Get_in"}},
                              {"topic": "tipping", "text_en": "Tipping is not customary.",
                               "source": {"provider": "wikivoyage", "url": "https://en.wikivoyage.org/wiki/Tokyo"}}],
                "climate": {"kind": "normals", "window": "03-20~03-23 (2022–2026)", "tmax_avg": 14.6, "tmin_avg": 4.4,
                            "precip_mm_avg": 3.0, "wet_days_pct": 40, "days": 20},
                "days": [{"date": "D0", "role": "arrival", "topics": ["transport_airport", "transport_local"]}],
                "sources": []}],
    "attributions": [{"provider": "wikivoyage", "text": "Wikivoyage contributors (CC BY-SA 4.0)"},
                     {"provider": "openmeteo", "text": "Weather data by Open-Meteo.com (CC BY 4.0)"}],
}
# LLM 추출(PR3)이 검증을 통과한 항목: 첫 장소의 한국어 요약·이유, 공항 주제의 한국어 요약 + 영어 원문 인용
REPORT["cities"][0]["places"][0].update(summary_ko="일왕이 사는 궁과 넓은 정원이에요.", why_ko="첫날 가볍게 둘러보기 좋아요", rank=1,
                                         vocab=[{"en": "East Gardens", "kind": "feature", "src": "lexicon"},
                                                {"en": "palace", "kind": "type", "src": "lexicon"}])
# 장소 어휘(PR-V1): 맛집에 대표 음식 — 슬롯 문장(PR-V2)이 쓴다
REPORT["cities"][0]["places"][5].update(vocab=[{"en": "sushi breakfast", "kind": "dish", "src": "pattern"}])
REPORT["cities"][0]["practical"][0].update(summary_ko="나리타와 하네다 두 공항이 도쿄로 이어져요.",
                                           quote_en="Narita and Haneda serve Tokyo.", situations=["transfer_route"])
COUNTRIES = [{"iso2": "JP", "name": "Japan", "ko": "일본", "capital": "Tokyo", "population": 1, "continent": "AS"}]
seen = {"post": [], "get": 0}


def research_route(route):
    req = route.request
    if req.method == "POST":
        seen["post"].append(json.loads(req.post_data or "{}"))
        body = {"status": "running", "job_id": "abcdefghijklmnop1234"}
        return route.fulfill(status=202, content_type="application/json", body=json.dumps(body))
    seen["get"] += 1
    rep = json.loads(json.dumps(REPORT))
    start = seen["post"][-1]["cities"][0]["start"] if seen["post"] else "2027-01-01"
    rep["cities"][0]["days"][0]["date"] = start
    body = ({"status": "running", "progress": [{"who": "도쿄", "step": "guide", "state": "running"}]} if seen["get"] < 2
            else {"status": "done", "progress": [], "report": rep})
    route.fulfill(status=200, content_type="application/json", body=json.dumps(body, ensure_ascii=False))


BRIEF = {"ok": True, "confidence": "verified", "city": "도쿄", "gaps": [],
         "sections": [{"kind": "overview", "title": "도시 소개", "text": "도쿄는 일본의 수도이다.", "source": "wikipedia:ko",
                       "url": "https://ko.wikipedia.org/wiki/도쿄"},
                      {"kind": "get_in", "title": "Get in", "text": "By plane Narita and Haneda.", "source": "wikivoyage:en",
                       "url": "https://en.wikivoyage.org/wiki/Tokyo"}],
         "attribution": "위키백과·위키여행 CC BY-SA 4.0, 위키데이터 CC0"}
brief_calls = []
gen_bodies = []


def brief_route(route):
    brief_calls.append(route.request.url)
    route.fulfill(status=200, content_type="application/json", body=json.dumps(BRIEF, ensure_ascii=False))


def setup(page, research=True):
    page.route("**/geo/countries", lambda r: r.fulfill(status=200, content_type="application/json",
                                                     body=json.dumps({"countries": COUNTRIES, "attribution": "GeoNames"})))
    gen_bodies.clear()

    def gen_route(r):
        gen_bodies.append(json.loads(r.request.post_data or "{}"))
        r.fulfill(status=503, content_type="application/json", body='{"detail":"busy"}')
    page.route("**/generate", gen_route)
    brief_calls.clear()
    page.route("**/city-brief**", brief_route)
    if research:
        page.route("**/research**", research_route)
    else:
        page.route("**/research**", lambda r: r.fulfill(status=200, content_type="application/json",
                                                     body='{"status":"unavailable","reason":"research_disabled"}'))
    page.goto(BASE + "/?demo=1", wait_until="domcontentloaded")
    page.wait_for_timeout(800)
    page.evaluate("""() => { S.user = DEMO_USER;
      const s = Dt.add(S.today, 50), e = Dt.add(S.today, 53);
      createTrip({ countries: ['일본'], country: '일본', cities: [{ name: '도쿄', gid: 1850147, ci: 0, start: s, end: e }],
                   studyStart: Dt.add(S.today, 5) });
      // 연구 결과가 늦게 와도 기다리게: 가짜 진행 단계는 그대로 돈다
      request('report'); }""")
    page.wait_for_function("() => S.screen === 'u-report'", timeout=30000)
    page.wait_for_timeout(300)


with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 390, "height": 844})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    # 위키보이지 등 외부 링크는 테스트에서 실제로 나가지 않게 막는다
    page.route("https://en.wikivoyage.org/**", lambda r: r.abort())
    setup(page)

    body = seen["post"][0] if seen["post"] else {}
    check("조사 요청: 나라 ISO2·도시 gid·날짜·장소 수", body.get("countries") == [{"name": "일본", "iso2": "JP"}]
          and body.get("cities", [{}])[0].get("gid") == 1850147 and body["cities"][0].get("attr", 0) >= 1, json.dumps(body, ensure_ascii=False))
    check("조사 요청에 사용자 정보가 없다", "uid" not in json.dumps(body) and "email" not in json.dumps(body))
    check("진행을 폴링해 결과를 받는다", seen["get"] >= 2, str(seen["get"]))
    check("보고서가 조사 모드", page.evaluate("S.reportMode") == "research", page.evaluate("S.reportMode"))
    text = page.inner_text(".app")
    check("조사 안내(위키보이지·실제로 조사)", "실제로 조사한 장소" in text and "18곳 중" in text)
    check("예시 고지는 없다", "미리 준비한 예시 데이터" not in text)
    names = page.evaluate("S.places.map(p => p.name)")
    check("조사 장소가 장소 목록이 된다", "Imperial Palace" in names and "Sushi Dai" in names, str(names))
    check("기본 선택 = 일정이 정한 장소 수, 나머지는 후보", page.evaluate("S.places.filter(p => p.selected).length") == page.evaluate("S.reportMeta['도쿄'].base")
          and page.evaluate("S.places.some(p => p.isCandidate)"))
    card = page.locator(".place", has_text="Imperial Palace").first.inner_text()
    check("장소 카드: 영어 원문 설명·출처·홈페이지·라이선스", "worth a visit" in card and "Wikivoyage · Tokyo/Chiyoda" in card
          and "홈페이지" in card and "CC BY-SA" in card, card)
    check("장소 카드: 한국어 요약·추천 이유가 영어 원문 위에", card.index("일왕이 사는 궁") < card.index("worth a visit")
          and "첫날 가볍게 둘러보기 좋아요" in card, card)
    tower = page.locator(".place", has_text="Tokyo Tower").first
    check("요약이 없는 장소는 영어 원문만(빈 한국어 줄 없음)", tower.locator(".why").count() == 0
          and tower.locator(".desc.en-sub").count() == 0 and "worth a visit" in tower.inner_text())
    check("위험한 홈페이지 링크는 그리지 않는다", page.locator('a[href^="javascript"]').count() == 0)
    info = page.inner_text(".rinfo")
    check("현지 정보: 날씨(평년값)·통화 원화 환율·긴급 전화·전기", "평년값" in info and "14.6" in info and "8.43원" in info
          and "110" in info and "100V" in info, info[:300])
    check("현지 정보: 영국 권고는 없고 외교부 해외안전여행 안내·좌측 통행·도착일 교통 안내", "FCDO" not in info
          and "외교부 해외안전여행" in info and "좌측" in info and "도착일" in info, info[:400])
    page.locator(".rinfo-topic summary", has_text="공항").click()
    air = page.locator(".rinfo-topic[open]").first
    check("실용 정보: 한국어 요약 + 근거 영어 원문 인용", air.locator("p").first.inner_text() == "나리타와 하네다 두 공항이 도쿄로 이어져요."
          and air.locator("blockquote.rinfo-quote").inner_text() == "Narita and Haneda serve Tokyo.", air.inner_text())
    air.locator("summary").click()
    page.locator(".rinfo-topic summary", has_text="팁").click()
    check("실용 정보 주제를 펼치면 영어 원문", page.locator(".rinfo-topic[open] p").first.inner_text() == "Tipping is not customary.")
    check("출처 표기(위키보이지 CC BY-SA·Open-Meteo)", "Wikivoyage contributors (CC BY-SA 4.0)" in page.inner_text(".rinfo-credits")
          and "Open-Meteo" in page.inner_text(".rinfo-credits"))
    for w in (320, 390):
        page.set_viewport_size({"width": w, "height": 800}); page.wait_for_timeout(150)
        check(f"{w}px: 가로 넘침 없음", page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"))

    # 장소 확정 → 방문 순서(조사 장소의 area 가 문자열이라 placeByCode 가 돈다)
    page.evaluate("ACT['confirm-places'](); document.querySelector('.modal [data-act]') && 0")
    page.evaluate("() => { S.modal = null; S.trip.status = 'route_requested'; request('route'); }")
    page.wait_for_function("() => S.screen === 'u-route'", timeout=40000)
    check("조사 장소로 방문 순서·일정표가 만들어진다", page.evaluate("S.days.some(d => d.placeIds.length)") and page.evaluate("!!S.plan"))
    page.evaluate("runAi(genToken)")
    page.wait_for_function("() => true", timeout=1000)
    page.wait_for_timeout(1500)
    sents = page.evaluate("placeSentences(S.places.find(p => p.name === 'Imperial Palace'), 5).map(s => s.en)")
    check("장소 어휘 슬롯 문장: 볼거리·종류 어휘로 만든 문장이 범용 틀보다 먼저(PR-V2)",
          sents[:2] == ["Where can I see the East Gardens?", "Where is the entrance to the palace?"], str(sents))
    sushi = page.evaluate("placeSentences(S.places.find(p => p.name === 'Sushi Dai'), 3).map(s => s.en)")
    check("맛집 슬롯 문장: 대표 음식 어휘", "I'd like to try the sushi breakfast, please." in sushi, str(sushi))
    cats = sorted({b.get("category_id") for b in gen_bodies})
    check("관광지도 AI 문장 요청(관광지 계약)·조사 키 함께", "attraction" in cats and "restaurant" in cats, str(cats))
    check("문장 생성 요청에 도시 조사 키(research_key)가 실린다(PR5)",
          bool(gen_bodies) and all(b.get("research_key") == "JP_1850147" for b in gen_bodies)
          and all("user" not in pl for b in gen_bodies for pl in b.get("places", [])), str(gen_bodies)[:300])
    check("조사 모드에서는 백업 브리프를 부르지 않는다", not brief_calls and page.locator(".brief-card").count() == 0)
    check("JS 오류 없음", not errors, "; ".join(errors[:3]))

    # 서버 조사가 꺼져 있으면 예전처럼 예시 데이터
    p2 = b.new_page(viewport={"width": 390, "height": 844})
    e2 = []
    p2.on("pageerror", lambda e: e2.append(str(e)))
    setup(p2, research=False)
    check("조사 꺼짐: 예시 데이터로 돌아간다", p2.evaluate("S.reportMode") == "example" and "미리 준비한 예시 데이터" in p2.inner_text(".app"))
    check("조사 꺼짐: 현지 정보 카드 없음", p2.locator(".rinfo").count() == 0)
    p2.wait_for_selector(".brief-card:not(.loading)", timeout=10000)
    bc = p2.inner_text(".brief-card")
    check("백업 경로: 도시 브리프 카드(도시 소개·가는 법·출처 확인·라이선스)", "도쿄 알아두기" in bc and "도쿄는 일본의 수도" in bc
          and "가는 법" in bc and "출처 확인" in bc and "CC BY-SA" in bc, bc[:200])
    check("백업 경로: 나라·도시를 실어 /city-brief 를 한 번 부른다", len(brief_calls) == 1 and "city=%EB%8F%84%EC%BF%84" in brief_calls[0]
          and "country=%EC%9D%BC%EB%B3%B8" in brief_calls[0], str(brief_calls))
    p2.evaluate("render()"); p2.wait_for_timeout(200)
    check("백업 경로: 다시 그려도 다시 부르지 않는다(캐시)", len(brief_calls) == 1, str(len(brief_calls)))
    check("조사 꺼짐: JS 오류 없음", not e2, "; ".join(e2[:3]))
    b.close()

print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
