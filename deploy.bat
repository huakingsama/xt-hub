@echo off
setlocal enabledelayedexpansion
set DIR=%~dp0
cd /d "%DIR%"

rem ---- locate tools dir: scan sibling folders of hub\ for robot-ip.txt ----
set TOOLS=
if exist "%DIR%robot-ip.txt" set TOOLS=%DIR%
if not defined TOOLS (
  for /d %%X in ("%DIR%..\*") do (
    if exist "%%~fX\robot-ip.txt" if not defined TOOLS set TOOLS=%%~fX
  )
)

if not defined TOOLS (
  echo [i] robot-ip.txt not found. Type the robot IP, e.g. 192.168.110.44
  set /p RIP=
  if "!RIP!"=="" (echo no input, abort & pause & exit /b 1)
  > "%DIR%robot-ip.txt" echo !RIP!
  set TOOLS=%DIR%
  echo [i] saved to %DIR%robot-ip.txt
)
set /p RIP=<"%TOOLS%\robot-ip.txt"
set RIP=%RIP: =%
if not "%~1"=="" (
  set RIP=%~1
  > "%TOOLS%\robot-ip.txt" echo %~1
  echo [i] IP overridden by argument: %~1
)

set KEY=
if exist "%TOOLS%\robot_key" set KEY=%TOOLS%\robot_key
if not defined KEY if exist "%DIR%robot_key" set KEY=%DIR%robot_key
if not defined KEY if exist "%DIR%..\robot_key" set KEY=%DIR%..\robot_key
if not defined KEY (echo [x] robot_key not found & pause & exit /b 1)
set SSHOPT=-o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile="%TOOLS%\known_hosts" -i "%KEY%"

echo ==========================================================
echo   XT-HUB  deploy
echo   robot : %RIP%
echo   tools : %TOOLS%
echo ==========================================================
echo.

echo [0/3] connectivity ...
ping -n 1 -w 1200 %RIP% >nul
if errorlevel 1 (
  echo   [x] cannot ping %RIP%
  echo       1^) is the robot powered on and on the same wifi/router
  echo       2^) did the PC change subnet - run find-robot.bat again
  pause & exit /b 1
)

echo [1/3] uploading hub ...
scp %SSHOPT% "hub_server.py" "install.sh" xtrobot@%RIP%:/home/xtrobot/ >nul
if errorlevel 1 (echo   upload failed: key or account wrong & pause & exit /b 1)

echo [2/3] installing on robot (systemd: xt-hub) ...
ssh %SSHOPT% xtrobot@%RIP% "sed -i 's/\r$//' /home/xtrobot/install.sh; bash /home/xtrobot/install.sh 8000"
if errorlevel 1 (echo   install failed - see output above & pause & exit /b 1)

echo.
echo [3/3] opening console ...
start "" "http://%RIP%:8000/"
echo.
echo ----------------------------------------------------------
echo   console : http://%RIP%:8000/
echo   login   : admin / admin123   (change it at /admin)
echo ----------------------------------------------------------
pause
