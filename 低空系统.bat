@echo off
setlocal EnableExtensions
title Low-Altitude Integrated Support System - Launcher
cd /d "%~dp0"

set "BE=%~dp0flight\flycontrol\low-altitude-demo\backend"
set "PORTAL_DIR=%~dp0platform\portal"
set "APP_DIR=%~dp0pilot-app\flyer-app"
set "COMMS_DIR=%~dp0comms\communication"

set "API_PORT=8082"
set "GROUND_PORT=8090"
set "PORTAL_PORT=5500"
set "APP_PORT=5502"

if not "%~1"=="" goto dispatch
set "INTERACTIVE=1"
goto menu

REM ============================================================ dispatch
:dispatch
if /i "%~1"=="portal"   goto c_portal
if /i "%~1"=="demo"     goto c_demo
if /i "%~1"=="rl"       goto c_rl
if /i "%~1"=="api"      goto c_api
if /i "%~1"=="pages"    goto c_pages
if /i "%~1"=="apidev"   goto c_apidev
if /i "%~1"=="app"      goto c_app
if /i "%~1"=="mobile"   goto c_mobile
if /i "%~1"=="device"   goto c_device
if /i "%~1"=="comms"    goto c_comms
if /i "%~1"=="decision" goto c_decision
if /i "%~1"=="apk"      goto c_apk
if /i "%~1"=="check"    goto c_check
if /i "%~1"=="lanip"    goto c_lanip
if /i "%~1"=="help"     goto usage
if /i "%~1"=="-h"       goto usage
if /i "%~1"=="/?"       goto usage
echo  [ERROR] Unknown command: %~1
echo.
goto usage

REM ============================================================ menu
:menu
cls
echo.
echo  ============================================================
echo    Low-Altitude Integrated Support System - Launcher
echo  ============================================================
echo.
echo     [1]  Full system           portal + bridge + flyer app + groundstation
echo     [2]  Demo console          3 features + mock UOM on 8099
echo     [3]  RL association lab    visualise the dedup policy network
echo     [4]  Backend only          8082, foreground, shows logs
echo     [5]  Backend + demo pages  8082 + demo.html + rl_lab.html
echo     [6]  Backend + built-in frontend page (8082)
echo     [7]  Groundstation desktop  PyQt5 window + DSM tiles on 8081
echo     [8]  Flyer app             5502, this PC only
echo     [9]  Phone / LAN test      8082 + 8090 + 5500 + 5502 on 0.0.0.0
echo    [10]  Communication page
echo    [11]  Decision engine prototype (Python)
echo    [12]  Build Android APK
echo    [13]  Self-check            pytest + web smoke + API probe
echo     [0]  Exit
echo.
set "choice="
set /p "choice=Enter a number: "
if "%choice%"=="1"  goto c_portal
if "%choice%"=="2"  goto c_demo
if "%choice%"=="3"  goto c_rl
if "%choice%"=="4"  goto c_api
if "%choice%"=="5"  goto c_pages
if "%choice%"=="6"  goto c_apidev
if "%choice%"=="7"  goto c_device
if "%choice%"=="8"  goto c_app
if "%choice%"=="9"  goto c_mobile
if "%choice%"=="10" goto c_comms
if "%choice%"=="11" goto c_decision
if "%choice%"=="12" goto c_apk
if "%choice%"=="13" goto c_check
if "%choice%"=="0"  goto end
goto menu

REM ============================================================ commands
:c_portal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-system.ps1"
goto end

:c_demo
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-demo.ps1"
goto end

:c_api
call :findpy
if not defined PY goto err_nopy
echo.
echo  flycontrol backend on http://127.0.0.1:%API_PORT%   (Ctrl+C to stop)
echo.
pushd "%BE%"
"%PY%" -m uvicorn app.main:app --host 127.0.0.1 --port %API_PORT%
popd
goto end

:c_apidev
call :findpy
if not defined PY goto err_nopy
pushd "%BE%"
echo.
echo  Backend + built-in frontend page: http://127.0.0.1:%API_PORT%
echo  Close this window to stop the server.
echo.
start "" cmd /c "timeout /t 3 /nobreak >nul & start http://127.0.0.1:%API_PORT%"
"%PY%" -m uvicorn app.main:app --host 127.0.0.1 --port %API_PORT%
popd
goto end

