#!/bin/bash
# 食亨智慧运营 — 双击安装
# macOS: 双击这个文件即可

cd "$(dirname "$0")"
clear
echo ""
echo "  ================================"
echo "  食亨智慧运营 — 正在安装..."
echo "  ================================"
echo ""

bash install.sh

echo ""
echo "  按任意键关闭窗口..."
read -n 1
