# knowledge/ — 集体智慧库

这里是agent经验回传、Seth提炼、再反哺回agent的闭环。

## 目录结构

```
knowledge/
├── README.md          ← 你在看的这个
├── weekly/            ← agent每周自动写的周报（给Seth看）
│   └── 2026-W14.md
├── patterns.md        ← 店铺规律（哪家店容易出什么问题）
├── operator-notes.md  ← 运营画像（每个运营关心什么、习惯什么）
├── rules.md           ← 从经验中沉淀的规则（Seth审核后生效）
└── skill-ideas.md     ← 待开发的skill想法（从运营需求中来）
```

## 数据流

```
运营跟agent对话
    ↓
agent记日志（memory/日期.md）
    ↓
agent每天heartbeat提炼经验（MEMORY.md）
    ↓
agent每周汇总成周报（knowledge/weekly/）
    ↓
Seth审阅周报
    ↓
有价值的 → 写入 patterns.md / rules.md
新需求 → 写入 skill-ideas.md
    ↓
rules.md 被agent读取，行为更新
skill-ideas.md 积累到一定程度 → 开发新skill
```

## Seth怎么用

1. 每周看一眼 `knowledge/weekly/` 最新的周报
2. 有价值的经验提炼到 `patterns.md` 或 `rules.md`
3. 运营提到的新需求记到 `skill-ideas.md`
4. `rules.md` 里的规则agent会自动读取并遵守
