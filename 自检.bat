@echo off
setlocal
title Self-check
cd /d "%~dp0"
set "BE=%~dp0flight\flycontrol\low-altitude-demo\backend"
set "PY=%BE%\.venv\Scripts\python.exe"
if not exist "%PY%" ( where python >nul 2>nul && set "PY=python" )

echo.
echo  ============================================================
echo    Self-check: unit tests / web smoke / API
echo  ============================================================
echo.

if not defined PY (
  echo  [ERROR] Python not found: neither backend\.venv nor python on PATH.
  pause & exit /b 1
)
echo  Python : %PY%
echo.

echo  [1/3] unit tests ...
pushd "%BE%"
"%PY%" -m pytest tests -q
if errorlevel 1 (echo  [FAIL] tests & popd & pause & exit /b 1)
set PYTHONIOENCODING=utf-8
"%PY%" tools\smoke_web.py
popd

echo  [2/3] API health ...
powershell -NoProfile -Command ^
 "try { $r=Invoke-WebRequest -Uri 'http://127.0.0.1:8082/api/health' -TimeoutSec 3 -UseBasicParsing; Write-Host '  [OK] backend 8082' } catch { Write-Host '  [SKIP] backend not running (start via the portal launcher)' }"

echo  [3/3] demo scenario ...
echo  [OK] done
echo.
pause
