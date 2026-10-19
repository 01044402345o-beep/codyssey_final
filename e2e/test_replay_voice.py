"""내 발음 다시 듣기 E2E — 설문 Q14 "내가 연습한 발음을 들어볼 수 있으면 좋겠습니다"(10/18, 40대).

가짜 마이크(440Hz 신호음)로 실제 MediaRecorder 녹음을 돌린다. 채점은 키 없는 로컬 서버(VAD 판정만).
보는 것: 결과 뒤 '내 발음 듣기'가 뜨는지, 누르면 방금 녹음이 실제로 재생되는지, 녹음이 이 탭 메모리에만
있고(채점 요청 1회 외 전송 없음) 카드를 넘기거나 다시 녹음하면 해제되는지.

    cd backend && uvicorn app.main:app --port 8768
    python ../e2e/test_replay_voice.py http://localhost:8768 [스크린샷 폴더]
"""
import os
import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1]
OUT = sys.argv[2] if len(sys.argv) > 2 else "."
results = []

TONE_MIC = """
  navigator.mediaDevices.getUserMedia = async () => {
    const ctx = new AudioContext();
    const osc = ctx.createOscillator(); osc.frequency.value = 440;
    const gain = ctx.createGain(); gain.gain.value = 0.5;
    const dst = ctx.createMediaStreamDestination();
    osc.connect(gain).connect(dst); osc.start();
    return dst.stream;
  };
"""


def check(name, cond, extra=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""))


def record(page, secs=1.5):
    page.locator('[data-act="speak-rec"]').first.click(); page.wait_for_timeout(int(secs * 1000))
    page.locator('[data-act="speak-rec"]').first.click()
    page.wait_for_function("SPK.state === 'idle' && !!SPK.result", timeout=30000)
    page.wait_for_timeout(200)


BLOB_SIZE = "async (u) => { try { const b = await (await fetch(u)).blob(); return { size: b.size, type: b.type }; } catch (e) { return { gone: true }; } }"

with sync_playwright() as p:
    b = p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
    ctx = b.new_context(viewport={"width": 390, "height": 844})
    ctx.add_init_script(TONE_MIC)
    page = ctx.new_page()
    errors, sent = [], []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("request", lambda r: sent.append(r.url) if r.method == "POST" else None)
    page.goto(BASE + "/?demo=1&frame=1#u-study")
    page.wait_for_timeout(800)
    page.evaluate("S.modal && S.modal.title === '아직 학습일이 아니에요' && ACT['modal-ok']()")   # 미래 날짜 확인 창 → 미리 학습하기
    page.locator('[data-act="flip"]').first.click(position={"x": 30, "y": 30})
    page.wait_for_timeout(600)
    page.locator('[data-act="sheet-open"]').first.click(); page.wait_for_timeout(300)   # 말해보기는 하단 회화 연습 시트 안
    check("녹음 전에는 '내 발음 듣기'가 없다", page.locator('[data-act="play-mine"]').count() == 0)

    page.locator('[data-act="speak-rec"]').first.click(); page.wait_for_timeout(300)
    page.locator('[data-act="modal-ok"]').click(); page.wait_for_timeout(1500)       # 동의 → 녹음 시작
    page.locator('[data-act="speak-rec"]').first.click()
    page.wait_for_function("SPK.state === 'idle' && !!SPK.result", timeout=30000)
    page.wait_for_timeout(200)
    res = page.locator(".speak-res").first.inner_text() if page.locator(".speak-res").count() else ""
    check("결과(말소리 없음 판정 포함) 뒤 '▶ 내 발음 듣기'가 뜬다", page.locator('[data-act="play-mine"]').count() == 1, res)
    url1 = page.evaluate("SPK.clip && SPK.clip.url")
    info = page.evaluate(BLOB_SIZE, url1)
    check("방금 녹음이 이 탭 메모리에 있다(blob: 주소, 크기 > 0)", url1.startswith("blob:") and info.get("size", 0) > 0, f"{url1[:30]} {info}")
    page.screenshot(path=os.path.join(OUT, "replay_voice_390.png"))

    page.locator('[data-act="play-mine"]').click()
    page.wait_for_timeout(700)
    st = page.evaluate("({ src: mineAudio && mineAudio.src, t: mineAudio ? mineAudio.currentTime : -1, paused: mineAudio ? mineAudio.paused : null })")
    check("누르면 방금 녹음을 실제로 재생한다", st["src"] == url1 and st["t"] > 0, str(st))

    posts = [u for u in sent if "/speak-check" not in u and "/user/state" not in u]
    check("녹음은 채점 요청(1회) 외에는 어디로도 보내지 않는다",
          sum(1 for u in sent if "/speak-check" in u) == 1 and not [u for u in posts if "blob" in u], str(sent))

    # 원어민 듣기를 누르면 내 녹음 재생이 멈춘다(겹치지 않게) — 이 브라우저에 음성이 없으면 건너뛴다
    if page.locator('[data-act="speak-card"]').count():
        page.locator('[data-act="play-mine"]').click(); page.wait_for_timeout(200)
        page.locator('[data-act="speak-card"]').click(); page.wait_for_timeout(200)
        check("원어민 '듣기'를 누르면 내 녹음 재생이 멈춘다", page.evaluate("!mineAudio || mineAudio.paused"))

    # 다시 녹음하면 이전 녹음은 해제되고 새 녹음으로 바뀐다
    record(page)
    url2 = page.evaluate("SPK.clip && SPK.clip.url")
    check("다시 녹음: 새 녹음으로 바뀌고 이전 녹음은 해제된다",
          url2 and url2 != url1 and page.evaluate(BLOB_SIZE, url1).get("gone") and page.evaluate(BLOB_SIZE, url2).get("size", 0) > 0, f"{url1[-8:]} -> {(url2 or '')[-8:]}")

    # 카드를 넘기면 녹음이 지워진다
    page.evaluate("ACT['card-next']()")
    page.wait_for_timeout(300)
    check("카드를 넘기면 녹음이 지워진다(버튼 없음, 주소 해제)",
          page.evaluate("SPK.clip") is None and page.locator('[data-act="play-mine"]').count() == 0
          and page.evaluate(BLOB_SIZE, url2).get("gone"), str(page.evaluate("SPK.clip")))

    check("페이지 JS 오류 없음", not errors, "; ".join(errors[:3]))
    b.close()

print(f"\n{sum(ok for _, ok in results)}/{len(results)} passed")
sys.exit(0 if all(ok for _, ok in results) else 1)
