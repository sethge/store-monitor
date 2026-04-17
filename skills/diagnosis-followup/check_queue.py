#!/usr/bin/env python3
"""
检查诊断队列，找出需要处理的店铺。
巡检结束后调用，或单独运行。

用法：
    python3 check_queue.py                  # 检查所有状态
    python3 check_queue.py --operator 张三   # 只看某个运营
    python3 check_queue.py --action          # 只显示需要行动的
"""

import json
import os
import glob
import argparse
from datetime import datetime, timedelta

QUEUE_DIR = os.path.expanduser("~/Downloads/diagnosis-queue")


def load_registry():
    path = os.path.join(QUEUE_DIR, "registry.json")
    if not os.path.exists(path):
        return {"operators": []}
    with open(path) as f:
        return json.load(f)


def scan_states(operator_filter=None):
    """扫描所有state.json，返回状态列表"""
    results = []
    pattern = os.path.join(QUEUE_DIR, "*/*/state.json")

    for state_path in sorted(glob.glob(pattern)):
        parts = state_path.replace(QUEUE_DIR + "/", "").split("/")
        if len(parts) < 3:
            continue
        operator_name = parts[0]
        store_dir_name = parts[1]

        if operator_filter and operator_name != operator_filter:
            continue

        # 跳过模板和汇总目录
        if operator_name.startswith("_"):
            continue

        with open(state_path) as f:
            state = json.load(f)

        brief_path = os.path.join(os.path.dirname(state_path), "brief.md")
        has_brief = os.path.exists(brief_path)

        results.append({
            "operator": operator_name,
            "store": store_dir_name,
            "step": state.get("step", "unknown"),
            "state": state,
            "has_brief": has_brief,
            "dir": os.path.dirname(state_path)
        })

    return results


def check_actions_needed(states):
    """检查哪些需要行动"""
    now = datetime.now()
    actions = []

    for s in states:
        state = s["state"]
        step = state.get("step", "")

        if step == "new" and s["has_brief"]:
            actions.append({
                "type": "push_diagnosis",
                "priority": "high",
                "operator": s["operator"],
                "store": s["store"],
                "msg": f"新诊断待推送给{s['operator']}"
            })

        elif step == "feedback":
            pushed = state.get("pushed_at")
            reminded = state.get("reminded_count", 0)
            if pushed:
                days_since = (now - datetime.fromisoformat(pushed)).days
                if days_since >= 2 and reminded == 0:
                    actions.append({
                        "type": "remind_feedback",
                        "priority": "medium",
                        "operator": s["operator"],
                        "store": s["store"],
                        "msg": f"推了{days_since}天没回复，该催了"
                    })
                elif days_since >= 5 and reminded >= 1:
                    actions.append({
                        "type": "escalate",
                        "priority": "high",
                        "operator": s["operator"],
                        "store": s["store"],
                        "msg": f"推了{days_since}天催了{reminded}次还没回复，需要升级"
                    })

        elif step == "todo":
            for todo in state.get("todos", []):
                if todo.get("status") == "pending" and todo.get("due"):
                    due = datetime.fromisoformat(todo["due"])
                    if now > due:
                        overdue_days = (now - due).days
                        actions.append({
                            "type": "remind_todo",
                            "priority": "medium" if overdue_days < 7 else "high",
                            "operator": s["operator"],
                            "store": s["store"],
                            "msg": f"TODO逾期{overdue_days}天: {todo['action']}"
                        })

        elif step == "executing":
            review_due = state.get("review_due")
            if review_due:
                due = datetime.fromisoformat(review_due)
                if now >= due:
                    actions.append({
                        "type": "do_review",
                        "priority": "medium",
                        "operator": s["operator"],
                        "store": s["store"],
                        "msg": f"该做Review了（执行后{(now - due).days + 7}天）"
                    })

    return actions


def format_dashboard(states):
    """生成人话版进度"""
    if not states:
        return "诊断队列为空，没有需要跟进的店铺。"

    by_operator = {}
    for s in states:
        op = s["operator"]
        if op not in by_operator:
            by_operator[op] = []
        by_operator[op].append(s)

    lines = []
    step_names = {
        "new": "新诊断待推",
        "feedback": "等反馈",
        "todo": "跟进TODO",
        "executing": "执行中",
        "review_done": "Review完成",
        "closed": "已关闭"
    }

    for op, stores in by_operator.items():
        lines.append(f"\n{op} ({len(stores)}家店)")
        for s in stores:
            step_label = step_names.get(s["step"], s["step"])
            extra = ""
            state = s["state"]
            if s["step"] == "feedback" and state.get("reminded_count", 0) > 0:
                extra = f"（催了{state['reminded_count']}次）"
            lines.append(f"  {s['store']} — {step_label}{extra}")

    return "\n".join(lines)


def format_actions(actions):
    """生成行动清单"""
    if not actions:
        return "当前没有需要行动的项目。"

    lines = ["需要行动："]
    for a in sorted(actions, key=lambda x: 0 if x["priority"] == "high" else 1):
        prefix = "!" if a["priority"] == "high" else "-"
        lines.append(f"  {prefix} {a['operator']} / {a['store']}: {a['msg']}")

    return "\n".join(lines)


def save_dashboard(states, actions):
    """保存dashboard.json供总agent读取"""
    summary_dir = os.path.join(QUEUE_DIR, "_summary")
    os.makedirs(summary_dir, exist_ok=True)

    dashboard = {
        "updated_at": datetime.now().isoformat(),
        "total_stores": len(states),
        "by_step": {},
        "actions_needed": len(actions),
        "actions": actions
    }

    for s in states:
        step = s["step"]
        dashboard["by_step"][step] = dashboard["by_step"].get(step, 0) + 1

    with open(os.path.join(summary_dir, "dashboard.json"), "w") as f:
        json.dump(dashboard, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--operator", help="只看某个运营")
    parser.add_argument("--action", action="store_true", help="只显示需要行动的")
    args = parser.parse_args()

    states = scan_states(args.operator)
    actions = check_actions_needed(states)
    save_dashboard(states, actions)

    if args.action:
        print(format_actions(actions))
    else:
        print(format_dashboard(states))
        if actions:
            print()
            print(format_actions(actions))
