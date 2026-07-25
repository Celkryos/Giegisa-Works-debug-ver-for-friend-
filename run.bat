@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ==============================================
echo   Starting Giegisa...
echo ==============================================

if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" "oc.py"
    exit /b 0
)

where pythonw >nul 2>nul
if not errorlevel 1 (
    start "" pythonw "oc.py"
    exit /b 0
)

echo.
echo [ERROR] The Giegisa environment is not installed.
echo Run install.bat first. Run this file again after it succeeds.
echo.
pause
exit /b 1
