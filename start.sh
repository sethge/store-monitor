#!/bin/bash
# 盯店巡检 — 手动启动浏览器（一般不需要，agent会自动启动）
# 仅在需要手动调试时使用

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PORT=9222

# 检查是否已有浏览器在跑
if curl --noproxy localhost -s http://localhost:$PORT/json/version &>/dev/null; then
    echo "✓ 浏览器已在运行 (端口$PORT)"
    exit 0
fi

echo "启动浏览器..."
# 用playwright自带的chromium
CHROME_BIN=$(python3 -c "
import glob, os
paths = glob.glob(os.path.expanduser('~/Library/Caches/ms-playwright/chromium-*/chrome-mac*/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing'))
if paths: print(sorted(paths)[-1])
" 2>/dev/null)

if [ -z "$CHROME_BIN" ]; then
    echo "❌ 没找到playwright自带的chromium，请先运行: playwright install chromium"
    exit 1
fi

EXT_PATH="$SCRIPT_DIR/goku"
USER_DATA="$HOME/chromium-debug"
mkdir -p "$USER_DATA"

"$CHROME_BIN" \
    --remote-debugging-port=$PORT \
    --user-data-dir="$USER_DATA" \
    --disable-extensions-except="$EXT_PATH" \
    --load-extension="$EXT_PATH" \
    --no-first-run \
    --disable-default-apps \
    --disable-sync \
    --no-default-browser-check &

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
