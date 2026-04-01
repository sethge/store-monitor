#!/bin/bash
# 食亨智慧运营 — Agent安装脚本
# 用法: cd store-monitor && bash install.sh

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
QCLAW_DIR="$HOME/.qclaw"

echo "安装食亨智慧运营Agent..."

# 1. 检查QClaw
if [ ! -d "$QCLAW_DIR" ]; then
    echo "❌ 没找到QClaw，请先安装QClaw"
    exit 1
fi
echo "✓ QClaw已安装"

# 2. 安装skills
echo "安装skills..."
mkdir -p "$QCLAW_DIR/skills"
for skill in store-patrol store-alert store-diagnosis ops-scheduler; do
    if [ -d "$SCRIPT_DIR/skills/$skill" ]; then
        cp -r "$SCRIPT_DIR/skills/$skill" "$QCLAW_DIR/skills/"
        echo "  ✓ $skill"
    fi
done

# 3. 安装agent配置（不覆盖已有的）
echo "安装agent配置..."
WORKSPACE="$QCLAW_DIR/workspace"
for f in SOUL.md USER.md HEARTBEAT.md MEMORY.md; do
    if [ ! -f "$WORKSPACE/$f" ] || [ "$1" = "--force" ]; then
        cp "$SCRIPT_DIR/agent-config/$f" "$WORKSPACE/"
        echo "  ✓ $f"
    else
        echo "  ⏭ $f（已存在，跳过。用 --force 覆盖）"
    fi
done

# knowledge目录
if [ ! -d "$WORKSPACE/knowledge" ] || [ "$1" = "--force" ]; then
    cp -r "$SCRIPT_DIR/agent-config/knowledge" "$WORKSPACE/"
    echo "  ✓ knowledge/"
fi

# 4. 链接store-monitor到workspace（如果不在的话）
if [ ! -d "$WORKSPACE/store-monitor" ]; then
    ln -s "$SCRIPT_DIR" "$WORKSPACE/store-monitor"
    echo "  ✓ 链接store-monitor到workspace"
fi

# 5. Python依赖
echo "检查Python依赖..."
python3 -c "import playwright" 2>/dev/null || {
    echo "安装playwright..."
    pip3 install playwright
    playwright install chromium
}
echo "  ✓ playwright"

python3 -c "import xlsxwriter" 2>/dev/null || {
    echo "安装xlsxwriter（竞对分析Excel）..."
    pip3 install xlsxwriter --break-system-packages 2>/dev/null || pip3 install xlsxwriter
}
echo "  ✓ xlsxwriter"

python3 -c "import lzstring" 2>/dev/null || {
    echo "安装lzstring（竞对链接生成）..."
    pip3 install lzstring --break-system-packages 2>/dev/null || pip3 install lzstring
}
echo "  ✓ lzstring"

# 6. ffmpeg（竞对视频提帧）
command -v ffmpeg &>/dev/null || {
    echo "安装ffmpeg..."
    if [ "$(uname -s)" = "Darwin" ]; then
        brew install ffmpeg
    else
        sudo apt update && sudo apt install -y ffmpeg
    fi
}
echo "  ✓ ffmpeg"

# 7. 竞对诊断配置文件
DIAG_CONFIG="$SCRIPT_DIR/skills/store-diagnosis/config.json"
if [ ! -f "$DIAG_CONFIG" ]; then
    echo "  ⚠ 竞对诊断需要 config.json，请联系管理员获取"
    echo "  文件位置: $DIAG_CONFIG"
else
    echo "  ✓ 竞对诊断配置已存在"
fi

echo ""
echo "✅ 安装完成！"
echo ""
echo "接下来需要手动做："
echo "  1. 启动Chrome调试模式（双击 盯店巡检.command）"
echo "  2. Chrome里加载悟空插件（chrome://extensions → 加载 goku 文件夹）"
echo "  3. 打开 bi.shihengtech.com 登录食亨"
echo "  4. 重启QClaw让它加载新skills"
echo ""
echo "之后在微信里跟agent说话就行了。"
