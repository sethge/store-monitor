#!/bin/bash
# 小q助手 - 双击启动服务
cd "$(dirname "$0")"

echo "========================================="
echo "  小q助手 启动中..."
echo "========================================="

# 检查Python3
if command -v /opt/homebrew/bin/python3 &>/dev/null; then
    PY=/opt/homebrew/bin/python3
elif command -v python3 &>/dev/null; then
    PY=python3
else
    echo ""
    echo "❌ 没有找到Python，需要先安装："
    echo "   打开终端，粘贴这行命令回车："
    echo "   /bin/bash -c \"\$(curl -fsSL https://cdn.npmmirror.com/binaries/homebrew/install.sh)\" && brew install python3"
    echo ""
    echo "装完后再双击这个文件"
    echo ""
    read -p "按回车关闭..."
    exit 1
fi

echo "Python: $PY"

# 检查flask依赖
if ! $PY -c "import flask" 2>/dev/null; then
    echo "安装依赖中（首次需要，约1分钟）..."
    $PY -m pip install flask requests pymysql -i https://pypi.tuna.tsinghua.edu.cn/simple --quiet 2>&1
    if [ $? -ne 0 ]; then
        echo "❌ 依赖安装失败，联系管理员"
        read -p "按回车关闭..."
        exit 1
    fi
    echo "✅ 依赖安装完成"
fi

# 杀掉旧进程
lsof -i :5500 -t 2>/dev/null | xargs kill -9 2>/dev/null
sleep 1

# 启动
echo ""
echo "✅ 服务启动成功！"
echo "   现在可以用Chrome扩展了"
echo "   这个窗口不要关（关了服务就停了）"
echo "========================================="
echo ""

$PY server.py
