@echo off
setlocal
title 低空综合保障系统 · 功能演示台
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-demo.ps1"
pause
