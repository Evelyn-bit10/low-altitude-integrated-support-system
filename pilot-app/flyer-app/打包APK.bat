@echo off
setlocal
title 挺中航空 · 飞手端 — Android APK 打包
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build-apk.ps1"
if errorlevel 1 pause
