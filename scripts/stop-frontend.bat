@echo off
cd /d "%~dp0.."
taskkill /F /IM electron.exe >nul 2>&1
exit
