#!/usr/bin/env python3
"""장소 직접 추가 · 장소 생성 하루 한도(11/05 사용자 지시).

  A 장소 생성(POST /research)이 하루 한도를 넘으면(429) — 예시·다른 소스로 채우지 않고
    '하루에 장소 검색을 할 수 있는 횟수를 초과했어요' 안내와 '대신 직접 입력하기' 단추
  B 직접 추가 카드는 빈칸(이름·종류)을 다 채우면 저절로 찾는다(누를 단추 없음). 찾는 동안 장소를 확정할 수 없다
  C 찾으면 확인 창: 사진(서버 /place-photo 를 거침)·이름·주소. '맞아요' → 찾은 이름·주소로 추가(확인 표시)
  D '아니에요' → 다시 찾거나 '이름만 추가'(주소 없음)
  E 확정 → 문장 생성 요청(/generate)에 확인한 주소만 실린다
"""
import json
import sys
from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8899"
fails = []
check_calls, gen_bodies, photo_calls = [], [], []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ((" — " + str(extra)) if (extra and not cond) else ""))
    if not cond:
        fails.append(name)


COUNTRIES = [{"iso2": "JP", "name": "Japan", "ko": "일본", "capital": "Tokyo", "population": 126000000, "continent": "AS"}]
PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                    "1f15c4890000000d4944415478da63f8ffff3f0005fe02fea7d6a4f00000000049454e44ae426082")


def research_route(route):
    route.fulfill(status=429, content_type="application/json", body=json.dumps(
        {"status": "quota", "code": "place_search_quota", "limit": 3, "used": 3, "message": "하루에 장소 검색을 할 수 있는 횟수를 초과했어요"},
        ensure_ascii=False))


def check_route(route):
    body = json.loads(route.request.post_data or "{}")
    check_calls.append(body)
    name = (body.get("place") or {}).get("name", "").lower()
    if name.startswith("tōdai") or name.startswith("todai"):
        out = {"status": "found", "name": "Tōdai-ji Temple", "distance_km": 2.4, "lat": 34.689, "lon": 135.8398,
               "address": "406-1 Zoshicho, Nara",
               "image": {"src": "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/Todaiji.jpg/500px-Todaiji.jpg",
                         "page": "https://commons.wikimedia.org/wiki/File:Todaiji.jpg", "credit": "Wikimedia Commons",
                      "author": "Kim", "license": "CC BY-SA 4.0", "license_url": "https://creativecommons.org/licenses/by-sa/4.0"},
               "source": {"provider": "wikidata", "url": "https://www.wikidata.org/wiki/Q186148", "title": "Tōdai-ji Temple"}}
    elif name.startswith("kasuga"):
        out = {"status": "found", "name": "Kasuga Taisha", "distance_km": 3.1, "lat": 34.68, "lon": 135.84, "address": "160 Kasuganocho, Nara",
               "image": {"provider": "google", "src": "https://lh3.googleusercontent.com/place-photos/KasugaABC=s500",
                         "authors": [{"name": "Kim Photo", "uri": "https://maps.google.com/maps/contrib/9"}]},
               "source": {"provider": "wikidata", "url": "https://www.wikidata.org/wiki/Q1137285", "title": "Kasuga Taisha"}}
    else:
        out = {"status": "not_found"}
    route.fulfill(status=200, content_type="application/json", body=json.dumps(out, ensure_ascii=False))


def gen_route(route):
    gen_bodies.append(json.loads(route.request.post_data or "{}"))
    route.fulfill(status=503, content_type="application/json", body='{"detail":"busy"}')


def photo_route(route):
    photo_calls.append(route.request.url)
    route.fulfill(status=200, content_type="image/png", body=PNG)


