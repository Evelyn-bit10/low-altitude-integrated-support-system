@echo off
setlocal
title Flyer App - real device test
cd /d "%~dp0"

set "ROOT=%~dp0"
set "API_DIR=%ROOT%..\..\flight\flycontrol\low-altitude-demo\backend"
set "PY=%API_DIR%\.venv\Scripts\python.exe"
if not exist "%PY%" ( where python >nul 2>nul && set "PY=python" )
set "BRIDGE=%ROOT%..\..\platform\portal\ground-bridge.py"
set "APP_PORT=5502"
set "API_PORT=8080"
set "GROUND_PORT=8090"
set "PORTAL_PORT=5500"

echo ============================================================
echo   Flyer App - real device test
echo   Starts: flycontrol API + ground bridge + flyer app + portal
echo ============================================================
echo.

if not defined PY (
  echo [ERROR] Python not found: neither backend\.venv nor python on PATH.
  echo         Install Python 3.10+ and add it to PATH.
  pause
  exit /b 1
)

REM ---------- detect LAN IP ----------
set "LANIP="
set "IPTMP=%TEMP%\tz_lanip.txt"
powershell -NoProfile -Command "$ip=(Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } | Select-Object -First 1).IPAddress; Write-Output $ip" > "%IPTMP%" 2>nul
if exist "%IPTMP%" set /p LANIP=<"%IPTMP%"
del "%IPTMP%" >nul 2>nul
if not defined LANIP set "LANIP=127.0.0.1"

echo LAN IP  : %LANIP%
echo Python  : %PY%
echo.

echo [1/4] flycontrol API   listening on 0.0.0.0:%API_PORT%
start "flycontrol-api" /D "%API_DIR%" /MIN "%PY%" -m uvicorn app.main:app --host 0.0.0.0 --port %API_PORT%

echo [2/4] ground bridge     listening on 0.0.0.0:%GROUND_PORT%
start "ground-bridge" /MIN "%PY%" "%BRIDGE%" --host 0.0.0.0 --port %GROUND_PORT%

echo [3/4] flyer app         listening on 0.0.0.0:%APP_PORT%
start "flyer-app" /D "%ROOT%" /MIN "%PY%" -m http.server %APP_PORT% --bind 0.0.0.0

echo [4/4] portal            listening on 0.0.0.0:%PORTAL_PORT%
start "portal" /D "%ROOT%..\..\platform\portal" /MIN "%PY%" -m http.server %PORTAL_PORT% --bind 0.0.0.0

echo.
echo Waiting for services ...
timeout /t 5 /nobreak >nul

echo.
echo ============================================================
echo   Open on the phone (same Wi-Fi as this PC):
echo.
echo     Flyer App   http://%LANIP%:%APP_PORT%/index.html
echo     Portal      http://%LANIP%:%PORTAL_PORT%/index.html
echo.
echo   The app auto-points at %LANIP% ports %API_PORT% / %GROUND_PORT%,
echo   i.e. the same backends the portal uses, so data is comparable.
echo ============================================================
echo.
echo   If the phone cannot connect:
echo     1) Allow Python through Windows Firewall (private + public)
echo     2) Or run once as Administrator:
echo        New-NetFirewallRule -DisplayName "TingzhongDemo" -Direction Inbound -Protocol TCP -LocalPort 5500,5502,8080,8090 -Action Allow
echo.
echo   Stop: close the minimized windows that were just opened.
echo.

start "" "http://127.0.0.1:%APP_PORT%/index.html"
pause
