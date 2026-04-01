# HEARTBEAT.md

## 每次heartbeat做这些事

### 1. 经验回顾（每天）

读今天的 `memory/YYYY-MM-DD.md`，问自己：

- 今天巡检发现了什么？有没有反复出现的问题？
- 运营纠正过我什么？
- 有没有店铺变化？
- 预警有没有在正常工作？

**把规律写进 MEMORY.md。** 提炼，不是复制。

### 2. 知识库更新（每天）

读 `knowledge/rules.md`，确保自己在遵守最新的规则。

有新发现时更新：
- 店铺规律 → 写入 `knowledge/patterns.md`
- 运营画像 → 写入 `knowledge/operator-notes.md`
- 运营提到的新需求 → 写入 `knowledge/skill-ideas.md`

### 3. 周总结（每周一）

每周一的heartbeat，写一份工作总结到 `knowledge/weekly/YYYY-WXX.md`，自己整理本周的运营认知成长：

```markdown
# YYYY年第XX周 运营认知总结

## 本周工作量
- 巡检次数、覆盖品牌
- 预警轮次、发现问题数

## 本周学到的
- （新的运营认知/规律/经验）

## 认知变化
- （哪些理解被修正了，之前以为X其实是Y）

## 待深入的问题
- （还没想清楚的、需要继续验证的）
```

### 4. 自检

- 定时任务还在正常跑吗？（`cron` list）
- 有没有连续失败的？
- Chrome调试端口活着吗？
