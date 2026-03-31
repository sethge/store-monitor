# 食亨智慧运营

美团+饿了么外卖店铺自动巡检工具。通过悟空插件切换店铺，自动检查差评、活动到期、推广余额、重要通知。

## 架构

本项目提供3个独立Skill + 1个调度Skill，均在 `~/.qclaw/skills/` 下：

| Skill | 功能 | 触发词 |
|-------|------|--------|
| store-patrol | 一次性全量巡检 | 巡检、盯店、检查店铺 |
| store-alert | 单轮预警检查（cron驱动） | 预警、盯着、监控 |
| store-diagnosis | 视频数据采集 | 诊断、分析视频 |
| ops-scheduler | 自然语言→cron定时任务 | 每天X点、每N分钟、安排 |

## 核心脚本

```bash
# 巡检（一次性）
NO_PROXY=localhost python3 run_fast.py "品牌1" "品牌2"
NO_PROXY=localhost python3 run_all_fast.py

# 预警（单轮，供cron调度）
NO_PROXY=localhost python3 run_fast.py --watch-once "品牌1" "品牌2"

# 预警（持续循环，本地调试用）
NO_PROXY=localhost python3 run_fast.py --watch "品牌1" "品牌2"
```

## 环境要求
- Python 3 + Playwright (`pip3 install playwright && playwright install chromium`)
- Chrome调试模式 (`--remote-debugging-port=9222`)
- 悟空插件（goku文件夹）+ 食亨账号登录
