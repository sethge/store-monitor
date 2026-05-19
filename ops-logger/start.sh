#!/bin/bash
# 小q助手 — 一键启动
# 连接运营自己的Chrome（带debug端口）+ 启动server.py
# 用法: bash start.sh

DIR="$(cd "$(dirname "$0")" && pwd)"
PARENT="$(dirname "$DIR")"

# 优先用 venv，没有就用 homebrew python
if [ -f "$DIR/venv/bin/python3" ]; then
    PYTHON="$DIR/venv/bin/python3"
elif [ -f "$PARENT/.venv/bin/python3" ]; then
    PYTHON="$PARENT/.venv/bin/python3"
elif [ -f "/opt/homebrew/bin/python3" ]; then
    PYTHON="/opt/homebrew/bin/python3"
else
    PYTHON="python3"
fi

echo "=============================="
echo "  小q助手 启动中..."
echo "=============================="

# ─── 1. 确保Chrome带debug端口 ───
echo "[1/2] 检查 Chrome..."
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT=9222

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
        # 用默认profile启动，不传 --user-data-dir
        "$CHROME" \
            --remote-debugging-port=$PORT \
            --no-first-run \
            --no-default-browser-check \
            > /dev/null 2>&1 &
        echo "  Chrome 已启动 (debug port $PORT)"
        sleep 3
        # 隐藏Chrome + 还焦点
        osascript -e 'tell application "System Events" to set visible of process "Google Chrome" to false' 2>/dev/null
        [ -n "$FRONT_APP" ] && osascript -e "tell application \"$FRONT_APP\" to activate" 2>/dev/null
    else
        echo "  WARNING: 找不到 Chrome，请手动打开"
    fi
fi

# ─── 2. 启动 server.py ───
echo "[2/2] 启动 server..."
lsof -i :5500 -t | xargs kill -9 2>/dev/null
sleep 1
nohup $PYTHON "$DIR/server.py" > "$DIR/server.log" 2>&1 &
sleep 2

if curl -s http://127.0.0.1:5500/health > /dev/null 2>&1; then
    echo "  Server OK (port 5500)"
else
    echo "  ERROR: server 启动失败，查看 $DIR/server.log"
    exit 1
fi

echo ""
echo "=============================="
echo "  小q助手已启动!"
echo "  Dashboard: http://127.0.0.1:5500"
echo "=============================="
