@echo off
setlocal
title Communication / Situation System - Launcher
cd /d "%~dp0"

:menu
cls
echo ============================================================
echo    Low-altitude landing point - live communication ^& situation
echo    Demo launcher
echo ============================================================
echo.
echo    [1] Open web demo (recommended, runs in the browser)
echo    [2] Run the Python decision-engine prototype
echo    [3] Open project folder
echo    [0] Exit
echo.
set /p choice=Enter an option number and press Enter:

if "%choice%"=="1" goto web
if "%choice%"=="2" goto python
if "%choice%"=="3" goto folder
if "%choice%"=="0" goto end
goto menu

:web
start "" "%~dp0index.html"
echo.
echo Opened index.html in the default browser.
echo.
pause
goto menu

:python
echo.
where python >nul 2>nul
if not errorlevel 1 (
    python "%~dp0decision_engine_demo.py"
    goto afterpy
)
where py >nul 2>nul
if not errorlevel 1 (
    py "%~dp0decision_engine_demo.py"
    goto afterpy
)
echo [ERROR] Python not found. Install Python 3 and add it to PATH.
:afterpy
echo.
pause
goto menu

:folder
explorer "%~dp0"
goto menu

:end
endlocal
exit /b
