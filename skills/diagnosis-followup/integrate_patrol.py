#!/usr/bin/env python3
"""
巡检后自动检查诊断队列。
巡检脚本跑完后调用这个，检查有没有新诊断要推、有没有该催的。

用法（在巡检结束后调用）：
    python3 skills/diagnosis-followup/integrate_patrol.py

输出人话版行动清单，agent拿到后自己判断怎么执行。
"""

import subprocess
import sys
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CHECK_QUEUE = os.path.join(SCRIPT_DIR, "check_queue.py")
QUEUE_DIR = os.path.expanduser("~/Downloads/diagnosis-queue")


def pull_queue():
    """拉取最新的诊断队列"""
    if not os.path.exists(os.path.join(QUEUE_DIR, ".git")):
        print("诊断队列仓库不存在，跳过。")
        return False

    try:
        result = subprocess.run(
            ["git", "pull", "origin", "main"],
            cwd=QUEUE_DIR,
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode != 0:
            # 可能还没有remote，没关系
            pass
        return True
    except Exception:
        return True  # 本地仓库存在就行


def check_and_report():
    """检查队列并返回行动清单"""
    if not pull_queue():
        return None

    try:
        result = subprocess.run(
            [sys.executable, CHECK_QUEUE, "--action"],
            capture_output=True,
            text=True,
            timeout=10
        )
        output = result.stdout.strip()
        if "没有需要行动" in output:
            return None
        return output
    except Exception as e:
        return f"检查诊断队列出错：{e}"


if __name__ == "__main__":
    report = check_and_report()
    if report:
        print("\n📋 诊断跟进：")
        print(report)
    else:
        print("诊断队列无待处理项。")
