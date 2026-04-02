# HEARTBEAT.md — 你的日常工作习惯

## 每天 17:30（下班总结）

收工前做一件事：回顾今天（和之前欠的）。

1. 看 `memory/interactions/` 和 `memory/.last_digest`，有没有**上次回顾之后**新的交互
2. 没有 → 不用做
3. 有 → 跑 `python3 learn.py digest`：
   - 提炼经验，更新 MEMORY.md 和 knowledge/
   - 有值得汇报的 → `python3 learn.py submit` 提交给 Seth

**补账：** 如果之前几天都没做过回顾，一次性把欠的都补上。看 `memory/.last_digest` 的日期，中间漏的天都要覆盖到。

### 每周一 17:30（额外）

除了日常回顾，多做一件事：

```bash
python3 learn.py weekly
```

生成周总结，放到 pending_review 让 Seth 看。

## 怎么判断"有没有交互"

```bash
ls memory/interactions/       # 有日志文件吗
cat memory/.last_digest       # 上次总结是哪天
```

没有新日志 = 没有交互 = 不用做。

## 你日常记录的时机

heartbeat 只管定期回顾。**日常记录靠你在交互中随手做：**

```bash
cd ~/.qclaw/workspace/store-monitor

# 运营安排了 skill
python3 learn.py usage "运营A要求每天10点巡检港翠+禾"

# 运营纠正了你
python3 learn.py feedback "运营说推广余额提前2天提醒"

# 运营教了你知识
python3 learn.py knowledge "新店前3天不开推广"
```

## 经验流转

```
你和运营交互 → learn.py 记录 → 个人 memory
                                    ↓
                          17:30 digest 提炼
                                    ↓
                    有价值的 → submit 回传 Seth
                                    ↓
                    Seth 标记 [B] → brain（集体认知）
                    Seth 标记 [M] → memory（集体经验）
```
