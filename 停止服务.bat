@echo off
setlocal EnableExtensions
title Stop all low-altitude services
cd /d "%~dp0"

REM  Ports used by the system:
REM    8082 backend | 8081 groundstation DSM tiles | 8090 ground bridge
REM    8099 mock UOM | 5500 portal | 5502 flyer app
set "PORTS=8082 8081 8090 8099 5500 5502"
set /a STOPPED=0
set /a SKIPPED=0
set /a FREE=0
set "DONE= "

echo.
echo  ============================================================
echo    Stopping all low-altitude services
echo    ports: %PORTS%
echo  ============================================================
echo.

for %%P in (%PORTS%) do call :stop_port %%P

echo.
echo  ------------------------------------------------------------
echo    stopped: %STOPPED%    skipped: %SKIPPED%    idle: %FREE%
echo  ------------------------------------------------------------
if %STOPPED%==0 if %SKIPPED%==0 echo    Nothing was running.
if %SKIPPED% GTR 0 echo    NOTE: [SKIP] ports are held by non-python processes and were left alone.
echo.
echo  Press any key to close this window.
echo.
pause >nul
endlocal
exit /b 0

REM ---------------------------------------------------------------- helpers
:stop_port
set "PORT=%~1"
set "HIT="
for /f "tokens=5" %%I in ('netstat -ano ^| findstr /r /c:":%PORT% " ^| findstr /i "LISTENING"') do call :try_kill %%I %PORT%
if not defined HIT (
    echo   [ -- ] port %PORT% : idle
    set /a FREE+=1
)
goto :eof

:try_kill
set "FOUND=1"
set "HIT=1"
set "PID=%~1"
set "PORT=%~2"
REM  same PID can show up twice (IPv4 + IPv6 listeners) - only handle it once
echo %DONE% | findstr /c:" %PID% " >nul && goto :eof
set "DONE=%DONE%%PID% "
set "PNAME=unknown"
for /f "tokens=1 delims=," %%N in ('tasklist /FI "PID eq %PID%" /FO CSV /NH 2^>nul') do set "PNAME=%%~N"
REM  match any interpreter name that starts with "python" (python.exe,
REM  pythonw.exe, python3.13.exe from the Store build, conda variants, ...)
echo %PNAME% | findstr /i /b /c:"python" >nul && goto kill
echo   [SKIP] port %PORT% : held by %PNAME% pid %PID% - not a project service, left alone
set /a SKIPPED+=1
goto :eof

:kill
REM  /T ends the child processes too - the QtWebEngine helper keeps the port alive otherwise
taskkill /PID %PID% /T /F >nul 2>&1
ping -n 3 127.0.0.1 >nul
set "STILL="
for /f "tokens=5" %%I in ('netstat -ano ^| findstr /r /c:":%PORT% " ^| findstr /i "LISTENING"') do set "STILL=1"
if defined STILL (
    echo   [WARN] port %PORT% : pid %PID% still holds the port after taskkill
) else (
    echo   [ OK ] port %PORT% : stopped %PNAME% pid %PID%
    set /a STOPPED+=1
)
goto :eof
