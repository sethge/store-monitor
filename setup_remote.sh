#!/bin/bash
# ==============================
# 食亨智慧运营 — 一键安装
# 运营只需要复制下面这一行到终端：
# curl -sL https://raw.githubusercontent.com/sethge/store-monitor/feature/watch-mode/setup_remote.sh | bash
# ==============================

set -e
echo ""
echo "  ================================"
echo "  食亨智慧运营 — 一键安装"
echo "  ================================"
echo ""

INSTALL_DIR="$HOME/.qclaw/workspace/store-monitor"

# 检查 QClaw
if [ ! -d "$HOME/.qclaw" ]; then
    echo "❌ 没找到 QClaw，请先安装 QClaw"
    exit 1
fi

# 检查 git
command -v git &>/dev/null || {
    echo "安装 git..."
    if [ "$(uname -s)" = "Darwin" ]; then
        xcode-select --install 2>/dev/null || true
    else
        sudo apt update && sudo apt install -y git
    fi
}

# 克隆或更新代码
if [ -d "$INSTALL_DIR/.git" ]; then
    echo "更新代码..."
    cd "$INSTALL_DIR"
    git fetch origin
    git checkout feature/watch-mode
    git pull origin feature/watch-mode
else
    echo "下载代码..."
    git clone -b feature/watch-mode https://github.com/sethge/store-monitor.git "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

# 运行安装
bash install.sh

echo ""
echo "  ================================"
echo "  ✅ 安装完成！"
echo "  ================================"
echo ""
echo "  接下来："
echo "  1. 双击桌面上的「盯店巡检」启动 Chrome"
echo "  2. Chrome 里加载悟空插件"
echo "  3. 打开 bi.shihengtech.com 登录食亨"
echo "  4. 重启 QClaw"
echo ""
echo "  之后在微信里说「巡检」就行了。"
echo ""
