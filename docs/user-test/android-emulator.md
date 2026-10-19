# Android 에뮬레이터로 배포본 확인하기 (터미널만 사용)

문서 목록: [docs/README.md](../README.md) · 결과 기록: [results.md](results.md) 6.2절

Android Studio 없이 **PowerShell 명령만으로** Android SDK·에뮬레이터를 설치하고, 가상 휴대폰의 **실제 Chrome** 에서 배포본(https://codyssey-final.onrender.com)을 열어 확인하는 방법이다. Android 를 한 번도 설치해 본 적 없는 사람을 기준으로 쓴다. 관리자 권한은 필요 없다(가상화가 꺼져 있을 때만 예외 — 5단계).

10/18 에 이 순서 그대로 Windows 11 에서 실행해 6-3(하드웨어 뒤로가기)·6-4(듣기 'your destination')를 확인했다. 확인 결과는 results.md 6.2절에 있다.

> **에뮬레이터는 실기기가 아니다.** 같은 Android·Chrome 코드가 돌지만 카메라·마이크·소리·성능은 다르다. 결과는 "에뮬레이터 확인"으로 적고 "실기기 확인"과 섞지 않는다.

---

## 0. 무엇이 설치되나

| 구성 | 용도 | 크기(10/18 실측) | 설치 위치 |
|---|---|---|---|
| JDK 17 (Eclipse Temurin, zip) | SDK 명령줄 도구가 Java 로 돈다 | 내려받기 182 MB → 풀면 303 MB | `%LOCALAPPDATA%\Android\jdk` |
| Android SDK Command-line Tools 12.0 | `sdkmanager`·`avdmanager` | 146 MB | `%LOCALAPPDATA%\Android\Sdk\cmdline-tools\latest` |
| platform-tools (adb 1.0.41) | 가상 폰에 명령 보내기·화면 캡처 | 수십 MB | `...\Sdk\platform-tools` |
| emulator 37.2 | 가상 폰 실행기 | 수백 MB | `...\Sdk\emulator` |
| 시스템 이미지 Android 14, Google Play, x86_64 | 가상 폰의 OS (Chrome·Google TTS 포함) | 약 3.5 GB | `...\Sdk\system-images\android-34\google_apis_playstore\x86_64` |
| 가상 기기(AVD) `codyssey_pixel` | Pixel 6 화면 크기의 폰 한 대 | 부팅 후 약 4 GB 까지 커짐 | `%USERPROFILE%\.android\avd` |

**합계 약 9 GB.** 디스크 여유 15 GB 이상, 메모리 8 GB 이상(16 GB 권장)인 PC 에서 한다. 시간은 네트워크에 따라 다르다 — 내려받기·설치 10~30분, 첫 부팅 약 3.5분(10/18 실측 205초).

---

## 1. 준비물 확인

PowerShell 을 연다(시작 → "PowerShell" 검색 → 그냥 실행. 관리자 아님).

```powershell
# 디스크 여유(GB)와 메모리(GB)
Get-PSDrive C | % { "{0:N1} GB free" -f ($_.Free/1GB) }
"{0:N1} GB RAM" -f ((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory/1GB)
# 하이퍼바이저가 켜져 있는가 (True 여야 에뮬레이터가 빠르게 돈다)
(Get-CimInstance Win32_ComputerSystem).HypervisorPresent
```

`HypervisorPresent` 가 `False` 여도 일단 진행한다. 5단계에서 정확히 확인하고 고친다.

9단계의 확인 스크립트는 Python 3.11 과 Playwright 패키지로 돈다. 저장소 루트에서 한 번만(이미 `backend\.venv` 가 있으면 건너뛴다):

```powershell
python --version                                   # 3.11.x (없으면 python.org 에서 설치)
python -m venv backend\.venv
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt playwright==1.63.0
```

**`playwright install` 은 하지 않아도 된다** — 에뮬레이터 속 Chrome 에 붙기 때문에 PC 용 브라우저를 쓰지 않는다.

---

## 2. 경로 변수 — 새 PowerShell 창마다 먼저 붙여 넣기

아래 모든 단계는 이 변수들을 쓴다. **창을 새로 열면 다시 붙여 넣는다**(PowerShell 변수는 창을 닫으면 사라진다). 시스템 환경 변수는 바꾸지 않는다 — 나중에 폴더만 지우면 흔적이 없다.

```powershell
$base = "$env:LOCALAPPDATA\Android"
$env:ANDROID_HOME     = "$base\Sdk"
$env:ANDROID_SDK_ROOT = "$base\Sdk"
if (Test-Path "$base\jdk") { $env:JAVA_HOME = (Get-ChildItem "$base\jdk" -Directory | Select-Object -First 1).FullName }
$sdkm = "$base\Sdk\cmdline-tools\latest\bin\sdkmanager.bat"
$avdm = "$base\Sdk\cmdline-tools\latest\bin\avdmanager.bat"
$emu  = "$base\Sdk\emulator\emulator.exe"
$adb  = "$base\Sdk\platform-tools\adb.exe"
```

---

## 3. JDK 17 과 SDK 명령줄 도구 내려받기

설치 프로그램(MSI) 대신 zip 을 받아 사용자 폴더에 푼다. 그래서 관리자 권한이 없어도 된다.

```powershell
$ProgressPreference = 'SilentlyContinue'   # 진행 막대를 끄면 내려받기가 훨씬 빠르다
New-Item -ItemType Directory -Force "$base\dl_jdk", "$base\dl_tools", "$base\Sdk\cmdline-tools" | Out-Null

# JDK 17 (Adoptium 공식 API — 항상 17 의 최신 GA zip)
Invoke-WebRequest 'https://api.adoptium.net/v3/binary/latest/17/ga/windows/x64/jdk/hotspot/normal/eclipse' -OutFile "$base\dl_jdk\jdk17.zip"
# Android SDK Command-line Tools (Google 공식)
Invoke-WebRequest 'https://dl.google.com/android/repository/commandlinetools-win-11076708_latest.zip' -OutFile "$base\dl_tools\cmdline-tools.zip"

Expand-Archive "$base\dl_jdk\jdk17.zip" "$base\jdk" -Force
Expand-Archive "$base\dl_tools\cmdline-tools.zip" "$base\dl_tools\x" -Force
# 중요: zip 안의 'cmdline-tools' 폴더를 반드시 'cmdline-tools\latest' 로 옮긴다
# (이 블록을 두 번째 실행한다면 이미 latest 가 있어 실패한다 — 그때는 이 줄을 건너뛴다)
Move-Item "$base\dl_tools\x\cmdline-tools" "$base\Sdk\cmdline-tools\latest"
```

**2단계 블록을 한 번 더 붙여 넣는다**(이제 `jdk` 폴더가 생겨서 `JAVA_HOME` 이 잡힌다). 그다음 확인:

```powershell
& "$env:JAVA_HOME\bin\java.exe" -version     # openjdk version "17.x" 가 나와야 한다
Test-Path $sdkm                               # True
```

> **함정 — 폴더 구조.** `sdkmanager` 는 자기가 `Sdk\cmdline-tools\latest\bin\` 에 있을 때만 SDK 위치를 제대로 안다. zip 을 `Sdk\cmdline-tools\` 에 그냥 풀면 `cmdline-tools\cmdline-tools\bin` 이 되어 "Could not determine SDK root" 오류가 난다.

---

## 4. 라이선스 동의와 패키지 설치

```powershell
# 라이선스: 질문마다 y 를 넣어 준다(질문이 여러 개라 y 를 넉넉히 보낸다)
(1..30 | % { 'y' }) -join "`n" | & $sdkm --sdk_root="$base\Sdk" --licenses
# 마지막 줄에 "All SDK package licenses accepted" 가 나오면 된다

# 에뮬레이터 · adb · Android 14(Google Play 포함) 시스템 이미지 — 약 4 GB, 10분 안팎
& $sdkm --sdk_root="$base\Sdk" "platform-tools" "emulator" "system-images;android-34;google_apis_playstore;x86_64"
```

확인:

```powershell
Test-Path $emu; Test-Path $adb
Test-Path "$base\Sdk\system-images\android-34\google_apis_playstore\x86_64\system.img"   # 셋 다 True
```

> **왜 `google_apis_playstore` 인가.** 이 이미지에만 **Chrome** 과 **Google TTS(영어 음성)** 가 들어 있다. `google_apis`(Play 없음)나 `default` 이미지는 기본 브라우저가 Chrome 이 아니거나 영어 음성이 없어 6-4(듣기)를 확인할 수 없다.
>
> **함정 — 멈춘 것처럼 보임.** 설치 중에는 진행 막대 줄만 갱신되어 화면이 멈춘 것처럼 보일 수 있다. 확인하려면 다른 창에서 폴더 크기가 느는지 본다:
> `"{0:N0} MB" -f ((Get-ChildItem "$env:LOCALAPPDATA\Android\Sdk" -Recurse -File | Measure-Object Length -Sum).Sum/1MB)`

---

## 5. 하드웨어 가속 확인

```powershell
& $emu -accel-check
```

| 출력 | 뜻 | 할 일 |
|---|---|---|
| `WHPX(...) is installed and usable.` | 정상(10/18 이 PC 는 이것) | 6단계로 |
| WHPX·AEHD 를 쓸 수 없다는 내용 | Windows 하이퍼바이저 플랫폼이 꺼져 있음 | 아래 |

꺼져 있으면 **관리자 PowerShell** 에서 한 번 켜고 재부팅한다(이 문서에서 관리자 권한이 필요한 유일한 곳):

```powershell
Enable-WindowsOptionalFeature -Online -FeatureName HypervisorPlatform -All
```

재부팅 후에도 안 되면 BIOS/UEFI 에서 CPU 가상화(Intel VT-x / AMD SVM)가 꺼져 있는 것이다. 작업 관리자 → 성능 → CPU 의 "가상화: 사용" 으로 확인한다.

---

## 6. 가상 기기(AVD) 만들기

```powershell
"no" | & $avdm create avd -n codyssey_pixel -k "system-images;android-34;google_apis_playstore;x86_64" -d pixel_6 --force
& $emu -list-avds          # codyssey_pixel 이 보이면 된다
```

`"no"` 는 "사용자 지정 하드웨어 프로필을 만들까요?" 질문에 대한 답이다. `-d pixel_6` 이 화면 1080×2400, 420dpi(Pixel 6)를 정한다.

---

## 7. 부팅하고 Chrome 으로 사이트 열기

### 7-1. 부팅

```powershell
Start-Process "$emu" -ArgumentList '-avd','codyssey_pixel','-no-snapshot','-no-boot-anim','-gpu','swiftshader_indirect','-netdelay','none','-netspeed','full'

$t0 = Get-Date
do {
  Start-Sleep 5
  # 'device' 상태인 에뮬레이터 이름을 찾는다(offline 줄이 섞여 있어도 된다)
  $dev = if ("$(& $adb devices)" -match '(emulator-\d+)\s+device\b') { $Matches[1] } else { '' }
  $b = if ($dev) { "$(& $adb -s $dev shell getprop sys.boot_completed 2>$null)".Trim() } else { '' }
} until ($b -eq '1' -or ((Get-Date) - $t0).TotalSeconds -gt 600)
"device=$dev boot_completed=$b ({0:N0}s)" -f ((Get-Date) - $t0).TotalSeconds
```

- 폰 모양 창이 뜬다. 첫 부팅은 3~4분. `boot_completed=1` 이 나오면 끝.
- 옵션 뜻: `-no-snapshot` 매번 새로 부팅(이전 상태가 섞이지 않게), `-no-boot-anim` 부팅 애니메이션 생략, `-gpu swiftshader_indirect` 그래픽을 CPU 로 그려 그래픽 드라이버 문제를 피함, `-netdelay none -netspeed full` 네트워크 지연 없음.
- 창은 마우스로 직접 눌러도 된다(손가락 대신). 오른쪽 세로 막대의 `◁` 가 하드웨어 뒤로가기, `○` 가 홈이다.

### 7-2. 어느 기기에 명령을 보낼지 확인

```powershell
& $adb devices -l
```

`emulator-5554  device` 가 보이면 된다. **다른 줄이 더 있으면**(10/18 에는 `emulator-5562 offline` 이 함께 보였다. 연결된 실제 폰도 여기 나온다) `-s` 없는 adb 명령은 `error: more than one device/emulator` 로 실패한다. 그래서 아래 명령은 모두 `-s $dev` 를 붙인다. `$dev` 는 7-1 루프가 채운다. 창을 새로 열었다면 직접 넣는다:

```powershell
$dev = 'emulator-5554'   # 위 목록에서 'device' 상태인 에뮬레이터 이름
```

### 7-3. Chrome 첫 실행 안내 끄고 사이트 열기

새 기기의 Chrome 은 처음에 "Chrome 에 오신 것을 환영합니다·동기화" 같은 첫 실행 화면을 띄워 자동 확인을 막는다. 명령줄 플래그로 끈다.

```powershell
& $adb -s $dev shell 'echo "_ --disable-fre --no-default-browser-check --no-first-run" > /data/local/tmp/chrome-command-line'
& $adb -s $dev shell am set-debug-app --persistent com.android.chrome   # 위 플래그 파일을 Chrome 이 읽게 한다
& $adb -s $dev shell am force-stop com.android.chrome
& $adb -s $dev shell am start -a android.intent.action.VIEW -d 'https://codyssey-final.onrender.com/' com.android.chrome
```

10~20초 기다린 뒤 지금 맨 앞 화면이 Chrome 인지 확인한다:

```powershell
& $adb -s $dev shell dumpsys window | Select-String mCurrentFocus
# ...com.android.chrome/org.chromium.chrome.browser.ChromeTabbedActivity 가 나오면 된다
```

> **함정 — 다른 화면이 앞에 있음.** 10/18 에는 Chrome 의 '앱 정보' 설정 화면이 앞에 떠 있었다. 홈으로 갔다가 다시 연다:
> `& $adb -s $dev shell input keyevent KEYCODE_HOME` 뒤에 위 `am start` 줄을 한 번 더.
>
> Render 무료 서버는 한동안 요청이 없으면 잠든다. 첫 화면이 30초 넘게 비어 있으면 PC 브라우저로 `https://codyssey-final.onrender.com/health` 를 한 번 열어 깨운다.

### 7-4. 화면 캡처 (선택)

```powershell
& $adb -s $dev shell screencap -p /sdcard/s.png
& $adb -s $dev pull /sdcard/s.png "$env:USERPROFILE\Desktop\emulator.png"
```

> **함정 — PNG 가 깨짐.** `adb exec-out screencap -p > 파일.png` 를 PowerShell 에서 그대로 쓰면 `>` 가 바이너리를 글자로 바꿔 저장해 PNG 가 깨질 수 있다. 위처럼 기기에 저장한 뒤 `pull` 로 가져온다(확인 스크립트는 파이썬이 바이트를 직접 받아 쓰므로 괜찮다).

---

## 8. Chrome 원격 디버깅 연결

에뮬레이터 속 Chrome 은 디버깅 소켓을 열어 둔다. PC 의 9222 포트로 연결하면 PC 에서 그 탭의 화면 상태를 읽을 수 있다.

```powershell
& $adb -s $dev forward tcp:9222 localabstract:chrome_devtools_remote
(Invoke-RestMethod http://localhost:9222/json) | % { "$($_.type) $($_.url)" }
# page https://codyssey-final.onrender.com/ 이 보이면 된다
```

PC 의 데스크톱 Chrome 주소창에 `chrome://inspect/#devices` 를 열면 같은 탭이 보이고, "inspect" 로 개발자 도구를 띄울 수도 있다(사람이 직접 볼 때).

---

## 9. 확인 스크립트 실행

저장소 루트에서(경로 변수 블록을 붙여 넣은 같은 창):

```powershell
$env:ANDROID_SERIAL = $dev
$env:PYTHONIOENCODING = 'utf-8'      # 한국어 출력이 깨지지 않게
backend\.venv\Scripts\python.exe e2e\android_emulator_check.py https://codyssey-final.onrender.com android-shots
```

스크립트가 하는 일([e2e/android_emulator_check.py](../../e2e/android_emulator_check.py)):

1. 열린 탭의 저장소를 비우고 새로고침 — 처음 온 사람과 같은 상태
2. '로그인 없이 시작' 을 누르고 데모 여행 계획을 규칙으로 만든다(AI 생성 호출 없음 → 비용 없음)
3. 홈 인사가 '손님님' 이 아닌지
4. **6-3**: 하단 탭으로 학습 → `adb shell input keyevent KEYCODE_BACK`(하드웨어 뒤로가기) → 홈으로 갔는지, Chrome 이 여전히 앞에 있는지. 상황별 연습에서도 한 번 더
5. **6-4**: 브라우저의 `speechSynthesis.speak` 에 넘어가는 문장을 가로채 기록한 뒤 대중교통 카드의 '듣기' 를 누른다 → `How do I get to your destination?`(대괄호 없음)인지
6. 단계마다 스크린샷을 `android-shots\` 에 저장. 하나라도 실패하면 종료 코드 1

10/18 출력(요약):

```
PASS 첫 화면에 '로그인 없이 시작'
PASS 6-3 뒤로가기: Chrome 이 닫히지 않음  [mCurrentFocus=...com.android.chrome/...ChromeTabbedActivity]
PASS 6-3 뒤로가기: 이전 화면(홈)으로  [u-home]
PASS 6-3 상황별 연습 → 뒤로가기 → 문장 모음, Chrome 유지
en voices: ['English Australia en_AU', 'English United Kingdom en_GB', 'English India en_IN', 'English Nigeria en_NG', 'English United States en_US']
spoken: [{'text': 'How do I get to your destination?', 'lang': 'en-US', 'voice': 'English United States'}]
PASS 6-4 듣기가 읽는 문장에 'your destination'(대괄호 없이)
```

> '손님님' 검사는 이 문서와 같은 PR 의 수정이 배포된 뒤에 통과한다. 10/18 배포본(#99)에서는 '손님님' 이 나와 이 검사로 발견했다.

### 로컬 서버를 확인할 때

에뮬레이터 안에서 `localhost` 는 가상 폰 자신이다. PC 를 가리키는 주소는 **`10.0.2.2`** 다.

```powershell
# 다른 창: cd backend; .venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
& $adb -s $dev shell am start -a android.intent.action.VIEW -d 'http://10.0.2.2:8000/' com.android.chrome
backend\.venv\Scripts\python.exe e2e\android_emulator_check.py http://10.0.2.2:8000 android-shots-local
```

로컬 서버에는 Firebase 설정이 없어 '로그인 없이 시작' 버튼이 나오지 않는다(기존 데모 로그인). 그래서 첫 검사는 실패한다 — 로컬은 6-3·6-4 부분만 참고한다.

---

## 10. 끄기

```powershell
& $adb -s $dev emu kill        # 가상 폰 종료(창이 닫힌다)
& $adb kill-server             # adb 백그라운드 프로세스 종료
```

다음에 다시 쓸 때는 2단계 변수 → 7단계부터 하면 된다(설치는 한 번만).

---

## 11. 완전히 지우기

먼저 10단계로 끈 다음, 이번에 만든 폴더 두 개만 지운다. 환경 변수는 바꾸지 않았으므로 되돌릴 것이 없다.

```powershell
Remove-Item -LiteralPath "$env:LOCALAPPDATA\Android" -Recurse -Force    # JDK·SDK·내려받은 zip
Remove-Item -LiteralPath "$env:USERPROFILE\.android" -Recurse -Force    # 가상 기기(약 4 GB)·adb 키
```

- `%USERPROFILE%\.android` 를 지우기 전에 안을 본다. 이 문서 전에 Android 를 쓴 적이 있다면(예: Android Studio) 다른 가상 기기가 들어 있을 수 있다 — 그때는 `avd\codyssey_pixel.avd` 와 `avd\codyssey_pixel.ini` 만 지운다.
- 10/18 에 지운 뒤에도 디스크 여유가 설치 전보다 적었다. 원인은 Windows 페이지 파일(`C:\pagefile.sys`, 시스템이 크기 관리)이 에뮬레이터 실행 중 커진 것이었다(35 GB, 최대 사용 17.6 GB). 보통 재부팅하면 줄어든다. 설정은 건드리지 않는다.

---

## 12. 문제 해결

| 증상 | 원인 | 해결 |
|---|---|---|
| `java` 를 찾을 수 없음 / `JAVA_HOME is not set` | 새 창에서 2단계 변수를 안 붙여 넣음 | 2단계 블록 다시 실행 |
| `Could not determine SDK root` | cmdline-tools 폴더 구조가 틀림 | 3단계 함정 참고 — `Sdk\cmdline-tools\latest\bin\sdkmanager.bat` 이어야 함 |
| 설치가 멈춘 것 같다 | 진행 막대만 갱신 중 | 4단계 함정 — 폴더 크기가 느는지 확인 |
| `-accel-check` 가 WHPX 를 못 씀 | 하이퍼바이저 플랫폼 꺼짐 | 5단계(관리자 1회 + 재부팅) |
| `error: more than one device/emulator` | adb 에 기기가 둘 이상(offline 포함) | 모든 adb 명령에 `-s emulator-5554` |
| 사이트 대신 다른 화면이 앞에 있음 | 이전 실행의 설정 화면 등 | 7-3 함정 — HOME 키 후 다시 `am start` |
| Chrome 환영·동기화 화면에서 멈춤 | 첫 실행 안내 | 7-3 의 플래그 3줄을 실행한 뒤 Chrome 을 force-stop 하고 다시 열기 |
| `http://localhost:9222/json` 연결 안 됨 | 포워딩 전이거나 Chrome 이 아직 안 뜸 | Chrome 이 앞에 있는지 확인 후 8단계 다시 |
| 스크립트: "탭에서 … 를 찾지 못했습니다" | Chrome 에 그 주소가 안 열림 | 7-3 의 `am start` 로 주소 열기 |
| 듣기 버튼 대신 "듣기를 지원하지 않아요" | Play 가 없는 이미지 | 4단계의 `google_apis_playstore` 이미지로 다시 |
| PNG 가 안 열림 | PowerShell `>` 리다이렉트 | 7-4 의 `shell screencap` + `pull` |
| 에뮬레이터 창이 검게 뜨거나 바로 꺼짐 | 그래픽 드라이버 | `-gpu swiftshader_indirect` 가 들어갔는지 확인 |

---

## 13. 이 방법이 확인하는 것과 못 하는 것

| 확인한다 | 확인하지 못한다 |
|---|---|
| Android 의 실제 Chrome 이 우리 화면을 그리고, 하드웨어 뒤로가기 키에 어떻게 반응하는지 | 실제 폰의 성능·터치 감각 |
| 듣기가 음성 엔진에 **어떤 문장**을 넘기는지, 재생이 시작되는지 | **소리 자체**(발음) — 사람이 들어야 한다. 에뮬레이터 창을 띄운 PC 스피커로는 들을 수 있다 |
| 기기에 영어 음성이 몇 개 있는지 | 말해 보기(마이크 녹음) — 에뮬레이터 마이크는 PC 마이크를 쓰지만 이 스크립트는 다루지 않는다 |
| | 카카오톡 앱 안 브라우저 — 이미지에 카카오톡이 없다(Play 스토어 로그인 후 설치는 가능, 미검증) |

참고로 이미지에 든 Chrome 은 113(10/18 기준 오래된 버전)이다. Play 스토어에 Google 계정으로 로그인하면 최신으로 올릴 수 있지만 이 문서의 확인에는 하지 않았다. `navigator.userAgent` 는 개인정보 보호 때문에 `Android 10; K` 로 줄여 보이므로, 실제 버전은 스크립트가 찍는 `chrome:` 줄(`dumpsys package`)을 본다.

Windows 기준으로만 검증했다. macOS·Linux 도 같은 구성(cmdline-tools → sdkmanager → avdmanager → emulator → adb)이지만 경로·내려받기 주소·가속(macOS 는 Hypervisor.framework, Apple Silicon 은 `arm64-v8a` 이미지)이 다르다.
