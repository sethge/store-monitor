#!/usr/bin/env python3
"""全量巡检 - 自动遍历插件下所有品牌"""
import asyncio, json, subprocess, re, sys, time, os
sys.path.insert(0, __import__('pathlib').Path(__file__).parent.__str__())

# 复用run_fast的所有逻辑
from run_fast import fast_mt, fast_ele, sd, check_promo, THREE_DAYS, CUTOFF
from plugin_helper import get_ext, pick_brand, get_stores, click_store_platform, close_store_pages, save_user_focus, restore_user_focus, stop_hider
from browser import ensure_https, kill_headless
from collections import OrderedDict
from datetime import datetime
from playwright.async_api import async_playwright
import patrol_log as L


async def get_all_brands(ext):
    """获取插件下所有品牌列表"""
    # 等插件就绪
    for _wait in range(5):
        ready = await ext.evaluate("() => document.querySelectorAll('.ant-select-selector').length > 0")
        if ready:
            break
        await asyncio.sleep(1)
    # 重置
    await ext.evaluate("() => document.querySelectorAll('button,span').forEach(e=>{if(e.textContent.trim()==='重 置')e.click()})")
    await asyncio.sleep(0.5)
    # 打开下拉
    await ext.evaluate("() => {const s=document.querySelectorAll('.ant-select-selector');if(s.length)s[s.length-1].dispatchEvent(new MouseEvent('mousedown',{bubbles:true}))}")
    await asyncio.sleep(1)
    # 获取所有品牌
    brands = await ext.evaluate(r"""() => {
        const opts = document.querySelectorAll('.ant-select-item-option');
        return Array.from(opts).map(o => o.textContent.trim()).filter(t => t.length > 2 && !t.match(/^\d+$/));
    }""")
    await ext.evaluate("() => document.activeElement && document.activeElement.blur()")
    await asyncio.sleep(0.3)
    return brands


