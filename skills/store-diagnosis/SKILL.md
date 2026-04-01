---
name: store-diagnosis
description: "外卖竞对数据采集。运营发视频，自动提帧读图，生成公网链接让运营填分析下载Excel。触发词：诊断、分析视频、竞对分析、分析这个店。"
setup: "bash skills/store-diagnosis/setup.sh"
---

# 竞对数据采集

## ⚠️ 你只需要做两件事

**第一步：提帧+读图**

先提帧：
```bash
python3 skills/store-diagnosis/extract_frames.py 视频1.mp4 视频2.mp4
```
输出采样帧路径（如 `/tmp/store_xxx/scene_001.jpg`）。

然后用OCR读取图片文字：
```bash
python3 skills/store-diagnosis/ocr_images.py /tmp/store_xxx/scene_001.jpg /tmp/store_xxx/scene_006.jpg /tmp/store_xxx/scene_011.jpg ...
```

输出JSON，每张图的OCR文字按从上到下排序。你根据OCR文字内容分析提取竞对数据。

如果你的模型支持直接读图片（`read` 工具），也可以用 `read` 直接看图，效果更好。OCR是备选方案。

读完后，组装成JSON写入 `/tmp/competitor_data.json`。

**第二步：生成链接**
```bash
python3 skills/store-diagnosis/run_diagnosis.py link /tmp/competitor_data.json
```
输出公网链接，发给运营。

**完事。不要自己生成Excel，不要自己编表格，不要输出文本总结就停。最终产出是一个链接。**

---

## JSON格式（写入 /tmp/competitor_data.json）

```json
[
  {
    "店铺名称": "XX麻辣烫(XX店)",
    "平台": "美团",
    "店铺评分": 4.8,
    "营业时间": "10:00-22:00",
    "月销": "3000+",
    "实际配送费": "0元",
    "配送方式": "美团快送",
    "评价数": 1200,
    "差评数": 15,
    "差评率": 0.0125,
    "满减档位": "30-5，50-10，80-18",
    "满减档位数": 3,
    "第一档满减力度": 0.167,
    "第二档满减力度": 0.2,
    "其他活动": "折扣商品5折起; 新人立减12",
    "热销菜": [
      {"名称": "招牌麻辣烫", "月销": "800+", "实际价格": 25.8, "折扣力度": 0},
      {"名称": "冒菜套餐", "月销": "500+", "实际价格": 22.8, "折扣力度": 0.7}
    ]
  }
]
```

**规则：**
- 热销菜取月销Top10，去掉蘸料/小料/饮料/米饭/配菜/单点不送
- 满减力度 = 减免额 ÷ 门槛（如30减5 → 0.167）
- 折扣力度 = 有划线价时 折扣价÷原价，没有则为0
- 看不到的字段写 "未获取"
- 多个视频 = JSON数组里多个对象

---

## 发链接给运营

```
数据提完了，打开这个链接查看竞对报告：
<链接>

• 数据可以直接点击修改
• 底部分析区需要填写
• 输入你的店铺名，点下载导出Excel
```

---

## 报错处理

任何报错先跑：`bash skills/store-diagnosis/setup.sh`

不要让运营自己查，帮他装好。
