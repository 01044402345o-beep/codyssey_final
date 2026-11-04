@echo off
rem Checks the node locally and through the public Funnel address.
setlocal
echo ---- local ----
curl -s -m 10 http://127.0.0.1:8443/healthz
echo.
for /f "tokens=1" %%u in ('tailscale funnel status 2^>nul ^| findstr /b /c:"https://"') do set "PUB=%%u"
if defined PUB (
  echo ---- public %PUB% ----
  curl -s -m 20 %PUB%/healthz
  echo.
) else (
  echo ---- public: Funnel is off ^(run funnel_on.cmd^) ----
)
echo.
echo Expect "ready": true. Last log lines:
powershell -NoProfile -Command "Get-Content -Tail 8 '%~dp0logs\server.log' -ErrorAction SilentlyContinue"
pause
