"""학습 화면 하단 '회화 연습' 시트 E2E (Leechangjin 님 요청 10/17, 목업 #97).

- 말해보기가 카드 뒷면에서 하단 시트로 옮겨졌다. 아래쪽 완료 안내는 제목 아래로 옮겼다.
- 시트: 내 문장 + 말해보기, 상대의 예상 답변(듣기), 내가 이어서 할 말. 입국심사처럼 상대가 먼저
  묻는 상황은 그 질문이 맨 위에 온다(설문 7-2 "상대 질문도 영어로").
- 닫기 버튼·바깥 탭·뒤로가기로 닫히고, 카드를 넘기면 닫힌다. 장소 문장(예상 답변 없음)은 말해보기만.

    cd backend && uvicorn app.main:app --port 8768
    python ../e2e/test_conversation_sheet.py http://localhost:8768
"""
import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1]
results = []

# 듣기 버튼이 실제로 그 영어 문장을 읽는지 보려고 speechSynthesis 를 가로챈다(test_speech_text 와 같은 방식).
SPEECH_SPY = """
(() => {
  window.__spoken = [];
  const synth = window.speechSynthesis;
  if (!synth) return;
  synth.speak = u => { window.__spoken.push(u.text); if (u.onstart) u.onstart(); if (u.onend) u.onend(); };
  synth.cancel = () => {};
  synth.getVoices = () => [];
})();
"""


def check(name, cond, extra=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""))


def open_drill(page, sit):
    page.evaluate("navFromMenu('u-coll')"); page.wait_for_timeout(300)
    page.locator(f'[data-act="drill"][data-v="{sit}"]').click(); page.wait_for_timeout(300)


