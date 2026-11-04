@echo off
rem Opens this PC's 127.0.0.1:8443 as a public HTTPS address through Tailscale Funnel.
rem Needs: Tailscale logged in, MagicDNS on, HTTPS certificates on, Funnel allowed in the tailnet policy.
where tailscale >nul 2>nul
if errorlevel 1 (echo [FAIL] tailscale CLI not found. Install Tailscale and log in. & pause & exit /b 1)
tailscale funnel --bg --https=443 http://127.0.0.1:8443
echo.
tailscale funnel status
echo.
echo Add the https://....ts.net address above to Render env PHONEME_REMOTE_URLS (no trailing slash).
echo Several PCs: one variable, comma separated, first = tried first. Example:
echo   PHONEME_REMOTE_URLS=https://pc1.example.ts.net,https://pc2.example.ts.net
echo Check all of them first: python tools\check_phoneme_nodes.py ^<url1^> ^<url2^>
pause
