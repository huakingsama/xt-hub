@echo off
setlocal
chcp 65001 >nul
set DIR=%~dp0
set KEY=%DIR%robot_key

rem ---- robot ip ----
set IP=
if exist "%DIR%robot-ip.txt" set /p IP=<"%DIR%robot-ip.txt"
if not defined IP set /p IP=robot ip: 
if "%~1" neq "" if "%~2" neq "" set IP=%~2

if "%~1"=="" (
  echo Drag a .html / .png / .pcd file onto this bat, or:
  echo    upload-3d.bat file.html 192.168.1.50
  goto :end
)

set FILE=%~1
set NAME=%~nx1

if not exist "%FILE%" (
  echo [x] file not found: %FILE%
  goto :end
)

echo [x] robot : %IP%
echo [x] upload: %NAME%

ssh -o StrictHostKeyChecking=no -i "%KEY%" xtrobot@%IP% "mkdir -p ~/3d_maps"
scp -o StrictHostKeyChecking=no -i "%KEY%" "%FILE%" xtrobot@%IP%:~/3d_maps/ || goto :fail

echo.
echo DONE. open the console, click "3D map" in the top bar:
echo        http://%IP%:8000/3d
goto :end

:fail
echo [x] upload failed (check ip / key / robot online)

:end
pause
