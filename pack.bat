@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] The build environment is not installed.
    echo Run install.bat first.
    pause
    exit /b 1
)

echo ==============================================
echo   Building Giegisa.exe...
echo ==============================================
echo.

".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean "Giegisa.spec"
if errorlevel 1 goto :failed

echo.
echo ==============================================
echo   Build succeeded.
echo   Output: dist\Giegisa.exe
echo ==============================================
pause
exit /b 0

:failed
echo.
echo ==============================================
echo   Build failed.
echo   Keep this window open and take a screenshot.
echo ==============================================
pause
exit /b 1