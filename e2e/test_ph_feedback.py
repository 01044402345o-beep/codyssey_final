"""소리별 결과의 기호를 누르면 그 소리 피드백이 나온다.

계약:
  1) 칩은 버튼이고, 누르면 카드 안에 그 기호의 설명 패널이 열린다.
  2) 패널에는 기호·판정(들렸다/약했다/안 들렸다)·조음 설명이 있고, 점수는 말하지 않는다.
  3) 같은 칩을 다시 누르거나 ✕ 로 닫힌다.
  4) 카드가 다시 그려져도(다른 칩 선택) 선택이 유지된다.
  5) 같은 기호가 두 번 나와도(seat·please 의 /iː/) 누른 칩만 선택된다.
  6) 새 결과(다시 녹음·다른 문장)가 오면 열린 설명은 닫힌다.
  7) 패널 버튼은 44px 이상, 라벨 '한 가지만 확인 부탁드려요'는 한 줄(세 줄로 꺾이지 않는다).
"""
import sys
from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8899"
fails = []
def check(n, c, e=""):
    print(("PASS " if c else "FAIL ") + n + ((" — " + str(e)) if (e and not c) else ""))
    if not c: fails.append(n)

RES = {"usable": True, "score": 86, "score_kind": "word_match_consensus", "target": "Can I have a window seat, please?",
 "heard": "Can I have a window sit, please?", "diff": {"missing": ["seat,"]}, "saved": False,
 "fix_one": "'seat'의 '이' 소리를 길게 말해 보세요.",
 "phonemes_acoustic": {"status": "ok", "phoneme_accuracy": 95.0, "counts": {"ok": 19, "weak": 0, "missing": 1},
   "focus": {"ipa": "iː", "word": "seat", "heard_as": "ɪ", "label": "길이", "tip": "길게 끌어 주세요"},
   "phonemes": [
     {"ipa": "k", "word": "Can", "status": "ok"}, {"ipa": "æ", "word": "Can", "status": "ok"},
     {"ipa": "aɪ", "word": "I", "status": "ok"}, {"ipa": "h", "word": "have", "status": "ok"},
     {"ipa": "ə", "word": "a", "status": "weak"},
     {"ipa": "w", "word": "window", "status": "ok"}, {"ipa": "ɪ", "word": "window", "status": "ok"},
     {"ipa": "iː", "word": "seat", "status": "missing", "heard_as": "ɪ"},
     {"ipa": "θ", "word": "please?", "status": "ok"}, {"ipa": "iː", "word": "please?", "status": "ok"}]}}

