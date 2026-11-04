@echo off
rem ============================================================
rem  MADI phoneme node - always-on PC
rem  Lives in <repo>\backend\phoneme-node. Run once by hand first,
rem  then register_task.cmd runs it hidden at logon.
rem  venv -> deps -> token -> model (SHA256) -> server, restart on crash
rem ============================================================
setlocal EnableExtensions EnableDelayedExpansion
title madi-phoneme-node
set "MODE=%~1"
set "NODE=%~dp0"
pushd "%NODE%.."
set "BACKEND=%CD%"
popd
set "REPO=%BACKEND%\.."
set "VENV=%BACKEND%\venv-phoneme"
set "PY=%VENV%\Scripts\python.exe"
set "LOGDIR=%NODE%logs"
set "LOG=%LOGDIR%\server.log"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
if not defined PHONEME_PORT set "PHONEME_PORT=8443"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"
for %%A in ("%LOG%") do if %%~zA GTR 5000000 move /y "%LOG%" "%LOG%.old" >nul

rem ---- 1) venv + deps (once; marker file means deps finished) ----
if not exist "%PY%" (
  echo [1/4] creating venv: %VENV%
  py -3 -m venv "%VENV%" >> "%LOG%" 2>&1
  if not exist "%PY%" python -m venv "%VENV%" >> "%LOG%" 2>&1
  if not exist "%PY%" (
    echo [FAIL] Python 3.10+ not found. Install from python.org with "Add python.exe to PATH".
    echo [%DATE% %TIME%] FAIL venv >> "%LOG%"
    goto :fail
  )
)
if not exist "%VENV%\.deps-ok" (
  echo [2/4] installing packages ^(first time only^)...
  "%PY%" -m pip install --disable-pip-version-check -q -r "%NODE%requirements-phoneme.txt" >> "%LOG%" 2>&1
  if errorlevel 1 (
    echo [FAIL] pip install failed. See %LOG%
    goto :fail
  )
  echo ok> "%VENV%\.deps-ok"
)

rem ---- 2) token (required: the node is public through Funnel) ----
set "PHONEME_TOKEN="
if exist "%NODE%token.txt" (
  for /f "usebackq delims=" %%t in ("%NODE%token.txt") do if not defined PHONEME_TOKEN set "PHONEME_TOKEN=%%t"
)
if not defined PHONEME_TOKEN (
  echo [FAIL] token.txt missing. Run make_token.cmd first.
  echo [%DATE% %TIME%] FAIL no token >> "%LOG%"
  goto :fail
)

rem ---- 3) model (317MB once, SHA256 checked) ----
echo [3/4] checking model ^(first run downloads 317MB^)...
"%PY%" "%REPO%\tools\fetch_phoneme_model.py" >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [FAIL] model download/verify failed. See %LOG%
  goto :fail
)

if /i "%MODE%"=="prepare" (
  echo [ok] prepared: venv, packages, token, model
  goto :end
)

rem ---- already running? (do not start a second copy) ----
netstat -ano | findstr /r /c:"127.0.0.1:%PHONEME_PORT% .*LISTENING" >nul
if not errorlevel 1 (
  echo [skip] something is already listening on 127.0.0.1:%PHONEME_PORT%
  echo [%DATE% %TIME%] skip: port %PHONEME_PORT% busy >> "%LOG%"
  goto :end
)

rem ---- 4) run, restart on crash (exit 2 = config error: stop) ----
echo [4/4] node on http://127.0.0.1:%PHONEME_PORT%  ^(log: %LOG%^)
set "PYTHONPATH=%BACKEND%"
:loop
echo [%DATE% %TIME%] start >> "%LOG%"
"%PY%" -m app.acoustic.server >> "%LOG%" 2>&1
set "RC=!ERRORLEVEL!"
echo [%DATE% %TIME%] exit code=!RC! >> "%LOG%"
if "!RC!"=="2" (
  echo [FAIL] server refused to start ^(token shorter than 24 chars?^). See %LOG%
  goto :fail
)
ping -n 31 127.0.0.1 >nul
goto loop

:fail
if /i not "%MODE%"=="hidden" if not defined MADI_NOPAUSE pause
endlocal & exit /b 1
:end
endlocal & exit /b 0