:c_pages
call :findpy
if not defined PY goto err_nopy
if exist "%BE%\.venv\Scripts\python.exe" (
    start "low-altitude-backend" /min /d "%BE%" "%BE%\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port %API_PORT%
    goto pages_open
)
%PY% -c "import fastapi, uvicorn" >nul 2>&1
if not errorlevel 1 (
    start "low-altitude-backend" /min /d "%BE%" %PY% -m uvicorn app.main:app --host 127.0.0.1 --port %API_PORT%
    goto pages_open
)
echo.
echo  [1/2] No usable backend environment found; creating %BE%\.venv ...
%PY% -m venv "%BE%\.venv"
if not exist "%BE%\.venv\Scripts\python.exe" goto err_venv
"%BE%\.venv\Scripts\python.exe" -m pip install -q --upgrade pip
if exist "%~dp0wheels\*.whl" (
    "%BE%\.venv\Scripts\python.exe" -m pip install -q --no-index --find-links "%~dp0wheels" -r "%BE%\requirements.txt"
) else (
    "%BE%\.venv\Scripts\python.exe" -m pip install -q -r "%BE%\requirements.txt"
)
start "low-altitude-backend" /min /d "%BE%" "%BE%\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port %API_PORT%

:pages_open
echo.
echo  [2/2] Starting backend on 127.0.0.1:%API_PORT% ...
ping -n 10 127.0.0.1 >nul
start "" "%PORTAL_DIR%\demo.html"
start "" "%PORTAL_DIR%\rl_lab.html"
echo.
echo  [OK] Pages opened. Backend runs in a minimized window named low-altitude-backend.
goto end

:c_rl
call :findpy
curl.exe -s -m 2 -o nul "http://127.0.0.1:%API_PORT%/api/health"
if not errorlevel 1 goto rl_open
if not defined PY goto err_nopy
echo  [..] Starting backend on 127.0.0.1:%API_PORT% ...
start "flycontrol" /min /d "%BE%" "%PY%" -m uvicorn app.main:app --host 127.0.0.1 --port %API_PORT%
ping -n 9 127.0.0.1 >nul
:rl_open
echo  [OK] Opening RL association lab (needs the backend on %API_PORT%).
start "" "%PORTAL_DIR%\rl_lab.html"
goto end

:c_device
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-system.ps1" -DeviceOnly
goto end

:c_app
call :findpy
if not defined PY (
    echo  [WARN] Python not found. Opening index.html directly.
    echo         Service Worker / PWA install needs an http server, so it will not be available.
    start "" "%APP_DIR%\index.html"
    goto end
)
echo.
echo  Flyer app: http://127.0.0.1:%APP_PORT%/index.html   (close the minimized window to stop)
echo.
start "flyer-app-server" /min /d "%APP_DIR%" "%PY%" "%PORTAL_DIR%\serve.py" %APP_PORT% --host 127.0.0.1
timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:%APP_PORT%/index.html"
goto end

:c_mobile
call :findpy
if not defined PY goto err_nopy
call :getlanip
echo.
echo  LAN IP : %LANIP%
echo  Python : %PY%
echo.
echo  [1/4] flycontrol API   0.0.0.0:%API_PORT%
start "flycontrol-api" /min /d "%BE%" "%PY%" -m uvicorn app.main:app --host 0.0.0.0 --port %API_PORT%
echo  [2/4] ground bridge     0.0.0.0:%GROUND_PORT%
start "ground-bridge" /min "%PY%" "%PORTAL_DIR%\ground-bridge.py" --host 0.0.0.0 --port %GROUND_PORT%
echo  [3/4] flyer app         0.0.0.0:%APP_PORT%
start "flyer-app" /min /d "%APP_DIR%" "%PY%" "%PORTAL_DIR%\serve.py" %APP_PORT% --host 0.0.0.0
echo  [4/4] portal            0.0.0.0:%PORTAL_PORT%
start "portal" /min /d "%PORTAL_DIR%" "%PY%" "%PORTAL_DIR%\serve.py" %PORTAL_PORT% --host 0.0.0.0
echo.
echo  Waiting for services ...
timeout /t 5 /nobreak >nul
echo.
echo  ============================================================
echo    Open on the phone (same Wi-Fi as this PC):
echo.
echo      Flyer app   http://%LANIP%:%APP_PORT%/index.html
echo      Portal      http://%LANIP%:%PORTAL_PORT%/index.html
echo.
echo    In the app: Settings - API   http://%LANIP%:%API_PORT%
echo                              ground http://%LANIP%:%GROUND_PORT%
echo  ============================================================
echo.
echo    If the phone cannot connect:
echo      1) Allow Python through Windows Firewall (private + public)
echo      2) Or run once as Administrator:
echo         New-NetFirewallRule -DisplayName "TingzhongDemo" -Direction Inbound -Protocol TCP -LocalPort 5500,5502,8082,8090 -Action Allow
echo.
echo    Stop: close the four minimized windows just opened.
echo.
start "" "http://127.0.0.1:%APP_PORT%/index.html"
goto end

