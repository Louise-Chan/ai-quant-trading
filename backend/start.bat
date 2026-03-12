@echo off
title Backend
cd /d "%~dp0"

for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8081" ^| findstr "LISTENING" 2^>nul') do taskkill /F /PID %%a >nul 2>&1
ping 127.0.0.1 -n 2 >nul

if exist __pycache__ rmdir /s /q __pycache__ 2>nul
if exist api\__pycache__ rmdir /s /q api\__pycache__ 2>nul

echo.
echo [gate-v2] Starting...
echo.

python main.py
pause
