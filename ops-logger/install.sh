#!/bin/bash
# 小q助手 — 安装脚本
# 运营机器上跑一次就行，装好后用 start.sh 启动
# 用法: bash install.sh

set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
PARENT="$(dirname "$DIR")"

echo ""
echo "=============================="
echo "  小q助手 安装"
echo "=============================="
echo ""

# ─── 0. 检查 Tabbit ───
TABBIT_APP="/Applications/Tabbit Browser.app"
if [ -d "$TABBIT_APP" ]; then
    echo "  Tabbit Browser 已安装"
else
    echo "  Tabbit Browser 未安装"
    echo "  请先下载安装: https://www.tabbit-ai.com/"
    echo "  安装完成后重新运行此脚本"
    exit 1
fi

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
    PIP="/opt/homebrew/bin/pip3"
    echo "  Python: $($PYTHON --version) (Homebrew)"
else
    PYTHON="python3"
    PIP="pip3"
    echo "  Python: $($PYTHON --version)"
fi

# PyPI 镜像
PIP_MIRROR=""
for mirror in \
    "-i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com" \
    "-i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn" \
    ""; do
    if $PIP install --dry-run $mirror pip &>/dev/null; then
        PIP_MIRROR="$mirror"
        break
    fi
done
PIP_CMD="$PIP install $PIP_MIRROR"

# ─── 2. Python 依赖 ───
echo "  安装依赖..."

# Flask (server.py)
$PYTHON -c "import flask" 2>/dev/null || {
    echo "    安装 flask..."
    $PIP_CMD flask 2>/dev/null || $PIP install flask
}
echo "    flask"

# Playwright (巡检用)
PLAYWRIGHT_VER="1.44.0"
$PYTHON -c "import playwright; v=playwright.__version__; exit(0 if v=='$PLAYWRIGHT_VER' else 1)" 2>/dev/null || {
    echo "    安装 playwright..."
    $PIP_CMD "playwright==$PLAYWRIGHT_VER" 2>/dev/null || $PIP install "playwright==$PLAYWRIGHT_VER"
    PLAYWRIGHT_DOWNLOAD_HOST="https://npmmirror.com/mirrors/playwright/" playwright install chromium 2>/dev/null || \
    playwright install chromium
}
echo "    playwright ($PLAYWRIGHT_VER)"

# ─── 3. 初始化目录 ───
mkdir -p "$PARENT/data"
echo "  数据目录就绪"

# ─── 4. 创建桌面启动快捷方式 ───
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
echo "  接下来需要手动做一次（之后不用再做）："
echo ""
echo "  1. 双击桌面上的「启动小q」"
echo "     → 会自动打开 Tabbit 浏览器"
echo ""
echo "  2. 在 Tabbit 里安装两个扩展："
echo "     a. 地址栏输入 chrome://extensions"
echo "     b. 右上角打开「开发者模式」"
echo "     c. 点「加载已解压的扩展程序」"
echo "        → 选择 $DIR"
echo "        → 再选 $PARENT/goku"
echo ""
echo "  3. 用悟空插件登录食亨账号"
echo ""
echo "  完成! 以后每天开工双击「启动小q」就行。"
echo ""
