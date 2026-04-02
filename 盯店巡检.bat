@echo off
chcp 65001 >nul
title 盯店巡检

set SCRIPT_DIR=%~dp0
:: 优先 Chromium，没有就用 Chrome
if exist "C:\Program Files\Chromium\Application\chrome.exe" (
    set CHROME="C:\Program Files\Chromium\Application\chrome.exe"
) else if exist "%LOCALAPPDATA%\Chromium\Application\chrome.exe" (
    set CHROME="%LOCALAPPDATA%\Chromium\Application\chrome.exe"
) else (
    set CHROME="C:\Program Files\Google\Chrome\Application\chrome.exe"
)
set PORT=9222

:: ===== 1. 检查Python =====
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Python未安装，请先安装Python: https://www.python.org/downloads/
    echo 安装时勾选 "Add Python to PATH"
    pause
    exit
)

:: ===== 2. 检查+安装依赖 =====
python -c "import playwright" >nul 2>&1
if %errorlevel% neq 0 (
    echo 安装依赖...
    pip install playwright
    playwright install chromium
)

:: ===== 3. 白名单悟空插件（防止Chrome屏蔽） =====
reg query "HKCU\SOFTWARE\Policies\Google\Chrome\ExtensionInstallAllowlist" /v 1 >nul 2>&1
if %errorlevel% neq 0 (
    reg add "HKCU\SOFTWARE\Policies\Google\Chrome\ExtensionInstallAllowlist" /v 1 /d "ekplipencnmccmaogdfnenioilpgfmab" /f >nul 2>&1
)

:: ===== 4. 启动Chrome调试模式 =====
curl --noproxy localhost -s http://localhost:%PORT%/json/version >nul 2>&1
if %errorlevel% neq 0 (
    echo 启动Chrome调试模式...
    start "" %CHROME% --remote-debugging-port=%PORT% --user-data-dir=%LOCALAPPDATA%\Chrome-Debug --load-extension=%SCRIPT_DIR%goku --disable-extensions-except=%SCRIPT_DIR%goku
    timeout /t 3 >nul

    echo.
    echo ============================================
    echo   首次使用需要手动操作：
    echo   1. Chrome打开 chrome://extensions/
    echo   2. 开启开发者模式
    echo   3. 加载已解压的扩展程序
    echo      选择 %SCRIPT_DIR%goku
    echo   4. 打开 bi.shihengtech.com 登录食亨
    echo ============================================
    echo.
    echo 完成后按任意键继续...
    pause >nul
)

:: ===== 4. 品牌列表 =====
if not exist "%SCRIPT_DIR%brands.txt" (
    echo 请在 brands.txt 中输入要监控的品牌（每行一个）
    echo 示例：> "%SCRIPT_DIR%brands.txt"
    echo 鸿运京味堂（北京站店）>> "%SCRIPT_DIR%brands.txt"
    echo 仙云居小笼包（宝山店）>> "%SCRIPT_DIR%brands.txt"
    notepad "%SCRIPT_DIR%brands.txt"
    echo 编辑完保存后按任意键继续...
    pause >nul
)

:: ===== 5. 跑巡检 =====
cd /d "%SCRIPT_DIR%"

:: 读取brands.txt转成参数
setlocal enabledelayedexpansion
set ARGS=
for /f "usebackq delims=" %%a in ("%SCRIPT_DIR%brands.txt") do (
    set ARGS=!ARGS! "%%a"
)

echo.
echo 开始巡检...
echo.
set NO_PROXY=localhost
python run_fast.py %ARGS%

echo.
pause
