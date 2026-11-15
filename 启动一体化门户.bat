@echo off
setlocal
title Low-Altitude Integrated Support System - Portal Launcher
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-system.ps1"
pause
