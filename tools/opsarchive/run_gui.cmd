@echo off
rem opsarchive GUI launcher (Windows).
rem Creates the venv if missing, installs dependencies once, then opens the GUI.
rem ASCII only: a non-ASCII batch file can break under a cp949 console.
setlocal
cd /d "%~dp0"

set "PY=%CD%\.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo [opsarchive] creating virtual environment...
  py -m venv .venv 2>nul || python -m venv .venv
  if not exist "%PY%" (
    echo [opsarchive] could not create .venv - install Python 3.10+ first.
    pause
    exit /b 1
  )
)

"%PY%" -c "import cryptography, google.auth" 2>nul
if errorlevel 1 (
  echo [opsarchive] installing dependencies (first run only)...
  "%PY%" -m pip install --upgrade pip
  "%PY%" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo [opsarchive] dependency install failed - see messages above.
    pause
    exit /b 1
  )
)

echo [opsarchive] starting GUI...
"%PY%" -m opsarchive gui
if errorlevel 1 pause
exit /b %errorlevel%
