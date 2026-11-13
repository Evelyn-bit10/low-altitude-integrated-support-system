@echo off
setlocal
title 挺中航空 · C 端
cd /d "%~dp0"

set "PORT=5502"
set "URL=http://127.0.0.1:%PORT%/index.html"

echo ============================================================
echo   挺中航空 · C 端（手机端 Web App）
echo ============================================================
echo.

set "PY="
if exist "..\..\flight\flycontrol\low-altitude-demo\backend\.venv\Scripts\python.exe" set "PY=..\..\flight\flycontrol\low-altitude-demo\backend\.venv\Scripts\python.exe"
if not defined PY ( where python >nul 2>nul && set "PY=python" )

if not defined PY (
  echo [提示] 未找到 Python，改为直接打开 index.html
  echo        直接打开时 Service Worker / PWA 安装不可用（需要 http 环境）。
  start "" "%~dp0index.html"
  pause
  exit /b 0
)

echo 正在启动本地服务: %URL%
start "flyer-app-server" /MIN "%PY%" -m http.server %PORT% --bind 127.0.0.1
timeout /t 2 /nobreak >nul
start "" "%URL%"

echo.
echo 已打开。使用建议：
echo   - 按 F12 打开设备模式，选择 iPhone 375 宽度预览手机效果
echo   - 浏览器菜单「安装应用 / 添加到主屏幕」可当独立 App 使用
echo   - 手机真机预览：见 README.md「真机预览」一节
echo.
echo 服务窗口已最小化；关闭那个窗口即停止服务。
pause
