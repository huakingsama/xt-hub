@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
set DIR=%~dp0
set KEY=%DIR%robot_key

rem ---- find robot-ip.txt ----
set IP=
if exist "%DIR%robot-ip.txt" (
  set /p IP=<"%DIR%robot-ip.txt"
) else (
  for /d %%X in ("%DIR%..\*") do (
    if exist "%%~fX\robot-ip.txt" if not defined IP set /p IP=<"%%~fX\robot-ip.txt"
  )
)
if not defined IP set /p IP=robot ip: 
if "%~1" neq "" set IP=%~1

echo [x] source : %DIR%
echo [x] robot  : %IP%

if not exist "%KEY%" (
  echo [x] robot_key not found in %DIR%
  goto :end
)

echo.
echo [1/3] upload hub_server.py + robot_stack.py ...
scp -o StrictHostKeyChecking=no -i "%KEY%" "%DIR%hub_server.py" xtrobot@%IP%:~/hub_server.py || goto :fail
if exist "%DIR%teleop_bridge.py" scp -o StrictHostKeyChecking=no -i "%KEY%" "%DIR%teleop_bridge.py" xtrobot@%IP%:~/teleop_bridge.py
if exist "%DIR%robot_stack.py" scp -o StrictHostKeyChecking=no -i "%KEY%" "%DIR%robot_stack.py" xtrobot@%IP%:~/robot_stack.py

echo [2/3] restart service ...
ssh -o StrictHostKeyChecking=no -i "%KEY%" xtrobot@%IP% "sudo -n systemctl restart xt-hub 2>/dev/null || (pkill -f 'hub_serve[r].py' ; sleep 1; cd ~ && nohup python3 hub_server.py --port 8000 > ~/hub.log 2>&1 & echo started-by-nohup); sudo -n systemctl restart xt-stack 2>/dev/null || (pgrep -f 'robot_stac[k].py' >/dev/null || (cd ~ && setsid nohup python3 robot_stack.py --port 8100 > ~/stack.log 2>&1 < /dev/null &)) ; echo stack-ok"

echo [3/3] verify ...
ssh -o StrictHostKeyChecking=no -i "%KEY%" xtrobot@%IP% "sleep 3; curl -s -m 5 http://127.0.0.1:8000/healthz; echo; curl -s -m 5 http://127.0.0.1:8100/status | head -c 160; echo"

echo.
echo DONE.  open  http://%IP%:8000
goto :end

:fail
echo [x] upload failed (check ip / key / robot online)

:end
pause
