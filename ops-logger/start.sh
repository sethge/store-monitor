#!/bin/bash
# 小q助手 — 一键启动
# 启动 Tabbit + server.py + 定时巡检 + 预警监测
# 用法: bash start.sh

DIR="$(cd "$(dirname "$0")" && pwd)"
PARENT="$(dirname "$DIR")"
PYTHON="/opt/homebrew/bin/python3"
[ ! -f "$PYTHON" ] && PYTHON="python3"

echo "=============================="
echo "  小q助手 启动中..."
echo "=============================="

# ─── 1. 启动 Tabbit ───
echo "[1/3] 启动 Tabbit..."
$PYTHON "$DIR/launch_tabbit.py" --port 9222
TABBIT_STATUS=$?
if [ $TABBIT_STATUS -ne 0 ]; then
  echo "  WARNING: Tabbit启动失败，巡检/预警功能不可用"
  echo "  操作日志记录功能仍然可用"
fi

# ─── 2. 启动 server.py ───
echo "[2/3] 启动 server..."
lsof -i :5500 -t | xargs kill -9 2>/dev/null
sleep 1
nohup $PYTHON "$DIR/server.py" > "$DIR/server.log" 2>&1 &
sleep 2

if ! curl -s http://127.0.0.1:5500/health > /dev/null; then
  echo "  ERROR: server启动失败，查看 $DIR/server.log"
  exit 1
fi
echo "  Server OK (port 5500)"

# ─── 3. 启动预警监测（可选，需要agent代码） ───
echo "[3/3] 检查巡检/预警..."
if [ -f "$PARENT/run_fast.py" ]; then
  # 检查是否已有预警进程在跑
  if pgrep -f "run_fast.py --watch" > /dev/null 2>&1; then
    echo "  预警监测已在运行"
  else
    echo "  巡检/预警就绪 (手动运行: cd $PARENT && $PYTHON run_fast.py 品牌名)"
    echo "  预警模式: $PYTHON run_fast.py --watch 09:00-22:00 品牌名"
  fi
else
  echo "  未找到巡检脚本，跳过"
fi

echo ""
echo "=============================="
echo "  小q助手已启动!"
echo "  Dashboard: http://127.0.0.1:5500"
echo "  Server PID: $(lsof -i :5500 -t)"
echo ""
echo "  Tabbit里安装扩展:"
echo "  1. 打开 chrome://extensions"
echo "  2. 开启开发者模式"
echo "  3. 加载已解压的扩展 → $DIR"
echo "  4. 加载Goku插件 → $PARENT/goku"
echo "=============================="