with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 390, "height": 844})
    ctx.add_init_script(SPEECH_SPY)
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE + "/?demo=1", wait_until="domcontentloaded")
    page.wait_for_timeout(700)
    page.evaluate("ensure('plan')")

    # --- 상황별 연습(공항): 시트 열기 전후 ---
    open_drill(page, "airport")
    check("카드 뒷면에는 말해보기가 없다", page.locator('.face [data-live="speak"]').count() == 0)
    check("하단에 '회화 연습 열기' 버튼", page.locator('.bottombar [data-act="sheet-open"]').count() == 1)
    check("완료 안내는 제목 아래로 옮겨졌다", page.locator('.app [data-live="status"]').count() == 1
          and page.locator('.bottombar [data-live="status"]').count() == 0)

    page.locator('[data-act="sheet-open"]').click(); page.wait_for_timeout(300)
    s = page.evaluate("(() => { const s = curSent(); return { en: s.en, talk: s.talk, alt: s.alt || [] }; })()")
    check("시트가 열리고 상태가 남는다", page.locator(".sheet").count() == 1 and page.evaluate("S.sheet") is True)
    check("시트에 내 문장과 말해보기", s["en"].split(",")[0] in page.locator(".sheet .talk-me").inner_text()
          and page.locator('.sheet [data-act="speak-rec"]').count() == 1, s["en"])
    lines = page.locator(".sheet .talk-line")
    want = len(s["talk"]["replies"]) + 1 + (1 if s["talk"].get("ask") else 0) + len(s["alt"])   # 다른 표현 줄 포함
    check("예상 답변 + 이어서 할 말이 데이터대로", lines.count() == want, f"{lines.count()} / {want}")
    check("예상 답변 문장이 보인다", s["talk"]["replies"][0]["en"] in page.locator(".sheet").inner_text())

    page.evaluate("window.__spoken = []")
    page.locator('.sheet [data-act="say-line"][data-k="r0"]').click(); page.wait_for_timeout(200)
    check("답변 '듣기'가 그 영어 문장을 읽는다", page.evaluate("window.__spoken") == [s["talk"]["replies"][0]["en"]], str(page.evaluate("window.__spoken")))
    page.evaluate("window.__spoken = []")
    page.locator('.sheet [data-act="say-line"][data-k="next"]').click(); page.wait_for_timeout(200)
    check("이어서 할 말 '듣기'", page.evaluate("window.__spoken") == [s["talk"]["next"]["en"]], str(page.evaluate("window.__spoken")))
    page.evaluate("window.__spoken = []")
    page.locator('.sheet [data-act="speak-card"]').click(); page.wait_for_timeout(200)   # 내 녹음과 비교할 원어민 듣기
    check("시트 안 내 문장 '듣기'", page.evaluate("window.__spoken") == [s["en"]], str(page.evaluate("window.__spoken")))

    # 닫는 세 가지 방법
    page.locator('[data-act="sheet-close"]').click(); page.wait_for_timeout(300)
    check("닫기 버튼으로 닫힌다", page.locator(".sheet").count() == 0 and not page.evaluate("S.sheet"))
    page.locator('[data-act="sheet-open"]').click(); page.wait_for_timeout(300)
    page.mouse.click(195, 40); page.wait_for_timeout(300)   # 시트 위쪽 어두운 바깥
    check("바깥을 누르면 닫힌다", page.locator(".sheet").count() == 0)
    page.locator('[data-act="sheet-open"]').click(); page.wait_for_timeout(300)
    page.go_back(); page.wait_for_timeout(400)
    check("뒤로가기는 시트만 닫고 학습 화면에 남는다", page.locator(".sheet").count() == 0 and page.evaluate("S.screen") == "u-study"
          and page.evaluate("S.drill") is not None)

    page.locator('[data-act="sheet-open"]').click(); page.wait_for_timeout(300)
    page.evaluate("ACT['card-next']()"); page.wait_for_timeout(300)
    check("카드를 넘기면 시트가 닫힌다", page.locator(".sheet").count() == 0 and page.evaluate("S.card.i") == 1)

    # --- 입국심사: 상대가 먼저 묻는 질문이 맨 위 ---
    page.evaluate("endDrill()")
    open_drill(page, "immigration")
    page.locator('[data-act="sheet-open"]').click(); page.wait_for_timeout(300)
    ask = page.evaluate("curSent().talk.ask")
    txt = page.locator(".sheet").inner_text()
    check("입국심사: '상대가 먼저' 질문이 내 문장보다 위", ask and "상대가 먼저" in txt and txt.index(ask["en"]) < txt.index(page.evaluate("curSent().en")), str(ask))
    page.evaluate("window.__spoken = []")
    page.locator('.sheet [data-act="say-line"][data-k="ask"]').click(); page.wait_for_timeout(200)
    check("질문 '듣기'", page.evaluate("window.__spoken") == [ask["en"]])
    page.locator('[data-act="sheet-close"]').click(); page.wait_for_timeout(200)

    # --- 장소 문장: 예상 답변이 없으면 말해보기만 ---
    day = page.evaluate("(S.sched.find(r => r.kind !== 'free' && r.ids.some(id => S.smap[id] && !S.smap[id].talk)) || {}).date || null")
    page.evaluate("endDrill()")
    page.evaluate(f"ACT['study-date']({{ dataset: {{ date: '{day}' }} }})"); page.wait_for_timeout(300)
    page.evaluate("S.modal && S.modal.title === '아직 학습일이 아니에요' && ACT['modal-ok']()")
    page.wait_for_timeout(300)
    idx = page.evaluate("pickRow().ids.findIndex(id => !S.smap[id].talk)") if day else -1
    if idx >= 0:
        page.evaluate(f"S.card.i = {idx}; render()"); page.wait_for_timeout(200)
        page.locator('[data-act="sheet-open"]').click(); page.wait_for_timeout(300)
        check("예상 답변이 없는 문장: 말해보기만 + 안내", page.locator(".sheet .talk-line").count() == 0
              and page.locator('.sheet [data-act="speak-rec"]').count() == 1 and "예상 답변이 아직 없어요" in page.locator(".sheet").inner_text())
        page.locator('[data-act="sheet-close"]').click(); page.wait_for_timeout(200)
    else:
        check("예상 답변이 없는 문장: 말해보기만 + 안내", False, "학습 날짜에 장소 문장이 없다")

    # --- 다른 화면으로 가면 시트가 남지 않는다 ---
    page.locator('[data-act="sheet-open"]').click(); page.wait_for_timeout(300)
    page.evaluate("go('u-home')"); page.wait_for_timeout(300)
    check("화면을 옮기면 시트가 닫힌다", not page.evaluate("S.sheet") and page.locator(".sheet").count() == 0)

    # --- 넓은 화면(일정표 2열)에서도 연다 ---
    page.set_viewport_size({"width": 1280, "height": 900})
    page.evaluate("go('u-sched')"); page.wait_for_timeout(400)
    if page.locator('[data-act="preview-ok"]').count():
        page.locator('[data-act="preview-ok"]').click(); page.wait_for_timeout(300)
    page.locator('[data-act="sheet-open"]').first.click(); page.wait_for_timeout(300)
    check("넓은 화면: 시트가 열리고 말해보기가 있다", page.locator('.sheet [data-act="speak-rec"]').count() == 1)
    page.locator('[data-act="sheet-close"]').click(); page.wait_for_timeout(200)

    check("페이지 JS 오류 없음", not errors, "; ".join(errors[:3]))
    b.close()

print(f"\n{sum(ok for _, ok in results)}/{len(results)} passed")
sys.exit(0 if all(ok for _, ok in results) else 1)
