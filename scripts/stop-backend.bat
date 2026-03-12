@echo off
cd /d "%~dp0.."
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8081" ^| findstr "LISTENING" 2^>nul') do taskkill /F /PID %%a >nul 2>&1
exit