def _log_error(error_type, message, context=None):
    """记录错误到 patrol_errors.json（追加）"""
    err_file = os.path.join(os.path.dirname(__file__), "ops-logger", "patrol_errors.json")
    entry = {
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "type": error_type,
        "msg": message,
        "ctx": context or {}
    }
    try:
        errors = []
        if os.path.exists(err_file):
            with open(err_file, "r") as f:
                errors = json.load(f)
        errors.append(entry)
        # 只保留最近200条
        errors = errors[-200:]
        with open(err_file, "w") as f:
            json.dump(errors, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    print(f"[ERROR] [{error_type}] {message}")


async def main():
    import argparse
    parser = argparse.ArgumentParser(description='全量巡检')
    parser.add_argument('brands', nargs='*', help='品牌名')
    parser.add_argument('--headless', action='store_true', help='无头模式，零窗口')
    args = parser.parse_args()

    # ========== Preflight Check ==========
    L.start()
    L.step("preflight", "启动前检查开始")

    # Check 1: playwright可用
    try:
        pw = await async_playwright().start()
        L.step("preflight", "playwright OK")
    except Exception as e:
        L.error("preflight", f"playwright启动失败: {e}")
        _log_error("preflight", f"playwright启动失败: {e}")
        return

    # Check 2: Chrome连接
    if args.headless:
        from browser import launch_headless
        try:
            L.step("preflight", "启动无头Chrome...")
            b, ctx = await launch_headless(pw)
            L.step("preflight", "无头Chrome OK")
        except Exception as e:
            L.error("preflight", f"headless Chrome启动失败: {e}")
            _log_error("preflight", f"headless Chrome启动失败: {e}")
            await pw.stop()
            return
        user_page = None
    else:
        from browser import launch as launch_browser
        try:
            b, ctx = await launch_browser(pw)
            L.step("preflight", "Chrome连接 OK")
        except Exception as e:
            L.error("preflight", f"Chrome连接失败: {e}")
            _log_error("preflight", f"Chrome连接失败: {e}")
            await pw.stop()
            return
        user_page = await save_user_focus(ctx)

    # Check 3: 悟空插件
    try:
        ext = await get_ext(ctx)
        L.step("preflight", "悟空插件 OK")
    except Exception as e:
        L.error("preflight", f"悟空插件找不到: {e}", detail=str([p.url[:80] for p in ctx.pages]))
        _log_error("preflight", f"悟空插件找不到: {e}", {"pages": [p.url[:80] for p in ctx.pages]})
        if args.headless: kill_headless()
        await pw.stop()
        return

    # Check 4: headless登录态
    if args.headless:
        from browser import check_headless_login
        login_ok, login_msg = await check_headless_login(ctx)
        if not login_ok:
            L.error("preflight", f"登录失败: {login_msg}")
            _log_error("preflight", f"登录失败: {login_msg}")
            kill_headless()
            await pw.stop()
            return
        L.step("preflight", f"登录 OK: {login_msg}")

    # Check 5: 品牌列表
    if args.brands:
        brands = args.brands
        L.step("preflight", f"指定品牌: {brands}")
    else:
        brands = await get_all_brands(ext)

    if not brands:
        L.error("preflight", "品牌列表为空")
        _log_error("preflight", "未获取到品牌列表")
        if args.headless: kill_headless()
        await pw.stop()
        return
    L.step("preflight", f"{len(brands)}个品牌，检查通过")
    print("--- 检查通过，开始巡检 ---\n")

    print(f"盯店全量巡检 - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"共 {len(brands)} 个品牌\n")
    for i, b in enumerate(brands):
        print(f"  {i+1}. {b}")
    print()

    t0 = time.time()
    all_issues = OrderedDict()
    all_stores = OrderedDict()  # 记录所有巡过的店: {display_name: [platform_name, ...]}

    for bi, brand in enumerate(brands):
        t_brand = time.time()
        brand_short = brand.split("（")[0]
        L.step("brand", f"[{bi+1}/{len(brands)}] {brand}")
        print(f"  [{bi+1}/{len(brands)}] {brand}...", end=" ", flush=True)

        try:
            await close_store_pages(ctx)
            ext = await get_ext(ctx)
        except Exception as e:
            L.error("brand", f"get_ext失败，跳过{brand}", detail=str(e))
            _log_error("brand_setup", f"get_ext失败，跳过{brand}", {"brand": brand, "error": str(e)})
            print(f"❌ 插件连接失败，跳过")
            all_issues[brand] = [{"platform":"","type":"error","msg":f"插件连接失败: {str(e)[:50]}","details":[]}]
            continue

        ok, status = await pick_brand(ext, brand)
        if not ok:
            L.error("brand", f"品牌未找到: {brand}")
            _log_error("brand_pick", f"品牌未找到: {brand}")
            print(f"❌")
            all_issues[brand] = [{"platform":"","type":"error","msg":"品牌未找到","details":[]}]
            continue

        try:
            stores = await get_stores(ext)
        except Exception as e:
            L.error("brand", f"获取店铺失败: {brand}", detail=str(e))
            _log_error("brand_stores", f"获取店铺失败: {brand}", {"error": str(e)})
            print(f"❌ 获取店铺失败")
            all_issues[brand] = [{"platform":"","type":"error","msg":f"获取店铺失败: {str(e)[:50]}","details":[]}]
            continue

        L.step("brand", f"{brand_short}: {len(stores)}家店铺")
        print(f"{len(stores)}店", end=" ", flush=True)

        for store_key, accounts in stores.items():
            real_name = store_key if not store_key.startswith('_auto_') else ""

            def display_name():
                n = real_name or brand
                if n and len(n) <= 6 and brand_short not in n:
                    return f"{brand_short}·{n}"
                if n and '店' in n and brand_short not in n and len(n) < 15:
                    return f"{brand_short}·{n}"
                return n

            for acct in accounts:
                p, p_name = acct['platform'], "美团" if acct['platform']=='meituan' else "饿了么"

                # 记录每个巡过的店+平台
                all_stores.setdefault(display_name(), [])
                if p_name not in all_stores[display_name()]:
                    all_stores[display_name()].append(p_name)

                if acct['action'] == '立刻授权':
                    all_issues.setdefault(display_name(), []).append(
                        {"platform": p_name, "type": "auth", "msg": "授权失败", "details": []})
                    continue
                if acct['action'] != '一键登录': continue

                try:
                    await close_store_pages(ctx)
                    ext = await get_ext(ctx)
                    await pick_brand(ext, brand)
                    result = await click_store_platform(ext, acct['account'])
                    if result != 'ok':
                        L.step("store", f"跳过 {acct['account']} (result={result})")
                        continue
                    await asyncio.sleep(3)  # 等Goku创建tab
                    await restore_user_focus(user_page)  # 再还焦点

                    # headless下Goku可能开http://，修正为https://
                    for x in ctx.pages:
                        if x.url.startswith("http://") and ('waimai.meituan.com' in x.url or 'ele.me' in x.url):
                            L.step("store", f"修正http→https: {x.url[:60]}")
                            await ensure_https(x)
                except Exception as e:
                    L.error("store", f"登录失败: {p_name} {acct.get('account','')}", detail=str(e))
                    _log_error("store_login", f"登录店铺失败，跳过", {"brand": brand, "store": store_key, "account": acct.get('account',''), "platform": p_name, "error": str(e)})
                    all_issues.setdefault(display_name(), []).append({"platform":p_name,"type":"error","msg":f"登录失败: {str(e)[:40]}","details":[]})
                    continue

                if p == 'meituan':
                    pg = None
                    for x in ctx.pages:
                        if 'waimai.meituan.com' in x.url and 'chrome-extension' not in x.url: pg=x; break
                    if pg:
                        L.step("scrape", f"美团数据采集: {pg.url[:60]}")
                        try:
                            issues = await fast_mt(pg)
                            name = issues.pop('name','')
                            if name and '*' not in name: real_name = name
                            for k, v in issues.items():
                                if k=='bad':
                                    all_issues.setdefault(display_name(), []).append({"platform":p_name,"type":"bad_review","msg":f"近3日中差评{len(v)}条","details":v})
                                elif k=='notices':
                                    all_issues.setdefault(display_name(), []).append({"platform":p_name,"type":"notice","msg":f"{len(v)}条通知","details":v})
                                elif k=='promo':
                                    all_issues.setdefault(display_name(), []).append({"platform":p_name,"type":"promo","msg":f"推广余额不足：{v['balance']}元/日消费{v['median']}元","details":[]})
                        except Exception as e:
                            all_issues.setdefault(display_name(), []).append({"platform":p_name,"type":"error","msg":f"检查出错: {str(e)[:30]}","details":[]})
                        try: await pg.close()
                        except: pass

                elif p == 'eleme':
                    pg = None
                    for x in ctx.pages:
                        if 'ele.me' in x.url and 'melody' in x.url: pg=x; break
                    if pg:
                        L.step("scrape", f"饿了么数据采集: {pg.url[:60]}")
                        try:
                            issues = await fast_ele(pg)
                            name = issues.pop('name','')
                            if name: real_name = name
                            for k, v in issues.items():
                                if k=='bad':
                                    all_issues.setdefault(display_name(), []).append({"platform":p_name,"type":"bad_review","msg":f"近3日中差评{len(v)}条","details":v})
                                elif k=='exp':
                                    all_issues.setdefault(display_name(), []).append({"platform":p_name,"type":"expiring","msg":f"{len(v)}个活动即将到期","details":v})
                                elif k=='promo':
                                    all_issues.setdefault(display_name(), []).append({"platform":p_name,"type":"promo","msg":f"推广余额不足：{v['balance']}元/日消费{v['median']}元","details":[]})
                        except Exception as e:
                            all_issues.setdefault(display_name(), []).append({"platform":p_name,"type":"error","msg":f"检查出错: {str(e)[:30]}","details":[]})
                        try: await pg.close()
                        except: pass

        print(f"{time.time()-t_brand:.0f}s")

    # 清理incomplete
    for store in list(all_issues.keys()):
        all_issues[store] = [i for i in all_issues[store] if i['type'] != 'incomplete']
        if not all_issues[store]:
            del all_issues[store]

    total = time.time() - t0
    issue_count = sum(len(items) for items in all_issues.values())
    L.step("summary", f"巡检完成: {len(brands)}品牌, {issue_count}个问题, {total:.0f}秒")
    print(f"\n摘要\n")

    if all_issues:
        for store, items in all_issues.items():
            print(f"⚠️ {store}")
            for item in items:
                print(f"  {item['platform']} {item['msg']}")
                for d in item.get('details', []):
                    if isinstance(d, dict):
                        if d.get('comment'):
                            print(f"    [{d['stars']}星] {sd(d.get('time',''))} — {d['comment'][:45]}")
                        elif d.get('name'):
                            print(f"    {d['name']} 剩{d['days']}天")
                        elif d.get('title'):
                            print(f"    {d['title']} — {sd(d.get('time',''))}" if d.get('time') else f"    {d['title']}")
                            if d.get('content') and d['content'] != d['title']:
                                print(f"      {d['content']}")
                    elif isinstance(d, str) and d:
                        print(f"    {d}")
            print()
    else:
        print("✅ 所有店铺运营正常\n")

    print(f"巡检完成 — {len(brands)}个品牌 总耗时{total:.0f}秒")

    # 保存结果JSON供插件读取
    result_file = os.path.join(os.path.dirname(__file__), "ops-logger", "patrol_result.json")
    try:
        result_data = {
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "brands": len(brands),
            "duration": int(total),
            "all_stores": dict(all_stores),
            "issues": {store: items for store, items in all_issues.items()},
        }
        with open(result_file, "w", encoding="utf-8") as f:
            json.dump(result_data, f, ensure_ascii=False, indent=2)
        print(f"结果已保存: {result_file}")
    except Exception as e:
        print(f"保存结果失败: {e}")

    # 自动记录
    from learn import log_interaction
    issue_count = sum(len(items) for items in all_issues.values())
    log_interaction("usage", f"全量巡检 {len(brands)}品牌，{issue_count}个问题，{total:.0f}秒")
    await stop_hider()
    if args.headless: kill_headless()
    await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
