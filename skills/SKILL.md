---
name: store-patrol
description: "外卖店铺巡检。一次性检查店铺的差评、活动到期、推广余额、重要通知。触发词：巡检、盯店、检查店铺、体检、跑一下、看看店。当用户想了解店铺当前状况时使用。"
---

# 店铺巡检

一次性检查美团+饿了么店铺，只报有问题的。

## 怎么跟用户沟通

**先说理解，确认后执行。**

### 用户说"巡检"

每个运营的插件账号下只有自己的店，"全部"就是跑他所有的店：
```
你: 全部跑一遍？
用户: 嗯
你: 好，跑着了。
```

指定品牌也行：
```
你: 好，跑港翠。
```

### 跑完之后

**逐行读脚本输出**，注意：
- "验证拦截"/"授权失败" → **必须说**
- "中差评" → 几条、说什么
- "推广余额" → 撑几天
- "活动到期" → 哪几个
- "运营正常" → 一句话

说完重点，**主动推进**：
```
港翠有2条差评都说等太久，推广快没了。其他正常。
推广要不要提醒充值？港翠要不要我持续盯着？
```

```
都正常。要不要我每天早上自动跑一遍？
```

### 店铺变化感知（关键！）

**每次跑完，对比你记住的上次品牌/店铺列表：**

- 多了新店 → "你多了一家XX店，以后巡检也跑上？"
- 少了店 → "XX店这次没了，是关了还是授权掉了？"
- 授权过期 → "XX店授权失败了，需要重新授权。"
- 连续几天同一个问题 → "港翠连续3天推广不足，是不是忘充了？"

**把变化记到memory里，下次对比用。**

## 前置条件

静默检查：
1. Chrome调试端口：`curl --noproxy localhost -s http://localhost:9222/json/version`
   - 失败 → `"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --remote-debugging-port=9222 --user-data-dir="/Users/seth/Library/Application Support/Chrome-Debug" --proxy-server="direct://" &`
2. Python依赖：`python3 -c "import playwright"`

## 执行

<skill_exec>

- 命令: NO_PROXY=localhost python3 run_all_fast.py
- 工作目录: /Users/seth/.qclaw/workspace/store-monitor
- 描述: 全量巡检

</skill_exec>

<skill_exec>

- 命令: NO_PROXY=localhost python3 run_fast.py {brands}
- 工作目录: /Users/seth/.qclaw/workspace/store-monitor
- 描述: 指定品牌，{brands} 用引号包裹

</skill_exec>
