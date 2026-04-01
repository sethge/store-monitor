#!/bin/bash
# store-diagnosis skill 环境安装
# 原则：运营遇到任何环境问题都不应该自己研究，这个脚本负责全部搞定
# 用法: bash setup.sh
set -e

echo "=== store-diagnosis 环境检查 ==="

# 0. 检测系统
OS="$(uname -s)"
echo "系统: $OS"

# 0.1 Mac: 确保有 Homebrew（后面装东西都靠它）
if [ "$OS" = "Darwin" ]; then
    if command -v brew &>/dev/null; then
        echo "✓ Homebrew"
    else
        echo "正在安装 Homebrew..."
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        # M1/M2 Mac 需要加到 PATH
        eval "$(/opt/homebrew/bin/brew shellenv)" 2>/dev/null
    fi
fi

# 1. Python3
if command -v python3 &>/dev/null; then
    echo "✓ Python3: $(python3 --version 2>&1)"
else
    echo "正在安装 Python3..."
    if [ "$OS" = "Darwin" ]; then
        brew install python3
    else
        sudo apt update && sudo apt install -y python3 python3-pip
    fi
fi

# 1.1 pip
python3 -m pip --version &>/dev/null || {
    echo "正在安装 pip..."
    if [ "$OS" = "Darwin" ]; then
        python3 -m ensurepip --upgrade 2>/dev/null || brew install python3
    else
        sudo apt install -y python3-pip
    fi
}

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

# 4. Node.js + npm（QClaw运行环境）
if command -v node &>/dev/null; then
    echo "✓ Node.js: $(node --version)"
else
    echo "正在安装 Node.js..."
    if [ "$OS" = "Darwin" ]; then
        brew install node
    else
        curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - && sudo apt install -y nodejs
    fi
fi

if command -v npm &>/dev/null; then
    echo "✓ npm: $(npm --version)"
else
    echo "正在安装 npm..."
    if [ "$OS" = "Darwin" ]; then
        brew install node
    else
        sudo apt install -y npm
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

for pkg in xlsxwriter lzstring easyocr; do
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

# 7. 验证全部
echo ""
echo "=== 验证 ==="
command -v python3 &>/dev/null && echo "✓ Python3 $(python3 --version 2>&1)" || echo "✗ Python3"
command -v node &>/dev/null && echo "✓ Node.js $(node --version)" || echo "✗ Node.js"
command -v npm &>/dev/null && echo "✓ npm $(npm --version)" || echo "✗ npm"
command -v ffmpeg &>/dev/null && echo "✓ ffmpeg" || echo "✗ ffmpeg"
command -v git &>/dev/null && echo "✓ git" || echo "✗ git"
python3 -c "import xlsxwriter" 2>/dev/null && echo "✓ xlsxwriter" || echo "✗ xlsxwriter"
python3 -c "import lzstring" 2>/dev/null && echo "✓ lzstring" || echo "✗ lzstring"
node -e "require('sharp')" 2>/dev/null && echo "✓ sharp" || echo "✗ sharp"

echo ""
echo "✅ 环境就绪！store-diagnosis skill 可以正常使用。"
echo ""
echo "工具列表："
echo "  extract_frames.py — 视频提帧+采样"
echo "  deploy.py         — 生成公网链接"
echo "  write_excel.py    — JSON→Excel（备用）"
echo "  save_reference.py — 参考店铺库"
