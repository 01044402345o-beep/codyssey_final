"""계정마다 진도·복습 키가 갈라지는지. 서버 왕복은 tests/test_user_state.py.

uid 가 없으면 cd_session·cd_weak·cd_consent 그대로다. 테마는 계정 접미사를 붙이지 않는다.
로그인 없이 계정 객체를 넣어 칸만 확인한다. Firestore 호출은 하지 않는다.

    cd backend && uvicorn app.main:app --port 8769
    python ../e2e/test_account_storage.py http://localhost:8769
"""
import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1]
results = []


def check(name, cond, extra=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""))


UID_A = "{ uid: 'uidA', name: 'A', email: 'a@example.com', provider: 'google.com' }"
UID_B = "{ uid: 'uidB', name: 'B', email: 'b@example.com', provider: 'google.com' }"

with sync_playwright() as p:
    b = p.chromium.launch()
    errors = []
    page = b.new_page(viewport={"width": 390, "height": 844})
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE + "/?demo=1")
    page.wait_for_timeout(800)
    page.evaluate("FirebaseAuth.ready")

    demo = page.evaluate(f"S.user = DEMO_USER; go('u-input'); localStorage.getItem('cd_session')")
    check("uid 없으면 cd_session 에 화면이 남는다", demo and "u-input" in demo, demo)
    check("uid 없을 때 계정 키는 생기지 않는다", page.evaluate("localStorage.getItem('cd_session:uidA')") is None)

    split = page.evaluate(f"""async () => {{
      await adoptAccount({UID_A}, {{ navigate: false }});
      ensure('plan');
      go('u-sched');
      await adoptAccount({UID_B}, {{ navigate: false }});
      ensure('plan');
      PROG.done = {{ '2026-01-02': 123 }};
      go('u-home');
      return {{
        a: localStorage.getItem('cd_session:uidA'),
        b: localStorage.getItem('cd_session:uidB'),
        demo: localStorage.getItem('cd_session'),
      }};
    }}""")
    check("A 의 화면은 A 키에만", split["a"] and "u-sched" in split["a"] and "u-home" not in split["a"], split["a"])
    check("B 의 완료 날짜는 B 키에만", split["b"] and "u-home" in split["b"] and "2026-01-02" in split["b"], split["b"])
    check("공용 키는 A·B 화면으로 바뀌지 않는다", split["demo"] and "u-input" in split["demo"] and "2026-01-02" not in split["demo"], split["demo"])

    back = page.evaluate(f"""async () => {{
      await adoptAccount({UID_A}, {{ navigate: true }});
      return S.screen;
    }}""")
    check("A 로 돌아오면 A 의 화면을 연다", back == "u-sched", back)
    check("B 키는 그대로", "2026-01-02" in (page.evaluate("localStorage.getItem('cd_session:uidB')") or ""))

    weak = page.evaluate(f"""() => {{
      S.user = {UID_A};
      saveWeakList([{{ category_id: 'restaurant', id: 'order_menu', situation: 'A만', en: 'Water', ko: '물' }}]);
      S.user = {UID_B};
      saveWeakList([{{ category_id: 'restaurant', id: 'order_menu', situation: 'B만', en: '', ko: '' }}]);
      return {{
        a: AI.loadWeak(AI.scopedStorage(localStorage, 'uidA'))[0].situation,
        b: AI.loadWeak(AI.scopedStorage(localStorage, 'uidB'))[0].situation,
        shared: localStorage.getItem('cd_weak'),
      }};
    }}""")
    check("복습 목록도 계정마다 갈린다", weak["a"] == "A만" and weak["b"] == "B만" and weak["shared"] in (None, "[]"), str(weak))

    page.evaluate("setTheme('dark')")
    check("테마는 계정 키로 나뉘지 않는다",
          page.evaluate("localStorage.getItem('cd_theme')") == "dark"
          and page.evaluate("localStorage.getItem('cd_theme:uidB')") is None)

    anon = page.evaluate("""() => {
      S.user = { uid: 'anon1', name: 'x', email: '', provider: 'anonymous' };
      return accountUid();
    }""")
    check("익명 계정은 칸을 만들지 않는다", anon == "")
    check("익명 uid 키가 없다", page.evaluate("localStorage.getItem('cd_session:anon1')") is None)

    left = page.evaluate(f"""async () => {{
      await adoptAccount({UID_B}, {{ navigate: false }});
      go('u-home');
      const demoBefore = localStorage.getItem('cd_session');
      ACT.logout();
      await new Promise(r => setTimeout(r, 400));
      return {{
        demo: localStorage.getItem('cd_session'),
        before: demoBefore,
        b: localStorage.getItem('cd_session:uidB'),
        screen: S.screen,
        uid: accountUid(),
      }};
    }}""")
    check("로그아웃하면 계정 칸을 공용 키에 복사하지 않는다",
          left["uid"] == "" and "2026-01-02" not in (left["demo"] or "") and "2026-01-02" in (left["b"] or ""),
          left["demo"])
    check("로그아웃 화면은 로그인", left["screen"] == "u-login", left["screen"])

    wiped = page.evaluate(f"""() => {{
      S.user = {UID_B};
      AI.saveTrip(personalStore(), {{ country: '미국', cities: [{{ name: '뉴욕', start: '2026-11-10', end: '2026-11-13' }}], studyStart: '2026-10-01' }});
      const before = localStorage.getItem('cd_trip:uidB');
      ACT.reset();
      return {{ before: !!before, after: localStorage.getItem('cd_trip:uidB') }};
    }}""")
    check("초기화는 그 계정 칸의 여행 입력을 지운다", wiped["before"] and wiped["after"] is None, str(wiped))

    check("자바스크립트 오류 없음", not errors, str(errors[:3]))
    b.close()

bad = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(bad)}/{len(results)} 통과")
if bad:
    print("실패: " + ", ".join(bad))
sys.exit(1 if bad else 0)
