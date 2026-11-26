@echo off
chcp 65001 >nul
title XT-HUB server (this PC)
cd /d "%~dp0"

set "PY="
if exist "C:\Users\ADmin\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe" set "PY=C:\Users\ADmin\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
if "%PY%"=="" if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if "%PY%"=="" set "PY=python"

echo ============================================================
echo  XT-HUB server will run on THIS PC, port 8000
echo  Clients on the same Wi-Fi connect to this PC's IP.
echo ============================================================
echo.

for /f "tokens=2 delims=:" %%A in ('ipconfig ^| findstr /c:"IPv4"') do (
  for /f "tokens=* delims= " %%B in ("%%A") do echo   http://%%B:8000
)
echo.
echo  [important] Windows firewall must allow TCP 8000.
echo  If friends cannot open it, run  open-firewall-8000.bat  as admin.
echo.

"%PY%" hub_server.py --port 8000
pause
