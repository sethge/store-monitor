#!/bin/bash
# 盯店巡检一键启动

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PORT=9222

# ===== 1. 找浏览器 =====
if [ -d "/Applications/Chromium.app" ]; then
    BROWSER="Chromium"
elif [ -d "/Applications/Google Chrome.app" ]; then
    BROWSER="Google Chrome"
else
    echo "❌ 没找到浏览器，请先安装 Chromium"
    exit 1
fi
echo "浏览器: $BROWSER"

# ===== 2. 确保调试端口开着 =====
if ! curl --noproxy localhost -s http://localhost:$PORT/json/version &>/dev/null; then
    echo "启动浏览器..."
    # 创建用户目录（避免路径不存在）
    USER_DATA="$HOME/chromium-debug"
    mkdir -p "$USER_DATA"
    # 直接跑二进制，open -a 传参不可靠
    if [ "$BROWSER" = "Chromium" ]; then
        /Applications/Chromium.app/Contents/MacOS/Chromium --remote-debugging-port=$PORT --user-data-dir="$USER_DATA" --proxy-server=direct:// &
    else
        /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=$PORT --user-data-dir="$USER_DATA" --proxy-server=direct:// &
    fi
    # 等浏览器启动
    for i in $(seq 1 15); do
        sleep 1
        if curl --noproxy localhost -s http://localhost:$PORT/json/version &>/dev/null; then
            echo "✓ 调试端口已连接"
            break
        fi
        echo "  等待浏览器启动...($i)"
    done
fi

# 最终确认
if ! curl --noproxy localhost -s http://localhost:$PORT/json/version &>/dev/null; then
    echo "❌ 浏览器调试端口启动失败"
    echo "请手动关掉所有浏览器窗口，再重新运行"
    exit 1
fi

echo "✓ 浏览器就绪"
echo ""
