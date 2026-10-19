"""Android 에뮬레이터의 실제 Chrome 으로 배포본을 확인한다 (results.md 6.2, 6-3·6-4).

준비·실행 전체 절차는 docs/user-test/android-emulator.md 를 따른다. 요약:
  - 에뮬레이터 부팅 완료, Chrome 이 확인할 주소를 열어 둔 상태
  - adb forward tcp:9222 localabstract:chrome_devtools_remote

    python e2e/android_emulator_check.py [확인할 주소] [스크린샷 폴더]
    (기본: https://codyssey-final.onrender.com  ./android-shots)

검사: 로그인 없이 시작 · 손님 인사 · 하드웨어 뒤로가기(6-3) · 듣기가 읽는 문장(6-4).
기기 키는 adb 로 보내고(사람 손가락과 같은 경로), 화면 상태는 Chrome 원격 디버깅으로 읽는다.
소리 자체는 듣지 않는다 — 음성 엔진에 넘어가는 문장과 재생 시작까지만 본다.
"""
import os
import shutil
import subprocess
import sys
import time

from playwright.sync_api import sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "https://codyssey-final.onrender.com"
OUT = sys.argv[2] if len(sys.argv) > 2 else "android-shots"
SERIAL = os.environ.get("ANDROID_SERIAL", "emulator-5554")   # adb devices 에 보이는 이름
_home = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT") or ""
ADB = next((p for p in (os.path.join(_home, "platform-tools", "adb.exe"), os.path.join(_home, "platform-tools", "adb")) if _home and os.path.exists(p)), None) or shutil.which("adb")
if not ADB:
    sys.exit("adb 를 찾지 못했습니다. ANDROID_HOME 을 SDK 폴더로 설정하세요.")
os.makedirs(OUT, exist_ok=True)
results = []


def adb(*a):
    return subprocess.run([ADB, "-s", SERIAL, *a], capture_output=True, text=True, timeout=60).stdout


def shot(name):
    # 바이너리(PNG)는 파이썬이 그대로 받아 쓴다. PowerShell 의 '>' 로 받으면 깨질 수 있다.
    data = subprocess.run([ADB, "-s", SERIAL, "exec-out", "screencap", "-p"], capture_output=True, timeout=60).stdout
    with open(os.path.join(OUT, name), "wb") as f:
        f.write(data)


def focused():
    line = next((l for l in adb("shell", "dumpsys", "window").splitlines() if "mCurrentFocus" in l), "")
    return line.strip()


def check(name, ok, extra=""):
    results.append((name, bool(ok)))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{extra}]" if extra else ""), flush=True)


