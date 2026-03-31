#!/bin/bash
# 盯店巡检一键启动

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT=9222

# ===== 1. 检查+安装依赖 =====
if ! command -v python3 &>/dev/null; then
    echo "安装Python..."
    brew install python
fi

python3 -c "import playwright" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "安装Playwright..."
    pip3 install --break-system-packages playwright
    playwright install chromium
fi

# ===== 2. 启动Chrome调试模式 =====
if ! curl --noproxy localhost -s http://localhost:$PORT/json/version &>/dev/null; then
    echo "启动Chrome调试模式..."
    "$CHROME" --remote-debugging-port=$PORT --user-data-dir=$HOME/Library/Application Support/Chrome-Debug --proxy-server="direct://" &
    sleep 3

    # 检查悟空插件
    if [ ! -d "$HOME/Library/Application Support/Chrome-Debug/Default/Extensions" ] || ! find $HOME/Library/Application Support/Chrome-Debug -path "*/goku*" -print -quit 2>/dev/null | grep -q .; then
        echo ""
        echo "⚠️  首次使用需要手动操作："
        echo "  1. Chrome打开 chrome://extensions/"
        echo "  2. 开启开发者模式"
        echo "  3. 加载已解压的扩展程序 → 选择 $SCRIPT_DIR/goku/goku"
        echo "  4. 打开 bi.shihengtech.com 登录食亨"
        echo ""
        echo "完成后按回车继续..."
        read
    fi
fi

# ===== 3. 输入品牌列表 =====
BRANDS_FILE="$SCRIPT_DIR/brands.txt"

if [ ! -f "$BRANDS_FILE" ]; then
    echo "首次运行，请输入要监控的品牌（每行一个，输入空行结束）："
    > "$BRANDS_FILE"
    while true; do
        read -p "  品牌名: " brand
        [ -z "$brand" ] && break
        echo "$brand" >> "$BRANDS_FILE"
    done
    echo "品牌列表已保存到 brands.txt，下次直接运行不用再输入"
fi

# 读取品牌列表
BRANDS=()
while IFS= read -r line; do
    [ -n "$line" ] && BRANDS+=("$line")
done < "$BRANDS_FILE"

if [ ${#BRANDS[@]} -eq 0 ]; then
    echo "brands.txt 为空，请编辑后重新运行"
    exit 1
fi

echo ""
echo "开始巡检 ${#BRANDS[@]} 个品牌..."
echo ""

# ===== 4. 跑巡检 =====
cd "$SCRIPT_DIR"
NO_PROXY=localhost python3 run_fast.py "${BRANDS[@]}"
