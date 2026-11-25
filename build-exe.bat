@echo off
chcp 936 >nul
setlocal
cd /d "%~dp0"

echo ============================================
echo   XT-HUB  build single-file exe
echo ============================================
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo [x] python not found in PATH
    pause & exit /b 1
)

echo [1/3] checking pyinstaller ...
python -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo       not installed, installing ...
    python -m pip install --upgrade pyinstaller
    if errorlevel 1 (
        echo [x] pip install failed
        pause & exit /b 1
    )
)

echo [2/3] building ...
python -m PyInstaller --onefile --console --name xthub ^
    --add-data "LICENSE;." ^
    hub_server.py
if errorlevel 1 (
    echo [x] build failed
    pause & exit /b 1
)

echo [3/3] result
if exist dist\xthub.exe (
    echo.
    echo   OK  dist\xthub.exe
    for %%F in (dist\xthub.exe) do echo   size: %%~zF bytes
    echo.
    echo   run:  dist\xthub.exe --demo --dry-run --port 18300
) else (
    echo [x] dist\xthub.exe not found
)

echo.
pause
