"""무음 녹음 E2E (Playwright + Chromium).

마이크를 '소리 없는 스트림'으로 바꿔 녹음한다. 무음은 서버·AI 로 보내지 않아야 한다.
(목표 문장을 함께 준 AI 는 무음에도 목표 문장을 들었다고 지어냈다 — 배포 실측 10/10, 95~100점.)

    cd backend && uvicorn app.main:app --port 8768 &
    python ../e2e/test_silence.py http://localhost:8768 /tmp/shots
"""
import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1]
OUT = sys.argv[2] if len(sys.argv) > 2 else "."
results = []


def check(name, cond, extra=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""))


SILENT_MIC = """
  window.__gum = 0;
  navigator.mediaDevices.getUserMedia = async () => {
    window.__gum++;
    const ctx = new AudioContext();
    return ctx.createMediaStreamDestination().stream;   // 아무것도 연결하지 않음 = 완전 무음
  };
"""

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1400, "height": 1000})
    ctx.add_init_script(SILENT_MIC)
    page = ctx.new_page()
    errors, speak_calls = [], []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("request", lambda r: speak_calls.append(r.url) if "/speak-check" in r.url else None)

    page.goto(BASE + "/#u-study")
    page.wait_for_timeout(800)
    page.locator('[data-act="flip"]').first.click(position={"x": 30, "y": 30})
    page.wait_for_timeout(700)

    page.locator('[data-act="speak-rec"]').first.click(); page.wait_for_timeout(300)
    check("동의 창", page.locator(".modal").count() == 1)
    check("동의 창에 '받아쓰기만' 처리 안내", "받아쓰기만" in page.locator(".modal").inner_text())
    page.locator('[data-act="modal-ok"]').click(); page.wait_for_timeout(1500)   # 1.5초 무음 녹음
    check("녹음 시작 (무음 마이크)", "녹음 끝내기" in page.locator('[data-act="speak-rec"]').first.inner_text())
    page.locator('[data-act="speak-rec"]').first.click(); page.wait_for_timeout(1500)

    res = page.locator(".speak-res").first
    txt = res.inner_text() if res.count() else ""
    check("무음은 /speak-check 호출 0회", len(speak_calls) == 0, str(len(speak_calls)))
    check("'목소리가 들리지 않았어요' 안내", "목소리가 들리지 않았어요" in txt, txt)
    check("'전송하지 않았어요' 명시", "전송하지 않았어요" in txt)
    check("점수 표시 없음", "단어 일치" not in txt and "점수" not in txt)
    check("복습 목록 저장 없음", page.evaluate("localStorage.getItem('cd_weak')") in (None, "[]"))
    page.screenshot(path=f"{OUT}/silence_result.png")

    # 다시 시도할 수 있다 (상태가 idle 로 돌아옴)
    check("다시 말해보기 가능", "말해보기" in page.locator('[data-act="speak-rec"]').first.inner_text())

    check("페이지 JS 오류 없음", not errors, "; ".join(errors))
    b.close()

failed = [r for r in results if not r[1]]
print(f"\n{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
