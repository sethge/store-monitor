#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交互经验学习引擎

两层机制：
  1. agent 从交互中提炼经验 → 存到运营个人 memory
  2. 定期把 memory 回传给 Seth → Seth 审阅后决定哪些进 brain（集体认知）

用法:
  # 记录运营的 skill 使用偏好
  python3 learn.py usage "运营A要求每天10点巡检港翠+禾，每10分钟预警"

  # 记录运营的纠正/反馈（立即写入 MEMORY.md）
  python3 learn.py feedback "运营说推广余额提前2天提醒就行，不用1天"

  # 记录运营分享的运营知识
  python3 learn.py knowledge "烧烤品类周末差评多是因为出餐慢，不是味道问题"

  # 每日总结：提炼当天经验，更新 memory + knowledge
  python3 learn.py digest

  # 回传：把积累的经验提交给 Seth 审阅
  python3 learn.py submit

  # 每周总结
  python3 learn.py weekly
"""
import json
import os
import sys
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).parent
MEMORY_DIR = BASE_DIR / "memory" / "interactions"
MEMORY_MD = BASE_DIR / "agent-config" / "MEMORY.md"
KNOWLEDGE_DIR = BASE_DIR / "agent-config" / "knowledge"
WISDOM_BRAIN = Path.home() / "wisdom-brain"
PENDING_DIR = BASE_DIR / "memory" / "pending_review"

LAST_DIGEST_FILE = BASE_DIR / "memory" / ".last_digest"

MEMORY_DIR.mkdir(parents=True, exist_ok=True)
PENDING_DIR.mkdir(parents=True, exist_ok=True)


def _today():
    return datetime.now().strftime("%Y-%m-%d")


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _load_config():
    """加载 Gemini API key"""
    import base64
    config_path = BASE_DIR / "skills" / "store-diagnosis" / "config.json"
    if config_path.exists():
        with open(config_path) as f:
            return json.load(f)
    gemini_ocr = BASE_DIR / "skills" / "store-diagnosis" / "gemini_ocr.py"
    if gemini_ocr.exists():
        content = gemini_ocr.read_text()
        m = re.search(r'_DEFAULT_CFG\s*=\s*"([^"]+)"', content)
        if m:
            return json.loads(base64.b64decode(m.group(1)).decode())
    return {}


def _get_gemini_key():
    cfg = _load_config()
    return os.environ.get('GEMINI_API_KEY') or cfg.get('gemini_api_key')


def _call_gemini(prompt, model='gemini-2.5-flash'):
    """调用 Gemini 分析"""
    from google import genai
    api_key = _get_gemini_key()
    if not api_key:
        print("无 Gemini API key，跳过分析", file=sys.stderr)
        return None
    client = genai.Client(api_key=api_key, http_options={'api_version': 'v1beta'})
    resp = client.models.generate_content(model=model, contents=[prompt])
    return resp.text.strip()


def _parse_json(text):
    """从 Gemini 返回中提取 JSON"""
    text = text.strip()
    if text.startswith('```'):
        lines = text.split('\n')
        json_lines = []
        inside = False
        for line in lines:
            if line.startswith('```') and not inside:
                inside = True; continue
            elif line.startswith('```') and inside:
                break
            elif inside:
                json_lines.append(line)
        text = '\n'.join(json_lines)
    return json.loads(text)


# ─────────────────────────────────
# 第一层：记录交互 → 存个人 memory
# ─────────────────────────────────

def log_interaction(category, content, operator=None):
    """记录一条交互经验到当天日志"""
    today = _today()
    log_file = MEMORY_DIR / f"{today}.md"

    entry = f"\n### [{_now()}] {category}\n"
    if operator:
        entry += f"运营: {operator}\n"
    entry += f"{content}\n"

    if not log_file.exists():
        log_file.write_text(f"# {today} 交互日志\n{entry}")
    else:
        with open(log_file, 'a') as f:
            f.write(entry)

    print(f"[记录] {category}: {content[:60]}", file=sys.stderr)

    # feedback 类型立即写入 MEMORY.md（运营纠正最重要，马上生效）
    if category == "feedback":
        _append_memory("我学到的规则", content)
        print(f"[即时] 规则已写入 MEMORY.md", file=sys.stderr)


def _append_memory(section, content):
    """往 MEMORY.md 的指定 section 追加一条"""
    text = MEMORY_MD.read_text()
    if content[:30] in text:
        return  # 避免重复

    marker = f"## {section}"
    if marker not in text:
        text += f"\n{marker}\n\n- {content}（{_today()}）\n"
        MEMORY_MD.write_text(text)
        return

    parts = text.split(marker, 1)
    rest = parts[1]
    next_section = rest.find("\n## ")
    if next_section == -1:
        new_text = parts[0] + marker + rest.rstrip() + f"\n- {content}（{_today()}）\n"
    else:
        before = rest[:next_section]
        after = rest[next_section:]
        new_text = parts[0] + marker + before.rstrip() + f"\n- {content}（{_today()}）\n" + after
    MEMORY_MD.write_text(new_text)


# ─────────────────────────────────
# 每日总结：提炼经验到 memory
# ─────────────────────────────────

def daily_digest():
    """读交互日志，提炼规律，更新个人 memory 和 knowledge。自动补账。"""

    # 确定需要覆盖的日期范围（从上次 digest 到今天）
    last_date = None
    if LAST_DIGEST_FILE.exists():
        last_date = LAST_DIGEST_FILE.read_text().strip()

    today = _today()
    recent_logs = []

    if last_date:
        # 从上次 digest 的第二天开始，到今天
        start = datetime.strptime(last_date, "%Y-%m-%d") + timedelta(days=1)
        end = datetime.now()
        current = start
        while current <= end:
            date = current.strftime("%Y-%m-%d")
            f = MEMORY_DIR / f"{date}.md"
            if f.exists():
                recent_logs.append(f.read_text())
            current += timedelta(days=1)
    else:
        # 第一次跑，读最近7天
        for i in range(7):
            date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            f = MEMORY_DIR / f"{date}.md"
            if f.exists():
                recent_logs.append(f.read_text())

    if not recent_logs:
        print("[digest] 无交互日志", file=sys.stderr)
        return

    all_logs = "\n---\n".join(recent_logs)
    memory_text = MEMORY_MD.read_text() if MEMORY_MD.exists() else ""
    rules_text = _read_if_exists(KNOWLEDGE_DIR / "rules.md")
    patterns_text = _read_if_exists(KNOWLEDGE_DIR / "patterns.md")
    operator_text = _read_if_exists(KNOWLEDGE_DIR / "operator-notes.md")

    prompt = f'''你是外卖运营AI助理的学习引擎。从交互日志中提炼经验。

## 最近交互日志
{all_logs}

## 已有记忆
{memory_text}

## 已有规则
{rules_text}

## 已有店铺规律
{patterns_text}

## 已有运营画像
{operator_text}

---

请返回 JSON，只包含**新发现的**（已有的不重复）：

{{
  "operator_habits": [
    {{"operator": "运营名", "habit": "具体习惯描述"}}
  ],
  "skill_patterns": [
    {{"pattern": "技能使用规律"}}
  ],
  "new_rules": [
    {{"rule": "规则内容", "source": "来源"}}
  ],
  "store_patterns": [
    {{"store": "店铺名", "pattern": "规律"}}
  ],
  "knowledge_candidates": [
    {{"topic": "主题", "content": "内容", "reason": "为什么值得变成集体认知"}}
  ]
}}

knowledge_candidates 是你觉得可能值得进入集体知识库的内容，但不是你来决定——你只是推荐，Seth会审。没有新发现就写空数组。只返回JSON。'''

    result_text = _call_gemini(prompt)
    if not result_text:
        return

    try:
        result = _parse_json(result_text)
    except json.JSONDecodeError:
        print(f"[digest] Gemini 返回非法 JSON", file=sys.stderr)
        return

    updated = []

    # 更新运营画像
    for h in result.get("operator_habits", []):
        _append_to_file(KNOWLEDGE_DIR / "operator-notes.md",
                        f"- **{h['operator']}**: {h['habit']}（{_today()}）")
        updated.append(f"运营画像: {h['operator']}")

    # 更新 skill 使用规律
    for p in result.get("skill_patterns", []):
        _append_memory("运营习惯", p["pattern"])
        updated.append(f"使用规律: {p['pattern'][:30]}")

    # 新规则
    for r in result.get("new_rules", []):
        _append_to_file(KNOWLEDGE_DIR / "rules.md",
                        f"- {r['rule']}（来源：{r['source']}，{_today()}）")
        _append_memory("我学到的规则", r["rule"])
        updated.append(f"新规则: {r['rule'][:30]}")

    # 店铺规律
    for s in result.get("store_patterns", []):
        _append_to_file(KNOWLEDGE_DIR / "patterns.md",
                        f"\n### {s['store']}\n- {s['pattern']}（{_today()}）")
        updated.append(f"店铺规律: {s['store']}")

    # 知识候选 → 放到 pending_review，等 Seth 审
    candidates = result.get("knowledge_candidates", [])
    if candidates:
        _save_pending(candidates)
        updated.append(f"待审知识: {len(candidates)}条")

    # 记录本次 digest 日期
    LAST_DIGEST_FILE.write_text(_today())

    if updated:
        print(f"[digest] 发现 {len(updated)} 条新经验:", file=sys.stderr)
        for u in updated:
            print(f"  ✅ {u}", file=sys.stderr)
    else:
        print(f"[digest] 暂无新发现", file=sys.stderr)

    return updated


def _read_if_exists(path):
    return path.read_text() if path.exists() else ""


def _append_to_file(path, content):
    """追加内容到文件，避免重复"""
    text = path.read_text() if path.exists() else ""
    if content[:30] in text:
        return
    with open(path, 'a') as f:
        f.write(f"\n{content}\n")


# ─────────────────────────────────
# 第二层：回传给 Seth 审阅
# ─────────────────────────────────

def _save_pending(candidates):
    """知识候选存到 pending_review，等 Seth 审并标记去向"""
    today = _today()
    pending_file = PENDING_DIR / f"{today}.md"

    content = ""
    if pending_file.exists():
        content = pending_file.read_text()
    else:
        content = f"""# {today} 待审经验

