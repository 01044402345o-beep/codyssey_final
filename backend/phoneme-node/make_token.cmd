@echo off
rem Creates token.txt (shared secret between Render and this node). Keeps an existing one.
setlocal
set "NODE=%~dp0"
if exist "%NODE%token.txt" (
  echo token.txt already exists - keeping it.
) else (
  py -3 -c "import secrets;print(secrets.token_urlsafe(32))" > "%NODE%token.txt" 2>nul || python -c "import secrets;print(secrets.token_urlsafe(32))" > "%NODE%token.txt"
)
echo.
echo Put this value into Render env PHONEME_TOKEN:
type "%NODE%token.txt"
echo.
pause
