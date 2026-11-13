@echo off
setlocal
title RL Association Lab - dedup policy
cd /d "%~dp0"

echo.
echo  ============================================
echo    RL Association Lab  (dedup policy viewer)
echo  ============================================
echo.

set "API=http://127.0.0.1:8080"
set "BE=%~dp0flight\flycontrol\low-altitude-demo\backend"
set "PY=%BE%\.venv\Scripts\python.exe"
set "PAGE=%~dp0platform\portal\rl_lab.html"

curl.exe -s -m 2 -o nul "%API%/api/health"
if errorlevel 1 goto startbe
echo  [OK] Backend already running on 8080
goto open

:startbe
echo  [..] Backend not running, starting it...
if not exist "%PY%" goto nopy
start "flycontrol" /min /d "%BE%" "%PY%" -m uvicorn app.main:app --host 127.0.0.1 --port 8080
ping -n 9 127.0.0.1 >nul

:open
if not exist "%PAGE%" goto nopage
start "" "%PAGE%"
echo  [OK] Page opened in browser.
echo  If the page says "not connected", wait 3s and refresh.
ping -n 4 127.0.0.1 >nul
exit /b 0

:nopy
echo  [ERROR] Python venv not found:
echo          %PY%
echo  Rebuild it first, see backend/README.md
pause
exit /b 1

:nopage
echo  [ERROR] Page not found:
echo          %PAGE%
pause
exit /b 1
