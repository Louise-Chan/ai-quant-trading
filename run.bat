@echo off
title SilentSigma Launcher
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo.
echo ============================================
echo    SilentSigma  -  One-Click Launcher
echo ============================================
echo.

rem --- 1. start backend in a separate minimized window ---
echo [1/2] Starting backend service...
start "SilentSigma Backend" /MIN cmd /c "scripts\start-backend.bat"

rem --- 2. wait for backend health endpoint to be ready (up to ~60s) ---
echo       Waiting for backend to be ready, please wait...
set /a tries=0

:wait_loop
set /a tries+=1
if !tries! gtr 60 goto health_timeout

powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8081/api/v1/health' -UseBasicParsing -TimeoutSec 1 -ErrorAction Stop; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>&1
if !errorlevel! equ 0 goto backend_ready

timeout /t 1 /nobreak >nul 2>&1
goto wait_loop

:health_timeout
echo.
echo [ERROR] Backend startup timeout (~60s).
echo         Please check the "SilentSigma Backend" window for details.
echo         Common causes: missing dependencies, port 8081 in use, Python errors.
echo.
pause
exit /b 1

:backend_ready
echo [1/2] Backend is ready.
echo.

rem --- 3. start frontend (Electron) in a separate minimized window ---
echo [2/2] Starting frontend (Electron)...
start "SilentSigma Frontend" /MIN cmd /c "scripts\start-frontend.bat"

rem --- 4. launcher exits after a short delay; backend/frontend keep running ---
echo.
echo Launch complete. The Electron window will appear shortly.
echo Closing this window will NOT stop the running services.
echo (To stop them, run scripts\stop-backend.bat and scripts\stop-frontend.bat)
echo.
timeout /t 3 /nobreak >nul 2>&1
exit /b 0
