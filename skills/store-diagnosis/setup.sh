#!/bin/bash
# store-diagnosis skill 环境安装（国内镜像，不依赖梯子）
set -e

echo "=== store-diagnosis 环境检查 ==="

OS="$(uname -s)"
PIP_MIRROR="-i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn"
PIP_CMD="pip3 install $PIP_MIRROR --break-system-packages"

# brew 镜像
if [ "$OS" = "Darwin" ]; then
    export HOMEBREW_BREW_GIT_REMOTE="https://mirrors.ustc.edu.cn/brew.git"
    export HOMEBREW_CORE_GIT_REMOTE="https://mirrors.ustc.edu.cn/homebrew-core.git"
    export HOMEBREW_BOTTLE_DOMAIN="https://mirrors.ustc.edu.cn/homebrew-bottles"
    export HOMEBREW_API_DOMAIN="https://mirrors.ustc.edu.cn/homebrew-bottles/api"
fi

# Homebrew
if [ "$OS" = "Darwin" ]; then
    command -v brew &>/dev/null || {
        echo "安装 Homebrew（中科大镜像）..."
        /bin/bash -c "$(curl -fsSL https://mirrors.ustc.edu.cn/misc/brew-install.sh)"
        eval "$(/opt/homebrew/bin/brew shellenv)" 2>/dev/null
    }
fi

# Python3
command -v python3 &>/dev/null || {
    echo "安装 Python3..."
    [ "$OS" = "Darwin" ] && brew install python3 || sudo apt install -y python3 python3-pip
}
echo "✓ Python3"

# pip
python3 -m pip --version &>/dev/null || {
    python3 -m ensurepip --upgrade 2>/dev/null || {
        [ "$OS" = "Darwin" ] && brew install python3 || sudo apt install -y python3-pip
    }
}

# ffmpeg
command -v ffmpeg &>/dev/null || {
    echo "安装 ffmpeg..."
    [ "$OS" = "Darwin" ] && brew install ffmpeg || sudo apt install -y ffmpeg
}
echo "✓ ffmpeg"

# Node.js
command -v node &>/dev/null || {
    echo "安装 Node.js..."
    if [ "$OS" = "Darwin" ]; then
        brew install node
    else
        curl -fsSL https://npmmirror.com/mirrors/node/latest-v20.x/SHASUMS256.txt >/dev/null 2>&1
        curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - && sudo apt install -y nodejs
    fi
}
echo "✓ Node.js"

# sharp
node -e "require('sharp')" 2>/dev/null || {
    echo "安装 sharp..."
    npm install -g sharp --registry=https://registry.npmmirror.com 2>/dev/null || {
        [ "$OS" = "Darwin" ] && brew install vips 2>/dev/null || sudo apt install -y libvips-dev 2>/dev/null
        npm install -g sharp --registry=https://registry.npmmirror.com
    }
}
echo "✓ sharp"

# Python 依赖
for pkg in xlsxwriter lzstring; do
    python3 -c "import $pkg" 2>/dev/null || {
        echo "安装 $pkg..."
        $PIP_CMD $pkg 2>/dev/null || pip3 install $PIP_MIRROR $pkg
    }
    echo "✓ $pkg"
done

# 腾讯云 OCR
python3 -c "from tencentcloud.ocr.v20181119 import ocr_client" 2>/dev/null || {
    echo "安装腾讯云OCR SDK..."
    $PIP_CMD tencentcloud-sdk-python 2>/dev/null || pip3 install $PIP_MIRROR tencentcloud-sdk-python
}
echo "✓ tencentcloud-sdk"

# Gemini
python3 -c "from google import genai" 2>/dev/null || {
    echo "安装 google-genai..."
    $PIP_CMD google-genai 2>/dev/null || pip3 install $PIP_MIRROR google-genai
}
echo "✓ google-genai"

# git
command -v git &>/dev/null || {
    [ "$OS" = "Darwin" ] && xcode-select --install 2>/dev/null || sudo apt install -y git
}
echo "✓ git"

echo ""
echo "✅ store-diagnosis 环境就绪"
