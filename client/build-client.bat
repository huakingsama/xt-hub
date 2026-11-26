@echo off
chcp 65001 >nul
REM build XT-HUB client exe (needs PyInstaller installed)
setlocal
cd /d "%~dp0"

set "PY=python"
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"

echo [1/2] building onedir package ...
"%PY%" -m PyInstaller --onedir --windowed --name XTHUBClient ^
  --distpath "..\..\client_build" ^
  --workpath "..\..\client_tmp" ^
  --specpath "..\..\client_tmp" ^
  --noconfirm xthub_client.py
if errorlevel 1 goto fail

echo [2/2] done.
echo   output: %~dp0..\..\client_build\XTHUBClient\XTHUBClient.exe
echo   next  : zip that folder with docs for distribution
pause
exit /b 0

:fail
echo [x] build failed
pause
exit /b 1
