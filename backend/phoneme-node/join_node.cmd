@echo off
rem ============================================================
rem  Join this PC as a MADI phoneme node - one click.
rem  Before: Python 3.10+ installed, Tailscale installed and logged in
rem          (same tailnet as the admin). Admin gives you the token.
rem  Does:   token -> venv/packages/model -> auto start (hidden)
rem          -> wait ready -> Funnel -> prints the address for the admin
rem  Options: join_node.cmd startup   start at boot as SYSTEM (run as administrator)
rem ============================================================
setlocal EnableExtensions
set "NODE=%~dp0"
set "MADI_NOPAUSE=1"
set "TS=tailscale"
where tailscale >nul 2>nul || set "TS=%ProgramFiles%\Tailscale\tailscale.exe"
echo.
echo === MADI phoneme node: join ===
echo.

rem ---- 1) token ----
if exist "%NODE%token.txt" goto :token_check
echo [1/6] Paste the token the admin gave you (PHONEME_TOKEN) and press Enter:
set /p "TOK=> "
if not defined TOK (echo [FAIL] no token entered. & goto :fail)
> "%NODE%token.txt" echo %TOK%
:token_check
powershell -NoProfile -Command "$t=(Get-Content -LiteralPath '%NODE%token.txt' -TotalCount 1).Trim(); if($t.Length -lt 24){exit 1}"
if errorlevel 1 (
  echo [FAIL] token.txt is shorter than 24 characters. Delete token.txt and run again with the admin's token.
  goto :fail
)
echo [1/6] token ok

rem ---- 2) prepare (venv, packages, model 317MB) ----
echo [2/6] preparing - first time downloads about 400MB, may take several minutes...
call "%NODE%serve_phoneme.bat" prepare
if errorlevel 1 (echo [FAIL] prepare failed. See %NODE%logs\server.log & goto :fail)

rem ---- 3) auto start ----
echo [3/6] registering auto start (hidden)...
call "%NODE%register_task.cmd" %1 >nul
if errorlevel 1 (echo [FAIL] task registration failed. For "startup", run as administrator. & goto :fail)

rem ---- 4) wait until the node is ready ----
echo [4/6] waiting for the node to load the model...
powershell -NoProfile -Command "for($i=0;$i -lt 60;$i++){try{$r=Invoke-RestMethod -TimeoutSec 3 http://127.0.0.1:8443/healthz; if($r.ready){exit 0}}catch{}; Start-Sleep 2}; exit 1"
if errorlevel 1 (echo [FAIL] node did not become ready in 2 minutes. See %NODE%logs\server.log & goto :fail)
echo [4/6] node ready on http://127.0.0.1:8443

rem ---- 5) Funnel (public HTTPS address) ----
echo [5/6] opening Funnel...
"%TS%" funnel --bg --https=443 http://127.0.0.1:8443 >nul 2>&1
"%TS%" funnel status | findstr /c:"https://" >nul
if errorlevel 1 (
  echo [FAIL] Funnel is not on. Ask the admin to check: HTTPS certificates on, and "funnel" in the tailnet policy nodeAttrs.
  "%TS%" funnel --bg --https=443 http://127.0.0.1:8443
  goto :fail
)
for /f "usebackq delims=" %%u in (`powershell -NoProfile -Command "$s=& '%TS%' status --json | ConvertFrom-Json; 'https://' + $s.Self.DNSName.TrimEnd('.')"`) do set "URL=%%u"
> "%NODE%node-url.txt" echo %URL%

rem ---- 6) public check ----
echo [6/6] checking the public address...
powershell -NoProfile -Command "for($i=0;$i -lt 10;$i++){try{$r=Invoke-RestMethod -TimeoutSec 10 '%URL%/healthz'; if($r.ready){exit 0}}catch{}; Start-Sleep 3}; exit 1"
if errorlevel 1 (echo [WARN] public address not answering yet - wait a minute and run check_node.cmd) else (echo [6/6] public address ok)

echo.
echo ============================================================
echo  DONE. Send this address to the admin:
echo.
echo     %URL%
echo.
echo  (also saved in node-url.txt)
echo ============================================================
pause
exit /b 0

:fail
echo.
echo Join stopped. Fix the message above and run join_node.cmd again (it is safe to re-run).
pause
exit /b 1
