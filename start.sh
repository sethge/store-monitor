#!/bin/bash
# 盯店助手 — 一键启动
# 启动Chrome（带debug端口，用于登录）+ 启动server.py
# 用法: bash start.sh

DIR="$(cd "$(dirname "$0")" && pwd)"

# 找Python
if [ -f "$DIR/ops-logger/venv/bin/python3" ]; then
    PYTHON="$DIR/ops-logger/venv/bin/python3"
elif [ -f "$DIR/.venv/bin/python3" ]; then
    PYTHON="$DIR/.venv/bin/python3"
elif [ -f "/opt/homebrew/bin/python3" ]; then
    PYTHON="/opt/homebrew/bin/python3"
else
    PYTHON="python3"
fi

echo "=============================="
echo "  盯店助手 启动中..."
echo "=============================="

# ─── 1. Chrome（带debug端口，用于登录+同步cookies） ───
echo "[1/2] 检查 Chrome..."
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT=9222
USER_DATA="$HOME/chrome-debug"

if curl --noproxy localhost -s http://localhost:$PORT/json/version > /dev/null 2>&1; then
    echo "  Chrome debug 已在运行"
else
    # Chrome在跑但没debug端口 → 需要重启
    if pgrep -f "Google Chrome" > /dev/null 2>&1; then
        echo "  Chrome需要重启以启用调试端口..."
        pkill -f "Google Chrome" 2>/dev/null
        sleep 2
    fi

    if [ -f "$CHROME" ]; then
        FRONT_APP=$(osascript -e 'tell application "System Events" to get name of first process whose frontmost is true' 2>/dev/null)
        mkdir -p "$USER_DATA"
        "$CHROME" \
            --remote-debugging-port=$PORT \
            --user-data-dir="$USER_DATA" \
            --load-extension="$DIR/goku,$DIR/ops-logger" \
            --no-first-run \
            --no-default-browser-check \
            --proxy-server="direct://" \
            > /dev/null 2>&1 &
        echo "  Chrome 已启动 (debug port $PORT)"
        sleep 3
        # 还焦点给之前的app
        [ -n "$FRONT_APP" ] && osascript -e "tell application \"$FRONT_APP\" to activate" 2>/dev/null
    else
        echo "  WARNING: 找不到 Chrome，请手动打开"
    fi
fi

# ─── 2. 启动 server.py ───
echo "[2/2] 启动 server..."
lsof -i :5500 -t | xargs kill -9 2>/dev/null
sleep 1
nohup $PYTHON "$DIR/ops-logger/server.py" > "$DIR/ops-logger/server.log" 2>&1 &
sleep 2

if curl -s http://127.0.0.1:5500/health > /dev/null 2>&1; then
    echo "  Server OK (port 5500)"
else
    echo "  ERROR: server 启动失败，查看 $DIR/ops-logger/server.log"
    exit 1
fi

echo ""
echo "=============================="
echo "  盯店助手已启动!"
echo ""
echo "  下一步："
echo "  1. 在Chrome中确认悟空插件已登录"
echo "  2. 在小q助手扩展中配置运营名"
echo "  3. 点击「开始巡检」"
echo ""
echo "  巡检会在后台无感运行，"
echo "  结果自动显示在扩展里。"
echo "=============================="
