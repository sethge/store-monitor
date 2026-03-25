# 盯店监控

美团+饿了么外卖店铺自动巡检工具。通过悟空插件切换店铺，自动检查差评、活动到期、推广余额、重要通知。

## 快速开始

```bash
# 指定品牌
NO_PROXY=localhost python3 run_fast.py "品牌1" "品牌2"

# 全量巡检（插件下所有品牌）
NO_PROXY=localhost python3 run_all_fast.py
```

## 环境要求
- Python 3 + Playwright (`pip3 install playwright && playwright install chromium`)
- Chrome调试模式 (`--remote-debugging-port=9222`)
- 悟空插件（goku文件夹）+ 食亨账号登录

## Skill
输入 `/盯店` 自动执行巡检
