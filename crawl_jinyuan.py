"""金原粉丝 — 新老客数据爬取"""
import asyncio
import json
from playwright.async_api import async_playwright

PORT = 9222

async def cdp_ws():
    import subprocess
    r = subprocess.run(
        ["curl", "--noproxy", "localhost", "-s", f"http://localhost:{PORT}/json/version"],
        capture_output=True, text=True, timeout=3
    )
    return json.loads(r.stdout).get("webSocketDebuggerUrl")

async def main():
    ws = await cdp_ws()
    if not ws:
        print("Chrome未启动，请先开浏览器")
        return

    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(ws)
        EXT_ID = "imnjpdamkohlnjmnlfngaoogfnahlldd"

        # ---- 1. 找悟空插件页面（extension tab在独立context里）----
        print("找悟空插件...")
        from plugin_helper import pick_brand, get_stores, click_store_platform
        ext = None
        for c in browser.contexts:
            for p in c.pages:
                if EXT_ID in p.url:
                    ext = p
                    ext_ctx = c
                    break
            if ext:
                break

        if not ext:
            print("悟空插件页面未找到")
            return
        print(f"悟空插件: {ext.url}")

        # 找普通页面的context（用于后续美团后台操作）
        ctx = None
        for c in browser.contexts:
            for p in c.pages:
                if 'e.meituan.com' in p.url or 'waimai.meituan.com' in p.url:
                    ctx = c
                    break
            if ctx:
                break
        if not ctx:
            ctx = browser.contexts[0]

        # ---- 2. 选金原粉丝品牌 ----
        print("选品牌: 金原粉丝...")
        ok, status = await pick_brand(ext, "金原粉丝")
        if not ok:
            print(f"品牌选择失败: {status}")
            return
        print(f"品牌状态: {status}")

        # ---- 3. 获取店铺列表 ----
        stores = await get_stores(ext)
        print(f"店铺列表: {list(stores.keys())}")

        # ---- 4. 登录美团后台 ----
        # 找美团的账号
        mt_account = None
        for store_name, platforms in stores.items():
            for p in platforms:
                if p['platform'] == 'meituan':
                    mt_account = p['account']
                    print(f"美团账号: {mt_account} ({store_name})")
                    break

        if not mt_account:
            print("没有找到美团账号")
            return

        result = await click_store_platform(ext, mt_account)
        print(f"登录结果: {result}")
        if result != 'ok':
            print("登录失败")
            return

        await asyncio.sleep(3)

        # ---- 5. 找美团商家后台页面 ----
        mt_page = None
        for p in ctx.pages:
            if 'waimai.meituan.com' in p.url or 'e.meituan.com' in p.url:
                mt_page = p
                print(f"美团后台页面: {p.url}")
                break

        if not mt_page:
            # 等待新页面打开
            print("等待美团后台页面...")
            for _ in range(10):
                await asyncio.sleep(1)
                for p in ctx.pages:
                    if 'waimai.meituan.com' in p.url or 'e.meituan.com' in p.url:
                        mt_page = p
                        print(f"美团后台页面: {p.url}")
                        break
                if mt_page:
                    break

        if not mt_page:
            print("找不到美团后台页面")
            return

        await mt_page.bring_to_front()
        await asyncio.sleep(2)

        # ---- 6. 爬订单数据（新老客）----
        # 先看当前页面是什么
        current_url = mt_page.url
        print(f"当前URL: {current_url}")

        # 导航到数据分析 - 新老客分析页面
        # 美团商家后台的客户分析路径
        print("\n导航到客户分析页面...")
        await mt_page.goto("https://e.meituan.com/data/customer", wait_until="networkidle", timeout=15000)
        await asyncio.sleep(2)
        url_after = mt_page.url
        print(f"跳转后URL: {url_after}")

        page_text = await mt_page.evaluate("() => document.body.innerText.substring(0, 500)")
        print(f"页面内容预览:\n{page_text}\n")

        # 如果客户分析页不行，试试数据中心
        if '404' in page_text or '找不到' in page_text or url_after == current_url:
            print("尝试数据中心...")
            await mt_page.goto("https://e.meituan.com/data", wait_until="networkidle", timeout=15000)
            await asyncio.sleep(2)
            page_text = await mt_page.evaluate("() => document.body.innerText.substring(0, 1000)")
            print(f"数据中心内容:\n{page_text}\n")

        # ---- 7. 爬订单列表（分页，用JS提取DOM）----
        print("\n导航到订单列表...")
        await mt_page.goto("https://e.meituan.com/order/list", wait_until="networkidle", timeout=15000)
        await asyncio.sleep(3)

        print(f"订单页URL: {mt_page.url}")

        # 提取页面上的关键数据
        order_summary = await mt_page.evaluate("""() => {
            const text = document.body.innerText;
            return text.substring(0, 2000);
        }""")
        print(f"订单页内容:\n{order_summary}\n")

        # 尝试找新老客的统计数据
        print("\n查找新老客统计...")
        await mt_page.goto("https://e.meituan.com/data/userAnalyze", wait_until="networkidle", timeout=15000)
        await asyncio.sleep(3)

        user_data = await mt_page.evaluate("() => document.body.innerText.substring(0, 3000)")
        print(f"用户分析页:\n{user_data}\n")

        print("\n爬取完成，整理数据中...")

asyncio.run(main())
