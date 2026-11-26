@echo off
chcp 65001 >nul
title Deploy XT-HUB to the robot (one click)
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================================
echo   XT-HUB  ->  robot  (192.168.110.44 by default)
echo   uploads hub + stack + client package, restarts services
echo ============================================================
echo.

rem ---- robot ip ----
set "IP=%~1"
if "%IP%"=="" (
  if exist "%~dp0robot-ip.txt" set /p IP=<"%~dp0robot-ip.txt"
)
if "%IP%"=="" set "IP=192.168.110.44"
set /p IP2=robot ip [%IP%]: 
if not "%IP2%"=="" set "IP=%IP2%"
echo %IP%>"%~dp0robot-ip.txt"

rem ---- key ----
set "KEY="
if exist "%~dp0robot_key" set "KEY=%~dp0robot_key"
if "%KEY%"=="" if exist "%~dp0..\..\robot_key" set "KEY=%~dp0..\..\robot_key"
if "%KEY%"=="" if exist "D:\A_dsh\SLAM\01_机器人_XTR1\一键脚本\robot_key" set "KEY=D:\A_dsh\SLAM\01_机器人_XTR1\一键脚本\robot_key"
if "%KEY%"=="" ( set "KEYOPT=" ) else ( set "KEYOPT=-i "%KEY%"" )

echo.
echo [1/6] ping ...
ping -n 2 %IP% >nul || ( echo [x] 车不通，先确认车上电+连同一个 Wi-Fi & pause & exit /b 1 )

echo [2/6] ssh ...
ssh -o StrictHostKeyChecking=no -o ConnectTimeout=8 %KEYOPT% xtrobot@%IP% "hostname; python3 -V; uptime"
if errorlevel 1 ( echo [x] ssh 失败 & pause & exit /b 1 )

echo [3/6] upload core files ...
ssh -o StrictHostKeyChecking=no %KEYOPT% xtrobot@%IP% "mkdir -p ~/xthub/dist"
scp -o StrictHostKeyChecking=no %KEYOPT% hub_server.py robot_stack.py make3d_html.py %KEY% xtrobot@%IP%:~/xthub/ 2>nul
scp -o StrictHostKeyChecking=no %KEYOPT% hub_server.py robot_stack.py make3d_html.py xtrobot@%IP%:~/xthub/
if errorlevel 1 ( echo [x] scp 失败 & pause & exit /b 1 )
if exist config.json scp -o StrictHostKeyChecking=no %KEYOPT% config.json xtrobot@%IP%:~/xthub/
if exist dist\client.zip scp -o StrictHostKeyChecking=no %KEYOPT% dist\client.zip xtrobot@%IP%:~/xthub/dist/

echo [4/6] restart services ...
ssh -o StrictHostKeyChecking=no %KEYOPT% xtrobot@%IP% "echo xtrobot | sudo -S systemctl restart xt-hub 2>/dev/null; echo xtrobot | sudo -S systemctl restart xt-stack 2>/dev/null; sleep 2; systemctl is-active xt-hub; systemctl is-active xt-stack"

echo [5/6] verify ...
ssh -o StrictHostKeyChecking=no %KEYOPT% xtrobot@%IP% "curl -s http://127.0.0.1:8000/healthz; echo; curl -s http://127.0.0.1:8000/api/client/version; echo; ss -lnt | grep -E ':8000|:8100'"

echo [6/6] done.
echo.
echo   ============================================
echo    open on any PC/phone in the same Wi-Fi:
echo       http://%IP%:8000
echo    accounts: zwh/zwh123   zbw lyh tjc sjrx / 1234
echo   ============================================
echo.
pause
