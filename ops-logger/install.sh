#!/bin/bash
# 小q助手 — 安装脚本
# 运营机器上跑一次就行
# 用法: bash install.sh

set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
PARENT="$(dirname "$DIR")"

echo ""
echo "=============================="
echo "  小q助手 安装"
echo "=============================="
echo ""

# ─── 1. Python 环境 ───
if [ "$(uname -s)" = "Darwin" ]; then
    export HOMEBREW_BREW_GIT_REMOTE="https://mirrors.ustc.edu.cn/brew.git"
    export HOMEBREW_CORE_GIT_REMOTE="https://mirrors.ustc.edu.cn/homebrew-core.git"
    export HOMEBREW_BOTTLE_DOMAIN="https://mirrors.ustc.edu.cn/homebrew-bottles"
    export HOMEBREW_API_DOMAIN="https://mirrors.ustc.edu.cn/homebrew-bottles/api"

    command -v brew &>/dev/null || {
        echo "  安装 Homebrew..."
        /bin/bash -c "$(curl -fsSL https://mirrors.ustc.edu.cn/misc/brew-install.sh)"
        eval "$(/opt/homebrew/bin/brew shellenv)" 2>/dev/null
    }

    if ! command -v /opt/homebrew/bin/python3 &>/dev/null; then
        echo "  安装 Python3..."
        brew install python3
    fi
fi

if command -v /opt/homebrew/bin/python3 &>/dev/null; then
    PYTHON="/opt/homebrew/bin/python3"
else
    PYTHON="python3"
fi
echo "  Python: $($PYTHON --version)"

# ─── 2. 创建 venv ───
VENV="$PARENT/.venv"
if [ ! -d "$VENV" ]; then
    echo "  创建虚拟环境..."
    $PYTHON -m venv "$VENV"
fi
VPYTHON="$VENV/bin/python3"
VPIP="$VENV/bin/pip3"
echo "  venv: $VENV"

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
echo "  安装依赖..."

$VPYTHON -c "import flask" 2>/dev/null || {
    echo "    安装 flask..."
    $PIP_CMD flask 2>/dev/null || $VPIP install flask
}
echo "    flask"

$VPYTHON -c "import requests" 2>/dev/null || {
    echo "    安装 requests..."
    $PIP_CMD requests 2>/dev/null || $VPIP install requests
}
echo "    requests"

PLAYWRIGHT_VER="1.44.0"
$VPYTHON -c "import playwright; v=playwright.__version__; exit(0 if v=='$PLAYWRIGHT_VER' else 1)" 2>/dev/null || {
    echo "    安装 playwright..."
    $PIP_CMD "playwright==$PLAYWRIGHT_VER" 2>/dev/null || $VPIP install "playwright==$PLAYWRIGHT_VER"
    PLAYWRIGHT_DOWNLOAD_HOST="https://npmmirror.com/mirrors/playwright/" $VPYTHON -m playwright install chromium 2>/dev/null || \
    $VPYTHON -m playwright install chromium
}
echo "    playwright ($PLAYWRIGHT_VER)"

# ─── 4. 初始化目录 ───
mkdir -p "$PARENT/data"

# ─── 5. 创建桌面启动快捷方式 ───
SHORTCUT="$HOME/Desktop/启动小q.command"
cat > "$SHORTCUT" << CMDEOF
#!/bin/bash
cd "$DIR"
bash start.sh
CMDEOF
chmod +x "$SHORTCUT"
echo "  桌面快捷方式已创建"

echo ""
echo "=============================="
echo "  安装完成!"
echo "=============================="
echo ""
echo "  双击桌面「启动小q」即可启动"
echo ""
echo "  首次启动后需要在 Chrome 里："
echo "  1. 打开 chrome://extensions → 开发者模式"
echo "  2. 加载已解压的扩展程序："
echo "     → $DIR (小q助手)"
echo "     → $PARENT/goku (悟空插件)"
echo "  3. 用悟空插件登录食亨账号"
echo ""
echo "  注意: 启动时会重启Chrome以启用调试端口"
echo "        Chrome会自动恢复之前打开的标签页"
echo ""
