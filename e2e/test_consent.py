"""말하기 연습 동의 · AI 표시 E2E (Playwright + Chromium 가짜 마이크).

서버를 API 키 없이(목업 응답) 띄운 뒤 실행한다.
    cd backend && uvicorn app.main:app --port 8768 &
    python ../e2e/test_consent.py http://localhost:8768 /tmp/shots

확인: 동의 전에는 마이크를 열지 않음, 거부·동의·재녹음·철회(복습 목록 삭제), 화면을 다시 그려도 카드 면 유지,
보고서 '예시 데이터' 고지, 로그인 고지, 실제 생성 흐름 후 문장 모음의 샘플/AI 배지.
"""
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = sys.argv[1]
OUT = sys.argv[2] if len(sys.argv) > 2 else "."
results = []


def check(name, cond, extra=""):
    results.append((name, bool(cond), extra))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""))


with sync_playwright() as p:
    # 가짜 마이크에 실제 말소리(TTS "I have a peanut allergy.")를 넣는다 — 서버 Silero VAD 를 통과해야 한다.
    speech_wav = str(Path(__file__).resolve().parents[1] / "backend" / "tests" / "fixtures" / "good.wav")
    b = p.chromium.launch(args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
                                f"--use-file-for-fake-audio-capture={speech_wav}"])
    ctx = b.new_context(viewport={"width": 1400, "height": 1000}, permissions=["microphone"])
    ctx.add_init_script("""
      window.__gum = 0;
      const orig = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
      navigator.mediaDevices.getUserMedia = (c) => { window.__gum++; return orig(c); };
    """)
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    speak_calls = []
    page.on("request", lambda r: speak_calls.append(r.url) if "/speak-check" in r.url else None)

    def flip():
        page.locator('[data-act="flip"]').first.click(position={"x": 30, "y": 30}); page.wait_for_timeout(700)

    page.goto(BASE + "/#u-study")
    page.wait_for_timeout(800)
    flip()
    ls = lambda k: page.evaluate(f"localStorage.getItem('{k}')")
    gum = lambda: page.evaluate("window.__gum")

    btn = page.locator('[data-act="speak-rec"]').first
    check("말해보기 버튼 표시", btn.count() == 1)
    check("녹음 안내에 '처음 녹음할 때 동의'", "처음 녹음할 때 동의" in page.locator(".speak-note").first.inner_text())

    # 1) 첫 클릭: 동의 창, 마이크는 열리지 않음
    btn.click(); page.wait_for_timeout(300)
    modal = page.locator(".modal")
    check("첫 클릭에 동의 창", modal.count() == 1 and "말하기 연습 전에 확인해 주세요" in modal.inner_text())
    check("동의 전 getUserMedia 0회", gum() == 0, f"gum={gum()}")
    page.screenshot(path=f"{OUT}/1_consent_modal.png")
    txt = modal.inner_text()
    for k in ["Google Gemini API", "저장하지 않아요", "사람 검토자", "민감한 개인정보는 말하지 마세요", "철회"]:
        check(f"동의 창에 '{k}'", k in txt)

    # 2) 거부
    page.locator('[data-act="modal-cancel"]').click(); page.wait_for_timeout(300)
    check("거부 후 창 닫힘", page.locator(".modal").count() == 0)
    check("거부 후 동의 저장 없음", ls("cd_consent") is None)
    check("거부 후에도 getUserMedia 0회", gum() == 0)

    # 3) 동의 → 바로 녹음 시작
    page.locator('[data-act="speak-rec"]').first.click(); page.wait_for_timeout(300)
    page.locator('[data-act="modal-ok"]').click(); page.wait_for_timeout(3000)   # 가짜 장치 신호음이 300ms 이상 쌓이도록
    c = json.loads(ls("cd_consent") or "null")
    check("동의 저장 (version 6·voice·at)", c and c.get("voice") is True and c.get("version") == 6 and c.get("at"), str(c))
    check("동의 후 getUserMedia 1회", gum() == 1, f"gum={gum()}")
    check("녹음 중 표시", "녹음 끝내기" in page.locator('[data-act="speak-rec"]').first.inner_text())
    page.screenshot(path=f"{OUT}/2_recording.png")

    # 4) 녹음 끝 → 채점(목업)
    page.locator('[data-act="speak-rec"]').first.click()
    page.wait_for_timeout(2500)
    res = page.locator(".speak-res").first
    check("/speak-check 호출됨", len(speak_calls) == 1, str(len(speak_calls)))
    check("말소리는 VAD 통과 → (키 없는 서버) 샘플 응답, 저장 안 함", res.count() == 1 and "샘플 응답" in res.inner_text() and "저장하지 않았어요" in res.inner_text(), res.inner_text() if res.count() else "")
    check("동의 후 안내 '동의함'", "동의함" in page.locator(".speak-note").first.inner_text())

    # 5) 두 번째 녹음은 창 없이 바로
    page.locator('[data-act="speak-rec"]').first.click(); page.wait_for_timeout(3000)
    check("재녹음 시 동의 창 없음", page.locator(".modal").count() == 0)
    check("재녹음 getUserMedia 2회", gum() == 2, f"gum={gum()}")
    page.locator('[data-act="speak-rec"]').first.click(); page.wait_for_timeout(2500)

    # 6) 홈 카드 + 철회 (복습 목록 하나 넣어 둔 뒤)
    page.evaluate("""localStorage.setItem('cd_weak', JSON.stringify([{category_id:'restaurant',id:'allergy_notice',situation:'알레르기',en:'I am allergic to nuts.',ko:'견과류 알레르기가 있어요.'}]))""")
    page.locator('[data-act="nav"][data-id="u-home"]').click(); page.wait_for_timeout(500)
    home = page.locator(".app").inner_text()
    check("홈에 AI·개인정보 카드", "AI · 개인정보" in home and "동의함" in home and "복습 목록: 1개" in home, home[-200:])
    page.locator('[data-act="consent-withdraw"]').scroll_into_view_if_needed()
    page.screenshot(path=f"{OUT}/3_home_privacy.png")
    page.locator('[data-act="consent-withdraw"]').click(); page.wait_for_timeout(300)
    check("철회 확인 창에 '1개도 함께'", "1개도 함께" in page.locator(".modal").inner_text())
    page.locator('[data-act="modal-ok"]').click(); page.wait_for_timeout(500)
    check("철회 후 동의 삭제", ls("cd_consent") is None)
    check("철회 후 복습 목록 삭제", ls("cd_weak") is None)
    home = page.locator(".app").inner_text()
    check("철회 후 홈 '동의하지 않음'", "동의하지 않음" in home and "복습 목록: 0개" in home)

    # 7) 철회 후 다시 녹음하면 다시 동의 창
    page.locator('[data-act="nav"][data-id="u-study"]').click(); page.wait_for_timeout(500)
    flip()
    page.locator('[data-act="speak-rec"]').first.click(); page.wait_for_timeout(300)
    check("철회 후 다시 동의 창", page.locator(".modal").count() == 1)
    check("철회 후 getUserMedia 증가 없음", gum() == 2, f"gum={gum()}")
    page.locator('[data-act="modal-cancel"]').click()

    # 8) 문구: 보고서는 예시 데이터, 로그인 고지, 문장 모음 배지
    page.goto(BASE + "/?fresh=1#u-report"); page.wait_for_timeout(1200)   # 새 로드 = 새 데모 여행 (보고서 단계)
    check("동의 철회 상태에서 시작 (생성은 동의와 무관)", ls("cd_consent") is None)
    rep = page.locator(".app").inner_text()
    check("보고서 '예시 데이터' 고지", "미리 준비한 예시 데이터" in rep)
    check("보고서에 '웹 검색으로 최신 정보' 없음", "웹 검색으로 최신 정보" not in rep)
    page.screenshot(path=f"{OUT}/4_report.png")
    # 실제 흐름: 장소 확정 → 방문 순서 → 문장 생성(/generate, 목업 서버라 sample)
    gen_calls = []
    page.on("request", lambda r: gen_calls.append(1) if "/generate" in r.url else None)
    page.locator('[data-act="confirm-places"]').click(); page.wait_for_timeout(300)
    page.locator('[data-act="modal-ok"]').click()
    for _ in range(60):
        page.wait_for_timeout(500)
        if page.evaluate("S.trip && S.trip.status") == "studying":
            break
    check("문장 생성까지 완료 + /generate 호출", page.evaluate("S.trip.status") == "studying" and gen_calls, f"calls={len(gen_calls)}")
    page.locator('[data-act="nav"][data-id="u-login"]').click(); page.wait_for_timeout(500)
    login_txt = page.locator(".screen").first.inner_text()
    check("로그인 고지 'AI 생성' 표시 안내", "'AI 생성' 표시" in login_txt)
    check("로그인 고지 문장 생성 시 Gemini 전송", "Google Gemini API로 전송" in login_txt)
    check("로그인 화면에 필수 동의 체크박스 없음", page.locator('.screen input[type="checkbox"]').count() == 0)
    check("로그인 버튼 활성 (동의 없이 이용 가능)", page.locator('[data-act="login"], [data-act="after-login"]').first.is_enabled())
    page.locator('[data-act="nav"][data-id="u-coll"]').click(); page.wait_for_timeout(800)
    page.locator('[data-act="coll-tab"][data-v="place"]').click(); page.wait_for_timeout(300)
    coll = page.locator(".app").inner_text()
    nb = page.locator(".sent .b-sample, .sent .b-ai").count()
    first = page.locator(".sent .b-sample, .sent .b-ai").first
    if nb:
        first.scroll_into_view_if_needed()
    check("문장 모음(장소별) 문장에 샘플/AI 배지 요소", nb > 0, f"badges={nb}")
    page.screenshot(path=f"{OUT}/5_collection.png")

    check("페이지 JS 오류 없음", not errors, "; ".join(errors))
    b.close()

failed = [r for r in results if not r[1]]
print(f"\n{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