with sync_playwright() as pw:
    b = pw.chromium.launch()
    for scheme in ("light", "dark"):
        pg = b.new_page(viewport={"width": 390, "height": 844}, color_scheme=scheme)
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(BASE + "/?demo=1&gate=off"); pg.wait_for_timeout(2400)
        if pg.locator('[data-act="guest"]').count():
            pg.locator('[data-act="guest"]').first.click(); pg.wait_for_timeout(1200)
        pg.evaluate("try{saveConsentHere(true)}catch(e){}; ensure('plan'); navFromMenu('u-study')"); pg.wait_for_timeout(1200)
        pg.evaluate("S.modal && ACT['modal-ok'] && ACT['modal-ok']()"); pg.wait_for_timeout(300)
        pg.locator('[data-act="flip"]').first.click(); pg.wait_for_timeout(300)
        pg.locator('[data-act="sheet-open"]').first.click(); pg.wait_for_timeout(600)
        pg.evaluate("(r) => { const s = curSent(); SPK.sid = s.id; SPK.line='me'; SPK.state='idle'; SPK.ph=null; SPK.result = { ...r, target: s.en }; updateSpeakUi(); }", RES)
        pg.wait_for_timeout(400)
        tag = scheme + ": "
        chips = pg.locator('.spk-ph')
        check(tag + "칩이 버튼이다", chips.count() == 10 and pg.evaluate("() => document.querySelector('.spk-ph').tagName") == "BUTTON", chips.count())
        check(tag + "처음에는 설명 패널이 없다", pg.locator('.spk-phd').count() == 0)

        pg.locator('.spk-ph[data-ipa="θ"]').first.click(); pg.wait_for_timeout(400)
        d = pg.locator('.spk-phd')
        check(tag + "칩을 누르면 패널이 열린다", d.count() == 1)
        txt = d.inner_text() if d.count() else ""
        check(tag + "그 기호가 제목에 나온다", "/θ/" in txt, txt[:60])
        check(tag + "조음 설명이 있다", "혀끝" in txt or "윗니" in txt, txt[:120])
        check(tag + "판정은 점수가 아니라 '들렸다'", "들렸" in txt and "%" not in txt.split("발음기호 화면")[0], txt[:120])
        check(tag + "선택된 칩이 aria-pressed=true", pg.get_attribute('.spk-ph[data-ipa="θ"]', "aria-pressed") == "true")

        pg.locator('.spk-ph[data-ipa="iː"]').first.click(); pg.wait_for_timeout(400)
        d2 = pg.locator('.spk-phd')
        t2 = d2.inner_text() if d2.count() else ""
        check(tag + "다른 칩을 누르면 그 소리로 바뀐다", "/iː/" in t2 and "/θ/" not in t2, t2[:60])
        check(tag + "안 들린 소리는 '안 들렸어요'", "안 들렸" in t2, t2[:60])
        check(tag + "들린 소리(heard_as)를 알려준다", "ɪ" in t2, t2[:80])
        pressed = pg.evaluate("() => [...document.querySelectorAll('.spk-ph[aria-pressed=\"true\"]')].map(b => b.dataset.word)")
        check(tag + "같은 기호가 둘이어도 누른 칩만 선택(seat)", pressed == ["seat"], pressed)
        small = pg.evaluate("() => [...document.querySelectorAll('.spk-phd button')].filter(b => b.getBoundingClientRect().height < 43.5).map(b => b.className)")
        check(tag + "패널 버튼은 44px 이상", not small, small)

        pg.locator('.spk-ph[data-ipa="iː"]').first.click(); pg.wait_for_timeout(400)
        check(tag + "같은 칩을 다시 누르면 닫힌다", pg.locator('.spk-phd').count() == 0)
        pg.locator('.spk-ph[data-ipa="ə"]').first.click(); pg.wait_for_timeout(400)
        check(tag + "약한 소리도 열린다", pg.locator('.spk-phd').count() == 1)
        pg.locator('[data-act="spk-ph-close"]').first.click(); pg.wait_for_timeout(400)
        check(tag + "✕ 로 닫힌다", pg.locator('.spk-phd').count() == 0)

        # 라벨 칸 높이는 옆 값(두 줄)에 맞춰 늘어나므로, 글자 자체의 줄 수를 센다(Range 의 줄 상자)
        lab = pg.evaluate("""() => { const k = [...document.querySelectorAll('.spk-row-k')].find(e => e.textContent.startsWith('한 가지만'));
          if (!k) return null; const rg = document.createRange(); rg.selectNodeContents(k);
          return new Set([...rg.getClientRects()].map(r => Math.round(r.top))).size; }""")
        check(tag + "라벨 '한 가지만 확인 부탁드려요'가 한 줄", lab == 1, lab)
        tops = pg.evaluate("() => [...document.querySelectorAll('.spk-row-v')].map(v => Math.round(v.getBoundingClientRect().left))")
        check(tag + "값 칸이 줄마다 같은 위치에서 시작", len(set(tops)) == 1, tops)
        pg.locator('.spk-ph[data-ipa="θ"]').first.click(); pg.wait_for_timeout(300)
        pg.evaluate("(r) => { SPK.result = { ...r, target: curSent().en }; updateSpeakUi(); }", RES); pg.wait_for_timeout(300)
        check(tag + "새 결과가 오면 열린 설명이 닫힌다", pg.locator('.spk-phd').count() == 0)

        m = pg.evaluate("""() => { const c = document.querySelector('.spk-card'); const r = c.getBoundingClientRect();
          return { hs: document.documentElement.scrollWidth - document.documentElement.clientWidth,
                   out: [...c.querySelectorAll('*')].filter(e => { const b = e.getBoundingClientRect();
                     return b.width > 0 && (b.right > r.right + 1 || b.left < r.left - 1); }).length }; }""")
        check(tag + "가로 스크롤 없음", m["hs"] == 0, m)
        check(tag + "패널이 카드 밖으로 넘지 않는다", m["out"] == 0, m)
        check(tag + "JS 오류 없음", not errs, errs)
        pg.close()
    b.close()

print("---")
print("ALL PASS" if not fails else "FAILED: " + ", ".join(fails))
sys.exit(1 if fails else 0)
