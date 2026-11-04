@echo off
rem Removes the scheduled task and stops the node.
setlocal
set "TASK=MadiPhonemeNode"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Stop-ScheduledTask -TaskName '%TASK%' -ErrorAction SilentlyContinue;" ^
  "Unregister-ScheduledTask -TaskName '%TASK%' -Confirm:$false -ErrorAction SilentlyContinue;" ^
  "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*app.acoustic.server*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:"127.0.0.1:8443 .*LISTENING"') do taskkill /PID %%p /F >nul 2>&1
echo Removed "%TASK%" and stopped the node.
pause
