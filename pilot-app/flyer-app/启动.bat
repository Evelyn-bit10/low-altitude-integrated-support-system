@echo off
setlocal
title Flyer App - web app (mobile)
cd /d "%~dp0"

set "PORT=5502"
set "URL=http://127.0.0.1:%PORT%/index.html"

echo ============================================================
echo   Flyer App - C-side web app (mobile)
echo ============================================================
echo.

set "PY="
if exist "..\..\flight\flycontrol\low-altitude-demo\backend\.venv\Scripts\python.exe" set "PY=..\..\flight\flycontrol\low-altitude-demo\backend\.venv\Scripts\python.exe"
if not defined PY ( where python >nul 2>nul && set "PY=python" )

if not defined PY (
  echo [WARN] Python not found, opening index.html directly.
  echo        Service Worker / PWA install needs an http server, so it will
  echo        not be available when the file is opened via file://
  start "" "%~dp0index.html"
  pause
  exit /b 0
)

echo Starting local server: %URL%
start "flyer-app-server" /MIN "%PY%" -m http.server %PORT% --bind 127.0.0.1
timeout /t 2 /nobreak >nul
start "" "%URL%"

echo.
echo Opened. Tips:
echo   - Press F12 and switch to device mode (iPhone 375 width) for mobile layout
echo   - Browser menu "Install app / Add to Home screen" makes it a standalone app
echo   - Real-device preview: see README.md
echo.
echo The server runs in a minimized window; close it to stop the server.
pause
