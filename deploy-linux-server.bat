@echo off
chcp 65001 >nul
title Deploy XT-HUB to a Linux server
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================================
echo  Deploy XT-HUB to a Linux box (lab server / mini PC / Pi)
echo  It uploads the files, then installs a systemd service.
echo ============================================================
echo.

rem --- target host
set "HOST=%~1"
if "%HOST%"=="" set "HOST=192.168.129.178"
set /p HOST2=target host [%HOST%]: 
if not "%HOST2%"=="" set "HOST=%HOST2%"

set "USER_=zwh"
set /p U2=ssh user [%USER_%]: 
if not "%U2%"=="" set "USER_=%U2%"

set "KEY=%USERPROFILE%\.ssh\id_dsh_slam"
if not exist "%KEY%" set "KEY="
set /p K2=ssh key path [%KEY%]: 
if not "%K2%"=="" set "KEY=%K2%"
if "%KEY%"=="" ( set "KEYOPT=" ) else ( set "KEYOPT=-i "%KEY%"" )

echo.
echo [1/4] test ssh ...
ssh -o StrictHostKeyChecking=no -o ConnectTimeout=8 %KEYOPT% %USER_%@%HOST% "echo hello; hostname; python3 -V"
if errorlevel 1 ( echo [x] ssh failed & pause & exit /b 1 )

echo [2/4] upload files ...
ssh -o StrictHostKeyChecking=no %KEYOPT% %USER_%@%HOST% "mkdir -p ~/xthub/dist"
scp -o StrictHostKeyChecking=no %KEYOPT% hub_server.py robot_stack.py make3d_html.py %USER_%@%HOST%:~/xthub/ 
if errorlevel 1 ( echo [x] scp failed & pause & exit /b 1 )
if exist config.json scp -o StrictHostKeyChecking=no %KEYOPT% config.json %USER_%@%HOST%:~/xthub/
if exist dist\client.zip scp -o StrictHostKeyChecking=no %KEYOPT% dist\client.zip %USER_%@%HOST%:~/xthub/dist/

echo [3/4] install systemd service (will ask for sudo password) ...
type deploy-linux-server.sh | ssh -t -o StrictHostKeyChecking=no %KEYOPT% %USER_%@%HOST% "cat > ~/xthub/deploy.sh; bash ~/xthub/deploy.sh ~/xthub"
if errorlevel 1 ( echo [x] install failed & pause & exit /b 1 )

echo [4/4] verify ...
ssh -o StrictHostKeyChecking=no %KEYOPT% %USER_%@%HOST% "curl -s http://127.0.0.1:8000/healthz; echo"
echo.
echo [ok] open from LAN:  http://%HOST%:8000
pause