> Seth 审阅后标记去向：
> - `[B]` → brain（集体认知，写入 wisdom-brain，如"新店前3天不开推广"）
> - `[M]` → memory（集体经验，更新所有 agent 的 MEMORY 模板，如"发票通知不用看"）
> - `[x]` → 不回传（个人的，或不够通用）

"""

    for k in candidates:
        entry = f"### [ ] {k['topic']}\n{k['content']}\n推荐理由: {k['reason']}\n\n"
        if k['topic'] not in content:
            content += entry

    pending_file.write_text(content)
    print(f"[待审] {len(candidates)} 条候选写入 {pending_file.name}", file=sys.stderr)


def submit_for_review():
    """把积累的经验打包提交，push 到 git 让 Seth 看"""

    # 收集所有 pending
    pending_files = sorted(PENDING_DIR.glob("*.md"))
    if not pending_files:
        # 没有 pending，那就直接把 memory 和 knowledge 回传
        print("[submit] 无待审内容，提交当前 memory 和 knowledge 快照", file=sys.stderr)

    # 生成汇总
    summary_file = PENDING_DIR / "SUMMARY.md"
    summary = f"# 经验回传汇总（{_today()}）\n\n"

    # memory 快照
    summary += "## 当前运营记忆\n\n"
    summary += MEMORY_MD.read_text() if MEMORY_MD.exists() else "（空）"
    summary += "\n\n---\n\n"

    # knowledge 快照
    for f in sorted(KNOWLEDGE_DIR.glob("*.md")):
        if f.name == "README.md":
            continue
        summary += f"## {f.stem}\n\n"
        summary += f.read_text()
        summary += "\n\n---\n\n"

    # pending 待审
    if pending_files:
        summary += "## 待审经验（请标记 ✅/❌）\n\n"
        for pf in pending_files:
            if pf.name == "SUMMARY.md":
                continue
            summary += pf.read_text()
            summary += "\n---\n"

    summary_file.write_text(summary)
    print(f"[submit] 汇总写入 {summary_file}", file=sys.stderr)

    # push 到专属分支
    import getpass
    user = getpass.getuser()
    branch = f"memory/{user}/{_today()}"
    try:
        subprocess.run(["git", "add", "memory/", "agent-config/MEMORY.md",
                        "agent-config/knowledge/"],
                       cwd=str(BASE_DIR), capture_output=True, timeout=5)
        subprocess.run(["git", "commit", "-m", f"memory: {_today()} 经验回传"],
                       cwd=str(BASE_DIR), capture_output=True, timeout=5)
        subprocess.run(["git", "push", "origin", f"HEAD:{branch}"],
                       cwd=str(BASE_DIR), capture_output=True, timeout=15)
        print(f"[submit] 已 push 到 {branch}", file=sys.stderr)
        print(f"\n📋 Seth，请查看分支 {branch} 的 memory/pending_review/SUMMARY.md", file=sys.stderr)
    except Exception as e:
        print(f"[submit] push 失败: {e}", file=sys.stderr)
        print(f"本地汇总在: {summary_file}", file=sys.stderr)


# ─────────────────────────────────
# Seth 审阅后：approved → brain
# ─────────────────────────────────

def approve(pending_file=None):
    """
    Seth 审完后执行。按标记分流：
    [B] → brain（wisdom-brain 集体认知）
    [M] → memory（更新所有 agent 的 MEMORY 模板）
    [x] → 跳过
    """
    if pending_file:
        files = [Path(pending_file)]
    else:
        files = sorted(PENDING_DIR.glob("*.md"))

    to_brain = []
    to_memory = []

    for f in files:
        if f.name == "SUMMARY.md":
            continue
        content = f.read_text()
        sections = re.split(r'### \[', content)
        for section in sections:
            if not section.strip():
                continue
            # 提取标记和内容
            lines = section.split('\n')
            first_line = lines[0]
            body = '\n'.join(lines[1:]).strip()
            # 去掉 "推荐理由:" 行，只保留核心内容
            body_lines = [l for l in body.split('\n') if not l.startswith('推荐理由:')]
            clean_body = '\n'.join(body_lines).strip()

            if first_line.startswith('B]') or first_line.startswith('b]'):
                topic = first_line.split(']', 1)[1].strip()
                if topic and clean_body:
                    to_brain.append({"topic": topic, "content": clean_body})

            elif first_line.startswith('M]') or first_line.startswith('m]'):
                topic = first_line.split(']', 1)[1].strip()
                if topic and clean_body:
                    to_memory.append({"topic": topic, "content": clean_body})

    # [B] → wisdom-brain
    if to_brain:
        notes_dir = WISDOM_BRAIN / "knowledge-notes"
        notes_dir.mkdir(parents=True, exist_ok=True)
        notes_file = notes_dir / f"{_today()}-approved.md"

        content = f"# {_today()} 审核通过的运营认知\n\n"
        for a in to_brain:
            content += f"## {a['topic']}\n{a['content']}\n\n"
        notes_file.write_text(content)
        print(f"[approve] {len(to_brain)} 条 → brain (wisdom-brain)", file=sys.stderr)

        try:
            subprocess.run(["git", "add", "-A"], cwd=str(WISDOM_BRAIN),
                           capture_output=True, timeout=5)
            subprocess.run(["git", "commit", "-m",
                            f"brain: {_today()} +{len(to_brain)} 条认知"],
                           cwd=str(WISDOM_BRAIN), capture_output=True, timeout=5)
            subprocess.run(["git", "push"], cwd=str(WISDOM_BRAIN),
                           capture_output=True, timeout=10)
        except:
            print(f"[approve] wisdom-brain push 失败", file=sys.stderr)

    # [M] → memory 模板（更新到 knowledge/rules.md，所有 agent git pull 后生效）
    if to_memory:
        rules_file = KNOWLEDGE_DIR / "rules.md"
        rules_text = rules_file.read_text() if rules_file.exists() else "# 运营规则\n"
        for m in to_memory:
            line = f"- {m['content']}（{_today()}）"
            if m['content'][:20] not in rules_text:
                rules_text += f"\n{line}\n"
        rules_file.write_text(rules_text)
        print(f"[approve] {len(to_memory)} 条 → memory (knowledge/rules.md)", file=sys.stderr)

        # push store-monitor 让所有 agent 拿到
        try:
            subprocess.run(["git", "add", "agent-config/knowledge/"],
                           cwd=str(BASE_DIR), capture_output=True, timeout=5)
            subprocess.run(["git", "commit", "-m",
                            f"rules: {_today()} +{len(to_memory)} 条经验"],
                           cwd=str(BASE_DIR), capture_output=True, timeout=5)
            subprocess.run(["git", "push"], cwd=str(BASE_DIR),
                           capture_output=True, timeout=10)
        except:
            print(f"[approve] store-monitor push 失败", file=sys.stderr)

    total = len(to_brain) + len(to_memory)
    if total:
        print(f"\n✅ 共处理 {total} 条（{len(to_brain)} 进 brain，{len(to_memory)} 进 memory）", file=sys.stderr)
    else:
        print("[approve] 没有标记 [B] 或 [M] 的内容", file=sys.stderr)


# ─────────────────────────────────
# 每周总结
# ─────────────────────────────────

def weekly_summary():
    """每周生成总结"""
    now = datetime.now()
    week_num = now.isocalendar()[1]
    year = now.year
    filename = f"{year}-W{week_num:02d}.md"

    weekly_dir = KNOWLEDGE_DIR / "weekly"
    weekly_dir.mkdir(parents=True, exist_ok=True)

    # 读过去7天日志
    logs = []
    for i in range(7):
        date = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        f = MEMORY_DIR / f"{date}.md"
        if f.exists():
            logs.append(f.read_text())

    if not logs:
        print("[weekly] 本周无交互日志", file=sys.stderr)
        return

    all_logs = "\n---\n".join(logs)
    memory_text = _read_if_exists(MEMORY_MD)

    prompt = f'''你是外卖运营AI助理的学习引擎。写一份本周总结。

## 本周交互日志
{all_logs}

## 当前记忆
{memory_text}

用以下格式（中文、简洁）：

# {year}年第{week_num}周 运营认知总结

## 本周工作量
- 交互次数、涉及的运营和品牌

## 运营怎么用 skill 的
- 各运营的使用习惯和偏好

## 本周学到的
- 新的运营认知/规律/经验

## 认知变化
- 哪些理解被修正了

## 推荐进入集体知识库的
- 哪些经验值得让所有 agent 共享（附理由）

## 待深入的问题
- 还没想清楚的

直接输出 markdown。'''

    result = _call_gemini(prompt)
    if result:
        weekly_file = weekly_dir / filename
        weekly_file.write_text(result)
        print(f"[weekly] 写入 {weekly_file}", file=sys.stderr)

        # 周总结也放进 pending_review 让 Seth 看
        pending = PENDING_DIR / f"weekly-{filename}"
        pending.write_text(f"# 周总结待审\n\n{result}")


# ─── CLI ───

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "digest":
        daily_digest()
    elif cmd == "weekly":
        weekly_summary()
    elif cmd == "submit":
        submit_for_review()
    elif cmd == "approve":
        f = sys.argv[2] if len(sys.argv) > 2 else None
        approve(f)
    elif cmd in ("usage", "feedback", "knowledge"):
        if len(sys.argv) < 3:
            print(f"用法: python3 learn.py {cmd} \"内容\"", file=sys.stderr)
            sys.exit(1)
        content = sys.argv[2]
        operator = sys.argv[3] if len(sys.argv) > 3 else None
        log_interaction(cmd, content, operator)
    else:
        print(f"未知命令: {cmd}", file=sys.stderr)
        print("可用: usage / feedback / knowledge / digest / submit / approve / weekly")
        sys.exit(1)


if __name__ == '__main__':
    main()
