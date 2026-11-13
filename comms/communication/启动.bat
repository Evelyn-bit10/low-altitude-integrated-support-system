@echo off
setlocal
title 低空起降点—飞行器实时通讯与态势系统 · 启动器
cd /d "%~dp0"

:menu
cls
echo ============================================================
echo    低空起降点—飞行器实时通讯与态势系统  Demo 启动器
echo ============================================================
echo.
echo    [1] 打开网页演示（推荐，浏览器直接运行）
echo    [2] 运行 Python 决策引擎原型
echo    [3] 打开项目文件夹
echo    [0] 退出
echo.
set /p choice=请输入选项编号并按回车: 

if "%choice%"=="1" goto web
if "%choice%"=="2" goto python
if "%choice%"=="3" goto folder
if "%choice%"=="0" goto end
goto menu

:web
start "" "%~dp0index.html"
echo.
echo 已在默认浏览器中打开 index.html（网页演示）。
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
echo [错误] 未检测到 Python。请先安装 Python 3 并加入 PATH，再试。
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
