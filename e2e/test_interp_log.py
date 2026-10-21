"""문장 모음 > 통역 기록 탭 E2E.

통역 화면에서 확정된 문장(liveCommit)이 이 브라우저에 남고, 문장 모음의 '통역 기록' 탭에서
대화 단위로 보이고 지워지는지. 서버 전송·음성 저장이 없다는 것은 화면 문구로 확인한다.
"""
import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1]
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
    check("빈 화면에도 '이 브라우저에만' 안내", "이 브라우저에만" in page.locator(".app-pad").inner_text())

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
    check("저장소 키도 지워진다", page.evaluate("localStorage.getItem('cd_ilog')") is None)

    # --- 다른 탭은 그대로 ---
    page.locator('[data-act="coll-tab"][data-v="common"]').click(); page.wait_for_timeout(400)
    check("공통 상황 탭은 그대로 동작", page.locator(".sent").count() >= 10 and page.locator(".ilog-card").count() == 0,
          str(page.locator(".sent").count()))
    check("페이지 오류 없음", not errors, str(errors[:2]))

    ctx.close(); b.close()

passed = sum(1 for _, ok in results if ok)
print(f"\n{passed}/{len(results)} passed")
sys.exit(0 if passed == len(results) else 1)
