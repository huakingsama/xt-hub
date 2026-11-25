@echo off
chcp 936 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

set PY=C:\Users\ADmin\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe
if not exist "%PY%" set PY=python

echo ============================================
echo   XT-HUB demo  (no robot needed)
echo   open:  http://127.0.0.1:18300
echo   login: admin / admin123
echo ============================================
echo.

rem 清掉占着 18300 的旧进程（会白屏多半是旧实例）
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":18300" ^| findstr LISTENING') do (
    echo [x] killing old pid %%P
    taskkill /PID %%P /F >nul 2>&1
)
timeout /t 2 >nul

echo [1/2] starting server ...
start "XT-HUB" /min "%PY%" hub_server.py --demo --dry-run --port 18300
timeout /t 3 >nul

echo [2/2] checking ...
curl -s -m 5 http://127.0.0.1:18300/healthz
echo.
echo.
echo if you see "ok ... demo=True" above, open the browser now.
start "" http://127.0.0.1:18300
echo.
pause
