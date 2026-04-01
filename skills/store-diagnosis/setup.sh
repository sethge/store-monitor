#!/bin/bash
# store-diagnosis skill 环境安装
# 用法: bash setup.sh
set -e

echo "=== store-diagnosis 环境检查 ==="

# 1. 检测系统
OS="$(uname -s)"
echo "系统: $OS"

# 2. Python3
if command -v python3 &>/dev/null; then
    PY=$(command -v python3)
    echo "✓ Python3: $PY ($(python3 --version 2>&1))"
else
    echo "✗ Python3 未安装"
    if [ "$OS" = "Darwin" ]; then
        echo "  安装方法: brew install python3"
    else
        echo "  安装方法: sudo apt install python3 python3-pip"
    fi
    exit 1
fi

# 3. ffmpeg
if command -v ffmpeg &>/dev/null; then
    echo "✓ ffmpeg: $(ffmpeg -version 2>&1 | head -1)"
else
    echo "✗ ffmpeg 未安装"
    if [ "$OS" = "Darwin" ]; then
        echo "  正在安装..."
        brew install ffmpeg
    else
        echo "  正在安装..."
        sudo apt update && sudo apt install -y ffmpeg
    fi
fi

# 4. Node.js + sharp（QClaw读图需要）
if command -v node &>/dev/null; then
    echo "✓ Node.js: $(node --version)"
else
    echo "✗ Node.js 未安装"
    if [ "$OS" = "Darwin" ]; then
        echo "  正在安装..."
        brew install node
    else
        echo "  正在安装..."
        curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - && sudo apt install -y nodejs
    fi
fi

# sharp（QClaw Agent读取图片需要）
if node -e "require('sharp')" 2>/dev/null; then
    echo "✓ sharp"
else
    echo "安装 sharp..."
    npm install -g sharp 2>/dev/null || {
        # 有些环境需要从源码编译
        if [ "$OS" = "Darwin" ]; then
            brew install vips 2>/dev/null
        else
            sudo apt install -y libvips-dev 2>/dev/null
        fi
        npm install -g sharp
    }
    echo "✓ sharp 已安装"
fi

# 5. Python依赖
PIP_FLAGS=""
if [ "$OS" = "Darwin" ]; then
    PIP_FLAGS="--break-system-packages"
fi

for pkg in xlsxwriter lzstring; do
    python3 -c "import $pkg" 2>/dev/null || {
        echo "安装 $pkg..."
        python3 -m pip install $pkg $PIP_FLAGS -q 2>/dev/null || pip3 install $pkg -q
    }
    echo "✓ $pkg"
done

# 5. git（deploy.py 需要 push 到 gh-pages）
if command -v git &>/dev/null; then
    echo "✓ git: $(git --version)"
else
    echo "✗ git 未安装"
    if [ "$OS" = "Darwin" ]; then
        echo "  安装方法: xcode-select --install"
    else
        echo "  安装方法: sudo apt install -y git"
    fi
fi

# 6. 验证
echo ""
echo "=== 验证 ==="
python3 -c "
import xlsxwriter; print('✓ xlsxwriter', xlsxwriter.__version__)
import lzstring; print('✓ lzstring')
"
ffmpeg -version >/dev/null 2>&1 && echo "✓ ffmpeg 可用" || echo "✗ ffmpeg 不可用"
git --version >/dev/null 2>&1 && echo "✓ git 可用" || echo "✗ git 不可用"

echo ""
echo "✅ 环境就绪！store-diagnosis skill 可以正常使用。"
echo ""
echo "工具列表："
echo "  extract_frames.py — 视频提帧+采样"
echo "  deploy.py         — 生成公网链接"
echo "  write_excel.py    — JSON→Excel（备用）"
echo "  save_reference.py — 参考店铺库"
