@echo off
chcp 936 >nul
setlocal
cd /d "%~dp0"

echo [1/3] staging ...
if exist build_pyz rmdir /s /q build_pyz
mkdir build_pyz
copy /y hub_server.py build_pyz\__main__.py >nul
copy /y LICENSE build_pyz\ >nul 2>&1

echo [2/3] packing zipapp ...
python -m zipapp build_pyz -o xthub.pyz -p "/usr/bin/env python3"
if errorlevel 1 (
    echo [x] zipapp failed - need python 3.5+
    pause & exit /b 1
)

echo [3/3] done
for %%F in (xthub.pyz) do echo   xthub.pyz  %%~zF bytes
echo.
echo   run:  python xthub.pyz --demo --dry-run --port 18300
echo.
pause
