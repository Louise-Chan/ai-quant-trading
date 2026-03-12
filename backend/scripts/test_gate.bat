@echo off
cd /d "%~dp0.."
if "%~1"=="" (
    echo Usage: test_gate.bat YOUR_API_KEY YOUR_API_SECRET [simulated^|real]
    echo Example: test_gate.bat abc123 xyz789 simulated
    pause
    exit /b 1
)
python scripts/test_gate_api.py %*
pause
