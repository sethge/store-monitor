#!/bin/bash
# 食亨智慧运营 — Agent安装脚本
# 所有下载走国内镜像，不依赖梯子
# 用法: cd store-monitor && bash install.sh

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
QCLAW_DIR="$HOME/.qclaw"

echo "安装食亨智慧运营Agent..."

# ─── 0. 国内镜像配置 ───
PIP_MIRROR="-i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn"
PIP_CMD="pip3 install $PIP_MIRROR --break-system-packages"
GIT_MIRROR="https://ghfast.top"  # GitHub 加速

if [ "$(uname -s)" = "Darwin" ]; then
    export HOMEBREW_BREW_GIT_REMOTE="https://mirrors.ustc.edu.cn/brew.git"
    export HOMEBREW_CORE_GIT_REMOTE="https://mirrors.ustc.edu.cn/homebrew-core.git"
    export HOMEBREW_BOTTLE_DOMAIN="https://mirrors.ustc.edu.cn/homebrew-bottles"
    export HOMEBREW_API_DOMAIN="https://mirrors.ustc.edu.cn/homebrew-bottles/api"
fi

# ─── 1. 检查QClaw ───
if [ ! -d "$QCLAW_DIR" ]; then
    echo "❌ 没找到QClaw，请先安装QClaw"
    exit 1
fi
echo "✓ QClaw已安装"

# ─── 2. 安装Brain（集体知识库）───
echo "安装Brain（运营知识库）..."
if [ ! -d "$HOME/wisdom-brain" ]; then
    # 先试加速镜像，失败用原地址
    git clone https://gitee.com/sethgeshiheng/wisdom-brain.git "$HOME/wisdom-brain" 2>/dev/null || \
    git clone https://gitee.com/sethgeshiheng/wisdom-brain.git "$HOME/wisdom-brain" 2>/dev/null && \
        echo "  ✓ wisdom-brain 已克隆" || \
        echo "  ⚠ wisdom-brain 克隆失败（不影响基础功能）"
else
    cd "$HOME/wisdom-brain" && git pull --quiet 2>/dev/null
    echo "  ✓ wisdom-brain 已更新"
fi
if [ ! -L "$SCRIPT_DIR/wisdom-brain" ]; then
    ln -sf "$HOME/wisdom-brain" "$SCRIPT_DIR/wisdom-brain"
    echo "  ✓ 链接 wisdom-brain"
fi

# ─── 3. 安装skills（软链接，git pull自动更新）───
echo "安装skills..."
mkdir -p "$QCLAW_DIR/skills"
for skill in store-patrol store-alert store-diagnosis ops-scheduler setup; do
    if [ -d "$SCRIPT_DIR/skills/$skill" ]; then
        rm -rf "$QCLAW_DIR/skills/$skill"
        ln -sf "$SCRIPT_DIR/skills/$skill" "$QCLAW_DIR/skills/$skill"
        echo "  ✓ $skill → 链接"
    fi
done
if [ -f "$SCRIPT_DIR/skills/SKILL.md" ]; then
    rm -f "$QCLAW_DIR/skills/SKILL.md"
    ln -sf "$SCRIPT_DIR/skills/SKILL.md" "$QCLAW_DIR/skills/SKILL.md"
    echo "  ✓ SKILL.md → 链接"
fi

# ─── 4. 安装agent配置（人格文件强制覆盖，确保是我们的风格）───
echo "安装agent配置..."
WORKSPACE="$QCLAW_DIR/workspace"
# 人格文件必须覆盖（SOUL/BRAIN/USER/HEARTBEAT），不然QClaw默认风格会覆盖我们的
for f in SOUL.md BRAIN.md USER.md HEARTBEAT.md; do
    cp "$SCRIPT_DIR/agent-config/$f" "$WORKSPACE/"
    echo "  ✓ $f（已覆盖）"
done
# MEMORY.md 不覆盖（运营个人记忆）
if [ ! -f "$WORKSPACE/MEMORY.md" ]; then
    cp "$SCRIPT_DIR/agent-config/MEMORY.md" "$WORKSPACE/"
    echo "  ✓ MEMORY.md（新建）"
else
    echo "  ⏭ MEMORY.md（保留个人记忆）"
fi
if [ ! -d "$WORKSPACE/knowledge" ] || [ "$1" = "--force" ]; then
    cp -r "$SCRIPT_DIR/agent-config/knowledge" "$WORKSPACE/"
    echo "  ✓ knowledge/"
fi
if [ ! -d "$WORKSPACE/store-monitor" ]; then
    ln -s "$SCRIPT_DIR" "$WORKSPACE/store-monitor"
    echo "  ✓ 链接store-monitor"
fi

# ─── 5. Homebrew（Mac）───
if [ "$(uname -s)" = "Darwin" ]; then
    command -v brew &>/dev/null || {
        echo "安装 Homebrew（中科大镜像）..."
        /bin/bash -c "$(curl -fsSL https://mirrors.ustc.edu.cn/misc/brew-install.sh)"
        eval "$(/opt/homebrew/bin/brew shellenv)" 2>/dev/null
    }
fi

