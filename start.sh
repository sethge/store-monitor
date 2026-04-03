#!/bin/bash
# 启动盯店专用浏览器
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PORT=9222

if curl --noproxy localhost -s http://localhost:$PORT/json/version &>/dev/null; then
    echo "✓ 已在运行"
    exit 0
fi

# 找Chrome
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
USER_DATA="$HOME/chrome-debug"

if [ ! -x "$CHROME" ]; then
    CHROME=$(python3 -c "
import glob, os
paths = glob.glob(os.path.expanduser('~/Library/Caches/ms-playwright/chromium-*/chrome-mac*/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing'))
if paths: print(sorted(paths)[-1])
" 2>/dev/null)
fi

if [ -z "$CHROME" ]; then
    echo "❌ 没找到Chrome"
    exit 1
fi

mkdir -p "$USER_DATA"
"$CHROME" \
    --remote-debugging-port=$PORT \
    --user-data-dir="$USER_DATA" \
    --disable-extensions-except="$SCRIPT_DIR/goku" \
    --load-extension="$SCRIPT_DIR/goku" \
    --no-first-run \
    --no-default-browser-check \
    --proxy-server="direct://" &

for i in $(seq 1 15); do
    sleep 1
    if curl --noproxy localhost -s http://localhost:$PORT/json/version &>/dev/null; then
        echo "✓ 就绪"
        exit 0
    fi
done
echo "❌ 启动失败"
exit 1
