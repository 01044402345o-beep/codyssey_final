"""말해보기 결과 카드(인포그래픽). 서버 응답 대신 결과를 직접 넣어 화면만 본다 — STT·음소 노드를 부르지 않는다.

    cd backend && uvicorn app.main:app --port 8768
    python ../e2e/test_speak_card.py http://localhost:8768 [스크린샷 폴더]
"""
import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1]
OUT = sys.argv[2] if len(sys.argv) > 2 else None
results = []


def check(name, cond, extra=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""))


IPA = [("k", "can"), ("æ", "can"), ("n", "can"), ("aɪ", "i"), ("h", "have"), ("æ", "have"), ("v", "have"), ("ə", "a"),
       ("w", "window"), ("ɪ", "window"), ("n", "window"), ("d", "window"), ("oʊ", "window"),
       ("s", "seat"), ("iː", "seat"), ("t", "seat"), ("p", "please"), ("l", "please"), ("iː", "please"), ("z", "please")]
ROWS = [{"ipa": i, "word": w, "status": "missing" if (w, i) == ("seat", "iː") else "ok", "gop": 0.9,
         "heard_as": "ɪ" if (w, i) == ("seat", "iː") else None} for i, w in IPA]
BASE_RES = {"usable": True, "cross_validated": True, "score": 86, "score_kind": "word_match_consensus",
            "heard": "Can I have a window sit, please?", "diff": {"missing": ["seat"], "extra": [], "replaced": [["seat", "sit"]]},
            "fix_one": "'seat'의 '이' 소리를 길게 말해 보세요.", "tip": "듣기 버튼으로 원어민 발음을 들은 뒤 따라 말해 보세요."}
WITH = {**BASE_RES, "phonemes_acoustic": {"status": "ok", "basis": "acoustic", "via": "remote", "phoneme_accuracy": 95.0,
        "phonemes": ROWS, "focus": {"ipa": "iː", "word": "seat", "heard_as": "ɪ", "label": "이(길게)", "tip": "입꼬리를 옆으로 당기고 길게."}}}
NODE_DOWN = {**BASE_RES, "phonemes_acoustic": {"status": "unavailable", "reason": "all_nodes_failed", "via": "remote"}}
LIMITED = {"usable": True, "limited": True, "cross_validated": False, "score": None, "heard": "Can I have a window sit",
           "reason": "음성 확인이 제한되어 점수와 자동 복습 저장을 제공하지 않습니다."}

CARD = '[data-live="speak-res"][data-k="me"] .spk-card'
INFO = """() => { const c = document.querySelector('[data-live="speak-res"][data-k="me"] .spk-card');
  const res = document.querySelector('[data-live="speak-res"][data-k="me"] .speak-res');
  const fh = c && c.querySelector('.spk-focus-h');
  return { card: !!c, text: res ? res.innerText : '', tag: c && c.querySelector('.spk-tag') ? c.querySelector('.spk-tag').textContent : null,
    miss: c ? [...c.querySelectorAll('.spk-w.miss')].map(e => e.textContent) : [],
    chips: c ? c.querySelectorAll('.spk-ph').length : 0, bad: c ? [...c.querySelectorAll('.spk-ph.missing')].map(e => e.textContent) : [],
    bars: c ? [...c.querySelectorAll('.spk-bar-l')].map(e => e.textContent) : [],
    focusLines: fh ? Math.round(fh.getBoundingClientRect().height / parseFloat(getComputedStyle(fh).lineHeight || 20)) : 0,
    chipsVisible: c ? [...c.querySelectorAll('.spk-ph')].every(e => { const r = e.getBoundingClientRect(), p = c.getBoundingClientRect(); return r.right <= p.right + 1 && r.left >= p.left - 1; }) : null,
    hscroll: document.documentElement.scrollWidth - document.documentElement.clientWidth }; }"""


def show(pg, res):
    pg.evaluate("(r) => { const s = curSent(); SPK.sid = s.id; SPK.line = 'me'; SPK.state = 'idle'; SPK.result = { ...r, target: s.en }; updateSpeakUi(); }", res)
    pg.wait_for_timeout(250)
    return pg.evaluate(INFO)


