@echo off
REM ============================================================================
REM  Breeze Trading Dashboard - launcher
REM
REM  Double-click this file (or the desktop shortcut) to start the app.
REM  Safe to run on a fresh clone: it creates the virtualenv, installs
REM  dependencies and seeds .env on first run, then starts the dashboard.
REM ============================================================================
setlocal
cd /d "%~dp0"

set "VENV_PY=.venv\Scripts\python.exe"

echo.
echo  === Breeze Trading Dashboard ===
echo.

REM --- 1. Virtualenv -----------------------------------------------------------
if not exist "%VENV_PY%" (
    echo  [setup] No virtualenv found - creating .venv ...
    python -m venv .venv
    if errorlevel 1 (
        echo.
        echo  [ERROR] Could not create the virtualenv.
        echo          Install Python 3.11+ from https://python.org and make sure
        echo          "python" works from a terminal, then run this again.
        goto :fail
    )
    REM Force a dependency install for the newly created venv.
    if exist ".venv\.deps-ok" del ".venv\.deps-ok"
)

REM --- 2. Dependencies ---------------------------------------------------------
if not exist ".venv\.deps-ok" (
    echo  [setup] Installing dependencies - this takes a few minutes the first time ...
    "%VENV_PY%" -m pip install --upgrade pip
    "%VENV_PY%" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo  [ERROR] Dependency install failed. Check your internet connection.
        goto :fail
    )
    echo ok > ".venv\.deps-ok"
)

REM --- 3. Credentials ----------------------------------------------------------
if not exist ".env" (
    echo.
    echo  [setup] No .env found - creating one from .env.example ...
    copy ".env.example" ".env" >nul
    echo.
    echo  ============================================================
    echo   ACTION NEEDED - add your ICICI Breeze credentials
    echo  ============================================================
    echo.
    echo   Edit .env in this folder and set:
    echo       BREEZE_API_KEY
    echo       BREEZE_API_SECRET
    echo       BREEZE_SESSION_TOKEN
    echo.
    echo   Get them at https://api.icicidirect.com  ^(My API^).
    echo   The session token expires every 24 hours - refresh it daily.
    echo.
    echo   DB_URL is optional. Leave it blank to run without PostgreSQL.
    echo  ============================================================
    echo.
    notepad .env
    echo  Press any key once you have saved .env ...
    pause >nul
)

REM --- 4. Launch ---------------------------------------------------------------
echo  [run] Starting the dashboard on http://localhost:8000 ...
echo        Leave this window open. Press Ctrl+C to stop.
echo.

REM Open the browser shortly after uvicorn binds the port.
start "" /b cmd /c "timeout /t 6 >nul & start ""  http://localhost:8000/paper"

"%VENV_PY%" app.py
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
    echo.
    echo  [ERROR] The app exited with code %RC%.
    echo          A common cause is port 8000 already being in use by another
    echo          copy of the app - close it and try again.
    goto :fail
)

endlocal
exit /b 0

:fail
echo.
pause
endlocal
exit /b 1
