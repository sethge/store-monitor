#!/bin/bash
# 小q助手 — 一键启动
# 启动 debug Chrome + server.py
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

# ─── 1. 启动 debug Chrome ───
echo "[1/2] 启动 Chrome..."
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
CHROME_DEBUG_DIR="$HOME/chrome-debug"

# 检查是否已在跑
if curl --noproxy localhost -s http://localhost:9222/json/version > /dev/null 2>&1; then
    echo "  Chrome debug 已在运行"
else
    if [ -f "$CHROME" ]; then
        mkdir -p "$CHROME_DEBUG_DIR"
        "$CHROME" \
            --remote-debugging-port=9222 \
            --user-data-dir="$CHROME_DEBUG_DIR" \
            --load-extension="$DIR","$PARENT/goku" \
            --no-first-run \
            --no-default-browser-check \
            --proxy-server="direct://" \
            --window-position=3000,3000 \
            --window-size=800,600 \
            > /dev/null 2>&1 &
        echo "  Chrome debug 已启动 (port 9222)"
        sleep 3
        # 最小化debug Chrome窗口，不干扰运营日常操作
        osascript -e '
            tell application "System Events"
                set chromeProcs to every process whose name is "Google Chrome"
                repeat with p in chromeProcs
                    set cmdLine to ""
                    try
                        set cmdLine to do shell script "ps -p " & (unix id of p) & " -o args= 2>/dev/null"
                    end try
                    if cmdLine contains "chrome-debug" then
                        tell p
                            set miniaturized of every window to true
                        end tell
                    end if
                end repeat
            end tell
        ' 2>/dev/null
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
