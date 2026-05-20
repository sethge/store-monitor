#!/bin/bash
# 小q助手 — 一键安装+启动
# 运营只需要跑这一句，剩下全自动
# 用法: bash <(curl -fsSL https://gitee.com/sethgeshiheng/store-monitor/raw/feature/watch-mode/ops-logger/setup.sh)

set -e

echo ""
echo "================================"
echo "  小q助手 一键安装"
echo "================================"
echo ""

# ─── 0. 安装目录 ───
INSTALL_DIR="$HOME/.qclaw/workspace/store-monitor"
OPS_DIR="$INSTALL_DIR/ops-logger"

# ─── 1. 拉代码 ───
echo "[1/5] 下载代码..."
if [ -d "$INSTALL_DIR/.git" ]; then
    cd "$INSTALL_DIR"
    git pull origin feature/watch-mode 2>/dev/null || git pull 2>/dev/null || true
    echo "  已更新"
else
    mkdir -p "$(dirname "$INSTALL_DIR")"
    git clone https://gitee.com/sethgeshiheng/store-monitor.git -b feature/watch-mode "$INSTALL_DIR" 2>/dev/null
    echo "  已下载"
fi

# ─── 2. Python 环境 ───
echo "[2/5] 检查 Python..."
if [ "$(uname -s)" = "Darwin" ]; then
    export HOMEBREW_BREW_GIT_REMOTE="https://mirrors.ustc.edu.cn/brew.git"
    export HOMEBREW_CORE_GIT_REMOTE="https://mirrors.ustc.edu.cn/homebrew-core.git"
    export HOMEBREW_BOTTLE_DOMAIN="https://mirrors.ustc.edu.cn/homebrew-bottles"
    export HOMEBREW_API_DOMAIN="https://mirrors.ustc.edu.cn/homebrew-bottles/api"

    if ! command -v /opt/homebrew/bin/python3 &>/dev/null && ! command -v python3 &>/dev/null; then
        command -v brew &>/dev/null || {
            echo "  安装 Homebrew (国内镜像)..."
            /bin/bash -c "$(curl -fsSL https://mirrors.ustc.edu.cn/misc/brew-install.sh)"
            eval "$(/opt/homebrew/bin/brew shellenv)" 2>/dev/null
        }
        echo "  安装 Python3..."
        brew install python3
    fi
fi

PYTHON=""
for p in "/opt/homebrew/bin/python3" "python3"; do
    if command -v "$p" &>/dev/null; then PYTHON="$p"; break; fi
done
echo "  Python: $($PYTHON --version)"

# ─── 3. venv + 依赖 ───
echo "[3/5] 安装依赖..."
VENV="$OPS_DIR/venv"
if [ ! -d "$VENV" ]; then
    $PYTHON -m venv "$VENV"
fi
VPIP="$VENV/bin/pip3"
VPYTHON="$VENV/bin/python3"

# 找可用PyPI镜像
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

for pkg in flask requests; do
    $VPYTHON -c "import $pkg" 2>/dev/null || {
        echo "  安装 $pkg..."
        $VPIP install $PIP_MIRROR $pkg 2>/dev/null || $VPIP install $pkg
    }
done

PLAYWRIGHT_VER="1.44.0"
$VPYTHON -c "import playwright" 2>/dev/null || {
    echo "  安装 playwright..."
    $VPIP install $PIP_MIRROR "playwright==$PLAYWRIGHT_VER" 2>/dev/null || $VPIP install "playwright==$PLAYWRIGHT_VER"
    PLAYWRIGHT_DOWNLOAD_HOST="https://npmmirror.com/mirrors/playwright/" $VPYTHON -m playwright install chromium 2>/dev/null || \
    $VPYTHON -m playwright install chromium
}
echo "  依赖 OK"

# ─── 4. 开机自启(LaunchAgent) ───
echo "[4/5] 设置开机自启..."
PLIST_NAME="com.xiaoq.server"
PLIST_PATH="$HOME/Library/LaunchAgents/$PLIST_NAME.plist"
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST_PATH" << PEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$PLIST_NAME</string>
    <key>ProgramArguments</key>
    <array>
        <string>$VENV/bin/python3</string>
        <string>$OPS_DIR/server.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$OPS_DIR</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$OPS_DIR/server.log</string>
    <key>StandardErrorPath</key>
    <string>$OPS_DIR/server.log</string>
</dict>
</plist>
PEOF
launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load "$PLIST_PATH" 2>/dev/null || true
echo "  server.py 开机自启 OK"

# ─── 5. 桌面快捷方式 ───
echo "[5/5] 创建桌面快捷方式..."
SHORTCUT="$HOME/Desktop/启动小q.command"
cat > "$SHORTCUT" << SEOF
#!/bin/bash
cd "$OPS_DIR"
bash start.sh
SEOF
chmod +x "$SHORTCUT"
echo "  桌面「启动小q」已创建"

# ─── 启动 ───
echo ""
echo "  正在启动..."
cd "$OPS_DIR"
bash start.sh

echo ""
echo "================================"
echo "  安装完成!"
echo ""
echo "  接下来两步:"
echo "  1. 点Chrome右上角「悟空」登录食亨"
echo "  2. 点「小q助手」输入你的名字"
echo "================================"
echo ""
