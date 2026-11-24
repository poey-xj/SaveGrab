@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0.."

set "PYTHONPATH=%CD%\build_tools;%CD%\vendor;%PYTHONPATH%"

echo [1/2] 检查 PyInstaller...
python -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo   缺少 PyInstaller，请先运行：python build\fetch_build_tools.py
    pause
    exit /b 1
)

echo [2/2] 开始打包...
python -m PyInstaller ^
    --noconfirm --clean ^
    --onedir --windowed ^
    --name SaveGrab ^
    --icon assets\app.ico ^
    --add-data "assets;assets" ^
    main.py

if errorlevel 1 (
    echo.
    echo 打包失败，看上面的报错。
    pause
    exit /b 1
)

echo.
echo 完成：dist\SaveGrab\SaveGrab.exe
pause
