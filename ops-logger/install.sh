#!/bin/bash
# 小q助手 — 安装脚本（QClaw调用，静默安装）
# 用法: bash install.sh

set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
PARENT="$(dirname "$DIR")"

echo "installing..."

# ─── 1. Python 环境 ───
if [ "$(uname -s)" = "Darwin" ]; then
    export HOMEBREW_BREW_GIT_REMOTE="https://mirrors.ustc.edu.cn/brew.git"
    export HOMEBREW_CORE_GIT_REMOTE="https://mirrors.ustc.edu.cn/homebrew-core.git"
    export HOMEBREW_BOTTLE_DOMAIN="https://mirrors.ustc.edu.cn/homebrew-bottles"
    export HOMEBREW_API_DOMAIN="https://mirrors.ustc.edu.cn/homebrew-bottles/api"

    command -v brew &>/dev/null || {
        echo "  installing homebrew..."
        /bin/bash -c "$(curl -fsSL https://mirrors.ustc.edu.cn/misc/brew-install.sh)"
        eval "$(/opt/homebrew/bin/brew shellenv)" 2>/dev/null
    }

    if ! command -v /opt/homebrew/bin/python3 &>/dev/null; then
        echo "  installing python3..."
        brew install python3
    fi
fi

if command -v /opt/homebrew/bin/python3 &>/dev/null; then
    PYTHON="/opt/homebrew/bin/python3"
else
    PYTHON="python3"
fi

# ─── 2. 创建 venv ───
VENV="$PARENT/.venv"
if [ ! -d "$VENV" ]; then
    $PYTHON -m venv "$VENV"
fi
VPYTHON="$VENV/bin/python3"
VPIP="$VENV/bin/pip3"

# PyPI 镜像
PIP_MIRROR=""
for mirror in \
    "-i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com" \
    "-i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn" \
    ""; do
    if $VPIP install --dry-run $mirror pip &>/dev/null; then
        PIP_MIRROR="$mirror"
        break
    fi
done
PIP_CMD="$VPIP install $PIP_MIRROR"

# ─── 3. Python 依赖 ───
$VPYTHON -c "import flask" 2>/dev/null || {
    $PIP_CMD flask 2>/dev/null || $VPIP install flask
}

$VPYTHON -c "import requests" 2>/dev/null || {
    $PIP_CMD requests 2>/dev/null || $VPIP install requests
}

PLAYWRIGHT_VER="1.44.0"
$VPYTHON -c "import playwright; v=playwright.__version__; exit(0 if v=='$PLAYWRIGHT_VER' else 1)" 2>/dev/null || {
    $PIP_CMD "playwright==$PLAYWRIGHT_VER" 2>/dev/null || $VPIP install "playwright==$PLAYWRIGHT_VER"
    PLAYWRIGHT_DOWNLOAD_HOST="https://npmmirror.com/mirrors/playwright/" $VPYTHON -m playwright install chromium 2>/dev/null || \
    $VPYTHON -m playwright install chromium
}

# ─── 4. 初始化目录 ───
mkdir -p "$PARENT/data"

# ─── 5. 启动 server ───
bash "$DIR/start.sh"

echo "ok"