# ─── 6. 浏览器（Chromium优先，不自动更新）───
if [ "$(uname -s)" = "Darwin" ]; then
    if [ -d "/Applications/Chromium.app" ]; then
        echo "  ✓ Chromium 已安装"
    elif command -v brew &>/dev/null; then
        echo "安装 Chromium（不会自动更新，比Chrome稳定）..."
        brew install --cask chromium 2>/dev/null && echo "  ✓ Chromium 已安装" || \
        echo "  ⚠ Chromium 安装失败，请手动下载: https://github.com/nicehash/Chromium/releases"
    else
        echo "  ⚠ 请安装 Chromium: https://github.com/nicehash/Chromium/releases"
    fi
fi

# ─── 7. ffmpeg（可选，有就用，没有自动用opencv替代）───
command -v ffmpeg &>/dev/null && echo "  ✓ ffmpeg" || {
    echo "  ⏭ ffmpeg 未安装（自动使用opencv替代，不影响功能）"
}

# ─── 7. Python依赖（全部清华镜像）───
echo "检查Python依赖..."

# opencv（视频提帧，替代 ffmpeg）
python3 -c "import cv2" 2>/dev/null || {
    echo "安装opencv..."
    $PIP_CMD opencv-python-headless 2>/dev/null || pip3 install $PIP_MIRROR opencv-python-headless
}
echo "  ✓ opencv"

# playwright（锁定1.44.0，1.58.0跟CDP有兼容问题）
PLAYWRIGHT_VER="1.44.0"
python3 -c "import playwright; v=playwright.__version__; exit(0 if v=='$PLAYWRIGHT_VER' else 1)" 2>/dev/null || {
    echo "安装playwright==$PLAYWRIGHT_VER..."
    $PIP_CMD "playwright==$PLAYWRIGHT_VER" 2>/dev/null || pip3 install $PIP_MIRROR "playwright==$PLAYWRIGHT_VER"
    PLAYWRIGHT_DOWNLOAD_HOST="https://npmmirror.com/mirrors/playwright/" playwright install chromium 2>/dev/null || \
    playwright install chromium
}
echo "  ✓ playwright ($PLAYWRIGHT_VER)"

for pkg in xlsxwriter lzstring cos-python-sdk-v5; do
    python3 -c "import $pkg" 2>/dev/null || {
        echo "安装 $pkg..."
        $PIP_CMD $pkg 2>/dev/null || pip3 install $PIP_MIRROR $pkg
    }
    echo "  ✓ $pkg"
done

# 腾讯云 OCR SDK
python3 -c "from tencentcloud.ocr.v20181119 import ocr_client" 2>/dev/null || {
    echo "安装腾讯云OCR SDK..."
    $PIP_CMD tencentcloud-sdk-python 2>/dev/null || pip3 install $PIP_MIRROR tencentcloud-sdk-python
}
echo "  ✓ tencentcloud-sdk"

# Gemini SDK
python3 -c "from google import genai" 2>/dev/null || {
    echo "安装google-genai..."
    $PIP_CMD google-genai 2>/dev/null || pip3 install $PIP_MIRROR google-genai
}
echo "  ✓ google-genai"

# ─── 8. 初始化memory目录 ───
mkdir -p "$SCRIPT_DIR/memory/interactions"
mkdir -p "$SCRIPT_DIR/memory/pending_review"
echo "  ✓ memory目录"

# ─── 9. 注册heartbeat定时任务 ───
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
      "message": "现在是下班时间，做今天的heartbeat。\n\n1. 检查 memory/interactions/ 里有没有新的交互日志（对比 memory/.last_digest 的日期）\n2. 有新交互 → 运行 cd ~/.qclaw/workspace/store-monitor && python3 learn.py digest\n3. digest 有发现 → 运行 python3 learn.py submit\n4. 如果今天是周一 → 额外运行 python3 learn.py weekly\n5. 没有新交互 → 什么都不用做",
      "deliver": true,
      "channel": "wechat-access",
      "bestEffortDeliver": true
    }
  }
}
CRONEOF
echo "  ✓ heartbeat定时任务"

# ─── 10. 禁止Chrome自动更新（146跟悟空插件不兼容）───
if [ "$(uname -s)" = "Darwin" ]; then
    defaults write com.google.Keystone.Agent checkInterval 0 2>/dev/null
    defaults write com.google.Chrome DisableAutoUpdate -bool true 2>/dev/null
    sudo rm -rf /Library/Google/GoogleSoftwareUpdate 2>/dev/null
    rm -rf ~/Library/Google/GoogleSoftwareUpdate 2>/dev/null
    echo "  ✓ Chrome自动更新已禁止"
fi

echo ""
echo "✅ 安装完成！"
echo ""
echo "接下来需要手动做："
echo "  1. 安装 Chromium（推荐，不会自动更新）或用 Chrome 145"
echo "  2. 双击「盯店巡检.command」启动浏览器"
echo "  3. 加载悟空插件（chrome://extensions → 加载 goku 文件夹）"
echo "  4. 打开 bi.shihengtech.com 登录食亨"
echo "  5. 重启QClaw"
echo ""
echo "之后在微信里跟agent说话就行了。"
