@echo off
chcp 65001 >nul
echo.
echo   ================================
echo   食亨智慧运营 — 一键安装
echo   ================================
echo.

set INSTALL_DIR=%USERPROFILE%\.qclaw\workspace\store-monitor

:: 检查 QClaw
if not exist "%USERPROFILE%\.qclaw" (
    echo ❌ 没找到 QClaw，请先安装 QClaw
    pause
    exit /b 1
)

:: 检查 git
where git >nul 2>&1
if %errorlevel% neq 0 (
    echo 安装 git...
    echo 请先下载安装 Git: https://git-scm.com/download/win
    echo 安装完后重新双击这个文件
    start https://git-scm.com/download/win
    pause
    exit /b 1
)

:: 检查 python
where python >nul 2>&1
if %errorlevel% neq 0 (
    where python3 >nul 2>&1
    if %errorlevel% neq 0 (
        echo 安装 Python...
        echo 请先下载安装 Python: https://www.python.org/downloads/
        echo 安装时勾选 "Add Python to PATH"
        start https://www.python.org/downloads/
        pause
        exit /b 1
    )
)

:: 克隆或更新代码
if exist "%INSTALL_DIR%\.git" (
    echo 更新代码...
    cd /d "%INSTALL_DIR%"
    git fetch origin
    git checkout feature/watch-mode
    git pull origin feature/watch-mode
) else (
    echo 下载代码...
    git clone -b feature/watch-mode https://github.com/sethge/store-monitor.git "%INSTALL_DIR%"
    cd /d "%INSTALL_DIR%"
)

:: 安装 Brain（运营知识库）
echo 安装Brain（运营知识库）...
if not exist "%USERPROFILE%\wisdom-brain\.git" (
    git clone https://github.com/sethge/wisdom-brain.git "%USERPROFILE%\wisdom-brain" 2>nul
    if %errorlevel% equ 0 (
        echo   ✓ wisdom-brain 已克隆
    ) else (
        echo   ⚠ wisdom-brain 克隆失败，请检查网络
    )
) else (
    cd /d "%USERPROFILE%\wisdom-brain" && git pull --quiet 2>nul
    echo   ✓ wisdom-brain 已更新
    cd /d "%INSTALL_DIR%"
)

:: 安装 agent 配置
echo 安装agent配置...
set WORKSPACE=%USERPROFILE%\.qclaw\workspace
for %%f in (SOUL.md BRAIN.md USER.md HEARTBEAT.md MEMORY.md) do (
    if not exist "%WORKSPACE%\%%f" (
        copy "agent-config\%%f" "%WORKSPACE%\%%f" >nul
        echo   ✓ %%f
    ) else (
        echo   ⏭ %%f（已存在）
    )
)
if not exist "%WORKSPACE%\knowledge" (
    xcopy /E /I /Q "agent-config\knowledge" "%WORKSPACE%\knowledge" >nul
    echo   ✓ knowledge/
)

:: 安装 skills（覆盖旧文件，确保最新）
echo 安装skills...
set SKILLS_DIR=%USERPROFILE%\.qclaw\skills
if not exist "%SKILLS_DIR%" mkdir "%SKILLS_DIR%"
for %%s in (store-alert store-diagnosis ops-scheduler setup) do (
    if exist "skills\%%s" (
        xcopy /E /I /Y /Q "skills\%%s" "%SKILLS_DIR%\%%s" >nul
        echo   ✓ %%s
    )
)
if exist "skills\SKILL.md" (
    copy /Y "skills\SKILL.md" "%SKILLS_DIR%\SKILL.md" >nul
    echo   ✓ SKILL.md
)

:: Python 依赖
echo 检查Python依赖...
python -c "import playwright" 2>nul || (
    echo 安装 playwright...
    pip install playwright
    playwright install chromium
)
echo   ✓ playwright

python -c "import xlsxwriter" 2>nul || (
    pip install xlsxwriter 2>nul
)
echo   ✓ xlsxwriter

python -c "import lzstring" 2>nul || (
    pip install lzstring 2>nul
)
echo   ✓ lzstring

python -c "from google import genai" 2>nul || (
    pip install google-genai 2>nul
)
echo   ✓ google-genai

python -c "from tencentcloud.ocr.v20181119 import ocr_client" 2>nul || (
    pip install tencentcloud-sdk-python 2>nul
)
echo   ✓ tencentcloud-sdk

:: 初始化 memory 目录
if not exist "memory\interactions" mkdir "memory\interactions"
if not exist "memory\pending_review" mkdir "memory\pending_review"
echo   ✓ memory目录

:: ffmpeg（可选，竞对诊断用）
where ffmpeg >nul 2>&1
if %errorlevel% neq 0 (
    echo   ⚠ ffmpeg 未安装（竞对诊断需要）
    echo   下载地址: https://www.gyan.dev/ffmpeg/builds/
    echo   下载后解压，把 bin\ffmpeg.exe 放到 C:\Windows\ 下
) else (
    echo   ✓ ffmpeg
)

echo.
echo   ================================
echo   ✅ 安装完成！
echo   ================================
echo.
echo   接下来：
echo   1. 双击「盯店巡检.bat」启动 Chrome
echo   2. Chrome 里加载悟空插件
echo   3. 打开 bi.shihengtech.com 登录食亨
echo   4. 重启 QClaw
echo.
echo   之后在微信里说「巡检」就行了。
echo.
pause