with sync_playwright() as p:
    b = p.chromium.launch()
    for scheme in ("light", "dark"):
        pg = b.new_page(viewport={"width": 390, "height": 844}, color_scheme=scheme)
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(BASE + "/?demo=1&gate=off"); pg.wait_for_timeout(2500)
        if pg.locator('[data-act="guest"]').count():
            pg.locator('[data-act="guest"]').first.click(); pg.wait_for_timeout(1200)
        pg.evaluate("try{saveConsentHere(true)}catch(e){}; ensure('plan'); navFromMenu('u-study')"); pg.wait_for_timeout(1200)
        pg.evaluate("S.modal && ACT['modal-ok'] && ACT['modal-ok']()"); pg.wait_for_timeout(300)
        pg.locator('[data-act="flip"]').first.click(); pg.wait_for_timeout(300)
        pg.locator('[data-act="sheet-open"]').first.click(); pg.wait_for_timeout(600)
        target = pg.evaluate("curSent().en")
        tag = f"{scheme}: "

        r = show(pg, WITH)
        check(tag + "음소 결과 있으면 카드", r["card"])
        check(tag + "'발음 점수 아님' 꼬리표", r["tag"] == "발음 점수 아님", str(r["tag"]))
        check(tag + "지표 두 개(단어 일치·음소 일치)", r["bars"] == ["단어 일치", "음소 일치"], str(r["bars"]))
        check(tag + "목표 문장에서 안 들린 단어만 표시", r["miss"] == ["seat,"], str(r["miss"]))
        check(tag + "음소 칩 20개, 틀린 소리 iː 하나", r["chips"] == 20 and r["bad"] == ["iː"], f"{r['chips']} {r['bad']}")
        check(tag + "음소 칩이 모두 카드 안에 보인다(줄바꿈, 가로로 밀리지 않음)", r["chipsVisible"] is True)
        check(tag + "고칠 소리 제목 한 줄", r["focusLines"] == 1, str(r["focusLines"]))
        check(tag + "가로 스크롤 없음", r["hscroll"] == 0, str(r["hscroll"]))
        check(tag + "점수를 '점수 N'으로 쓰지 않는다", "점수 86" not in r["text"], r["text"][:80])
        if OUT:
            pg.locator(CARD).first.screenshot(path=f"{OUT}/speak_card_{scheme}.png")

        # 값('100%')이 한 줄 — 글꼴이 넓은 기기(iPhone)·글자 키움에서도. 320px + 글자 150% 로 재현한다
        show(pg, {**WITH, "score": 100})
        pg.set_viewport_size({"width": 320, "height": 700})
        pg.add_style_tag(content="html{font-size:150%}")
        pg.wait_for_timeout(200)
        bars = pg.evaluate("""() => [...document.querySelectorAll('[data-live="speak-res"][data-k="me"] .spk-metric')].map(b => {
          const v = b.querySelector('.spk-bar-v'), l = b.querySelector('.spk-bar-l'), t = b.querySelector('.spk-track');
          const lh = parseFloat(getComputedStyle(v).lineHeight) || parseFloat(getComputedStyle(v).fontSize) * 1.3;
          const vr = v.getBoundingClientRect(), br = b.getBoundingClientRect();
          return { text: v.textContent, oneLine: vr.height < lh * 1.6, inside: vr.right <= br.right + 1, track: Math.round(t.getBoundingClientRect().width),
                   labelOneLine: l.getBoundingClientRect().height < lh * 1.6 }; })""")
        check(tag + "막대 값 '100%' 한 줄(320px·글자 150%)", bars and all(x["oneLine"] and x["inside"] for x in bars), str(bars))
        check(tag + "막대 이름 한 줄·막대가 남는다", bars and all(x["labelOneLine"] and x["track"] >= 40 for x in bars), str(bars))
        pg.set_viewport_size({"width": 390, "height": 844})
        pg.reload(); pg.wait_for_timeout(2000)
        if pg.locator('[data-act="guest"]').count():
            pg.locator('[data-act="guest"]').first.click(); pg.wait_for_timeout(1000)
        pg.evaluate("try{saveConsentHere(true)}catch(e){}; ensure('plan'); navFromMenu('u-study')"); pg.wait_for_timeout(1000)
        pg.evaluate("S.modal && ACT['modal-ok'] && ACT['modal-ok']()"); pg.wait_for_timeout(300)
        pg.locator('[data-act="flip"]').first.click(); pg.wait_for_timeout(300)
        pg.locator('[data-act="sheet-open"]').first.click(); pg.wait_for_timeout(600)

        r = show(pg, NODE_DOWN)
        check(tag + "노드 실패면 음소 줄 없이 카드(단어 쪽만)", r["card"] and r["chips"] == 0 and r["bars"] == ["단어 일치"], str(r["bars"]))
        check(tag + "노드 실패에도 안 들린 단어 표시", r["miss"] == ["seat,"])

        r = show(pg, LIMITED)
        check(tag + "제한 모드는 카드 아님(점수 없음, 글 그대로)", not r["card"] and "제한" in r["text"], r["text"][:60])
        check(tag + "자바스크립트 오류 없음", not errors, str(errors))
        pg.close()
    b.close()

ok = sum(1 for _, c in results if c)
print(f"\n{ok}/{len(results)} passed")
sys.exit(0 if ok == len(results) else 1)
