"""무음 녹음 E2E (Playwright + Chromium).

마이크를 '소리 없는 스트림'으로 바꿔 녹음한다. 녹음은 우리 서버까지 가지만, 서버의 Silero 신경망
VAD 가 말소리 없음으로 판정해 전사·피드백 AI 를 부르지 않아야 한다(데시벨 판정 아님).
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
  window.__micMode = 'silent';
  navigator.mediaDevices.getUserMedia = async () => {
    window.__gum++;
    // 실제 마이크처럼 오디오 프레임이 계속 나오는 스트림. silent: 크기 0(디지털 무음), tone: 큰 440Hz 신호음.
    const ctx = new AudioContext();
    const osc = ctx.createOscillator(); osc.frequency.value = 440;
    const gain = ctx.createGain(); gain.gain.value = window.__micMode === 'tone' ? 0.5 : 0.0;
    const dst = ctx.createMediaStreamDestination();
    osc.connect(gain).connect(dst); osc.start();
    return dst.stream;
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
    speak_json = []
    page.on("response", lambda r: speak_json.append(r) if "/speak-check" in r.url else None)

    page.goto(BASE + "/#u-study")
    page.wait_for_timeout(800)
    page.locator('[data-act="flip"]').first.click(position={"x": 30, "y": 30})
    page.wait_for_timeout(700)

    page.locator('[data-act="speak-rec"]').first.click(); page.wait_for_timeout(300)
    check("동의 창", page.locator(".modal").count() == 1)
    check("동의 창에 '말소리가 있을 때만' 전송 안내", "말소리가 있을 때만" in page.locator(".modal").inner_text())
    page.locator('[data-act="modal-ok"]').click(); page.wait_for_timeout(1500)   # 1.5초 무음 녹음
    check("녹음 시작 (무음 마이크)", "녹음 끝내기" in page.locator('[data-act="speak-rec"]').first.inner_text())
    page.locator('[data-act="speak-rec"]').first.click(); page.wait_for_timeout(1500)

    res = page.locator(".speak-res").first
    txt = res.inner_text() if res.count() else ""
    check("녹음은 서버로 1회 전송", len(speak_calls) == 1, str(len(speak_calls)))
    check("서버 VAD 판정 '음성이 인식되지 않았습니다'", "음성이 인식되지 않았습니다" in txt, txt)
    check("목업(샘플) 응답이 아님 = 키 없이도 VAD 가 판정", "샘플 응답" not in txt)
    body = speak_json[0].json() if speak_json else {}
    check("서버 응답 vad.speech_sec == 0 (Silero)", body.get("vad", {}).get("speech_sec") == 0
          and "silero" in body.get("vad", {}).get("engine", ""), str(body.get("vad")))
    check("서버 응답에 전사(stt) 결과 없음", "stt" not in body)
    check("점수 표시 없음", "단어 일치" not in txt and "점수" not in txt)
    check("복습 목록 저장 없음", page.evaluate("localStorage.getItem('cd_weak')") in (None, "[]"))
    page.screenshot(path=f"{OUT}/silence_result.png")

    # 큰 440Hz 신호음 — 데시벨 기준이면 '소리 있음'으로 통과했을 입력. Silero 는 말소리가 아니라고 본다.
    page.evaluate("window.__micMode = 'tone'")
    speak_json.clear(); speak_calls.clear()
    page.locator('[data-act="speak-rec"]').first.click(); page.wait_for_timeout(1500)
    page.locator('[data-act="speak-rec"]').first.click(); page.wait_for_timeout(2000)
    tone_txt = page.locator(".speak-res").first.inner_text()
    tone = speak_json[0].json() if speak_json else {}
    check("큰 신호음: 서버로 1회 전송", len(speak_calls) == 1, str(len(speak_calls)))
    check("큰 신호음: Silero 말소리 0초 → '음성이 인식되지 않았습니다'",
          tone.get("vad", {}).get("speech_sec") == 0 and tone.get("vad", {}).get("duration_sec", 0) > 0.5
          and "음성이 인식되지 않았습니다" in tone_txt, f"{tone.get('vad')} / {tone_txt}")

    # 다시 시도할 수 있다 (상태가 idle 로 돌아옴)
    check("다시 말해보기 가능", "말해보기" in page.locator('[data-act="speak-rec"]').first.inner_text())

    check("페이지 JS 오류 없음", not errors, "; ".join(errors))
    b.close()

failed = [r for r in results if not r[1]]
print(f"\n{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
