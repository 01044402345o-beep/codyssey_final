"""홈(메인화면) 편의 기능 E2E — 새로고침 뒤 실제 여행 복원 · D-Day 카드 → 여행 설정 수정/저장 · 하단 로그아웃 카드.

온보딩(여행 입력 → 보고서 → 방문 순서 → 홈)까지 도달한 사용자가 겪는 것을 확인한다.
서버 왕복(계정 저장)은 tests/test_user_state.py, 계정별 키 분리는 test_account_storage.py 가 본다.

    cd backend && uvicorn app.main:app --port 8768
    python ../e2e/test_home_settings.py http://localhost:8768
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
    # 해시 없이 연다(실제 제품 경로) → 세션 복원이 켜져 새로고침 저장이 동작한다.
    page.goto(BASE + "/", wait_until="domcontentloaded")
    page.wait_for_timeout(500)
    # 로그인 뒤 홈까지 온 상태를 만든다.
    page.evaluate("S.user = DEMO_USER; ensure('plan'); go('u-home')")
    page.wait_for_timeout(300)

    check("홈 도달 · 여행과 계획이 있다", page.evaluate("!!S.trip && !!S.plan && S.screen === 'u-home'"), page.evaluate("S.screen"))

    # --- 홈 하단 로그아웃 카드 ---
    card = page.evaluate("""() => {
      const c = document.querySelector('.account-card');
      return {
        exists: !!c,
        logout: c ? !!c.querySelector('[data-act="logout-home"]') : false,
        pad: c ? getComputedStyle(c).paddingTop : null,
        afterPrivacy: !!(document.querySelector('.card.account-card')),
      };
    }""")
    check("홈 맨 아래에 계정 카드 + 로그아웃 버튼", card["exists"] and card["logout"], str(card))
    check("계정 카드가 AI·개인정보 카드보다 아래에 있다",
          page.evaluate("""(() => {
            const cards = [...document.querySelectorAll('.app-pad > .card, .app-pad > .sec-title')];
            const acc = document.querySelector('.account-card');
            const priv = [...document.querySelectorAll('.sec-title h4')].find(h => h.textContent.includes('AI · 개인정보'));
            return !!priv && acc && priv.compareDocumentPosition(acc) & Node.DOCUMENT_POSITION_FOLLOWING;
          })()"""))

    # --- D-Day 카드 = 여행 설정 수정 진입점 ---
    check("D-Day 카드가 수정 진입점", page.locator('.hero[data-act="edit-trip"]').count() == 1)
    check("D-Day 카드가 진짜 button (키보드로 열 수 있다)",
          page.evaluate("document.querySelector('.hero[data-act=\\'edit-trip\\']').tagName") == "BUTTON")
    page.locator('.hero[data-act="edit-trip"]').focus()
    page.keyboard.press("Enter")
    page.wait_for_timeout(250)
    check("Enter 키로 여행 설정 수정 화면이 열린다", page.evaluate("S.screen") == "u-edit", page.evaluate("S.screen"))
    page.evaluate("go('u-home')")
    page.wait_for_timeout(200)
    page.locator('.hero[data-act="edit-trip"]').click()
    page.wait_for_timeout(300)
    edit = page.evaluate("""() => ({
      scr: S.screen,
      country: document.querySelector('[data-bind="country"]') && document.querySelector('[data-bind="country"]').value,
      tripCountry: S.trip.country,
      cities: [...document.querySelectorAll('[data-bind^="city."][data-bind$=".name"]')].map(i => i.value),
    })""")
    check("카드를 누르면 여행 설정 수정 화면", edit["scr"] == "u-edit", str(edit))
    check("현재 여행 입력이 미리 채워져 있다",
          edit["country"] == edit["tripCountry"] and edit["cities"] == page.evaluate("S.trip.cities.map(c => c.name)"), str(edit))

    # --- 날짜만 수정 → 저장: 장소·문장 틀은 그대로, 학습 일정표만 다시 계산 ---
    before = page.evaluate("({ per: S.plan.per.length, cities: S.trip.cities.map(c => c.name), old: S.trip.studyStart })")
    new_start = page.evaluate("Dt.add(S.trip.tripStart, -10)")
    page.fill('[data-bind="studyStart"]', new_start)
    page.wait_for_timeout(150)
    page.click('[data-act="save-trip"]')
    page.wait_for_timeout(400)
    after = page.evaluate("""() => ({
      scr: S.screen, modal: !!S.modal, study: S.trip.studyStart,
      cities: S.trip.cities.map(c => c.name), per: S.plan.per.length, plan: !!S.plan, status: S.trip.status,
    })""")
    check("날짜만 바꾸면 확인 창 없이 저장되고 홈으로", after["scr"] == "u-home" and not after["modal"], str(after))
    check("학습 시작일이 저장됐다", after["study"] == new_start and after["study"] != before["old"], f'{before["old"]} → {after["study"]}')
    check("도시·장소는 그대로, 일정표는 다시 계산",
          after["cities"] == before["cities"] and after["per"] == before["per"] and after["plan"] and after["status"] == "studying",
          f'before={before} after={after}')

    # --- 새로고침: 저장한 여행으로 홈이 복원된다 (실제 제품 경로: 해시 없이 다시 연다) ---
    page.goto(BASE + "/", wait_until="domcontentloaded")
    page.wait_for_timeout(900)
    reloaded = page.evaluate("""() => ({
      scr: S.screen, trip: !!S.trip, plan: !!S.plan,
      study: S.trip && S.trip.studyStart,
      cities: S.trip && S.trip.cities.map(c => c.name),
      stored: (() => { try { return JSON.parse(localStorage.getItem('cd_trip') || 'null'); } catch (e) { return null; } })(),
    })""")
    check("새로고침 뒤에도 실제 여행으로 홈이 열린다", reloaded["scr"] == "u-home" and reloaded["trip"] and reloaded["plan"], str(reloaded))
    check("저장한 학습 시작일·도시가 그대로 복원", reloaded["study"] == new_start and reloaded["cities"] == before["cities"], str(reloaded))
    check("브라우저에 여행 입력이 남아 있다(장소·문장 본문은 없음)",
          reloaded["stored"] and reloaded["stored"]["studyStart"] == new_start and "places" not in reloaded["stored"] and "sents" not in reloaded["stored"], str(reloaded["stored"]))

    # --- 날짜만 바꿔 완료한 날이 사라질 때는 저장 전에 확인한다 ---
    before_prog = page.evaluate("""() => {
      const rows = S.sched.filter(r => r.kind !== 'free');
      rows.slice(0, 2).forEach(r => { r.completed = true; r.completedAt = Date.now(); PROG.done[r.date] = r.completedAt; });
      return progress().done;
    }""")
    page.locator('.hero[data-act="edit-trip"]').click()
    page.wait_for_timeout(250)
    page.fill('[data-bind="studyStart"]', page.evaluate("Dt.add(S.trip.tripStart, -5)"))
    page.wait_for_timeout(150)
    page.click('[data-act="save-trip"]')
    page.wait_for_timeout(250)
    warn = page.evaluate("({ modal: !!S.modal, title: S.modal && S.modal.title, scr: S.screen, done: progress().done })")
    check("완료한 날이 빠지면 저장 전에 확인 창", warn["modal"] and "학습 시작일" in (warn["title"] or ""), str(warn))
    check("확인 전에는 저장·진도 변화 없음", warn["scr"] == "u-edit" and warn["done"] == before_prog, str(warn))
    page.click('[data-act="modal-cancel"]')
    page.wait_for_timeout(200)
    check("취소하면 수정 화면 유지·진도 그대로",
          page.evaluate("S.screen") == "u-edit" and page.evaluate("progress().done") == before_prog)
    page.click('[data-act="save-trip"]')
    page.wait_for_timeout(200)
    page.click('[data-act="modal-ok"]')
    page.wait_for_timeout(400)
    after_prog = page.evaluate("({ scr: S.screen, done: progress().done })")
    check("확정하면 저장되고 빠진 완료는 사라진다", after_prog["scr"] == "u-home" and after_prog["done"] < before_prog, str(after_prog))

    # --- 도시 변경 → 저장: 보고서부터 다시 만들지 묻는다 ---
    page.locator('.hero[data-act="edit-trip"]').click()
    page.wait_for_timeout(250)
    page.fill('[data-bind="city.0.name"]', "시카고")
    page.wait_for_timeout(150)
    page.click('[data-act="save-trip"]')
    page.wait_for_timeout(300)
    ask = page.evaluate("({ modal: !!S.modal, title: S.modal && S.modal.title, scr: S.screen, country: S.trip.country, city: S.trip.cities[0].name })")
    check("도시를 바꾸면 다시 만들지 묻는 확인 창", ask["modal"] and "다시 만들까요" in (ask["title"] or ""), str(ask))
    check("확정 전에는 여행이 바뀌지 않는다", ask["city"] == before["cities"][0] and ask["scr"] == "u-edit", str(ask))
    page.click('[data-act="modal-cancel"]')
    page.wait_for_timeout(200)
    check("취소하면 수정 화면에 그대로", page.evaluate("S.screen") == "u-edit" and not page.evaluate("!!S.modal"))

    # --- 재생성 확정: 보고서 단계로 넘어간다 ---
    page.click('[data-act="save-trip"]')
    page.wait_for_timeout(250)
    page.click('[data-act="modal-ok"]')
    page.wait_for_timeout(500)
    regen = page.evaluate("({ city: S.trip.cities[0].name, status: S.trip.status, scr: S.screen })")
    check("확정하면 새 도시로 보고서를 다시 만든다",
          regen["city"] == "시카고" and (regen["status"] == "report_requested" or regen["status"] == "report_generating"), str(regen))

    # --- 홈 하단 로그아웃 (확인 창) ---
    page.evaluate("S.user = DEMO_USER; ensure('plan'); go('u-home')")
    page.wait_for_timeout(300)
    page.click('[data-act="logout-home"]')
    page.wait_for_timeout(200)
    check("로그아웃도 확인 창을 띄운다", page.evaluate("!!S.modal") and "로그아웃" in page.locator(".modal").inner_text())
    page.click('[data-act="modal-ok"]')
    page.wait_for_timeout(600)
    out = page.evaluate("({ scr: S.screen, uid: accountUid() })")
    check("로그아웃하면 로그인 화면으로", out["scr"] == "u-login" and out["uid"] == "", str(out))
    page.goto(BASE + "/", wait_until="domcontentloaded")
    page.wait_for_timeout(700)
    check("로그아웃 뒤 새로고침해도 로그인 화면", page.evaluate("S.screen") == "u-login", page.evaluate("S.screen"))
    kept = page.evaluate("""(() => { try { return JSON.parse(localStorage.getItem('cd_trip') || 'null'); } catch (e) { return null; } })()""")
    check("로그아웃해도 여행 입력은 브라우저에 남는다",
          kept and kept.get("cities") and kept["cities"][0]["name"] == "시카고", str(kept))

    # --- Firebase 계정 경로: 여행 입력이 계정 칸에 갈라져 저장된다(서버 왕복은 test_user_state.py) ---
    acct = page.evaluate("""() => {
      const trip = { country: '프랑스', cities: [{ name: '파리', start: '2026-11-10', end: '2026-11-13' }], studyStart: '2026-10-02' };
      S.user = { uid: 'uidT', name: 'T', email: 't@example.com', provider: 'google.com' };
      writeLocalState({ session: null, weak: [], consent: null, trip });
      const scoped = AI.scopedStorage(localStorage, 'uidT');
      const local = localState();
      return {
        onAccount: AI.loadTrip(scoped),
        inLocalState: local.trip,
        scopedKey: localStorage.getItem('cd_trip:uidT') !== null,
        sharedTail: (localStorage.getItem('cd_trip') || '').includes('프랑스'),
        stateHasTrip: stateHas({ session: null, weak: [], consent: null, trip }),
      };
    }""")
    check("계정 칸(cd_trip:uidT)에 여행 입력이 저장된다", acct["scopedKey"] and acct["onAccount"] and acct["onAccount"]["country"] == "프랑스", str(acct))
    check("서버로 올리는 묶음(localState)에 trip 이 들어간다", acct["inLocalState"] and acct["inLocalState"]["studyStart"] == "2026-10-02", str(acct))
    check("공용 칸(cd_trip)은 계정 여행으로 오염되지 않는다", acct["sharedTail"] is False, str(acct))
    check("여행만 있어도 '기록 있음'으로 본다(서버에 올릴 대상)", acct["stateHasTrip"] is True)
    check("계정마다 다른 여행이 섞이지 않는다",
          page.evaluate("""() => {
            AI.saveTrip(AI.scopedStorage(localStorage, 'uidU'), { country: '영국', cities: [{ name: '런던', start: '2026-11-10', end: '2026-11-13' }], studyStart: '2026-10-01' });
            writeLocalState({ session: null, weak: [], consent: null, trip: null });
            return AI.loadTrip(AI.scopedStorage(localStorage, 'uidU')).country === '영국'
              && AI.loadTrip(AI.scopedStorage(localStorage, 'uidT')) === null;
          }"""))

    page.evaluate("S.user = null; ACT.reset()")
    page.wait_for_timeout(200)
    check("전체 초기화는 공용 여행 입력을 지운다", page.evaluate("localStorage.getItem('cd_trip')") is None)

    check("자바스크립트 오류 없음", not errors, str(errors[:3]))
    b.close()

bad = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(bad)}/{len(results)} 통과")
if bad:
    print("실패: " + ", ".join(bad))
sys.exit(1 if bad else 0)
