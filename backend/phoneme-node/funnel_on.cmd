@echo off
rem Opens this PC's 127.0.0.1:8443 as a public HTTPS address through Tailscale Funnel.
rem Needs: Tailscale logged in, MagicDNS on, HTTPS certificates on, Funnel allowed in the tailnet policy.
where tailscale >nul 2>nul
if errorlevel 1 (echo [FAIL] tailscale CLI not found. Install Tailscale and log in. & pause & exit /b 1)
tailscale funnel --bg --https=443 http://127.0.0.1:8443
echo.
tailscale funnel status
echo.
echo Put the https://....ts.net address above into Render env PHONEME_REMOTE_URL (no trailing slash).
pause
