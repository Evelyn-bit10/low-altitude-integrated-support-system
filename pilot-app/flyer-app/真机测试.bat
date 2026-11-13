@echo off
setlocal
title 挺中航空 · 飞手端 — 手机真机测试
cd /d "%~dp0"

set "ROOT=%~dp0"
set "API_DIR=%ROOT%..\..\flight\flycontrol\low-altitude-demo\backend"
set "API_PY=%API_DIR%\.venv\Scripts\python.exe"
set "BRIDGE=%ROOT%..\..\platform\portal\ground-bridge.py"
set "APP_PORT=5502"
set "API_PORT=8080"
set "GROUND_PORT=8090"
set "PORTAL_PORT=5500"

echo ============================================================
echo   挺中航空 · 飞手端 — 手机真机测试
echo   一并启动：flycontrol API ＋ 地面站数据桥 ＋ 飞手端 ＋ 一体化门户
echo ============================================================
echo.

if not exist "%API_PY%" (
  echo [错误] 未找到 flycontrol 的虚拟环境：
  echo        %API_PY%
  pause
  exit /b 1
)

REM ---------- 取本机局域网 IP ----------
set "LANIP="
set "IPTMP=%TEMP%\tz_lanip.txt"
powershell -NoProfile -Command "$ip=(Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } | Select-Object -First 1).IPAddress; Write-Output $ip" > "%IPTMP%" 2>nul
if exist "%IPTMP%" set /p LANIP=<"%IPTMP%"
del "%IPTMP%" >nul 2>nul
if not defined LANIP set "LANIP=127.0.0.1"

echo 本机局域网 IP : %LANIP%
echo.

echo [1/4] flycontrol API  监听 0.0.0.0:%API_PORT%
start "flycontrol-api" /D "%API_DIR%" /MIN "%API_PY%" -m uvicorn app.main:app --host 0.0.0.0 --port %API_PORT%

echo [2/4] 地面站数据桥     监听 0.0.0.0:%GROUND_PORT%
start "ground-bridge" /MIN "%API_PY%" "%BRIDGE%" --host 0.0.0.0 --port %GROUND_PORT%

echo [3/4] 飞手端 App       监听 0.0.0.0:%APP_PORT%
start "flyer-app" /D "%ROOT%" /MIN "%API_PY%" -m http.server %APP_PORT% --bind 0.0.0.0

echo [4/4] 一体化门户       监听 0.0.0.0:%PORTAL_PORT%
start "portal" /D "%ROOT%..\..\platform\portal" /MIN "%API_PY%" -m http.server %PORTAL_PORT% --bind 0.0.0.0

echo.
echo 等待服务就绪...
timeout /t 5 /nobreak >nul

echo.
echo ============================================================
echo   手机浏览器打开（手机需与电脑连同一 Wi-Fi）：
echo.
echo     飞手端 App     http://%LANIP%:%APP_PORT%/index.html
echo     网页端门户     http://%LANIP%:%PORTAL_PORT%/index.html
echo.
echo   App 会自动把后端指向 %LANIP% 的 %API_PORT% / %GROUND_PORT%，
echo   与网页端门户用的是同一套后端，数据可直接对比。
echo ============================================================
echo.
echo   手机打不开时：
echo     1) 放行 Windows 防火墙的 Python（专用和公用网络都勾上）
echo     2) 或以管理员身份运行一次下面命令，一次性放行所需端口：
echo        New-NetFirewallRule -DisplayName "TingzhongDemo" -Direction Inbound -Protocol TCP -LocalPort 5500,5502,8080,8090 -Action Allow
echo.
echo   停止服务：把新开的那几个最小化窗口关掉即可。
echo.

start "" "http://127.0.0.1:%APP_PORT%/index.html"
pause
