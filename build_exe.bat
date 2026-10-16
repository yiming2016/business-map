@echo off
REM 一键打包 Windows 批处理版本
chcp 65001 > nul
cd /d "%~dp0"
python build_exe.py
if errorlevel 1 (
    echo 打包失败
    pause
    exit /b 1
)
echo.
echo 打包成功。EXE 在 dist\SZ_MetroEditor.exe
pause
