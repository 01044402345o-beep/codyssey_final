"""HTML 구조 검사 E2E — 화면을 실제로 그린 뒤, HTML5 검사기(html5.validator.nu)가 잡은 종류의 오류를 로컬에서 잡는다.

10/21 html5.validator.nu 로 그린 화면을 검사했더니 홈 D-Day 카드(버튼) 안에 div 가 있었다
("Element div not allowed as child of element button"). 버튼·링크 안에는 phrasing content 만 둘 수 있다.
검사기는 외부 서비스라 CI 에서 부르지 않는다 — 같은 규칙을 화면마다 직접 본다:
  - button / a[href] 안에 블록·상호작용 요소(div·p·h1~h6·ul·ol·li·section·article·form·table·button·a·input·select·textarea·label·details) 없음
  - 같은 id 가 두 번 나오지 않음
  - aria-label 은 역할이 있는 요소에만(div·span 에 쓰면 role 필요)

    cd backend && uvicorn app.main:app --port 8768
    python ../e2e/test_html_valid.py http://localhost:8768
"""
import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1]
results = []

SCAN = """() => {
  const bad = [];
  const inner = 'div,p,h1,h2,h3,h4,h5,h6,ul,ol,li,section,article,form,table,button,a,input,select,textarea,label,details';
  const tag = e => e.tagName.toLowerCase() + (e.className && typeof e.className === 'string' ? '.' + e.className.split(' ')[0] : '');
  document.querySelectorAll('button, a[href]').forEach(el => el.querySelectorAll(inner).forEach(c => bad.push(tag(el) + ' > ' + tag(c))));
  const ids = {}; document.querySelectorAll('[id]').forEach(e => { ids[e.id] = (ids[e.id] || 0) + 1; });
  Object.entries(ids).filter(([, n]) => n > 1).forEach(([k]) => bad.push('id 중복 #' + k));
  document.querySelectorAll('div[aria-label]:not([role]), span[aria-label]:not([role])').forEach(e => bad.push('role 없는 aria-label: ' + tag(e)));
  return [...new Set(bad)];
}"""

STEPS = [
    ("로그인", "go('u-login')"),
    ("이메일 로그인", "S.authMode = 'login'; go('u-auth')"),
    ("여행 입력", "S.user = DEMO_USER; ensure('user'); go('u-input')"),
    ("홈(여행 전)", "ensure('plan'); go('u-home')"),
    ("일정표", "go('u-sched')"),
    ("학습", "S.today = S.sched.filter(r => r.kind !== 'free')[0].date; go('u-study'); S.modal = null; render()"),
    ("회화 연습 시트", "ACT['sheet-open']()"),
    ("대화하기", "document.querySelector('[data-act=talk-start]') && ACT['talk-start']()"),
    ("문장 모음", "S.sheet = false; go('u-coll')"),
    ("여행 설정 수정", "navFromMenu('u-edit')"),
    ("홈(여행 중)", "S.today = S.trip.tripStart; go('u-home')"),
    ("통역", "typeof scrInterp === 'function' && go('u-interp')"),
    ("통역 크게 보여주기", "typeof scrInterp === 'function' && (S.interp.show = S.sents[0].id, render())"),
    ("홈(여행 후)", "S.interp && (S.interp.show = null); S.today = Dt.add(S.trip.tripEnd, 1); go('u-home')"),
]


def check(name, cond, extra=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""))


with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 390, "height": 844})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE + "/?demo=1"); page.wait_for_timeout(1000)
    for name, js in STEPS:
        page.evaluate(js); page.wait_for_timeout(300)
        bad = page.evaluate(SCAN)
        check(f"{name}: 버튼·링크 안 블록/상호작용 요소 없음, id 중복 없음, aria-label 역할", not bad, "; ".join(bad[:5]))
    check("페이지 JS 오류 없음", not errors, "; ".join(errors[:3]))
    b.close()

print(f"\n{sum(ok for _, ok in results)}/{len(results)} passed")
sys.exit(0 if all(ok for _, ok in results) else 1)
