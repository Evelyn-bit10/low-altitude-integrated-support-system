@echo off
setlocal
title Low-Altitude Demo Launcher
cd /d "%~dp0"

echo.
echo  ============================================================
echo    Low-Altitude Integrated Support System - Demo Launcher
echo  ============================================================
echo.

set "BE=%~dp0flight\flycontrol\low-altitude-demo\backend"
set "PY=%BE%\.venv\Scripts\python.exe"
set "WH=%~dp0wheels"

if exist "%PY%" goto hasenv
set "SYS="
py -3 -c "import sys" >nul 2>&1 && set "SYS=py -3"
if not defined SYS ( python -c "import sys" >nul 2>&1 && set "SYS=python" )
if not defined SYS (
  echo  [ERROR] Python 3 not found. Install Python 3.10+ first.
  pause & exit /b 1
)
echo  [1/3] Creating virtual environment ...
%SYS% -m venv "%BE%\.venv"
if not exist "%PY%" ( echo  [ERROR] venv creation failed & pause & exit /b 1 )

echo  [2/3] Installing dependencies ...
"%PY%" -m pip install -q --upgrade pip
if exist "%WH%\*.whl" (
  "%PY%" -m pip install -q --no-index --find-links "%WH%" -r "%BE%\requirements.txt"
) else (
  "%PY%" -m pip install -q -r "%BE%\requirements.txt"
)

:hasenv
echo  [3/3] Starting backend on 127.0.0.1:8080 ...
start "low-altitude-backend" /min /d "%BE%" "%PY%" -m uvicorn app.main:app --host 127.0.0.1 --port 8080
ping -n 10 127.0.0.1 >nul
start "" "%~dp0platform\portal\demo.html"
start "" "%~dp0platform\portal\rl_lab.html"
echo.
echo  Backend runs in a minimized window. Close it to stop.
echo  Demo: platform\portal\demo.html   RL lab: platform\portal\rl_lab.html
echo  Self-check: 自检.bat
echo.
pause
