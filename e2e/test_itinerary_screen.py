"""오늘 날짜와 장소 보고서 연결.

해시로 연 보고서는 예시 고지를 유지하고 /itinerary 를 부르지 않는다.
preset 은 BASE_TODAY 축을 유지한다. 실제 장소 화면은 서버 응답을 접어 그린다.

    cd backend && uvicorn app.main:app --port 8768
    python ../e2e/test_itinerary_screen.py http://localhost:8768
"""
import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1]
results = []


def check(name, cond, extra=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""))


INIT = """
  window.__itin = 0;
  const orig = window.fetch.bind(window);
  window.fetch = (url, opt) => {
    if (String(url).includes('/itinerary')) window.__itin++;
    return orig(url, opt);
  };
"""

with sync_playwright() as p:
    b = p.chromium.launch()
    errors = []
    page = b.new_page(viewport={"width": 390, "height": 844})
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.add_init_script(INIT)
    page.goto(BASE + "/?demo=1", wait_until="domcontentloaded")
    page.wait_for_timeout(800)

    boot = page.evaluate("""() => {
      const n = new Date();
      const pad = v => String(v).padStart(2, '0');
      const local = n.getFullYear() + '-' + pad(n.getMonth() + 1) + '-' + pad(n.getDate());
      return { today: S.today, local, base: BASE_TODAY, study: S.draft.studyStart, trip: S.draft.cities[0].start };
    }""")
    check("첫 화면의 오늘은 로컬 달력일이다", boot["today"] == boot["local"], str(boot))
    check("첫 초안은 그 오늘에서 학습·출발을 잡는다",
          boot["study"] == page.evaluate("Dt.add(S.today, 9)") and boot["trip"] == page.evaluate("Dt.add(S.today, 49)"))

    page.goto(BASE + "/?demo=1&fresh=1#u-report", wait_until="domcontentloaded")
    page.wait_for_function("() => typeof S !== 'undefined' && S.screen === 'u-report'", timeout=15000)
    report = page.locator(".app").inner_text()
    check("해시 보고서는 예시 고지를 유지한다", "미리 준비한 예시 데이터" in report, page.evaluate("S.screen"))
    check("해시 보고서는 /itinerary 를 부르지 않는다", page.evaluate("window.__itin") == 0, str(page.evaluate("window.__itin")))

    page.evaluate("preset('default')")
    page.wait_for_timeout(300)
    preset = page.evaluate("({ today: S.today, expect: Dt.add(BASE_TODAY, 49), screen: S.screen, mode: S.reportMode })")
    check("preset 은 예시 달력으로 오늘을 되돌린다", preset["today"] == preset["expect"] and preset["screen"] == "u-route", str(preset))

    painted = page.evaluate("""() => {
      const cities = [{ name: '뉴욕', start: '2026-11-10', end: '2026-11-12' }];
      const places = [
        { provider_id: 'p1', name: 'Joe Pizza', attribution: 'Google Maps', fetched_at: '2026-10-16T01:02:03Z',
          source_url: 'https://maps.google.com/?cid=p1',
          data: { formatted_address: '7 Carmine St', primary_type: 'pizza_restaurant', business_status: 'OPERATIONAL' } },
        { provider_id: 'p2', name: 'Quiet Museum', attribution: 'Google Maps', fetched_at: '2026-10-16T01:02:03Z',
          source_url: 'https://maps.google.com/?cid=p2',
          data: { formatted_address: '1 Museum Mile', primary_type: 'museum', business_status: 'OPERATIONAL' } },
      ];
      const days = [{ day: 1, blocks: [
        { time_label: 'morning', place_id: 'p1', sentence_ko: '창가 자리 부탁해요.', why: 'pizza_restaurant · 7 Carmine St' },
        { time_label: 'afternoon', place_id: 'p2', sentence_ko: '', why: 'museum · 1 Museum Mile' },
      ] }];
      const folded = AI.foldItinerary(cities, [{ error: null, body: {
        status: 'verified', reason: '', places, days,
        queries: [{ included_type: 'cafe', status: 'unavailable', reason: 'http_429' }],
      } }], { '뉴욕': 2 });
      createTrip({ country: '미국', cities, studyStart: '2026-10-25' });
      S.today = '2026-10-25';
      S.reportMode = folded.mode;
      S.places = folded.places;
      S.reportMeta = folded.meta;
      S.itineraryBlocks = folded.blocksByCity;
      S.trip.status = 'report_done';
      go('u-report');
      const reportText = document.body.innerText;
      S.plan = null;
      ensure('plan');
      go('u-route');
      const routeText = document.body.innerText;
      const menuView = S.routeView;
      const dropped = S.places.find(p => p.providerId === 'p2');
      dropped.selected = false;
      S.days = AI.placeBlocksOnDays(R.buildDays(S.trip.cities), S.places, S.trip.cities, S.itineraryBlocks);
      go('u-route');
      const after = document.body.innerText;
      const empty = AI.foldItinerary(cities, [{ error: null, body: { status: 'unavailable', reason: 'no_verified_places', places: [], days: [] } }], { '뉴욕': 2 });
      createTrip({ country: '미국', cities, studyStart: '2026-10-25' });
      S.reportMode = empty.mode;
      S.places = empty.places;
      S.reportMeta = empty.meta;
      S.trip.status = 'report_done';
      go('u-report');
      return {
        mode: folded.mode,
        report: reportText,
        route: routeText,
        menuView,
        after,
        empty: document.body.innerText,
        calls: window.__itin,
      };
    }""")
    check("확인된 장소 화면에는 예시 고지가 없다", "미리 준비한 예시 데이터" not in painted["report"] and "Joe Pizza" in painted["report"], painted["mode"])
    check("장소 카드에 주소·출처·실패한 종류가 있다",
          "7 Carmine St" in painted["report"] and "Google Maps" in painted["report"] and "http_429" in painted["report"])
    check("장소 카드에 메뉴와 이유 문장을 넣지 않는다",
          "대표 메뉴" not in painted["report"] and "pizza_restaurant · 7 Carmine St" not in painted["report"])
    check("메뉴로 연 계획도 하루 블록을 유지한다", painted["menuView"] == "blocks", painted["menuView"])
    check("하루 블록은 한국어가 있을 때만 보여주고 경로 문구를 쓰지 않는다",
          "하루 블록" in painted["route"] and "오전" in painted["route"] and "창가 자리 부탁해요." in painted["route"]
          and "최적 경로" not in painted["route"] and "동선을 계산" not in painted["route"]
          and "pizza_restaurant · 7 Carmine St" not in painted["route"])
    check("선택을 끈 장소는 하루 블록에서 빠진다", "Quiet Museum" not in painted["after"] and "Joe Pizza" in painted["after"])
    check("확인된 장소가 없으면 예시 장소로 채우지 않는다",
          "확인된 장소가 없어요" in painted["empty"] and "미리 준비한 예시 데이터" not in painted["empty"] and "구시가지" not in painted["empty"])
    check("화면을 접는 동안 /itinerary 를 더 부르지 않는다", painted["calls"] == 0)
    check("자바스크립트 오류 없음", not errors, str(errors[:3]))
    b.close()

bad = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(bad)}/{len(results)} 통과")
if bad:
    print("실패: " + ", ".join(bad))
sys.exit(1 if bad else 0)