:c_comms
if not exist "%COMMS_DIR%\index.html" goto err_nofile
start "" "%COMMS_DIR%\index.html"
echo  [OK] Opened the communication / situation page (it connects to 127.0.0.1:%API_PORT% by itself).
goto end

:c_decision
call :findpy
if not defined PY goto err_nopy
if not exist "%COMMS_DIR%\decision_engine_demo.py" goto err_nofile
echo.
"%PY%" "%COMMS_DIR%\decision_engine_demo.py"
goto end

:c_apk
powershell -NoProfile -ExecutionPolicy Bypass -File "%APP_DIR%\build-apk.ps1"
if errorlevel 1 pause
goto end

:c_check
call :findpy
if not defined PY goto err_nopy
echo.
echo  Python : %PY%
echo.
echo  [1/2] unit tests + web smoke ...
pushd "%BE%"
"%PY%" -m pytest tests -q
if errorlevel 1 (echo. & echo  [FAIL] unit tests & popd & goto end)
set "PYTHONIOENCODING=utf-8"
"%PY%" tools\smoke_web.py
popd
echo  [2/2] API health on %API_PORT% ...
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:%API_PORT%/api/health' -TimeoutSec 3 -UseBasicParsing; if ($r.StatusCode -eq 200) { Write-Host '  [OK] backend running' } } catch { Write-Host '  [SKIP] backend not running (use low-altitude launcher menu 5 or 6)' }"
goto end

:c_lanip
call :getlanip
echo %LANIP%
goto end

:usage
echo.
echo  Low-Altitude Integrated Support System - launcher
echo.
echo  Usage:  %~nx0 [command]
echo          %~nx0                (no argument: interactive menu)
echo.
echo  Commands:
echo    portal     full system: portal + data bridge + flyer app + groundstation
echo    demo       demo console (3 features + mock UOM on 8099)
echo    rl         RL association lab (starts the backend if needed)
echo    api        backend only on 8082, foreground, shows logs
echo    pages      backend + demo.html + rl_lab.html
echo    apidev     backend + its built-in frontend page
echo    device     groundstation desktop (PyQt5 window + DSM tiles on 8081)
echo    app        flyer app on 5502 (this PC only)
echo    mobile     phone / LAN test (8082 + 8090 + 5500 + 5502 on 0.0.0.0)
echo    comms      communication / situation page
echo    decision   decision engine prototype (Python)
echo    apk        build the Android APK
echo    check      self-check: pytest + web smoke + API probe
echo    lanip      print the LAN IP used for phone access
echo    help       this text
echo.

REM ============================================================ helpers
:findpy
set "PY="
if exist "%BE%\.venv\Scripts\python.exe" set "PY=%BE%\.venv\Scripts\python.exe"
if not defined PY ( where python >nul 2>nul && set "PY=python" )
if not defined PY ( where py >nul 2>nul && set "PY=py" )
exit /b 0

:getlanip
set "LANIP="
for /f "usebackq delims=" %%i in (`powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-system.ps1" -LanIpOnly`) do set "LANIP=%%i"
if not defined LANIP set "LANIP=127.0.0.1"
exit /b 0

REM ============================================================ errors
:err_nopy
echo.
echo  [ERROR] Python not found: neither backend\.venv nor python / py on PATH.
echo          Install Python 3.10+ and add it to PATH, or run this launcher and
echo          pick menu 5 to build backend\.venv automatically.
echo.
goto end

:err_venv
echo.
echo  [ERROR] Failed to create %BE%\.venv
echo          Check that Python 3.10+ is installed and that the folder is writable.
echo.
goto end

:err_nofile
echo.
echo  [ERROR] Expected file not found. The project tree looks incomplete.
echo.
goto end

:end
if defined INTERACTIVE pause
endlocal
exit /b 0
