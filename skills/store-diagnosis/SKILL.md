---
name: store-diagnosis
description: "外卖竞对数据采集。运营发视频，一键提帧+OCR+解析+生成公网链接。触发词：诊断、分析视频、竞对分析、分析这个店。"
setup: "bash skills/store-diagnosis/setup.sh"
---

# 竞对数据采集

## 你只需要跑一条命令

```bash
python3 skills/store-diagnosis/run_diagnosis.py 视频1.mp4 视频2.mp4 ...
```

这条命令自动完成全部流程：提帧 → OCR识别 → 解析数据 → 生成公网链接。

**stdout输出的就是链接，把链接发给运营即可。**

## 发链接给运营

```
数据提完了，打开这个链接查看竞对报告：
<链接>

• 数据可以直接点击修改
• 底部分析区需要填写
• 输入你的店铺名，点下载导出Excel
```

## 报错处理

任何报错先跑：`bash skills/store-diagnosis/setup.sh`

## 红线

1. **只跑 run_diagnosis.py 这一条命令。** 不要自己生成Excel，不要自己编表格。
2. **最终产出是一个链接。** 不是文件，不是文本总结。
3. **环境问题跑 setup.sh。** 不甩给运营。
