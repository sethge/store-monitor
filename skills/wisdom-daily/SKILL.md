---
name: wisdom-daily
description: "运营知识日报汇总。读取今天的日志，生成结构化日报，push到wisdom-brain仓库供Seth审阅。触发词：日报、今日学习、知识汇总。也可由cron每天21:00自动触发。"
---

# 运营知识日报

## 执行步骤

### 1. 读取今天的日志

```bash
cat wisdom-brain/knowledge-notes/$(date +%Y-%m-%d).md 2>/dev/null
```

如果没有日志，说明今天没有运营知识讨论，跳过。

### 2. 生成日报

读取日志内容，汇总成结构化日报，写入：
```
wisdom-brain/knowledge-digest/$(date +%Y-%m-%d)-日报.md
```

日报格式：
```markdown
# 运营知识日报 YYYY-MM-DD

## 今日收获
- 条目1...
- 条目2...

## 被纠正的认知
（如有）原来的理解 → 运营纠正后的理解

## 新发现的经验
（如有）具体经验和适用场景

## 待确认的问题
（如有）需要进一步验证的问题

## 建议更新知识库
（如有）哪些内容应该更新到认知框架或知识提炼中
```

### 3. 推送到仓库

```bash
cd wisdom-brain && git add -A && git commit -m "日报 $(date +%Y-%m-%d)" && git push
```

这样Seth那边 git pull 就能看到今天所有运营的学习记录。
