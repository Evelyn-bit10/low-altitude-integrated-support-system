@echo off
setlocal
title Flyer App - Android APK Build
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build-apk.ps1"
if errorlevel 1 pause
