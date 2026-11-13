@echo off
setlocal
title 挺中航空 · 低空综合保障系统 — 一键启动
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-system.ps1"
pause