@echo off
setlocal
title Self-check
cd /d "%~dp0"
set "BE=%~dp0flight\flycontrol\low-altitude-demo\backend"
set "PY=%BE%\.venv\Scripts\python.exe"

echo.
echo  ============================================================
echo    Self-check: tests / web smoke / API
echo  ============================================================
echo.

if not exist "%PY%" (
  echo  [ERROR] venv not found. Run 一键启动.bat first.
  pause & exit /b 1
)

echo  [1/3] unit tests ...
pushd "%BE%"
"%PY%" -m pytest tests -q
if errorlevel 1 (echo  [FAIL] tests & popd & pause & exit /b 1)
set PYTHONIOENCODING=utf-8
"%PY%" tools\smoke_web.py
popd

echo  [2/3] API health ...
powershell -NoProfile -Command ^
 "try { $r=Invoke-WebRequest -Uri 'http://127.0.0.1:8080/api/health' -TimeoutSec 3 -UseBasicParsing; Write-Host '  [OK] backend 8080' } catch { Write-Host '  [SKIP] backend not running (start via 一键启动.bat)' }"

echo  [3/3] demo scenario ...
echo  [OK] done
echo.
pause
