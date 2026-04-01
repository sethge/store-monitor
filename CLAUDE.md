# 盯店监控

美团+饿了么外卖店铺自动巡检工具。通过悟空插件切换店铺，自动检查差评、活动到期、推广余额、重要通知。

## 快速开始

```bash
# 指定品牌（跑一次）
NO_PROXY=localhost python3 run_fast.py "品牌1" "品牌2"

# 全量巡检（插件下所有品牌）
NO_PROXY=localhost python3 run_all_fast.py

# 预警模式（只看通知，每10分钟一轮，到18:00结束）
NO_PROXY=localhost python3 run_fast.py --watch "品牌1" "品牌2"
```

## 环境要求
- Python 3 + Playwright (`pip3 install playwright && playwright install chromium`)
- Chrome调试模式 (`--remote-debugging-port=9222`)
- 悟空插件（goku文件夹）+ 食亨账号登录

## Skill
输入 `/盯店` 自动执行，支持三种模式：
- **巡检** — `/盯店` 或 `/盯店 品牌名`，跑一次全量检查
- **预警** — `/盯店 预警`，只看通知，每10分钟一轮，到18:00结束
- **诊断** — `/盯店 诊断 视频路径`，视频提帧→Agent读图提取JSON→deploy.py生成公网链接（GitHub Pages）→运营在网页填分析+下载Excel
