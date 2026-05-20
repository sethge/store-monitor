#!/bin/bash
# 小q助手 — 一键安装+启动
# QClaw自动调用，运营不碰终端
# 幂等：跑多少次都安全

set -e

INSTALL_DIR="$HOME/.qclaw/workspace/store-monitor"
OPS_DIR="$INSTALL_DIR/ops-logger"

echo "[小q] 开始安装..."

# ─── 1. 拉代码 ───
REPO_URL="https://gitee.com/sethgeshiheng/store-monitor"
BRANCH="feature/watch-mode"

if [ -d "$INSTALL_DIR/.git" ]; then
    cd "$INSTALL_DIR"
    git pull origin $BRANCH 2>/dev/null || true
    echo "[小q] 代码已更新"
elif command -v git &>/dev/null; then
    mkdir -p "$(dirname "$INSTALL_DIR")"
    git clone "$REPO_URL.git" -b $BRANCH "$INSTALL_DIR"
    echo "[小q] 代码已下载"
else
    # 没有git，用zip下载
    mkdir -p "$INSTALL_DIR"
    ZIP_URL="$REPO_URL/repository/archive/$BRANCH.zip"
    curl -fsSL "$ZIP_URL" -o /tmp/store-monitor.zip
    unzip -qo /tmp/store-monitor.zip -d /tmp/store-monitor-tmp
    # Gitee zip解压后目录名是 store-monitor-feature-watch-mode
    cp -R /tmp/store-monitor-tmp/store-monitor-*/* "$INSTALL_DIR/"
    rm -rf /tmp/store-monitor.zip /tmp/store-monitor-tmp
    echo "[小q] 代码已下载(zip)"
fi

# 链接skills到QClaw
mkdir -p "$HOME/.qclaw/skills"
for skill in setup store-patrol store-alert store-diagnosis ops-scheduler; do
    src="$INSTALL_DIR/skills/$skill"
    dst="$HOME/.qclaw/skills/$skill"
    [ -d "$src" ] && [ ! -e "$dst" ] && ln -sf "$src" "$dst"
done

# ─── 2. Python 环境 ───
if [ "$(uname -s)" = "Darwin" ]; then
    export HOMEBREW_BREW_GIT_REMOTE="https://mirrors.ustc.edu.cn/brew.git"
    export HOMEBREW_CORE_GIT_REMOTE="https://mirrors.ustc.edu.cn/homebrew-core.git"
    export HOMEBREW_BOTTLE_DOMAIN="https://mirrors.ustc.edu.cn/homebrew-bottles"
    export HOMEBREW_API_DOMAIN="https://mirrors.ustc.edu.cn/homebrew-bottles/api"

    if ! command -v /opt/homebrew/bin/python3 &>/dev/null && ! command -v python3 &>/dev/null; then
        command -v brew &>/dev/null || {
            /bin/bash -c "$(curl -fsSL https://mirrors.ustc.edu.cn/misc/brew-install.sh)"
            eval "$(/opt/homebrew/bin/brew shellenv)" 2>/dev/null
        }
        brew install python3
    fi
fi

PYTHON=""
for p in "/opt/homebrew/bin/python3" "python3"; do
    if command -v "$p" &>/dev/null; then PYTHON="$p"; break; fi
done

# ─── 3. venv + 依赖 ───
VENV="$OPS_DIR/venv"
[ ! -d "$VENV" ] && $PYTHON -m venv "$VENV"
VPIP="$VENV/bin/pip3"
VPYTHON="$VENV/bin/python3"

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
    $VPYTHON -c "import $pkg" 2>/dev/null || $VPIP install $PIP_MIRROR $pkg 2>/dev/null || $VPIP install $pkg
done

PLAYWRIGHT_VER="1.44.0"
$VPYTHON -c "import playwright" 2>/dev/null || {
    $VPIP install $PIP_MIRROR "playwright==$PLAYWRIGHT_VER" 2>/dev/null || $VPIP install "playwright==$PLAYWRIGHT_VER"
    PLAYWRIGHT_DOWNLOAD_HOST="https://npmmirror.com/mirrors/playwright/" $VPYTHON -m playwright install chromium 2>/dev/null || \
    $VPYTHON -m playwright install chromium
}
echo "[小q] 依赖 OK"

# ─── 4. LaunchAgent: server.py 开机自启 ───
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
echo "[小q] server 开机自启 OK"

# ─── 5. 启动 server.py ───
if ! curl -s --max-time 2 http://127.0.0.1:5500/health > /dev/null 2>&1; then
    lsof -i :5500 -t | xargs kill -9 2>/dev/null || true
    sleep 1
    nohup $VPYTHON "$OPS_DIR/server.py" > "$OPS_DIR/server.log" 2>&1 &
    sleep 2
fi

if curl -s --max-time 2 http://127.0.0.1:5500/health > /dev/null 2>&1; then
    echo "[小q] server 已启动 (port 5500)"
else
    echo "[小q] ERROR: server 启动失败"
    exit 1
fi

# ─── 6. 启动 Chrome (debug端口 + 自动加载扩展) ───
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT=9222

if ! curl --noproxy localhost -s http://localhost:$PORT/json/version > /dev/null 2>&1; then
    # Chrome在跑但没debug端口 → 重启
    if pgrep -f "Google Chrome" > /dev/null 2>&1; then
        pkill -f "Google Chrome" 2>/dev/null
        sleep 2
    fi

    if [ -f "$CHROME" ]; then
        # 自动加载扩展
        LOAD_EXT="$OPS_DIR"
        [ -d "$INSTALL_DIR/goku" ] && LOAD_EXT="$LOAD_EXT,$INSTALL_DIR/goku"

        "$CHROME" \
            --remote-debugging-port=$PORT \
            --no-first-run \
            --no-default-browser-check \
            --proxy-server="direct://" \
            --load-extension="$LOAD_EXT" \
            > /dev/null 2>&1 &
        sleep 3
        echo "[小q] Chrome 已启动 (debug + 扩展自动加载)"
    else
        echo "[小q] ERROR: 找不到Chrome"
        exit 1
    fi
else
    echo "[小q] Chrome 已在运行"
fi

echo "[小q] 安装完成！"
