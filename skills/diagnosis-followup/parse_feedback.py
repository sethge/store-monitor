#!/usr/bin/env python3
"""
解析运营的自然语言反馈，生成结构化feedback.md。

agent收到运营回复后调用，把自然语言变成结构化记录。
不是完全自动——agent读brief.md拿到判断列表，再对照运营回复逐条匹配。

用法：
    # agent在skill执行过程中调用
    from parse_feedback import FeedbackParser

    parser = FeedbackParser(brief_path, store_dir)
    parser.parse_conversation(messages)  # messages = agent和运营的对话记录
    parser.save()
"""

import json
import os
import re
from datetime import datetime


class FeedbackParser:
    def __init__(self, brief_path, store_dir):
        self.brief_path = brief_path
        self.store_dir = store_dir
        self.brief = self._read_brief()
        self.judgments = []  # 从brief提取的判断列表
        self.suggestions = []  # 从brief提取的建议列表
        self.feedback = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "operator": "",
            "judgments": [],
            "suggestions": [],
            "operator_additions": [],
            "uncovered": []
        }

    def _read_brief(self):
        with open(self.brief_path, "r") as f:
            return f.read()

    def extract_items_from_brief(self):
        """从brief.md提取判断和建议列表"""
        lines = self.brief.split("\n")
        section = None
        idx_j = 0
        idx_s = 0

        for line in lines:
            stripped = line.strip()
            if "诊断核心结论" in stripped:
                section = "judgment"
                continue
            elif "建议" in stripped and section == "judgment":
                section = "suggestion"
                continue
            elif "你要带回来" in stripped:
                section = None
                continue

            if section == "judgment" and re.match(r"^\d+\.", stripped):
                idx_j += 1
                content = re.sub(r"^\d+\.\s*", "", stripped)
                self.judgments.append({"idx": idx_j, "content": content})
            elif section == "suggestion" and stripped.startswith("-"):
                idx_s += 1
                content = stripped.lstrip("- ")
                self.suggestions.append({"idx": idx_s, "content": content})

    def match_response(self, judgment_content, response_text):
        """
        判断运营对某个判断的态度。
        返回 (attitude, reason)
        attitude: 认同/部分认同/不认同/未回复
        """
        response_lower = response_text.lower()

        # 明确的不认同
        deny_patterns = ["不对", "不是", "不认同", "不同意", "错了", "不准"]
        partial_patterns = ["部分对", "部分认同", "有道理但", "差不多但"]
        agree_patterns = ["对", "是的", "没错", "认同", "确实", "准的", "对的"]

        for p in deny_patterns:
            if p in response_text:
                reason = response_text
                return "不认同", reason

        for p in partial_patterns:
            if p in response_text:
                reason = response_text
                return "部分认同", reason

        for p in agree_patterns:
            if p in response_text:
                return "认同", response_text

        return "未明确", response_text

    def match_suggestion_response(self, suggestion_content, response_text):
        """
        判断运营对建议的态度。
        返回 (adopted, reason, timeline)
        """
        done_patterns = ["做了", "充了", "改了", "已经"]
        will_do_patterns = ["可以", "试试", "做", "好的"]
        wont_do_patterns = ["做不了", "不行", "不做", "暂时不", "没法"]

        for p in done_patterns:
            if p in response_text:
                return "已执行", response_text, "已完成"

        for p in wont_do_patterns:
            if p in response_text:
                return "不采纳", response_text, None

        for p in will_do_patterns:
            if p in response_text:
                # 尝试提取时间
                time_match = re.search(r"(这周|下周|明天|今天|\d+天)", response_text)
                timeline = time_match.group(1) if time_match else "待定"
                return "采纳", response_text, timeline

        return "未明确", response_text, None

    def build_feedback_md(self, operator_name, judgment_results, suggestion_results,
                          operator_additions=None, uncovered=None):
        """
        生成feedback.md内容。

        judgment_results: [(judgment_content, attitude, reason), ...]
        suggestion_results: [(suggestion_content, adopted, reason, timeline), ...]
        """
        lines = [
            f"# 反馈：{os.path.basename(self.store_dir)}",
            f"日期：{self.feedback['date']}",
            f"运营：{operator_name}",
            "",
            "## 判断确认",
            "| # | 诊断判断 | 运营态度 | 运营说法 |",
            "|---|---------|---------|---------|"
        ]

        for i, (content, attitude, reason) in enumerate(judgment_results, 1):
            reason_clean = reason.replace("|", "｜").replace("\n", " ") if reason else ""
            lines.append(f"| {i} | {content[:30]} | {attitude} | {reason_clean[:50]} |")

        lines.extend([
            "",
            "## 建议反馈",
            "| # | 建议 | 采纳 | 说法 | 预计时间 |",
            "|---|------|------|------|---------|"
        ])

        for i, (content, adopted, reason, timeline) in enumerate(suggestion_results, 1):
            reason_clean = reason.replace("|", "｜").replace("\n", " ") if reason else ""
            timeline_str = timeline or ""
            lines.append(f"| {i} | {content[:30]} | {adopted} | {reason_clean[:40]} | {timeline_str} |")

        if operator_additions:
            lines.extend(["", "## 运营补充的信息"])
            for item in operator_additions:
                lines.append(f"- {item}")

        if uncovered:
            lines.extend(["", "## 未覆盖项"])
            for item in uncovered:
                lines.append(f"- {item}")
        else:
            lines.extend(["", "## 未覆盖项", "- 无"])

        return "\n".join(lines)

    def save_feedback(self, content):
        """写feedback.md"""
        path = os.path.join(self.store_dir, "feedback.md")
        with open(path, "w") as f:
            f.write(content)
        return path

    def update_state(self, next_step="todo", todos=None):
        """更新state.json"""
        state_path = os.path.join(self.store_dir, "state.json")
        with open(state_path) as f:
            state = json.load(f)

        state["step"] = next_step
        state["feedback_received_at"] = datetime.now().isoformat()
        if todos:
            state["todos"] = todos

        with open(state_path, "w") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        return state_path


if __name__ == "__main__":
    print("这个模块供agent在skill执行过程中import调用，不直接运行。")
    print("用法见文件头部注释。")
