@echo off
setlocal
title flycontrol 后端 · 低空动态起降飞行程序实时调整系统
cd /d "%~dp0backend"

if not exist ".venv\Scripts\python.exe" (
    echo [错误] 未找到虚拟环境 backend\.venv。
    echo        请先执行:  python -m venv .venv
    echo        再执行:  .venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)

echo ============================================================
echo   flycontrol 后端启动中 ...
echo   地址: http://127.0.0.1:8080   (flycontrol 前端)
echo   接口文档: http://127.0.0.1:8080/docs
echo.
echo   联动提示: 保持本窗口运行, 再双击 communication\启动.bat
echo   打开通讯态势系统, 两者即自动双向同步。
echo   (无 Postgres 时自动回退 SQLite, 无需额外配置)
echo ============================================================
echo.
echo 按 Ctrl+C 停止后端。
echo.

".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8080
pause
