@echo off
setlocal
title flycontrol backend - dynamic landing/departure procedure system
cd /d "%~dp0backend"

set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" ( where python >nul 2>nul && set "PY=python" )

if not defined PY (
    echo [ERROR] Python not found: neither backend\.venv nor python on PATH.
    echo         Install Python 3.10+, or create the venv:
    echo             python -m venv .venv
    echo             .venv\Scripts\pip install -r requirements.txt -r requirements-dev.txt
    pause
    exit /b 1
)

echo ============================================================
echo   flycontrol backend starting ...
echo   URL  : http://127.0.0.1:8080
echo   Docs : http://127.0.0.1:8080/docs
echo.
echo   Python: %PY%
echo   Tip  : keep this window open, then run comms\communication launcher
echo          to open the live communication / situation view.
echo   Note : falls back to SQLite when PostgreSQL is not configured.
echo ============================================================
echo.
echo Press Ctrl+C to stop.
echo.

"%PY%" -m uvicorn app.main:app --host 127.0.0.1 --port 8080
pause
