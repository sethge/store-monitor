# 食亨智慧运营 — Windows 一键安装
# 运营复制这一行到 PowerShell：
# irm https://raw.githubusercontent.com/sethge/store-monitor/feature/watch-mode/setup_remote.ps1 | iex

Write-Host ""
Write-Host "  ================================" -ForegroundColor Cyan
Write-Host "  食亨智慧运营 — 一键安装" -ForegroundColor Cyan
Write-Host "  ================================" -ForegroundColor Cyan
Write-Host ""

$INSTALL_DIR = "$env:USERPROFILE\.qclaw\workspace\store-monitor"

# 检查 QClaw
if (-not (Test-Path "$env:USERPROFILE\.qclaw")) {
    Write-Host "❌ 没找到 QClaw，请先安装 QClaw" -ForegroundColor Red
    Read-Host "按回车退出"
    exit 1
}

# 检查 git
try { git --version | Out-Null } catch {
    Write-Host "❌ 没找到 git，正在打开下载页面..." -ForegroundColor Red
    Start-Process "https://git-scm.com/download/win"
    Write-Host "安装 git 后重新运行这条命令"
    Read-Host "按回车退出"
    exit 1
}

# 检查 python
$python = "python"
try { & $python --version | Out-Null } catch {
    $python = "python3"
    try { & $python --version | Out-Null } catch {
        Write-Host "❌ 没找到 Python，正在打开下载页面..." -ForegroundColor Red
        Start-Process "https://www.python.org/downloads/"
        Write-Host "安装时勾选 'Add Python to PATH'，安装后重新运行"
        Read-Host "按回车退出"
        exit 1
    }
}

# 克隆或更新
if (Test-Path "$INSTALL_DIR\.git") {
    Write-Host "更新代码..."
    Set-Location $INSTALL_DIR
    git fetch origin
    git checkout feature/watch-mode
    git pull origin feature/watch-mode
} else {
    Write-Host "下载代码..."
    git clone -b feature/watch-mode https://gitee.com/sethgeshiheng/store-monitor.git $INSTALL_DIR
    Set-Location $INSTALL_DIR
}

# 运行安装
Write-Host ""
Write-Host "运行安装脚本..."
& cmd /c "安装.bat"

Write-Host ""
Write-Host "  ✅ 安装完成！" -ForegroundColor Green
Write-Host ""
