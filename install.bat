@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ==============================================
echo   Giegisa environment installer
echo ==============================================
echo.

set "PY_CMD="
py -3.13 -c "import sys" >nul 2>nul && set "PY_CMD=py -3.13"
if not defined PY_CMD py -3 -c "import sys" >nul 2>nul && set "PY_CMD=py -3"
if not defined PY_CMD python -c "import sys" >nul 2>nul && set "PY_CMD=python"

if not defined PY_CMD (
    echo [ERROR] Python was not found.
    echo Install 64-bit Python and enable "Add Python to PATH".
    echo Restart Windows, then run install.bat again.
    echo.
    pause
    exit /b 1
)

echo [1/4] Python detected:
%PY_CMD% --version
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [2/4] Creating the project environment...
    %PY_CMD% -m venv ".venv"
    if errorlevel 1 goto :failed
) else (
    echo [2/4] The project environment already exists.
)

echo [3/4] Updating pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :failed

echo.
echo [4/4] Installing Giegisa dependencies...
".venv\Scripts\python.exe" -m pip install -r "requirements.txt" -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 (
    echo Mirror failed. Retrying with the official package index...
    ".venv\Scripts\python.exe" -m pip install -r "requirements.txt"
    if errorlevel 1 goto :failed
)

".venv\Scripts\python.exe" -c "import PyQt6, pynput, openai, PyInstaller, charset_normalizer, pypdf, fitz; print('Dependency check passed.')"
if errorlevel 1 goto :failed

echo.
echo ==============================================
echo   Installation succeeded.
echo   Run:   run.bat
echo   Build: pack.bat
echo ==============================================
pause
exit /b 0

:failed
echo.
echo ==============================================
echo   Installation failed.
echo   Keep this window open and take a screenshot.
echo ==============================================
pause
exit /b 1
