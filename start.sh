#!/bin/bash
# 盯店巡检一键启动

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# 只用 Chromium（Chrome 会强制自动更新导致插件不兼容）
if [ -d "/Applications/Chromium.app" ]; then
    CHROME="/Applications/Chromium.app/Contents/MacOS/Chromium"
else
    echo "❌ 没找到 Chromium，正在安装..."
    brew install --cask chromium 2>/dev/null || {
        echo "安装失败，请手动下载: https://github.com/nicehash/Chromium/releases"
        exit 1
    }
    CHROME="/Applications/Chromium.app/Contents/MacOS/Chromium"
fi
PORT=9222

# ===== 1. 检查+安装依赖 =====
if ! command -v python3 &>/dev/null; then
    echo "安装Python..."
    brew install python
fi

python3 -c "import playwright; assert playwright.__version__=='1.44.0'" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "安装Playwright 1.44.0..."
    pip3 install --break-system-packages -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn playwright==1.44.0
    PLAYWRIGHT_DOWNLOAD_HOST="https://npmmirror.com/mirrors/playwright/" playwright install chromium 2>/dev/null || playwright install chromium
fi

# ===== 禁止Chrome自动更新 =====
defaults write com.google.Keystone.Agent checkInterval 0 2>/dev/null
defaults write com.google.Chrome DisableAutoUpdate -bool true 2>/dev/null
sudo rm -rf /Library/Google/GoogleSoftwareUpdate 2>/dev/null
rm -rf ~/Library/Google/GoogleSoftwareUpdate 2>/dev/null

# ===== 2. 启动Chrome调试模式 =====
if ! curl --noproxy localhost -s http://localhost:$PORT/json/version &>/dev/null; then
    echo "启动浏览器调试模式..."
    # 不用 --load-extension（Chrome 146 已失效），插件首次手动加载后会自动保存
    "$CHROME" --remote-debugging-port=$PORT --user-data-dir="$HOME/Library/Application Support/Chrome-Debug" --proxy-server="direct://" --disable-features=ExtensionDeveloperModeWarning &
    sleep 3

    # 检查悟空插件是否已加载过
    GOKU_LOADED=false
    if [ -d "$HOME/Library/Application Support/Chrome-Debug/Default/Extensions" ]; then
        # 检查扩展目录里有没有悟空
        find "$HOME/Library/Application Support/Chrome-Debug" -name "manifest.json" -exec grep -l "悟空" {} \; 2>/dev/null | grep -q . && GOKU_LOADED=true
    fi

    if [ "$GOKU_LOADED" = "false" ]; then
        echo ""
        echo "⚠️  首次使用需要手动加载悟空插件（只需一次）："
        echo "  1. 浏览器打开 chrome://extensions/"
        echo "  2. 开启右上角「开发者模式」"
        echo "  3. 点「加载已解压的扩展程序」→ 选择: $SCRIPT_DIR/goku"
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