with sync_playwright() as p:
    b = p.chromium.connect_over_cdp("http://localhost:9222")
    ctx = b.contexts[0]
    host = URL.split("//")[-1].split("/")[0]
    page = next((pg for pg in ctx.pages if host in pg.url), None)
    if page is None:
        sys.exit(f"Chrome 탭에서 {host} 를 찾지 못했습니다. 문서 7단계로 주소를 먼저 여세요. 열린 탭: {[pg.url for pg in ctx.pages]}")
    print("url:", page.url)
    print("chrome:", adb("shell", "dumpsys", "package", "com.android.chrome").split("versionName=")[-1].split()[0])
    # 이전 실행의 손님 기록이 남아 있으면 첫 화면이 로그인이 아니다 — 깨끗한 상태에서 시작한다
    page.evaluate("try { localStorage.clear(); sessionStorage.clear(); } catch (e) {}")
    page.reload(); page.wait_for_function("typeof S !== 'undefined' && S.screen", timeout=90000); page.wait_for_timeout(1500)
    shot("01_first.png")

    # --- 로그인 없이 시작 (#99) ---
    check("첫 화면에 '로그인 없이 시작'", page.locator('[data-act="guest"]').count() == 1, page.evaluate("S.screen"))
    page.locator('[data-act="guest"]').click()
    page.wait_for_timeout(800)
    # 학습 화면에 필요한 여행·계획을 규칙으로 준비한다(AI 문장 생성을 부르지 않는다)
    page.evaluate("ensure('plan'); go('u-home')")
    page.wait_for_timeout(800)
    shot("02_home.png")
    body = page.inner_text("body")
    check("홈 인사가 '손님님'이 아님", "손님님" not in body, body[:30].replace("\n", " / "))
    hist0 = page.evaluate("history.length")

    # --- 6-3: 홈 → (하단 탭) 학습 → 하드웨어 뒤로가기 ---
    page.locator('[data-act="tab"][data-id="u-study"]').first.click()
    page.wait_for_timeout(800)
    st = page.evaluate("({ scr: S.screen, hist: history.length })")
    check("탭으로 학습 화면 진입(히스토리 쌓임)", st["scr"] == "u-study" and st["hist"] > hist0, f"{hist0} -> {st}")
    shot("03_study.png")
    adb("shell", "input", "keyevent", "KEYCODE_BACK")
    time.sleep(2)
    check("6-3 뒤로가기: Chrome 이 닫히지 않음", "com.android.chrome" in focused(), focused())
    check("6-3 뒤로가기: 이전 화면(홈)으로", page.evaluate("S.screen") == "u-home", page.evaluate("S.screen"))
    shot("04_after_back.png")

    page.locator('[data-act="tab"][data-id="u-coll"]').first.click(); page.wait_for_timeout(700)
    page.locator('[data-act="drill"][data-v="transit"]').first.click(); page.wait_for_timeout(800)
    adb("shell", "input", "keyevent", "KEYCODE_BACK"); time.sleep(2)
    check("6-3 상황별 연습 → 뒤로가기 → 문장 모음, Chrome 유지",
          page.evaluate("S.screen") == "u-coll" and "com.android.chrome" in focused(), f"{page.evaluate('S.screen')} | {focused()}")

    # --- 6-4: 대중교통 연습 첫 카드 'How do I get to [destination]?' 듣기 ---
    page.evaluate("""() => { window.__said = [];
      const ss = window.speechSynthesis; if (!ss) return;
      const orig = ss.speak.bind(ss);
      ss.speak = u => { window.__said.push({ text: u.text, lang: u.lang, voice: u.voice && u.voice.name }); return orig(u); }; }""")
    page.locator('[data-act="drill"][data-v="transit"]').first.click(); page.wait_for_timeout(800)
    voices = page.evaluate("(window.speechSynthesis && speechSynthesis.getVoices().filter(v => /^en/i.test(v.lang)).map(v => v.name + ' ' + v.lang)) || []")
    print("en voices:", voices)
    page.locator(".flip").first.click(); page.wait_for_timeout(500)
    shot("05_card.png")
    card = page.locator(".flip").first.inner_text()
    btn = page.locator('[data-act="speak-card"]')
    check("6-4 듣기 버튼이 보임(이 기기에 영어 음성 있음)", btn.count() == 1 and len(voices) > 0, f"{len(voices)}개")
    if btn.count():
        btn.first.click(); page.wait_for_timeout(2500)
    said = page.evaluate("window.__said")
    print("spoken:", said)
    en = next((s["text"] for s in said if "get to" in s["text"]), "")
    check("6-4 화면에 [your destination]", "your destination" in card, card.replace("\n", " / ")[:80])
    check("6-4 듣기가 읽는 문장에 'your destination'(대괄호 없이)", "your destination" in en and "[" not in en, en)
    print("speaking right after:", page.evaluate("window.speechSynthesis ? speechSynthesis.speaking || speechSynthesis.pending : null"))
    shot("06_after_speak.png")

print(f"\n{sum(ok for _, ok in results)}/{len(results)} passed  (스크린샷: {os.path.abspath(OUT)})")
sys.exit(0 if all(ok for _, ok in results) else 1)
