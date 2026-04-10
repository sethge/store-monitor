---
name: backend-diagnosis
description: "通过悟空插件登录店铺后台，读数据做诊断分析。触发词：诊断XX店、看看XX数据、XX店怎么样、帮我分析XX"
---

# 店铺后台诊断

通过悟空插件搜索品牌 → 登录后台 → 读数据 → 分析 → 给建议。

## 第一步：连浏览器，找悟空插件

```python
from plugin_helper import get_ext, pick_brand, get_stores, click_store_platform
```

浏览器没开就引导："双击桌面上的盯店巡检打开"。

## 第二步：搜索品牌（重要！）

**插件的品牌列表默认只显示前10个，但可以搜索。必须用 `pick_brand()` 搜索，不要自己数列表。**

```python
# 用户说"金原鸭血粉丝（西关大润发）"
ok, status = await pick_brand(ext, "金原鸭血粉丝（西关大润发）")
# pick_brand 会自动在下拉框里输入"金原鸭血粉丝"搜索
# 括号里的内容用来精确匹配（区分同品牌不同店）
```

如果返回 `ok=False`：
- "插件未就绪" → 引导运营登录食亨
- "品牌未找到" → 确认品牌名是否正确，让运营看看插件里有没有

## 第三步：获取店铺列表，登录后台

```python
stores = await get_stores(ext)
# 返回 {店铺名: [{platform, account, action}]}

# 登录指定平台
result = await click_store_platform(ext, account)
```

## 第四步：读后台数据

**⚠️ 不要新开页面！美团和饿了么后台都是侧边栏导航的单页应用。**

登录后只有一个后台页面，所有数据都在这个页面里通过左侧菜单切换：
- 经营分析 → 经营数据 / 店铺分
- 顾客管理
- 商品管理
- 活动中心
- 门店推广

**在同一个页面里点侧边栏切换，不要goto新URL，不要new_page。**

美团后台结构：
- frame0 = 外壳（含侧边栏菜单）
- frame1 = 内容区（点击侧边栏后这里的内容会变）
- 点侧边栏菜单项 → frame1自动加载对应内容 → 读frame1的数据

```python
# 在frame0里点击侧边栏
await frame0.evaluate("""(text) => {
    const all = Array.from(document.querySelectorAll('*'));
    for(const el of all) {
        if(el.children.length < 3 && el.textContent.trim() === text) {
            el.click(); return;
        }
    }
}""", "经营分析")
await asyncio.sleep(2)
# 然后读frame1的内容
```

按外卖公式的每个变量读数据：

**基础指标：** 评分、月售
**新客链路：** 曝光量、进店率、下单率、新客数
**老客链路：** 存量客户、复购率、复购频次、老客数
**客单价**
**菜单结构 + 满减 + 活动 + 推广状态**
**商品销量TOP + 差评**

新客和老客的数据要分开看。

## 第五步：分析诊断

按BRAIN.md的框架分析：

1. **卖对的东西了吗？** — 卖什么/不卖什么/卖给谁/什么场景
2. **把东西卖对了吗？** — 按公式找漏点，哪个变量最拉垮

先说明显错误，再说最大问题，最后给具体建议。

## 红线

1. **品牌搜索必须用 pick_brand()，不要自己读列表。** 列表只显示前10个，搜索才能找到所有品牌。
2. **新老客数据分开看。** 不要混在一起分析。
3. **缺基线数据就问运营。** 不要自己瞎估。
