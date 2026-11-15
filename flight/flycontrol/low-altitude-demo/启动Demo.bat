@echo off
chcp 65001 >nul
title Low-Altitude Flight Procedure Demo
cd /d "%~dp0"

set "VENV=%~dp0backend\.venv"
set "PY=%VENV%\Scripts\python.exe"

if exist "%PY%" goto runvenv

REM ---- no backend venv: reuse a system Python that already has the deps ----
set "SYS="
where python >nul 2>nul && set "SYS=python"
if not defined SYS ( where py >nul 2>nul && set "SYS=py -3" )
if not defined SYS (
    echo [Error] Python 3.10+ not found. Install it and add it to PATH.
    pause
    exit /b 1
)
%SYS% -c "import fastapi, uvicorn" >nul 2>&1
if not errorlevel 1 goto runsys

echo [FirstRun] Virtual environment not found. Creating and installing dependencies...
%SYS% -m venv "%VENV%"
if not exist "%PY%" (
    echo [Error] Failed to create venv. Install Python 3.10+ and add it to PATH.
    pause
    exit /b 1
)
"%PY%" -m pip install --upgrade pip --quiet
"%PY%" -m pip install fastapi "uvicorn[standard]" sqlalchemy pydantic --quiet
echo [Done] Dependencies installed.

:runvenv
call :banner
start "" cmd /c "timeout /t 3 /nobreak >nul & start http://127.0.0.1:8080"
"%PY%" -m uvicorn app.main:app --host 127.0.0.1 --port 8080
goto stopped

:runsys
echo [Info] Using system Python (fastapi/uvicorn already installed).
call :banner
start "" cmd /c "timeout /t 3 /nobreak >nul & start http://127.0.0.1:8080"
%SYS% -m uvicorn app.main:app --host 127.0.0.1 --port 8080
goto stopped

:banner
cd /d "%~dp0backend"
echo.
echo  ==============================================================
echo   Low-Altitude Dynamic Flight Procedure System - Demo
echo   URL:  http://127.0.0.1:8080
echo   Close this window to stop the server.
echo  ==============================================================
echo.
exit /b

:stopped
echo.
echo Server stopped. Press any key to exit.
pause >nul
