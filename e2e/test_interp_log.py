"""문장 모음 > 통역 기록 탭 E2E.

통역 화면에서 확정된 문장(liveCommit)이 이 기기에 남고, 문장 모음의 '통역 기록' 탭에서
대화 단위로 보이고 지워지는지. 로그인 계정은 '사용자의 통역 기록을 서버에 저장' 동의 뒤에만
PUT /user/interp-log 로 올리고, 다른 기기에서 꺼내 보고, 저장을 끄면 DELETE 로 서버 사본을 지우는지.
서버는 페이지 안 가짜 fetch 로 대신하고, 올린 본문은 실제 백엔드 parse_ilog 로 검사한다.
"""
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = sys.argv[1]
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app import user_state  # noqa: E402  — 화면이 올린 본문을 서버 검사기로 확인한다
results = []


def check(name, cond, extra=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""))


SEED = """(() => {
  const has = t => /[가-힣]/.test(t);
  const mk = (id, ago, route, pairs) => ({ id, at: Date.now() - ago, a: 'ko', b: 'en', trip: { id: 't-' + id, route },
    lines: pairs.map(([s, d]) => ({ src: s, dst: d, s: has(s) ? 'ko' : 'en', t: has(d) ? 'ko' : 'en', at: Date.now() - ago })) });
  const list = [
    mk('s-new', 3600e3, '일본 · 도쿄', [['화장실이 어디예요?', 'Where is the restroom?'], ['감사합니다', 'Thank you']]),
    mk('s-old', 2 * 864e5, '미국 · 뉴욕', [['Do you take cards?', '카드 되나요?']]),
  ];
  localStorage.setItem('cd_ilog', JSON.stringify({ v: 1, list }));
  S.ilog = null; S.coll.tab = 'log'; S.coll.logOpen = null; go('u-coll');
})()"""

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 390, "height": 844}, permissions=["clipboard-read", "clipboard-write"])
    page = ctx.new_page(); errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE + "/?demo=1"); page.wait_for_timeout(800)
    page.evaluate("S.user = DEMO_USER; ensure('plan'); S.today = S.trip.tripStart; go('u-coll')"); page.wait_for_timeout(400)

    seg = page.locator(".seg.coll-seg button")
    check("문장 모음 탭이 3개(공통 상황·장소별·통역 기록)", seg.count() == 3, str(seg.count()))
    check("탭 3개가 390px 폭 안에 들어간다", page.evaluate("""(() => { const b = [...document.querySelectorAll('.seg.coll-seg button')];
        const r = document.querySelector('.seg.coll-seg').getBoundingClientRect();
        return b.length === 3 && b.every(x => { const q = x.getBoundingClientRect(); return q.right <= r.right + 1 && q.width > 60; }); })()"""))
    check("세 번째 탭 이름이 '통역 기록'", "통역 기록" in seg.nth(2).inner_text(), seg.nth(2).inner_text())

    # --- 기록이 없을 때 ---
    seg.nth(2).click(); page.wait_for_timeout(400)
    check("통역 기록 탭으로 들어간다", "on" in (page.locator(".seg.coll-seg button").nth(2).get_attribute("class") or ""))
    check("기록이 없으면 안내가 나온다", "아직 통역 기록이 없어요" in page.locator(".app-pad").inner_text())
    check("로그인 안 한 사용자: 계정 저장은 로그인 안내만", "로그인하면 통역 기록을 계정에 저장" in page.locator(".app-pad").inner_text()
          and page.locator('[data-act="ilog-consent"]').count() == 0)

    # --- 기록이 있을 때 ---
    page.evaluate(SEED); page.wait_for_timeout(500)
    check("탭 배지에 전체 문장 수", "통역 기록 3" in page.locator(".seg.coll-seg").inner_text(), page.locator(".seg.coll-seg").inner_text())
    check("대화 단위 카드 2개", page.locator(".ilog-card").count() == 2, str(page.locator(".ilog-card").count()))
    check("최근 대화가 펼쳐진 채로 시작", page.locator(".ilog-card").first.locator(".ilog-body").count() == 1)
    check("접힌 카드는 본문이 없다", page.locator(".ilog-card").nth(1).locator(".ilog-body").count() == 0)
    first = page.locator(".ilog-card").first
    check("원문·번역이 함께 보인다", "화장실이 어디예요?" in first.inner_text() and "Where is the restroom?" in first.inner_text())
    check("내가 한 말은 '나 · 한국어'", "나 · 한국어" in first.inner_text())
    page.locator(".ilog-card").nth(1).locator(".ilog-head").click(); page.wait_for_timeout(350)
    check("다른 대화를 누르면 그 대화가 펼쳐진다", page.locator(".ilog-card").nth(1).locator(".ilog-body").count() == 1
          and page.locator(".ilog-card").first.locator(".ilog-body").count() == 0)
    check("상대가 한 말은 '상대 · 영어'", "상대 · 영어" in page.locator(".ilog-card").nth(1).inner_text())
    check("상대 발화의 번역이 한국어로 보인다", "카드 되나요?" in page.locator(".ilog-card").nth(1).inner_text())

    # --- 복사 ---
    page.evaluate("window.__copied = null; navigator.clipboard.writeText = t => { window.__copied = t; return Promise.resolve(); }")
    page.locator(".ilog-card").nth(1).locator('[data-act="ilog-copy"]').first.click(); page.wait_for_timeout(300)
    check("복사 버튼은 번역문을 복사한다", page.evaluate("window.__copied") == "카드 되나요?", str(page.evaluate("window.__copied")))

    # --- 새로고침해도 남는다 ---
    page.reload(); page.wait_for_timeout(800)
    page.evaluate("S.user = DEMO_USER; ensure('plan'); S.coll.tab = 'log'; go('u-coll')"); page.wait_for_timeout(400)
    check("새로고침해도 기록이 남아 있다", page.locator(".ilog-card").count() == 2)

    # --- 통역 화면의 확정 문장이 기록으로 이어진다 ---
    page.evaluate("""(() => {
      LIVE.src = 'ko'; LIVE.dst = 'en'; ilogStart();
      LIVE.cap = { source: '계산서 주세요', target: 'Could I have the bill?', sp: '', tp: '' };
      liveCommit(); })()"""); page.wait_for_timeout(300)
    saved = page.evaluate("""(() => { const l = JSON.parse(localStorage.getItem('cd_ilog')).list;
        const hit = l.find(x => x.lines.some(y => y.src === '계산서 주세요'));
        return hit ? hit.lines : []; })()""")
    check("통역 확정 문장이 저장된다", len(saved) == 1 and saved[0]["src"] == "계산서 주세요", str(saved)[:80])
    check("통역 기록에 '나'로 분류된다", saved[0]["s"] == "ko" and saved[0]["t"] == "en")
    page.evaluate("S.ilog = null; S.coll.tab = 'log'; S.coll.logOpen = null; go('u-coll')"); page.wait_for_timeout(400)
    check("방금 한 통역이 목록 맨 위에", "계산서 주세요" in page.locator(".ilog-card").first.inner_text())
    check("통역 배지가 4로 늘어난다", "통역 기록 4" in page.locator(".seg.coll-seg").inner_text())

    # --- 한 대화 지우기 ---
    page.locator(".ilog-card").first.locator('[data-act="ilog-del"]').click(); page.wait_for_timeout(300)
    check("지우기 전에 확인 창", page.locator(".modal").count() == 1)
    page.locator('[data-act="modal-ok"]').click(); page.wait_for_timeout(400)
    check("확인하면 그 대화만 지워진다", page.locator(".ilog-card").count() == 2, str(page.locator(".ilog-card").count()))
    check("저장소에서도 지워진다", page.evaluate("JSON.parse(localStorage.getItem('cd_ilog')).list.length") == 2)

    # --- 넓은 화면: 대화 목록 + 본문 2열 ---
    page.set_viewport_size({"width": 1280, "height": 900}); page.wait_for_timeout(500)
    check("넓은 화면: 왼쪽 대화 목록", page.locator(".split-list .ilog-pick").count() == 2, str(page.locator(".split-list .ilog-pick").count()))
    check("넓은 화면: 오른쪽에 그 대화 본문", page.locator(".split-detail .ilog-card").count() == 1)
    page.locator(".ilog-pick").nth(0).click(); page.wait_for_timeout(350)
    check("넓은 화면: 대화를 고르면 오른쪽이 바뀐다", page.locator(".split-detail .ilog-card").count() == 1)
    page.set_viewport_size({"width": 390, "height": 844}); page.wait_for_timeout(400)

    # --- 모두 지우기 ---
    page.locator('[data-act="ilog-clear"]').first.click(); page.wait_for_timeout(300)
    page.locator('[data-act="modal-ok"]').click(); page.wait_for_timeout(400)
    check("모두 지우면 빈 상태", "아직 통역 기록이 없어요" in page.locator(".app-pad").inner_text())
    check("저장소에서도 비워진다", page.evaluate("JSON.parse(localStorage.getItem('cd_ilog')).list.length") == 0)

    # --- 다른 탭은 그대로 ---
    page.locator('[data-act="coll-tab"][data-v="common"]').click(); page.wait_for_timeout(400)
    check("공통 상황 탭은 그대로 동작", page.locator(".sent").count() >= 10 and page.locator(".ilog-card").count() == 0,
          str(page.locator(".sent").count()))

    # --- 로그인 계정: 동의 → 서버 저장 → 다른 기기에서 꺼내 보기 → 저장 끄기 ---
    FAKE = """(uid) => {
      window.__srv = window.__srv || { ilog: null, calls: [] };
      window.fetch = async (url, opt = {}) => {
        const path = String(url).replace(/^https?:\\/\\/[^/]+/, '');
        const m = (opt.method || 'GET').toUpperCase();
        if (path !== '/user/interp-log') return { ok: true, status: 200, json: async () => ({}) };
        __srv.calls.push(m + ' ' + ((opt.headers || {}).Authorization || ''));
        if (m === 'GET') return { ok: true, status: 200, json: async () => ({ ilog: __srv.ilog }) };
        if (m === 'PUT') { const b = JSON.parse(opt.body); __srv.ilog = b; __srv.last = opt.body; return { ok: true, status: 200, json: async () => ({ saved: true }) }; }
        if (m === 'DELETE') { __srv.ilog = null; return { ok: true, status: 200, json: async () => ({ deleted: true }) }; }
      };
      const fa = window.FirebaseAuth; fa.enabled = true; fa.account = { uid, provider: 'google.com' }; fa.idToken = async () => 'tok-' + uid;
      S.user = { uid, provider: 'google.com', name: 'A', email: 'a@example.com' }; S.ilog = null;
      ensure('plan'); S.today = S.trip.tripStart; S.coll = { tab: 'log', filter: 'all', logOpen: null }; go('u-coll');
    }"""
    page.evaluate(FAKE, "uidA"); page.wait_for_timeout(300)
    page.evaluate("""(() => { LIVE.src = 'ko'; LIVE.dst = 'en'; ilogStart();
      LIVE.cap = { source: '물 좀 주세요', target: 'Could I get some water?', sp: '', tp: '' }; liveCommit();
      LIVE.cap = { source: 'Sure, one moment.', target: '네, 잠시만요.', sp: '', tp: '' }; liveCommit(); go('u-coll'); })()""")
    page.wait_for_timeout(1900)
    check("동의 전에는 서버로 보내지 않는다", page.evaluate("__srv.calls.filter(c => c.startsWith('PUT')).length") == 0,
          str(page.evaluate("__srv.calls")))
    check("로그인 계정의 기록은 계정 칸(cd_ilog:uid)에 남는다",
          page.evaluate("JSON.parse(localStorage.getItem('cd_ilog:uidA') || '{\"list\":[]}').list.length") == 1)
    check("'계정에 저장하기' 단추가 보인다", page.locator('[data-act="ilog-consent"]').count() == 1)
    page.locator('[data-act="ilog-consent"]').click(); page.wait_for_timeout(300)
    modal = page.locator(".modal").inner_text() if page.locator(".modal").count() else ""
    check("동의 창: '사용자의 통역 기록을 서버에 저장' 문구", "사용자의 통역 기록을 서버에 저장" in modal, modal[:60])
    check("동의 창: 상대방 말도 저장된다고 알린다", "상대방이 한 말도" in modal)
    check("동의 창: 음성은 저장 안 함·보관 기간·철회 방법", all(k in modal for k in ["음성은 저장하지 않아요", "탈퇴할 때까지", "계정 저장 끄기"]))
    page.locator('[data-act="modal-cancel"]').click(); page.wait_for_timeout(300)
    check("취소하면 저장하지 않는다", page.evaluate("__srv.ilog") is None and page.locator('[data-act="ilog-consent"]').count() == 1)
    page.locator('[data-act="ilog-consent"]').click(); page.wait_for_timeout(300)
    page.locator('[data-act="modal-ok"]').click(); page.wait_for_timeout(900)
    body = page.evaluate("__srv.last || null")
    check("동의하면 계정에 저장(PUT, 로그인 토큰)", body is not None and "PUT Bearer tok-uidA" in page.evaluate("__srv.calls"), str(page.evaluate("__srv.calls")))
    parsed = None
    try:
        parsed = user_state.parse_ilog(json.loads(body)) if body else None
    except user_state.StoreError as exc:
        parsed = None; print("  parse_ilog:", exc.code)
    check("올린 본문을 서버 검사기(parse_ilog)가 받는다", parsed is not None)
    check("올린 본문에 동의 버전과 두 문장(상대 말 포함)", parsed and parsed["consent"]["version"] == page.evaluate("ILOG_CONSENT_VERSION")
          and [ln["src"] for ln in parsed["list"][0]["lines"]] == ["물 좀 주세요", "Sure, one moment."], str(parsed)[:120])
    raw = json.loads(body) if body else {"list": [{}]}
    check("음성·여행 id 는 보내지 않는다", body and "audio" not in body and set((raw["list"][0].get("trip") or {"route": ""})) == {"route"},
          str(raw["list"][0].get("trip")))
    check("화면에 '계정에 저장 중'과 끄기 단추", "계정에 저장 중" in page.locator(".app-pad").inner_text() and page.locator('[data-act="ilog-revoke"]').count() == 1)
    # 동의 뒤 새 통역 문장은 곧바로(잠시 뒤) 서버에도 올라간다
    page.evaluate("""(() => { LIVE.cap = { source: '얼마예요?', target: 'How much is it?', sp: '', tp: '' }; liveCommit(); })()""")
    page.wait_for_timeout(2000)
    check("동의 뒤 새 문장도 계정에 올라간다", page.evaluate("__srv.ilog.list[0].lines.length") == 3)

    # 다른 기기(빈 브라우저)에서 같은 계정으로 로그인 → 꺼내 보기
    srv = page.evaluate("__srv.ilog")
    ctx2 = b.new_context(viewport={"width": 390, "height": 844}); page2 = ctx2.new_page()
    page2.on("pageerror", lambda e: errors.append(str(e)))
    page2.goto(BASE + "/?demo=1"); page2.wait_for_timeout(800)
    page2.evaluate("(s) => { window.__srv = { ilog: s, calls: [] }; }", srv)
    page2.evaluate(FAKE, "uidA"); page2.wait_for_timeout(200)
    page2.locator('[data-act="coll-tab"][data-v="log"]').click(); page2.wait_for_timeout(900)
    check("다른 기기: 통역 기록 탭을 열면 계정의 기록을 꺼내 본다", "물 좀 주세요" in page2.locator(".app-pad").inner_text(),
          page2.locator(".app-pad").inner_text()[:80])
    check("다른 기기: 같은 계정의 동의를 그대로 쓴다", "계정에 저장 중" in page2.locator(".app-pad").inner_text())
    # 다른 계정은 그 기록을 못 본다(서버는 uid 별 — 가짜 서버를 비워 흉내)
    page2.evaluate("(() => { window.__srv = { ilog: null, calls: [] }; })()")
    page2.evaluate(FAKE, "uidB"); page2.wait_for_timeout(200)
    page2.locator('[data-act="coll-tab"][data-v="log"]').click(); page2.wait_for_timeout(700)
    check("다른 계정으로 바꾸면 앞 계정 기록이 안 보인다", "물 좀 주세요" not in page2.locator(".app-pad").inner_text()
          and page2.locator('[data-act="ilog-consent"]').count() == 1)
    ctx2.close()

    # 저장 끄기 → 서버 사본 DELETE, 이 기기 기록은 남음
    page.locator('[data-act="ilog-revoke"]').first.click(); page.wait_for_timeout(300)
    check("저장 끄기 전에 확인 창", page.locator(".modal").count() == 1)
    page.locator('[data-act="modal-ok"]').click(); page.wait_for_timeout(800)
    check("저장을 끄면 서버 사본을 지운다(DELETE)", page.evaluate("__srv.ilog") is None and any(c.startswith("DELETE") for c in page.evaluate("__srv.calls")))
    check("이 기기의 기록은 남는다", "물 좀 주세요" in page.locator(".app-pad").inner_text())
    check("끈 뒤에는 다시 '계정에 저장하기'", page.locator('[data-act="ilog-consent"]').count() == 1)
    n_put = page.evaluate("__srv.calls.filter(c => c.startsWith('PUT')).length")
    page.evaluate("""(() => { LIVE.cap = { source: '고마워요', target: 'Thanks', sp: '', tp: '' }; liveCommit(); })()""")
    page.wait_for_timeout(2000)
    check("끈 뒤에는 더 올리지 않는다", page.evaluate("__srv.calls.filter(c => c.startsWith('PUT')).length") == n_put)
    page.evaluate("go('u-home')"); page.wait_for_timeout(300)
    check("홈 개인정보 카드에 통역 기록 저장 상태", "통역 기록 계정 저장" in page.locator("body").inner_text())
    check("페이지 오류 없음", not errors, str(errors[:2]))

    ctx.close(); b.close()

passed = sum(1 for _, ok in results if ok)
print(f"\n{passed}/{len(results)} passed")
sys.exit(0 if passed == len(results) else 1)
