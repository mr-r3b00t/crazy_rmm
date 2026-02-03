@echo off
:: ══════════════════════════════════════════════════════════════════════════════
::  Remote Support Client — Windows x64 Build Script
::  Run this on a Windows machine with Python 3.10+ installed.
:: ══════════════════════════════════════════════════════════════════════════════
setlocal enabledelayedexpansion

echo.
echo ══════════════════════════════════════════════════════════
echo   Remote Support Client — Windows x64 Builder
echo ══════════════════════════════════════════════════════════
echo.

:: ── Check Python ─────────────────────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo [FAIL] Python not found. Install Python 3.10+ from https://python.org
    echo        Make sure "Add Python to PATH" is checked during install.
    pause
    exit /b 1
)

for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo [OK]   Python %PYVER% found.

:: ── Create virtual environment ───────────────────────────────────────────────
if not exist "build_env" (
    echo [INFO] Creating virtual environment...
    python -m venv build_env
)
call build_env\Scripts\activate.bat
echo [OK]   Virtual environment activated.

:: ── Install dependencies ─────────────────────────────────────────────────────
echo [INFO] Installing build dependencies...
pip install --quiet --upgrade pip
pip install --quiet pyinstaller==6.* websockets mss Pillow pyautogui

if errorlevel 1 (
    echo [FAIL] Failed to install dependencies.
    pause
    exit /b 1
)
echo [OK]   Dependencies installed.

:: ── Build ────────────────────────────────────────────────────────────────────
echo [INFO] Building executable...
echo.

pyinstaller ^
    --noconfirm ^
    --clean ^
    --onefile ^
    --noconsole ^
    --name "RemoteSupportClient" ^
    --target-arch x86_64 ^
    --hidden-import websockets ^
    --hidden-import websockets.legacy ^
    --hidden-import websockets.legacy.client ^
    --hidden-import websockets.legacy.server ^
    --hidden-import websockets.legacy.protocol ^
    --hidden-import mss ^
    --hidden-import mss.windows ^
    --hidden-import PIL.Image ^
    --hidden-import PIL.JpegImagePlugin ^
    --hidden-import pyautogui ^
    --hidden-import pyautogui._pyautogui_win ^
    --hidden-import pyscreeze ^
    --hidden-import pytweening ^
    --hidden-import pyperclip ^
    --hidden-import mouseinfo ^
    --exclude-module matplotlib ^
    --exclude-module numpy ^
    --exclude-module scipy ^
    --exclude-module pandas ^
    client_windows.py

if errorlevel 1 (
    echo.
    echo [FAIL] Build failed. Check errors above.
    pause
    exit /b 1
)

:: ── Done ─────────────────────────────────────────────────────────────────────
echo.
echo ══════════════════════════════════════════════════════════
echo   BUILD SUCCESSFUL
echo ══════════════════════════════════════════════════════════
echo.
echo   Output: dist\RemoteSupportClient.exe
echo.
echo   Usage:
echo     RemoteSupportClient.exe
echo     RemoteSupportClient.exe --server ws://192.168.1.100:3000
echo     RemoteSupportClient.exe --server ws://myserver.com:3000 --fps 15 --quality 60
echo.

:: Show file size
for %%A in (dist\RemoteSupportClient.exe) do (
    set /a SIZE=%%~zA / 1048576
    echo   Size: ~!SIZE! MB
)
echo.

deactivate
pause
