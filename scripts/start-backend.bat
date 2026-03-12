@echo off
chcp 65001 >nul 2>&1
title Backend

set "SCRIPT_DIR=%~dp0"
set "BACKEND_DIR=%SCRIPT_DIR%..\backend"
set "PROJECT_ROOT=%SCRIPT_DIR%.."

cd /d "%PROJECT_ROOT%"
cd /d "%BACKEND_DIR%"
if not exist main.py (
    echo Error: main.py not found in %BACKEND_DIR%
    pause
    exit /b 1
)

for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8081" ^| findstr "LISTENING" 2^>nul') do taskkill /F /PID %%a >nul 2>&1
ping 127.0.0.1 -n 2 >nul

if exist __pycache__ rmdir /s /q __pycache__ 2>nul
if exist api\__pycache__ rmdir /s /q api\__pycache__ 2>nul

echo.
echo [gate-v2] Starting backend...
echo.

python main.py

pause
