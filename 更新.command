#!/bin/bash
cd "$(dirname "$0")"
clear
echo ""
echo "  ================================"
echo "  食亨智慧运营 — 更新中..."
echo "  ================================"
echo ""
git pull origin feature/watch-mode
bash install.sh
echo ""
echo "  ✅ 更新完成！可以关掉这个窗口了。"
echo ""
read -n 1
