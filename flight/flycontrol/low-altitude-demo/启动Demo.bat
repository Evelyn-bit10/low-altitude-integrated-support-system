@echo off
chcp 65001 >nul
title Low-Altitude Flight Procedure Demo
cd /d "%~dp0"

set "VENV=%~dp0backend\.venv"
set "PY=%VENV%\Scripts\python.exe"

if not exist "%PY%" (
    echo [FirstRun] Virtual environment not found. Creating and installing dependencies...
    where python >nul 2>nul && (python -m venv "%VENV%") || (py -3 -m venv "%VENV%")
    if not exist "%PY%" (
        echo [Error] Failed to create venv. Install Python 3.10+ and add it to PATH.
        pause
        exit /b 1
    )
    "%PY%" -m pip install --upgrade pip --quiet
    "%PY%" -m pip install fastapi "uvicorn[standard]" sqlalchemy pydantic --quiet
    echo [Done] Dependencies installed.
)

cd /d "%~dp0backend"

echo.
echo  ==============================================================
echo   Low-Altitude Dynamic Flight Procedure System - Demo
echo   URL:  http://127.0.0.1:8080
echo   Close this window to stop the server.
echo  ==============================================================
echo.

start "" cmd /c "timeout /t 3 /nobreak >nul & start http://127.0.0.1:8080"

"%PY%" -m uvicorn app.main:app --host 127.0.0.1 --port 8080

echo.
echo Server stopped. Press any key to exit.
pause >nul
