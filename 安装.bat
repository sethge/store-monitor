@echo off
chcp 65001 >nul
echo.
echo   ================================
echo   食亨智慧运��� — 一键安装
echo   ================================
echo.

set INSTALL_DIR=%USERPROFILE%\.qclaw\workspace\store-monitor
set PIP_MIRROR=-i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn
set GIT_MIRROR=https://ghfast.top

:: 检查 QClaw
if not exist "%USERPROFILE%\.qclaw" (
    echo   ❌ 没找到 QClaw，请先安装 QClaw
    pause
    exit /b 1
)

:: 检查 git
where git >nul 2>&1
if %errorlevel% neq 0 (
    echo   ❌ 没找到 git
    echo   请下载安装: https://git-scm.com/download/win
    start https://git-scm.com/download/win
    pause
    exit /b 1
)

:: 检查 python
set PYTHON=python
where python >nul 2>&1
if %errorlevel% neq 0 (
    set PYTHON=python3
    where python3 >nul 2>&1
    if %errorlevel% neq 0 (
        echo   ❌ 没找到 Python
        echo   请下载安装: https://www.python.org/downloads/
        echo   安装时务必勾选 "Add Python to PATH"
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
    git clone -b feature/watch-mode %GIT_MIRROR%/https://github.com/sethge/store-monitor.git "%INSTALL_DIR%" 2>nul || (
        git clone -b feature/watch-mode https://github.com/sethge/store-monitor.git "%INSTALL_DIR%"
    )
    cd /d "%INSTALL_DIR%"
)

:: 安装 Brain
echo 安装Brain...
if not exist "%USERPROFILE%\wisdom-brain\.git" (
    git clone %GIT_MIRROR%/https://github.com/sethge/wisdom-brain.git "%USERPROFILE%\wisdom-brain" 2>nul || (
        git clone https://github.com/sethge/wisdom-brain.git "%USERPROFILE%\wisdom-brain" 2>nul
    )
    echo   ✓ wisdom-brain
) else (
    cd /d "%USERPROFILE%\wisdom-brain" && git pull --quiet 2>nul
    echo   ✓ wisdom-brain 已更新
    cd /d "%INSTALL_DIR%"
)

:: 安装 skills（覆盖旧文件）
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

:: agent 配置
echo 安装agent配置...
set WORKSPACE=%USERPROFILE%\.qclaw\workspace
for %%f in (SOUL.md BRAIN.md USER.md HEARTBEAT.md MEMORY.md) do (
    if not exist "%WORKSPACE%\%%f" (
        copy "agent-config\%%f" "%WORKSPACE%\%%f" >nul
        echo   ✓ %%f
    ) else (
        echo   ⏭ %%f
    )
)
if not exist "%WORKSPACE%\knowledge" (
    xcopy /E /I /Q "agent-config\knowledge" "%WORKSPACE%\knowledge" >nul
    echo   ✓ knowledge/
)

:: Python 依赖（清华镜像）
echo 检查Python依赖...
%PYTHON% -c "import playwright" 2>nul || (
    echo   安装 playwright...
    %PYTHON% -m pip install %PIP_MIRROR% playwright 2>nul
    playwright install chromium
)
echo   ✓ playwright

for %%p in (xlsxwriter lzstring) do (
    %PYTHON% -c "import %%p" 2>nul || (
        %PYTHON% -m pip install %PIP_MIRROR% %%p 2>nul
    )
    echo   ✓ %%p
)

%PYTHON% -c "from tencentcloud.ocr.v20181119 import ocr_client" 2>nul || (
    echo   安装腾讯云OCR SDK...
    %PYTHON% -m pip install %PIP_MIRROR% tencentcloud-sdk-python 2>nul
)
echo   ✓ tencentcloud-sdk

%PYTHON% -c "from google import genai" 2>nul || (
    echo   安装 google-genai...
    %PYTHON% -m pip install %PIP_MIRROR% google-genai 2>nul
)
echo   ✓ google-genai

:: memory 目录
if not exist "memory\interactions" mkdir "memory\interactions"
if not exist "memory\pending_review" mkdir "memory\pending_review"
echo   ✓ memory目录

:: ffmpeg
where ffmpeg >nul 2>&1
if %errorlevel% neq 0 (
    echo   安装 ffmpeg...
    :: 尝试用 winget 装
    winget install --id Gyan.FFmpeg -e --source winget >nul 2>&1
    where ffmpeg >nul 2>&1
    if %errorlevel% neq 0 (
        :: winget 失败，尝试用 choco
        where choco >nul 2>&1 && choco install ffmpeg -y >nul 2>&1
        where ffmpeg >nul 2>&1
        if %errorlevel% neq 0 (
            echo   ⚠ ffmpeg 自动安装失败
            echo   请手动下载: https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip
            echo   解压后把 bin\ffmpeg.exe 复制到 C:\Windows\
        )
    )
)
where ffmpeg >nul 2>&1 && echo   ✓ ffmpeg

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
