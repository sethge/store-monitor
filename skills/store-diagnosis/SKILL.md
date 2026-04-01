---
name: store-diagnosis
description: "外卖竞对数据采集+网页报告闭环。运营发送竞对店铺录屏视频，自动提帧读图提取结构化数据，生成公网链接（GitHub Pages），运营在网页上填写分析后下载Excel。触发词：诊断、分析视频、提取菜单、店铺分析、数据整理、分析这个店、竞对分析。"
setup: "bash skills/store-diagnosis/setup.sh"
---

# 竞对数据采集 + 网页报告闭环

视频 → 提帧读图 → 结构化JSON → 公网链接 → **运营在网页填分析+下载Excel**。

核心原则：**网页是闸门——数据区可编辑，分析区必须填，未填完会高亮提示。**

## 环境要求

首次使用运行：`bash skills/store-diagnosis/setup.sh`

需要：ffmpeg（提帧）+ xlsxwriter（备用Excel）。安装脚本会自动检测和安装。

---

## Phase 1: 数据采集（自动，不用问运营）

收到视频后直接开干：
```
收到，我来提取数据。
```

**Step 1** — 提帧：
```bash
python3 skills/store-diagnosis/extract_frames.py 视频1.mp4 视频2.mp4 ...
```

**Step 2** — Agent自己看sampled里的图片，提取结构化JSON。

提取规则：
- 基础：店铺名称、平台、评分、营业时间、月销
- 配送：配送费、配送方式
- 评价：评价数、差评数、差评率
- 满减：每档金额、档数、第一/二档力度（减免额÷门槛）
- 活动：折扣/新客/收藏/神券等
- 热销菜Top10：去掉蘸料/小料/饮料/米饭/配菜/单点不送。记录名称/月销/价格/折扣力度
- 看不到的字段写"未获取"

---

## Phase 2: 生成公网链接

Agent运行deploy.py，把提取的JSON数据编码到URL hash中，通过GitHub Pages生成公网链接：

```bash
python3 skills/store-diagnosis/deploy.py --data '<完整JSON>'
```

输出一个公网链接，运营打开即可看到Excel格式的竞对报告表格。

---

## Phase 3: 发链接给运营

Agent把链接发给运营：

```
数据提完了，打开这个链接查看竞对报告：
<公网链接>

打开后你会看到Excel格式的表格：
• 数据区全部可编辑——如果爬错了直接改
• 底部分析区（结论/调整措施/目的）需要你填写
• 填完后输入你的店铺名，点下载按钮即可导出Excel
• 没填完点下载会高亮提示哪里没填，再点一次可强制下载

填完下载Excel就行。
```

不需要在聊天里收集分析，网页是闸门。

---

## Phase 4: 运营下载Excel

运营在网页上完成操作：
- 检查/修正数据区
- 填写分析区（结论/调整措施/目的）
- 输入店铺名 → 按钮实时同步显示"下载 XX竞对分析.xlsx"
- 未填完点下载 → 高亮提示哪里没填，再点一次可强制下载
- 点下载 → 浏览器端ExcelJS生成带完整样式的xlsx（橙色FFC000表头、thin边框、合并单元格）

---

## 沟通规则

1. **收到视频直接开干**，不要问确认
2. **生成链接后发给运营**，告诉他"打开填分析，填完下载Excel"
3. **不需要在聊天里收集分析**，网页是闸门

---

## 工具列表

| 文件 | 功能 |
|------|------|
| extract_frames.py | 视频提帧+采样，输出JSON到stdout |
| deploy.py | 竞对数据JSON → 生成公网链接 |
| web/index.html | 网页版竞对报告（GitHub Pages托管） |
| write_excel.py | 服务端Excel生成（备用，Agent本地用） |
| save_reference.py | 参考店铺库管理 |
| setup.sh | 环境安装（ffmpeg+xlsxwriter+lzstring） |

## 参考店铺库

位置：`knowledge/reference_stores.json`

查询：
```bash
python3 skills/store-diagnosis/save_reference.py --list              # 全部
python3 skills/store-diagnosis/save_reference.py --list --category 轻食  # 按品类
```

Agent可以在其他场景查库，比如运营问"帮我看看轻食品类的参考店铺"。

---

## 红线

1. **Phase 1-2自动执行。** 收到视频不问确认，直接提帧→读图→生成链接。
2. **不能替运营写结论。** 网页上的分析区由运营自己填写。
3. **数据提取要严谨。** 热销菜去掉蘸料/小料等，满减逐档算力度，看不到写"未获取"。
4. **参考库必须有理由。** 不能无脑存，运营说了为什么才存。
