@echo off
rem Registers the node in Task Scheduler (hidden, no time limit, restart on failure).
rem   register_task.cmd           at logon of this user (no admin needed)
rem   register_task.cmd startup   at boot as SYSTEM, before anyone logs on (run as administrator)
setlocal
set "TASK=MadiPhonemeNode"
set "VBS=%~dp0serve_phoneme_hidden.vbs"
if not exist "%VBS%" (echo [FAIL] serve_phoneme_hidden.vbs not found & pause & exit /b 1)
if not exist "%~dp0token.txt" (echo [FAIL] token.txt missing - run make_token.cmd first & pause & exit /b 1)
set "TRIG=AtLogOn -User $env:USERDOMAIN\$env:USERNAME"
set "PRIN=New-ScheduledTaskPrincipal -UserId $env:USERDOMAIN\$env:USERNAME -LogonType Interactive -RunLevel Limited"
if /i "%~1"=="startup" (
  set "TRIG=AtStartup"
  set "PRIN=New-ScheduledTaskPrincipal -UserId SYSTEM -LogonType ServiceAccount -RunLevel Limited"
)
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$a = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument ('\"' + '%VBS%' + '\"');" ^
  "$t = New-ScheduledTaskTrigger -%TRIG%; $t.Delay = 'PT30S';" ^
  "$s = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew;" ^
  "$p = %PRIN%;" ^
  "Register-ScheduledTask -TaskName '%TASK%' -Action $a -Trigger $t -Settings $s -Principal $p -Force | Out-Null;" ^
  "Start-ScheduledTask -TaskName '%TASK%';" ^
  "Get-ScheduledTask -TaskName '%TASK%' | Select-Object TaskName, State | Format-List"
if errorlevel 1 (
  echo [FAIL] registration failed. For "startup" mode, run this file as administrator.
  if not defined MADI_NOPAUSE pause
  exit /b 1
)
echo.
echo Registered "%TASK%". Check in about a minute:  check_node.cmd
if not defined MADI_NOPAUSE pause
exit /b 0
