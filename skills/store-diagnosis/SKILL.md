---
name: store-diagnosis
description: "外卖竞对数据采集+网页报告闭环。运营发送竞对店铺录屏视频，自动提帧读图提取结构化数据，生成公网链接（GitHub Pages），运营在网页上填写分析后下载Excel。触发词：诊断、分析视频、提取菜单、店铺分析、数据整理、分析这个店、竞对分析。"
setup: "bash skills/store-diagnosis/setup.sh"
---

# 竞对数据采集

视频 → 提帧 → 读图 → JSON → 公网链接 → 运营填分析下载Excel。

**重要：你必须走完全部步骤直到生成链接发给运营。不能只输出文本总结就停下来。**

## 执行步骤（必须全部完成）

### Step 1: 提帧

```bash
python3 skills/store-diagnosis/extract_frames.py 视频1.mp4 视频2.mp4 ...
```

拿到每个视频的采样帧路径列表。

### Step 2: 读图

用 read_images.py 把采样帧转成 base64：

```bash
python3 skills/store-diagnosis/read_images.py /tmp/store_xxx/scene_001.jpg /tmp/store_xxx/scene_006.jpg ...
```

拿到 base64 后，作为图片内容读取，从中提取数据。

### Step 3: 组装JSON

**这一步是关键。** 你必须把读图提取的数据组装成以下**严格JSON格式**，不是文本总结：

```json
[
  {
    "店铺名称": "XX麻辣烫",
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

规则：
- 热销菜取月销Top10，去掉蘸料/小料/饮料/米饭/配菜/单点不送
- 满减力度 = 减免额 ÷ 门槛（如30减5 → 5÷30=0.167）
- 折扣力度 = 有划线价时为 折扣价÷原价，没有则为0
- 看不到的字段写 "未获取"
- 多个视频就是数组里多个对象

### Step 4: 生成链接

把上一步的JSON保存到临时文件，然后运行 deploy.py：

```bash
echo '<你组装的JSON>' > /tmp/competitor_data.json
python3 skills/store-diagnosis/deploy.py --data /tmp/competitor_data.json
```

会输出一个公网链接，类似：`https://sethge.github.io/store-monitor/#NobwRI6X...`

### Step 5: 发链接给运营

**必须走到这一步。** 把链接发给运营：

```
数据提完了，打开这个链接查看竞对报告：
<链接>

打开后：
• 数据区可以直接点击修改（爬错的改一下）
• 底部分析区需要你填写（结论/调整措施/目的）
• 输入你的店铺名，点下载按钮导出Excel
```

---

## 常见问题

**Q: sandbox限制读不了图片？**
用 read_images.py 转 base64 绕过。

**Q: deploy.py 报错缺 lzstring？**
运行 `bash skills/store-diagnosis/setup.sh` 自动安装。

**Q: 任何环境报错？**
运行 `bash skills/store-diagnosis/setup.sh`，不让运营自己查。

---

## 工具列表

| 文件 | 功能 |
|------|------|
| extract_frames.py | 视频提帧+采样 |
| read_images.py | 图片转base64（绕过sandbox） |
| deploy.py | JSON → 公网链接 |
| write_excel.py | JSON → Excel（备用） |
| save_reference.py | 参考店铺库 |
| setup.sh | 环境自动安装 |
| web/index.html | 网页报告模板 |

## 红线

1. **必须走完Step 1-5。** 不能只输出文本总结就停。最终产出是一个公网链接。
2. **数据必须是JSON格式。** 不是markdown，不是文本总结，是严格的JSON。
3. **环境问题自动修。** 跑 setup.sh，不甩给运营。
