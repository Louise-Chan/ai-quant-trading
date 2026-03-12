@echo off
cd /d "%~dp0"
echo.
echo 1=Start Backend  2=Stop Backend
echo 3=Start Frontend 4=Stop Frontend
echo 0=Exit
echo.
set /p c=Choice:
if "%c%"=="1" call scripts\start-backend.bat
if "%c%"=="2" call scripts\stop-backend.bat
if "%c%"=="3" call scripts\start-frontend.bat
if "%c%"=="4" call scripts\stop-frontend.bat
if "%c%"=="0" exit
pause
