@echo off
chcp 65001 >nul
title 后端诊断
echo.
echo ========== 后端诊断 ==========
echo.

set BASE=http://127.0.0.1:8081/api/v1

echo [1] 检查 debug/version (gate-v2 标识)
curl -s "%BASE%/debug/version" 2>nul
echo.
echo.

echo [2] 检查 broker/testgate (需登录后带 token)
echo    若未登录会返回 401，属正常
curl -s "%BASE%/broker/testgate?mode=simulated" 2>nul
echo.
echo.

echo [3] 检查 broker/status
curl -s "%BASE%/broker/status" 2>nul
echo.
echo.

echo ========== 诊断完成 ==========
echo.
echo 若 debug/version 返回 404 或没有 backend_version: gate-v2
echo 说明 8081 端口运行的不是 gate-v2，请：
echo   1. 关闭所有后端窗口 (Ctrl+C)
echo   2. 运行 start-backend.bat 或 启动-后端.bat
echo   3. 确认窗口显示 "gate-v2 后端"
echo.
pause
