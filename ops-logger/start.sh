#!/bin/bash
# 小q助手 — 一键启动
# 启动 server.py + Chrome(debug端口+自动加载扩展)
# 用法: bash start.sh

DIR="$(cd "$(dirname "$0")" && pwd)"
PARENT="$(dirname "$DIR")"

# Python路径优先级: venv > homebrew > system
for p in "$DIR/venv/bin/python3" "$PARENT/.venv/bin/python3" "/opt/homebrew/bin/python3" "python3"; do
    if [ -x "$p" ] || command -v "$p" &>/dev/null; then
        PYTHON="$p"
        break
    fi
done

echo "=============================="
echo "  小q助手 启动中..."
echo "=============================="

# ─── 1. 启动 server.py ───
echo "[1/2] 启动 server..."
if curl -s --max-time 2 http://127.0.0.1:5500/health > /dev/null 2>&1; then
    echo "  Server 已在运行"
else
    lsof -i :5500 -t | xargs kill -9 2>/dev/null
    sleep 1
    nohup $PYTHON "$DIR/server.py" > "$DIR/server.log" 2>&1 &
    sleep 2
    if curl -s --max-time 2 http://127.0.0.1:5500/health > /dev/null 2>&1; then
        echo "  Server OK (port 5500)"
    else
        echo "  ERROR: server 启动失败，查看 $DIR/server.log"
    fi
fi

# ─── 2. 确保Chrome带debug端口 + 自动加载扩展 ───
echo "[2/2] 检查 Chrome..."
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT=9222

# 扩展路径
EXT_OPSLOGGER="$DIR"
EXT_GOKU="$PARENT/goku"
LOAD_EXT=""
[ -d "$EXT_OPSLOGGER" ] && LOAD_EXT="$EXT_OPSLOGGER"
[ -d "$EXT_GOKU" ] && LOAD_EXT="$LOAD_EXT,$EXT_GOKU"

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
        "$CHROME" \
            --remote-debugging-port=$PORT \
            --no-first-run \
            --no-default-browser-check \
            --proxy-server="direct://" \
            --load-extension="$LOAD_EXT" \
            > /dev/null 2>&1 &
        echo "  Chrome 已启动 (debug:$PORT + 扩展自动加载)"
        sleep 3
        [ -n "$FRONT_APP" ] && osascript -e "tell application \"$FRONT_APP\" to activate" 2>/dev/null
    else
        echo "  WARNING: 找不到 Chrome"
    fi
fi

echo ""
echo "=============================="
echo "  小q助手已启动!"
echo "  点Chrome右上角「小q助手」图标开始用"
echo "=============================="
