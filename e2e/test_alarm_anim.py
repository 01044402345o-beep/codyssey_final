"""오늘의 알람 카드의 움직임 — 계약만 검사한다.

계약:
  1) 종 아이콘·글로우·오늘 막대는 '계속' 돈다(진입과 무관).
  2) 들어오는 동작(숫자·막대·레일)은 화면 진입 1회만 — 카드를 뒤집어 다시 그려도 재생되지 않는다.
  3) prefers-reduced-motion: reduce 면 전부 꺼진다.
  4) 움직여도 글자는 그대로 읽힌다(숫자·단위·라벨).
"""
import sys
from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8899"
fails = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ((" — " + str(extra)) if (extra and not cond) else ""))
    if not cond:
        fails.append(name)


def enter(pg):
    """알람은 덱의 첫 장이다 — resetCard 로 '알람부터' 상태를 만든 뒤 학습 탭으로 들어간다."""
    pg.goto(BASE + "/?demo=1&gate=off"); pg.wait_for_timeout(2300)
    if pg.locator('[data-act="guest"]').count():
        pg.locator('[data-act="guest"]').first.click(); pg.wait_for_timeout(1200)
    pg.evaluate("try{saveConsentHere(true)}catch(e){}; ensure('plan')"); pg.wait_for_timeout(600)
    pg.evaluate("() => { resetCard(S.today); S.studyEntry = 'tab'; go('u-study'); }"); pg.wait_for_timeout(900)
    pg.evaluate("() => { const m = S.modal; if (m) ACT['modal-ok'](); }"); pg.wait_for_timeout(400)
    if pg.locator(".alarm").count() == 0:
        print("   진단:", pg.evaluate("() => ({screen: S.screen, alarm: S.card && S.card.alarm, kind: pickRow() && pickRow().kind, fx: alarmFxPending})"))


def anim(pg, sel):
    return pg.evaluate("(s) => { const e = document.querySelector(s); if (!e) return null; const c = getComputedStyle(e);"
                       " return (c.animationName || 'none') + '|' + (c.animationIterationCount || ''); }", sel)


with sync_playwright() as pw:
    br = pw.chromium.launch()
    pg = br.new_page(viewport={"width": 390, "height": 844})
    enter(pg)
    if pg.locator(".alarm").count() == 0:
        # 알람이 덱 첫 장이 아닌 상태(이미 오늘 학습 완료 등)면 그 자체를 실패로 본다
        check("알람 카드가 학습 화면에 있다", False)
    else:
        check("계속: 종이 흔들린다", "al-ring" in (anim(pg, ".alarm-ic svg") or ""), anim(pg, ".alarm-ic svg"))
        check("계속: 글로우가 숨쉰다", "al-breathe" in (anim(pg, ".alarm::after") or "") or
              "al-breathe" in pg.evaluate("() => getComputedStyle(document.querySelector('.alarm'), '::after').animationName"), anim(pg, ".alarm::after"))
        check("계속: 오늘 막대가 숨쉰다", "al-today" in (anim(pg, ".alarm-week i.today") or ""), anim(pg, ".alarm-week i.today"))
        check("한 번: 진입 직후 숫자가 떠오른다", "al-rise" in (anim(pg, ".alarm-big") or ""), anim(pg, ".alarm-big"))
        check("한 번: 막대가 순서대로 자란다",
              pg.evaluate("() => [...document.querySelectorAll('.alarm-week i')].every(e => getComputedStyle(e).animationName.includes('al-bar'))"))
        check("막대 순번(--i)이 붙어 있다",
              pg.evaluate("() => { const b = [...document.querySelectorAll('.alarm-week i')]; return b.length === 7 && b.every((e, k) => e.style.getPropertyValue('--i') === String(k)); }"))

        big_before = pg.inner_text(".alarm-big").strip()
        label_before = pg.inner_text(".alarm-label").strip()

        # 카드를 뒤집어 다시 그려도 '들어오는' 동작은 재생되지 않는다
        pg.evaluate("() => ACT['alarm-next']()"); pg.wait_for_timeout(600)
        later = pg.evaluate("() => { const e = document.querySelector('.alarm'); return e ? e.classList.contains('alarm-fx') : null; }")
        check("다시 그려도 들어오는 동작은 재생되지 않는다", later in (False, None), later)

        check("움직여도 숫자는 그대로 읽힌다", big_before.endswith("/10장") and big_before[0].isdigit(), big_before)
        check("움직여도 라벨이 읽힌다", len(label_before) > 4, label_before)
    pg.close()

    # reduced motion
    pg = br.new_page(viewport={"width": 390, "height": 844}, reduced_motion="reduce")
    enter(pg)
    if pg.locator(".alarm").count():
        names = pg.evaluate("""() => ['.alarm-ic svg', '.alarm-big', '.alarm-week i.today', '.alarm-rail i']
          .map(s => { const e = document.querySelector(s); return e ? getComputedStyle(e).animationName : 'x'; })""")
        check("reduced motion: 애니메이션 전부 없음", all(n in ("none", "x") for n in names), names)
    pg.close()
    br.close()

print("---")
print("ALL PASS" if not fails else "FAILED: " + ", ".join(fails))
sys.exit(1 if fails else 0)
