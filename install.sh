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

# 2. 安装Brain（集体知识库）
echo "安装Brain（运营知识库）..."
if [ ! -d "$HOME/wisdom-brain" ]; then
    git clone https://github.com/sethge/wisdom-brain.git "$HOME/wisdom-brain" 2>/dev/null && \
        echo "  ✓ wisdom-brain 已克隆" || \
        echo "  ⚠ wisdom-brain 克隆失败，请检查网络"
else
    cd "$HOME/wisdom-brain" && git pull --quiet 2>/dev/null
    echo "  ✓ wisdom-brain 已更新"
fi
# 链接到项目目录
if [ ! -L "$SCRIPT_DIR/wisdom-brain" ]; then
    ln -sf "$HOME/wisdom-brain" "$SCRIPT_DIR/wisdom-brain"
    echo "  ✓ 链接 wisdom-brain"
fi

# 3. 安装skills
echo "安装skills..."
mkdir -p "$QCLAW_DIR/skills"
for skill in store-patrol store-alert store-diagnosis ops-scheduler setup; do
    if [ -d "$SCRIPT_DIR/skills/$skill" ]; then
        cp -r "$SCRIPT_DIR/skills/$skill" "$QCLAW_DIR/skills/"
        echo "  ✓ $skill"
    fi
done

# 3. 安装agent配置（不覆盖已有的）
echo "安装agent配置..."
WORKSPACE="$QCLAW_DIR/workspace"
for f in SOUL.md BRAIN.md USER.md HEARTBEAT.md MEMORY.md; do
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

# 8. 学习引擎依赖
echo "检查学习引擎依赖..."
python3 -c "from google import genai" 2>/dev/null || {
    echo "安装google-genai（学习引擎需要）..."
    pip3 install google-genai --break-system-packages 2>/dev/null || pip3 install google-genai
}
echo "  ✓ google-genai"

# 9. 初始化memory目录
mkdir -p "$SCRIPT_DIR/memory/interactions"
mkdir -p "$SCRIPT_DIR/memory/pending_review"
echo "  ✓ memory目录"

# 10. 注册内置定时任务（heartbeat）
echo "注册heartbeat定时任务..."
HEARTBEAT_CRON="$SCRIPT_DIR/.heartbeat_cron.json"
cat > "$HEARTBEAT_CRON" << 'CRONEOF'
{
  "action": "add",
  "job": {
    "name": "heartbeat-每日总结",
    "schedule": { "kind": "cron", "expr": "30 17 * * *", "tz": "Asia/Shanghai" },
    "sessionTarget": "isolated",
    "wakeMode": "now",
    "payload": {
      "kind": "agentTurn",
      "message": "现在是下班时间，做今天的heartbeat。\n\n1. 检查 memory/interactions/ 里有没有新的交互日志（对比 memory/.last_digest 的日期）\n2. 有新交互 → 运行 cd /Users/seth/.qclaw/workspace/store-monitor && python3 learn.py digest\n3. digest 有发现 → 运行 python3 learn.py submit\n4. 如果今天是周一 → 额外运行 python3 learn.py weekly\n5. 没有新交互 → 什么都不用做\n\n把结果简要告诉Seth。",
      "deliver": true,
      "channel": "wechat-access",
      "bestEffortDeliver": true
    }
  }
}
CRONEOF
echo "  ✓ heartbeat定时任务配置已生成: .heartbeat_cron.json"

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
echo "heartbeat（每天17:30自动总结）已内置，不需要额外配置。"
