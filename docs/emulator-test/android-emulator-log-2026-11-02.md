# Android 에뮬레이터 설치 — 실제 실행 로그 (2026-11-02)

[android-emulator.md](android-emulator.md) 를 **보충**하는 문서다. 그 문서가 "무엇을 왜 하는지"라면, 이 문서는 **그 순서를 실제로 한 번 더 따라 하며 친 명령과 화면에 나온 출력을 그대로** 적은 기록이다.
처음 하는 사람이 "내 화면에 이게 나오면 맞게 가고 있는 건가?"를 대조할 수 있게 쓴다.

- 언제·어디서: 2026-11-02 새벽(KST), Windows 11 Home (빌드 26300), 메모리 15.5 GB, 디스크 여유 131.9 GB
- 왜: 폰에서 화면이 계속 깜빡이고 탭이 안 먹히는 결함(PR #202)을 실제 Android Chrome 에서 확인하려고. 10/18 에 설치했던 SDK 는 지워져 있었다
- 셸: **PowerShell**(관리자 아님). 아래 명령은 전부 PowerShell 에 그대로 붙여 넣는 형태다

> **읽는 법.** 각 단계는 `명령` → `실제 출력` → `읽는 법`(무엇이 나오면 정상인지) 순서다.
> 출력에서 사용자 이름이 들어간 경로는 `C:\Users\<나>` 로 바꿔 적었다.

---

## 1단계. 준비물 확인

**명령**

```powershell
Get-PSDrive C | % { "{0:N1} GB free" -f ($_.Free/1GB) }
"{0:N1} GB RAM" -f ((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory/1GB)
(Get-CimInstance Win32_ComputerSystem).HypervisorPresent
Test-Path "$env:LOCALAPPDATA\Android"     # 예전에 설치한 흔적이 있는가
Test-Path "$env:USERPROFILE\.android"     # 가상 기기·adb 키 폴더
```

**실제 출력**

```
131.9 GB free
15.5 GB RAM
True
False
True
```

**읽는 법**

| 줄 | 뜻 | 기준 |
|---|---|---|
| `131.9 GB free` | C 드라이브 여유 공간 | 15 GB 이상이면 된다 (설치 후 약 9 GB 를 쓴다) |
| `15.5 GB RAM` | 메모리 | 8 GB 이상, 16 GB 권장 |
| `True` | 하이퍼바이저(가상화) 켜짐 | `False` 여도 일단 진행 — 5단계에서 다시 본다 |
| `False` | `%LOCALAPPDATA%\Android` 가 없다 | 처음 설치(또는 예전 것을 지운 상태)라는 뜻 |
| `True` | `%USERPROFILE%\.android` 는 있다 | 안을 보면 `adbkey`·`adbkey.pub` 두 파일뿐이었다 — 예전에 adb 를 쓴 흔적이고, 지우지 않아도 된다 |

> 이 PC 에는 scrcpy(폰 화면 미러링 도구)가 깔려 있어서 그 안에 든 `adb` 가 PATH 에 먼저 잡혀 있었다. 이 문서에서는 헷갈리지 않게 **항상 전체 경로(`$adb`)로** adb 를 부른다.

Python 은 기존 `backend\.venv`(Python 3.10)를 썼다. 원 문서는 3.11 을 적었지만 9단계 스크립트는 3.10 에서도 돈다.

---

## 2단계. 경로 변수

**PowerShell 창을 새로 열 때마다** 먼저 붙여 넣는다. 변수는 창을 닫으면 사라진다(시스템 설정을 바꾸지 않으니 흔적도 안 남는다).

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

출력은 없다. 아무것도 안 나오면 정상이다.

---

## 3단계. JDK 17 과 SDK 명령줄 도구 내려받기·풀기

### 3-1. 내려받기

**명령**

```powershell
$ProgressPreference = 'SilentlyContinue'   # 진행 막대를 끄면 훨씬 빠르다
New-Item -ItemType Directory -Force "$base\dl_jdk", "$base\dl_tools", "$base\Sdk\cmdline-tools" | Out-Null

$t = Get-Date
Invoke-WebRequest 'https://api.adoptium.net/v3/binary/latest/17/ga/windows/x64/jdk/hotspot/normal/eclipse' -OutFile "$base\dl_jdk\jdk17.zip"
"jdk zip: {0:N1} MB ({1:N0}s)" -f ((Get-Item "$base\dl_jdk\jdk17.zip").Length/1MB), ((Get-Date)-$t).TotalSeconds

$t = Get-Date
Invoke-WebRequest 'https://dl.google.com/android/repository/commandlinetools-win-11076708_latest.zip' -OutFile "$base\dl_tools\cmdline-tools.zip"
"tools zip: {0:N1} MB ({1:N0}s)" -f ((Get-Item "$base\dl_tools\cmdline-tools.zip").Length/1MB), ((Get-Date)-$t).TotalSeconds
```

**실제 출력**

```
jdk zip: 182.0 MB (20s)
tools zip: 146.5 MB (34s)
```

**읽는 법** — 크기가 원 문서(182 MB · 146 MB)와 같으면 제대로 받은 것이다. 몇 KB 짜리면 주소가 막혀 오류 페이지를 받은 것이니 다시 받는다.
`Invoke-WebRequest` 는 끝날 때까지 아무것도 안 보인다(진행 막대를 껐으므로). 멈춘 게 아니다.

### 3-2. 풀고, 폴더 구조 맞추기

**명령**

```powershell
Expand-Archive "$base\dl_jdk\jdk17.zip" "$base\jdk" -Force
Expand-Archive "$base\dl_tools\cmdline-tools.zip" "$base\dl_tools\x" -Force
Move-Item "$base\dl_tools\x\cmdline-tools" "$base\Sdk\cmdline-tools\latest"   # ← 가장 중요한 줄
```

출력은 없다.

**왜 `Move-Item` 이 중요한가** — zip 안에는 `cmdline-tools\bin\sdkmanager.bat` 가 들어 있다. 이걸 그대로 `Sdk\cmdline-tools\` 에 풀면 `Sdk\cmdline-tools\cmdline-tools\bin` 이 되고, sdkmanager 가 "Could not determine SDK root" 로 실패한다. 반드시 `Sdk\cmdline-tools\latest\bin\` 이 되게 옮긴다.

### 3-3. 확인

2단계 블록을 **한 번 더** 붙여 넣는다(이제 `jdk` 폴더가 생겨 `JAVA_HOME` 이 잡힌다). 그다음:

**명령**

```powershell
Get-ChildItem "$base\jdk" -Directory | % Name
& "$env:JAVA_HOME\bin\java.exe" -version
Test-Path $sdkm
Get-ChildItem "$base\Sdk\cmdline-tools\latest" | % Name
```

**실제 출력**

```
jdk-17.0.20.1+1
openjdk version "17.0.20.1" 2026-08-18
OpenJDK Runtime Environment Temurin-17.0.20.1+1 (build 17.0.20.1+1)
OpenJDK 64-Bit Server VM Temurin-17.0.20.1+1 (build 17.0.20.1+1, mixed mode, sharing)
True
bin
lib
NOTICE.txt
source.properties
```

**읽는 법**

- `openjdk version "17.…"` — Java 17 이 잡혔다. 숫자 뒤쪽(17.0.20.1)은 받는 날에 따라 다르다(Adoptium 주소가 "17 의 최신"을 주므로).
- `True` — `sdkmanager.bat` 가 제자리에 있다.
- `bin`·`lib`·`NOTICE.txt`·`source.properties` — `latest` 바로 아래에 이 넷이 보여야 한다. `cmdline-tools` 가 또 보이면 3-2 의 `Move-Item` 이 잘못된 것이다.

> 이 PC 에는 원래 JDK 25(Adoptium)도 PATH 에 있었다. 위 방식은 `JAVA_HOME` 을 이 창에서만 JDK 17 로 바꾸므로 기존 JDK 와 부딪히지 않는다.

---

## 4단계. 라이선스 동의와 패키지 설치

### 4-1. 라이선스

**명령**

```powershell
(1..30 | % { 'y' }) -join "`n" | & $sdkm --sdk_root="$base\Sdk" --licenses
```

**실제 출력 (마지막 몇 줄)**

```
10.8 Open Source Software. In the event Open Source software is included with Evaluation Software, ...
---------------------------------------
Accept? (y/N): All SDK package licenses accepted
```

**읽는 법** — 라이선스 전문이 길게 지나가고, **마지막 줄이 `All SDK package licenses accepted`** 이면 된다. `y` 를 30개 보낸 것은 질문이 여러 개라서다(남는 `y` 는 무시된다).

### 4-2. 패키지 설치 (약 4 GB)

**명령**

```powershell
$t = Get-Date
& $sdkm --sdk_root="$base\Sdk" "platform-tools" "emulator" "system-images;android-34;google_apis_playstore;x86_64"
"install {0:N0}s" -f ((Get-Date)-$t).TotalSeconds
```

**실제 출력** (진행 막대 줄을 빼면 이것뿐이다)

```
Loading package information...
Loading local repository...
install 245s
```

**읽는 법**

- 성공해도 "완료" 같은 문장이 **따로 나오지 않는다.** 진행 막대(`[====   ] 45% Downloading ...`)가 한 줄에서 계속 갱신되다가 프롬프트로 돌아오면 끝이다. 그래서 끝난 뒤에 아래 **확인**으로 판정한다.
- 이번에는 **245초(약 4분)** 걸렸다(10/18 원 문서는 "10분 안팎").

**진행 중 확인 — 멈춘 것 같을 때**

설치 중에 다른 PowerShell 창에서 폴더별 크기를 보면 어디까지 왔는지 알 수 있다.

```powershell
Get-ChildItem "$env:LOCALAPPDATA\Android\Sdk" -Force | % { "{0}  {1:N0} MB" -f $_.Name, ((Get-ChildItem $_.FullName -Recurse -File -Force -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum/1MB) }
```

이번에 시간 순서대로 본 값:

| 시점 | 출력 | 뜻 |
|---|---|---|
| 시작 약 1분 | `cmdline-tools 146 MB` · `emulator 0 MB` · `.temp 0 MB` | **크기가 안 늘어도 정상.** 받는 중인 zip 은 `.temp` 안에 있는데, 받는 동안에는 크기가 0 으로 보인다 |
| 같은 때 | `.temp\PackageOperation01\emulator-windows_x64-16740729.zip` 의 `Length` 를 따로 보니 `315209376`(약 300 MB) | 실제로는 받고 있었다. 탐색기 '자세히 보기'로 이 파일 크기를 봐도 된다 |
| 시작 약 2분 | `emulator 1,070 MB` · `system-images 0 MB` | 에뮬레이터 설치 끝, 시스템 이미지 받는 중 |
| 끝난 뒤 | 아래 표 | |

> 진짜로 멈췄는지 의심되면 `Get-CimInstance Win32_Process -Filter "Name='java.exe'"` 로 java 프로세스가 살아 있는지 본다. sdkmanager 는 java 로 돈다.

**확인**

```powershell
Test-Path $emu; Test-Path $adb
Test-Path "$base\Sdk\system-images\android-34\google_apis_playstore\x86_64\system.img"
& $adb version | Select -First 2
& $emu -version | Select -First 1
```

**실제 출력**

```
True
True
True
Android Debug Bridge version 1.0.41
Version 37.0.1-15733141
Android emulator version 37.2.13.0 (build_id 16740729) (CL:N/A)
```

설치 후 폴더 크기:

| 폴더 | 크기 |
|---|---|
| `cmdline-tools` | 146 MB |
| `emulator` | 1,070 MB |
| `platform-tools` | 17 MB |
| `system-images` | 3,107 MB |

**읽는 법** — `True` 셋이면 설치 성공이다. 에뮬레이터는 37.2.13 으로 10/18(37.2)보다 조금 새 버전이 깔렸다(sdkmanager 가 그날의 최신을 받는다).

---

## 5단계. 하드웨어 가속 확인

**명령**

```powershell
& $emu -accel-check
```

**실제 출력**

```
accel:
0
WHPX(10.0.26300) is installed and usable.
accel
```

**읽는 법** — 가운데 `0` 은 "문제없음" 코드이고, **`WHPX(...) is installed and usable.`** 이 나오면 된다. WHPX 는 Windows 의 가상화 기능(Windows Hypervisor Platform)이다.
다른 문장(WHPX·AEHD 를 쓸 수 없음)이 나오면 원 문서 5단계대로 관리자 PowerShell 에서 한 번 켜고 재부팅한다.

---

## 6단계. 가상 기기(AVD) 만들기

**명령**

```powershell
"no" | & $avdm create avd -n codyssey_pixel -k "system-images;android-34;google_apis_playstore;x86_64" -d pixel_6 --force
& $emu -list-avds
Get-ChildItem "$env:USERPROFILE\.android\avd" | % Name
```

**실제 출력**

```
[=======================================] 100% Fetch remote repository...
Auto-selecting single ABI x86_64
codyssey_pixel
codyssey_pixel.avd
codyssey_pixel.ini
```

**읽는 법**

- `Auto-selecting single ABI x86_64` — 받은 이미지가 x86_64 하나라 그걸로 골랐다는 뜻. 정상.
- `-list-avds` 가 `codyssey_pixel` 을 보여 주면 가상 폰 한 대가 만들어진 것이다.
- `.android\avd` 아래 `codyssey_pixel.avd`(폴더)와 `codyssey_pixel.ini`(설정 파일)가 생긴다. 나중에 지울 때 이 둘만 지우면 된다.
- 맨 앞 `"no"` 는 "사용자 지정 하드웨어 프로필을 만들까요?" 질문에 미리 답한 것이다. 넣지 않으면 그 질문에서 멈춘다.

---

## 7단계. 부팅하고 Chrome 으로 사이트 열기

### 7-1. 부팅

**명령** (부팅이 끝날 때까지 5초마다 확인하고, 10분이 넘으면 멈춘다)

```powershell
& $adb devices
Start-Process "$emu" -ArgumentList '-avd','codyssey_pixel','-no-snapshot','-no-boot-anim','-gpu','swiftshader_indirect','-netdelay','none','-netspeed','full'

$t0 = Get-Date
do {
  Start-Sleep 5
  $dev = if ("$(& $adb devices)" -match '(emulator-\d+)\s+device\b') { $Matches[1] } else { '' }
  $b = if ($dev) { "$(& $adb -s $dev shell getprop sys.boot_completed 2>$null)".Trim() } else { '' }
} until ($b -eq '1' -or ((Get-Date) - $t0).TotalSeconds -gt 600)
"device=$dev boot_completed=$b ({0:N0}s)" -f ((Get-Date) - $t0).TotalSeconds
& $adb devices -l
```

**실제 출력**

```
List of devices attached

device=emulator-5554 boot_completed=1 (72s)
List of devices attached
emulator-5554          device product:sdk_gphone64_x86_64 model:sdk_gphone64_x86_64 device:emu64xa transport_id:31010
emulator-5562          offline transport_id:31017
```

**읽는 법**

- 폰 모양 창이 PC 화면에 뜬다. **`boot_completed=1`** 이 나오면 부팅이 끝난 것이다. 이번에는 **72초**(10/18 은 205초).
- 맨 처음 `& $adb devices` 가 빈 목록을 보여 주는 건 정상이다. 에뮬레이터를 켜기 전이기 때문이다.
- **`emulator-5562 offline` 줄이 또 보였다.** 10/18 원 문서에도 같은 줄이 나온다. 예전에 비정상 종료된 에뮬레이터의 흔적이라 무시해도 된다. 다만 이 줄 때문에 `-s` 없이 adb 를 부르면 `more than one device/emulator` 로 실패하니, 아래 명령은 전부 `-s $dev`(`emulator-5554`)를 붙인다.

### 7-2. Chrome 첫 실행 안내 끄고 사이트 열기

**명령**

```powershell
$dev = 'emulator-5554'
& $adb -s $dev shell 'echo "_ --disable-fre --no-default-browser-check --no-first-run" > /data/local/tmp/chrome-command-line'
& $adb -s $dev shell am set-debug-app --persistent com.android.chrome
& $adb -s $dev shell am force-stop com.android.chrome
& $adb -s $dev shell am start -a android.intent.action.VIEW -d 'https://codyssey-final.onrender.com/' com.android.chrome
& $adb -s $dev shell dumpsys package com.android.chrome | Select-String "versionName" | Select -First 1
```

**실제 출력**

```
Starting: Intent { act=android.intent.action.VIEW dat=https://codyssey-final.onrender.com/... pkg=com.android.chrome }

    versionName=113.0.5672.136
```

**읽는 법** — `Starting: Intent ...` 는 "Chrome 에 이 주소를 열라고 보냈다"는 뜻이다. 앞의 세 줄(플래그 파일 쓰기·디버그 앱 지정·강제 종료)은 출력이 없다.
Chrome 버전은 **113.0.5672.136** — 시스템 이미지에 들어 있는 그대로라 10/18 과 같다. 실제 폰의 최신 Chrome 보다 한참 오래된 버전이라는 점을 기억해 둔다(13절).

15초쯤 기다린 뒤 맨 앞 화면이 Chrome 인지 확인한다.

```powershell
& $adb -s $dev shell dumpsys window | Select-String mCurrentFocus
```

```
  mCurrentFocus=Window{f6289bd u0 com.android.chrome/org.chromium.chrome.browser.ChromeTabbedActivity}
```

`com.android.chrome/...ChromeTabbedActivity` 가 보이면 Chrome 이 앞에 있는 것이다.

### 7-3. 화면 캡처

**명령** (PowerShell)

```powershell
& $adb -s $dev shell screencap -p /sdcard/s.png
& $adb -s $dev pull /sdcard/s.png "$env:USERPROFILE\Desktop\emulator.png"
```

> **함정 — Git Bash 에서 치면 실패한다.** 이번에 같은 명령을 Git Bash(MINGW)에서 쳤더니 이렇게 나왔다.
>
> ```
> usage: screencap [-hp] [-d display-id] [FILENAME]
> ```
>
> Git Bash 가 `/sdcard/s.png` 를 Windows 경로(`C:/Program Files/Git/sdcard/s.png`)로 바꿔서 기기에 넘기기 때문이다. **PowerShell 에서 치거나**, Git Bash 라면 앞에 `MSYS_NO_PATHCONV=1` 을 붙인다. 원 문서의 명령은 전부 PowerShell 기준이다.

---

## 8단계. Chrome 원격 디버깅 연결

**명령**

```powershell
& $adb -s $dev forward tcp:9222 localabstract:chrome_devtools_remote
(Invoke-RestMethod http://localhost:9222/json) | % { "$($_.type) $($_.url)" }
```

**실제 출력**

```
9222
page https://codyssey-final.onrender.com/
```

**읽는 법** — 첫 줄 `9222` 는 PC 의 9222 번 포트를 연결했다는 뜻이다. 둘째 줄에 **`page https://codyssey-final.onrender.com/`** 이 보이면 PC 에서 그 탭을 조종할 준비가 된 것이다.

---

## 9단계. 확인 스크립트 실행

**명령** (저장소 루트에서)

```powershell
$env:ANDROID_SERIAL = $dev
$env:ANDROID_HOME = "$base\Sdk"     # 스크립트가 adb 를 이 경로에서 찾는다
$env:PYTHONIOENCODING = 'utf-8'
backend\.venv\Scripts\python.exe e2e\android_emulator_check.py https://codyssey-final.onrender.com android-shots
```

> **`ANDROID_HOME` 을 꼭 넣는다.** 넣지 않으면 스크립트가 PATH 의 adb 를 쓴다. 이 PC 처럼 scrcpy 의 adb 가 PATH 에 있으면 버전이 다른 adb 두 개가 서로의 서버를 끄면서 연결이 끊길 수 있다.

**실제 출력** (두 번째 실행 — 첫 실행은 아래 함정 참고)

```
chrome: 113.0.5672.136
PASS 첫 화면에 '로그인 없이 시작'  [u-login]
PASS 홈 인사가 '손님님'이 아님
PASS 탭으로 학습 화면 진입(히스토리 쌓임)  [6 -> {'scr': 'u-study', 'hist': 7}]
PASS 6-3 뒤로가기: Chrome 이 닫히지 않음  [mCurrentFocus=...com.android.chrome/...ChromeTabbedActivity]
FAIL 6-3 뒤로가기: 이전 화면(홈)으로  [u-sched]
PASS 6-3 상황별 연습 → 뒤로가기 → 문장 모음, Chrome 유지
en voices: ['English Australia en_AU', 'English United Kingdom en_GB', 'English India en_IN', 'English Nigeria en_NG', 'English United States en_US']
PASS 6-4 듣기 버튼이 보임(이 기기에 영어 음성 있음)  [5개]
spoken: [{'text': 'How do I get to your destination?', 'lang': 'en-US', 'voice': 'English United States'}]
PASS 6-4 화면에 [your destination]
PASS 6-4 듣기가 읽는 문장에 'your destination'(대괄호 없이)
```

**결과: 10개 중 9개 통과, 1개 실패.** 실패 1건은 앱 결함이 아니다.

**실패 1건을 읽는 법 — 스크립트의 전제가 낡았다**

스크린샷(`android-shots\03_study.png`)을 보면 학습 탭을 누른 순간 **"아직 학습일이 아니에요"** 창이 떠 있다. 데모 여행이 11/10 부터라 오늘(11/02)은 학습일 전이기 때문이다. 이 창이 떠 있을 때 뒤로가기 키를 누르면, 앱은 창의 **"일정표로"** 단추와 같은 동작을 한다(`app.js` 의 `onPop` → `closeModal()` → `go('u-sched')`). 그래서 홈이 아니라 일정표(`u-sched`)로 갔다.
10/18 에는 그날이 학습일이어서 창이 뜨지 않았고, 스크립트도 그 상태를 기준으로 쓰였다. **스크립트를 날짜와 무관하게 고치기 전까지 이 한 줄은 "창이 떠 있으면 일정표로 가는 게 맞다"로 읽는다.**

> **함정 — 첫 실행이 멈춘 것처럼 보임.** 첫 실행에서는 같은 창(`미리 학습하기` 단추) 때문에 다음 탭을 누르지 못하고 Playwright 가 "subtree intercepts pointer events" 를 수십 번 반복하다 시간 초과로 끝났다. 두 번째 실행은 앞 실행이 남긴 상태 덕에 끝까지 갔다. 처음 하는 사람이 이 반복 로그를 보면 "깨졌다"고 생각하기 쉬운데, 원인은 앱 화면 위에 떠 있는 창이다. `android-shots\` 의 마지막 스크린샷을 보면 바로 알 수 있다.

---

## 추가 확인 — 폰 깜빡임 수정(#202)이 실제 Android Chrome 에서 맞는가

이번 설치의 원래 목적이다. #202 는 "일부 엔진은 `getVoices()` 를 부를 때마다 `voiceschanged` 를 다시 보내고, 그때마다 화면 전체를 다시 그려 깜빡이고 탭이 먹히지 않는다"고 보고 고친 PR 이다. 데스크톱 Chromium 에서 **그런 엔진을 흉내 내** 재현했을 뿐, 실제 Android 에서 그런지는 확인하지 못했었다.

8단계의 원격 디버깅 연결로 에뮬레이터 속 Chrome 에 붙어 확인했다(스크립트: 배포본을 새로고침하고, ① `getVoices()` 를 10번 부른 뒤 알림 횟수를 세고, ② 하단 탭을 터치 이벤트로 눌러 2.5초 동안의 다시 그리기 횟수를 센다).

**실제 출력**

```
deploy: dc33dc1
has sig guard: True
engine: {'voices': 64, 'events_after_10_getVoices': 0}
tap u-sched: screen=u-sched renders_in_2.5s=1 voiceschanged_total=0
tap u-coll: screen=u-coll renders_in_2.5s=1 voiceschanged_total=0
tap u-home: screen=u-home renders_in_2.5s=1 voiceschanged_total=0
tap u-coll: screen=u-coll renders_in_2.5s=1 voiceschanged_total=0
```

**읽는 법 — 결론을 정확히**

| 줄 | 뜻 |
|---|---|
| `deploy: dc33dc1` · `has sig guard: True` | 배포본에 #202 가 들어가 있다 |
| `events_after_10_getVoices: 0` | **이 Chrome(113)·이 음성 엔진(Google TTS, 음성 64개)은 `getVoices()` 를 불러도 알림을 다시 보내지 않는다** |
| `renders_in_2.5s=1` | 탭 한 번에 화면을 한 번만 그린다. 깜빡임 루프 없음 |

따라서 **이 에뮬레이터에서는 #202 가 가정한 원인이 재현되지 않았다.** #202 는 그런 엔진이 있을 때를 막는 방어 수정으로는 유효하지만, **사용자가 본 폰 깜빡임의 원인이라는 증거는 아직 없다.**

남은 차이 — 이 에뮬레이터와 사용자 폰이 다를 수 있는 곳:

- Chrome 버전: 에뮬레이터는 113, 실제 폰은 훨씬 새 버전일 가능성이 높다
- 음성 엔진: 에뮬레이터는 Google TTS. 삼성 폰은 기본이 Samsung TTS 다
- 카카오톡 인앱 브라우저: 에뮬레이터에는 카카오톡이 없다
- 사용자 보고의 "예전 배포본 캐시가 남은 기기에서 더 심함"

다음 확인은 **실제 폰**(USB 연결 후 `adb devices` 에 보이게 하고 같은 8단계 원격 디버깅)으로 하는 게 가장 빠르다. 실기기도 같은 방법으로 붙는다.

---

## 끄기와 정리

이 기록을 쓴 뒤 에뮬레이터는 켜 둔 상태로 두었다. 끌 때는 원 문서 10단계 그대로다.

```powershell
& $adb -s emulator-5554 emu kill
& $adb kill-server
```

설치물(약 4.5 GB: SDK 4,340 MB + JDK 303 MB)과 가상 기기(`%USERPROFILE%\.android\avd\codyssey_pixel.*`)는 지우지 않았다. 지우는 방법은 원 문서 11단계.

---

## 원 문서와 달랐던 점 요약

| 항목 | 원 문서(10/18) | 이번(11/02) |
|---|---|---|
| JDK | 17.x | 17.0.20.1+1 |
| 에뮬레이터 | 37.2 | 37.2.13 |
| 패키지 설치 시간 | 10분 안팎 | 245초 |
| 첫 부팅 | 205초 | 72초 |
| Chrome | 113 | 113.0.5672.136 (같음) |
| 9단계 결과 | 전부 통과 | 9/10 — 실패 1건은 날짜 때문에 뜨는 "아직 학습일이 아니에요" 창(스크립트 전제가 낡음) |
| Python | 3.11 | 3.10(기존 `backend\.venv`) — 문제없음 |
| 새로 찾은 함정 | — | 설치 초반 폴더 크기가 0 으로 보임 · Git Bash 의 경로 변환으로 `screencap` 실패 · PATH 에 다른 adb(scrcpy)가 있으면 `ANDROID_HOME` 지정 필요 |
