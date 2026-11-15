@echo off
setlocal
title Low-Altitude Integrated Support System - Demo Console
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-demo.ps1"
pause
