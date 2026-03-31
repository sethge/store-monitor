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

### 3. 周报（每周一）

每周一的heartbeat，写一份周报到 `knowledge/weekly/YYYY-WXX.md`，给Seth看：

```markdown
# YYYY年第XX周 运营助理周报

## 本周概况
- 跑了几次巡检，覆盖几个品牌
- 预警跑了多少轮，发现几个问题
- 几个运营在用

## 发现的规律
- （本周新发现的店铺规律）

## 运营反馈
- （运营说了什么有价值的反馈）

## 问题和建议
- （我觉得哪里可以改进）
- （运营可能需要什么新功能）
```

### 4. 自检

- 定时任务还在正常跑吗？（`cron` list）
- 有没有连续失败的？
- Chrome调试端口活着吗？
