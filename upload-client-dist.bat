@echo off
chcp 65001 >nul
REM Push the client upgrade package to the robot so clients can self-update.
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "ZIP=%~dp0dist\client.zip"
if not exist "%ZIP%" (
  echo [x] dist\client.zip not found. Build the client first:
  echo     client\build-client.bat
  echo     then zip client_build_new\XTHUBClient into dist\client.zip
  pause & exit /b 1
)

REM locate robot ip
set "IP="
if exist "%~dp0robot-ip.txt" set /p IP=<"%~dp0robot-ip.txt"
if "%IP%"=="" if exist "%~dp0..\..\robot-ip.txt" set /p IP=<"%~dp0..\..\robot-ip.txt"
if "%IP%"=="" set /p IP=robot ip: 

REM locate key
set "KEY="
if exist "%~dp0robot_key" set "KEY=%~dp0robot_key"
if "%KEY%"=="" if exist "%~dp0..\..\robot_key" set "KEY=%~dp0..\..\robot_key"
if "%KEY%"=="" if exist "%USERPROFILE%\.ssh\id_ed25519" set "KEY=%USERPROFILE%\.ssh\id_ed25519"

echo [1/3] robot : %IP%
echo [2/3] key   : %KEY%
if not "%KEY%"=="" set "KEYOPT=-i "%KEY%""

ssh -o StrictHostKeyChecking=no %KEYOPT% xtrobot@%IP% "mkdir -p ~/xthub/dist"
if errorlevel 1 ( echo [x] ssh failed & pause & exit /b 1 )

echo [3/3] upload dist\client.zip ...
scp -o StrictHostKeyChecking=no %KEYOPT% "%ZIP%" xtrobot@%IP%:~/xthub/dist/client.zip
if errorlevel 1 ( echo [x] scp failed & pause & exit /b 1 )

echo.
echo [ok] done. check:  curl http://%IP%:8000/api/client/version
pause
