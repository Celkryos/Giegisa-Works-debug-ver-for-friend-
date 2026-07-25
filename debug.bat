@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] The debug environment is not installed.
    echo Run install.bat first.
    pause
    exit /b 1
)

echo ==============================================
echo   Giegisa debug mode
echo   Keep this window open while the pet is running.
echo ==============================================
echo.

".venv\Scripts\python.exe" "oc.py"
set "EXIT_CODE=%ERRORLEVEL%"

echo.
echo ==============================================
echo   Giegisa stopped. Exit code: %EXIT_CODE%
echo   If an error is shown above, take a screenshot.
echo ==============================================
pause
exit /b %EXIT_CODE%