with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 390, "height": 844})
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.route("**/geo/countries", lambda r: r.fulfill(status=200, content_type="application/json",
                                                     body=json.dumps({"countries": COUNTRIES, "attribution": "GeoNames"})))
    pg.route("**/research**", research_route)
    pg.route("**/itinerary**", lambda r: r.fulfill(status=500, body="should not be called"))
    pg.route("**/city-brief**", lambda r: r.fulfill(status=503, body="{}"))
    pg.route("**/place-check", lambda r: (pg.wait_for_timeout(0), check_route(r)))
    pg.route("**/place-photo**", photo_route)
    google_calls = []
    pg.route("https://lh3.googleusercontent.com/**", lambda r: (google_calls.append(r.request.url), r.fulfill(status=200, content_type="image/png", body=PNG)))
    pg.route("**/generate", gen_route)
    pg.goto(BASE + "/?demo=1&gate=off", wait_until="domcontentloaded"); pg.wait_for_timeout(800)
    pg.evaluate("""() => { S.user = DEMO_USER;
      const s = Dt.add(S.today, 50), e = Dt.add(S.today, 53);
      createTrip({ countries: ['일본'], country: '일본', cities: [{ name: '나라', gid: 1855612, ci: 0, start: s, end: e }],
                   studyStart: Dt.add(S.today, 5) });
      request('report'); }""")
    pg.wait_for_function("() => S.screen === 'u-report'", timeout=30000)
    pg.wait_for_timeout(300)

    # ── A: 한도 초과 ──
    text = pg.inner_text(".app")
    check("A1 한도 초과 안내", "하루에 장소 검색을 할 수 있는 횟수를 초과했어요" in text, text[:200])
    check("A2 '대신 직접 입력하기' 단추", pg.locator("[data-act=place-manual]").count() == 1)
    check("A3 예시·다른 소스로 채우지 않는다(장소 0곳)", pg.evaluate("S.places.length") == 0 and "미리 준비한 예시" not in text)
    pg.click("[data-act=place-manual]"); pg.wait_for_timeout(300)
    check("A4 누르면 직접 입력 칸으로(포커스)", pg.evaluate("document.activeElement && document.activeElement.id") == "add-place-name")

    # ── B: 빈칸을 다 채우면 저절로 찾는다 · 찾는 동안 확정 막기 ──
    pg.fill("#add-place-name", "Todai-ji")
    pg.wait_for_timeout(1000)
    check("B1 종류 기본값은 관광지 — 이름만 적어도 찾기 시작", pg.input_value("#add-place-kind") == "attraction")
    pg.wait_for_function("() => /찾고 있어요/.test(document.getElementById('add-place-st').innerText) || (S.modal && /이 장소가 맞나요/.test(S.modal.title))", timeout=8000)
    # 찾는 동안 확정 막기 — 느린 응답으로 한 번 더(이름을 비웠다가 다시 적으면 새 조회가 시작된다)
    slow = {"go": False}
    pg.unroute("**/place-check")
    pg.route("**/place-check", lambda r: (pg.wait_for_timeout(900), check_route(r)))
    pg.fill("#add-place-name", ""); pg.wait_for_timeout(150)
    pg.fill("#add-place-name", "Todai-ji")
    pg.wait_for_function("() => /찾고 있어요/.test(document.getElementById('add-place-st').innerText)", timeout=8000)
    check("B2 찾는 동안 안내", "끝나면 장소를 확정할 수 있어요" in pg.inner_text("#add-place-st"))
    check("B3 찾는 동안 확정 단추가 꺼진다", pg.evaluate("document.querySelector('[data-act=confirm-places]').disabled"))
    check("B4 입력 칸 포커스·글자가 그대로", pg.input_value("#add-place-name") == "Todai-ji")

    # ── C: 확인 창 ──
    pg.wait_for_function("() => S.modal && /이 장소가 맞나요/.test(S.modal.title)", timeout=10000)
    modal = pg.inner_text(".modal")
    check("C1b 사진 표시 요건: 저작자·라이선스·원본 링크", "© Kim" in modal and "CC BY-SA 4.0" in modal and "원본" in modal, modal[:300])
    check("C1 확인 창: 이름·주소·출처", "Tōdai-ji Temple" in modal and "406-1 Zoshicho, Nara" in modal and "Wikidata" in modal, modal[:240])
    src = pg.evaluate("(() => { const i = document.querySelector('.modal .pc-photo img'); return i ? i.getAttribute('src') : ''; })()")
    check("C2 사진은 서버(/place-photo)를 거친다", src.startswith("/place-photo?src=https%3A%2F%2Fupload.wikimedia.org") or "/place-photo?src=https%3A%2F%2Fupload.wikimedia.org" in src, src)
    pg.wait_for_timeout(300)
    check("C3 사진이 실제로 그려진다", pg.evaluate("(() => { const i = document.querySelector('.modal .pc-photo img'); return !!i && i.complete && i.naturalWidth > 0; })()"))
    check("C4 장소 확인 요청에 사용자 정보 없음", "uid" not in json.dumps(check_calls[-1]) and check_calls[-1].get("place") == {"name": "Todai-ji", "kind": "attraction"}, str(check_calls[-1]))
    pg.click("[data-act=modal-ok]"); pg.wait_for_timeout(300)
    added = pg.evaluate("S.places.map(p => [p.name, p.kind, p.selected, p.verified, p.address, p.user])")
    check("C5 '맞아요' → 찾은 이름·주소로 추가(확인 표시)", added == [["Tōdai-ji Temple", "attraction", True, True, "406-1 Zoshicho, Nara", True]], str(added))
    card = pg.locator(".place", has_text="Tōdai-ji Temple").first.inner_text()
    check("C6 카드에 주소·출처·확인", "406-1 Zoshicho" in card and "사용자 확인" in card, card)
    check("C7 입력 칸이 비워진다", pg.input_value("#add-place-name") == "" and pg.input_value("#add-place-kind") == "")

    # ── D: '아니에요' → 이름만 추가 ──
    pg.fill("#add-place-name", "Kasuga")
    pg.select_option("#add-place-kind", "attraction")
    pg.wait_for_function("() => S.modal && /이 장소가 맞나요/.test(S.modal.title)", timeout=10000)
    gm = pg.inner_text(".modal")
    gsrc = pg.evaluate("(() => { const i = document.querySelector('.modal .pc-photo img'); return i ? i.getAttribute('src') : ''; })()")
    check("D1 공용 사진이 없으면 Google 사진 — 우리 서버를 거치지 않고 바로", gsrc == "https://lh3.googleusercontent.com/place-photos/KasugaABC=s500", gsrc)
    pg.wait_for_timeout(300)
    check("D1b Google 사진이 실제로 그려진다", bool(google_calls) and pg.evaluate(
        "(() => { const i = document.querySelector('.modal .pc-photo img'); return !!i && i.complete && i.naturalWidth > 0; })()"))
    check("D1c 찍은 사람·Google 지도 표시", "Kim Photo" in gm and "Google 지도" in gm, gm[:200])
    pg.click("[data-act=modal-cancel]"); pg.wait_for_timeout(300)
    check("D2 '아니에요' → 다시 찾거나 이름만 추가 안내", "아니라고 하셨어요" in pg.inner_text("#add-place-st")
          and pg.locator("[data-act=add-place-plain]").count() == 1)
    pg.click("[data-act=add-place-plain]"); pg.wait_for_timeout(300)
    check("D3 이름만 추가 — 적은 이름·주소 없음·확인 표시 없음", pg.evaluate(
        "S.places.some(p => p.name === 'Kasuga' && p.user && !p.verified && !p.address)"))
    pg.fill("#add-place-name", "Tōdai-ji Temple"); pg.select_option("#add-place-kind", "attraction"); pg.wait_for_timeout(1200)
    check("D4 이미 있는 장소는 다시 찾지 않는다", not pg.evaluate("!!S.modal"))

    # ── E: 확정 → 문장 생성 요청에 확인한 주소만 ──
    pg.evaluate("() => { S.modal = null; S.trip.status = 'route_requested'; request('route'); }")
    pg.wait_for_function("() => window.__gen || true", timeout=1000)
    for _ in range(80):
        if gen_bodies:
            break
        pg.wait_for_timeout(250)
    places = [pl for body in gen_bodies for c in (body.get("cities") or [body]) for pl in (c.get("places") or [])]
    todai = [pl for pl in places if pl.get("name") == "Tōdai-ji Temple"]
    kasuga = [pl for pl in places if pl.get("name") == "Kasuga"]
    check("E1 문장 생성 요청에 확인한 주소가 실린다", bool(todai) and todai[0].get("address") == "406-1 Zoshicho, Nara" and todai[0].get("user") is True,
          json.dumps(places, ensure_ascii=False)[:300])
    check("E2 이름만 추가한 장소에는 주소가 없다", bool(kasuga) and "address" not in kasuga[0], str(kasuga))
    for w in (320, 390):
        pg.set_viewport_size({"width": w, "height": 800}); pg.wait_for_timeout(150)
    check("JS 오류 없음", not errs, errs[:2])
    b.close()

print("---")
print("ALL PASS" if not fails else "FAILED: " + ", ".join(fails))
sys.exit(1 if fails else 0)
