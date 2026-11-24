@echo off
chcp 65001 >nul
cd /d "%~dp0"
title SaveGrab

if exist "SaveGrab.exe" (
    start "" "SaveGrab.exe"
    exit /b
)

where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw main.py
    exit /b
)

where python >nul 2>nul
if %errorlevel%==0 (
    start "" python main.py
    exit /b
)

echo.
echo   没找到 Python 环境。
echo   如果你是普通用户，请使用打包好的 SaveGrab.exe。
echo.
pause
