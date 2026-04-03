#!/bin/bash
# 盯店巡检 — 启动专用浏览器（双击运行）
# 优先用系统Chrome，没有就用playwright的chromium

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PORT=9222

# 检查是否已有浏览器在跑
if curl --noproxy localhost -s http://localhost:$PORT/json/version &>/dev/null; then
    echo "✓ 浏览器已在运行 (端口$PORT)"
    exit 0
fi

# 找浏览器：优先系统Chrome，没有就用playwright的chromium
if [ -x "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" ]; then
    CHROME_BIN="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    USER_DATA="$HOME/Library/Application Support/Chrome-Debug"
    echo "启动Chrome调试模式..."
else
    CHROME_BIN=$(python3 -c "
import glob, os
paths = glob.glob(os.path.expanduser('~/Library/Caches/ms-playwright/chromium-*/chrome-mac*/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing'))
if paths: print(sorted(paths)[-1])
" 2>/dev/null)
    USER_DATA="$HOME/chromium-debug"
    echo "启动chromium..."
fi

if [ -z "$CHROME_BIN" ]; then
    echo "❌ 没找到Chrome或chromium"
    exit 1
fi

EXT_PATH="$SCRIPT_DIR/goku"
mkdir -p "$USER_DATA"

"$CHROME_BIN" \
    --remote-debugging-port=$PORT \
    --user-data-dir="$USER_DATA" \
    --disable-extensions-except="$EXT_PATH" \
    --load-extension="$EXT_PATH" \
    --no-first-run \
    --disable-default-apps \
    --disable-sync \
    --no-default-browser-check \
    --proxy-server="direct://" &

for i in $(seq 1 15); do
    sleep 1
    if curl --noproxy localhost -s http://localhost:$PORT/json/version &>/dev/null; then
        echo "✓ 浏览器就绪 (端口$PORT)"
        exit 0
    fi
    echo "  等待启动...($i)"
done

echo "❌ 启动失败"
exit 1
