#!/usr/bin/env python3
"""全量巡检 - 自动遍历插件下所有品牌"""
import asyncio, json, subprocess, re, sys, time, os
from datetime import timezone, timedelta as _td
_CN_TZ = timezone(_td(hours=8))
sys.path.insert(0, __import__('pathlib').Path(__file__).parent.__str__())

# 复用run_fast的所有逻辑
from run_fast import fast_mt, fast_ele, sd, check_promo, THREE_DAYS, CUTOFF
from plugin_helper import get_ext, pick_brand, get_stores, click_store_platform, close_store_pages, save_user_focus, restore_user_focus, stop_hider
from browser import ensure_https, kill_headless
from collections import OrderedDict
from datetime import datetime
from playwright.async_api import async_playwright
import patrol_log as L


def _report_to_remote(log_type="error"):
    """巡检结束后上报日志到管理员server，管理员实时可查"""
    import requests as _req
    try:
        # 从OSS发现管理员URL
        s = _req.Session()
        s.trust_env = False
        resp = s.get("https://meihu-video.oss-cn-hangzhou.aliyuncs.com/tools/ops-logger-server.json", timeout=5)
        if not resp.ok:
            return
        url = resp.json().get("url", "")
        if not url:
            return

        entries = []
        ops_dir = os.path.join(os.path.dirname(__file__), "ops-logger")

        if log_type == "error":
            err_file = os.path.join(ops_dir, "patrol_errors.json")
            if os.path.exists(err_file):
                with open(err_file) as f:
                    entries = json.load(f)
            # 也上报debug日志
            debug_file = os.path.join(ops_dir, "patrol_debug.json")
            if os.path.exists(debug_file):
                with open(debug_file) as f:
                    debug = json.load(f)
                entries.append({"_type": "debug", "steps": debug[-50:]})  # 最近50步
        elif log_type == "patrol":
            result_file = os.path.join(ops_dir, "patrol_result.json")
            if os.path.exists(result_file):
                with open(result_file) as f:
                    result = json.load(f)
                entries = [{"ts": result.get("ts", ""), "brands": result.get("brands", 0),
                            "duration": result.get("duration", 0), "issues": result.get("issues", {})}]

        if not entries:
            return

        import socket
        hostname = socket.gethostname()
        operator = "unknown"
        cfg_file = os.path.join(ops_dir, "config.json")
        if os.path.exists(cfg_file):
            with open(cfg_file) as f:
                operator = json.load(f).get("operator", "unknown")

        s.post(f"{url}/api/logs/report",
               json={"operator": operator, "hostname": hostname, "type": log_type, "entries": entries},
               timeout=10)
        print(f"[report] 已上报 {log_type} 日志到管理员")
    except Exception as e:
        print(f"[report] 上报失败: {e}")


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


def _post_brand_progress(brand, brand_issues, brand_stores_map, all_stores_map, done_count, total_count):
    """每完成一个品牌，立刻推送进度到server，popup实时刷新"""
    import requests as _req
    try:
        payload = {
            "brand": brand,
            "issues": {store: items for store, items in brand_issues.items()},
            "brand_stores": {brand: brand_stores_map.get(brand, [])},
            "all_stores": dict(all_stores_map),
            "done": done_count,
            "total": total_count,
        }
        s = _req.Session()
        s.trust_env = False
        s.post("http://127.0.0.1:5500/api/patrol/progress", json=payload, timeout=3)
    except Exception:
        pass  # 推送失败不影响巡检


def _log_error(error_type, message, context=None):
    """记录错误到 patrol_errors.json（追加）"""
    err_file = os.path.join(os.path.dirname(__file__), "ops-logger", "patrol_errors.json")
    entry = {
        "ts": datetime.now(_CN_TZ).strftime("%Y-%m-%d %H:%M:%S"),
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
    # preflight失败时立即上报，管理员能远程看到
    if error_type == "preflight":
        try:
            _report_to_remote("error")
        except Exception:
            pass


async def main():
    import argparse
    parser = argparse.ArgumentParser(description='全量巡检')
    parser.add_argument('brands', nargs='*', help='品牌名')
    parser.add_argument('--headless', action='store_true', help='无头模式，零窗口')
    parser.add_argument('--operator', default='', help='运营名')
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
            L.step("preflight", "启动无头Chrome...(步骤2/5)")
            b, ctx = await launch_headless(pw)
            # 记录启动后的状态
            sw_urls = [sw.url[:60] for sw in getattr(ctx, 'service_workers', [])]
            bg_urls = [bp.url[:60] for bp in getattr(ctx, 'background_pages', [])]
            page_urls = [p.url[:60] for p in ctx.pages]
            L.step("preflight", "无头Chrome OK", detail=f"pages={page_urls}, sw={sw_urls}, bg={bg_urls}")
        except Exception as e:
            err_msg = str(e)
            L.error("preflight", f"headless Chrome启动失败(步骤2): {e}", detail=err_msg)
            _log_error("preflight", f"headless Chrome启动失败: {e}")
            # 人话报错直接打印
            if "【需要操作】" in err_msg:
                print(f"\n❌ {err_msg}\n")
            else:
                print(f"\n❌ 无头Chrome启动失败，请确认debug Chrome正在运行且悟空已登录。\n")
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
        L.step("preflight", "悟空插件 OK(步骤3/5)")
    except Exception as e:
        L.error("preflight", f"悟空插件找不到(步骤3): {e}", detail=str([p.url[:80] for p in ctx.pages]))
        _log_error("preflight", f"悟空插件找不到: {e}", {"pages": [p.url[:80] for p in ctx.pages]})
        print(
            "\n❌ 【卡在：打开悟空插件】悟空插件打不开。\n"
            "请在Chrome里确认悟空插件正常，登出外卖通后重新用手机号登录，再跑无头巡检。\n"
        )
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
            print(f"\n❌ {login_msg}\n")
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

    print(f"盯店全量巡检 - {datetime.now(_CN_TZ).strftime('%Y-%m-%d %H:%M')}")
    print(f"共 {len(brands)} 个品牌\n")
    for i, b in enumerate(brands):
        print(f"  {i+1}. {b}")
    print()

    t0 = time.time()
    all_issues = OrderedDict()
    _cookie_snapshots = []  # cookie快照，预警时复用
    all_stores = OrderedDict()  # 记录所有巡过的店: {display_name: [platform_name, ...]}
    brand_stores = OrderedDict()  # 品牌→店铺映射: {brand: [display_name, ...]}

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

                # 记录每个巡过的店+平台+品牌映射
                all_stores.setdefault(display_name(), [])
                if p_name not in all_stores[display_name()]:
                    all_stores[display_name()].append(p_name)
                brand_stores.setdefault(brand, [])
                if display_name() not in brand_stores[brand]:
                    brand_stores[brand].append(display_name())

                if acct['action'] == '立刻授权':
                    all_issues.setdefault(display_name(), []).append(
                        {"platform": p_name, "type": "auth", "msg": "授权失败", "details": []})
                    continue
                if acct['action'] != '一键登录': continue

                async def _do_login_and_get_page():
                    """登录并返回平台页面，支持context销毁后重试"""
                    await close_store_pages(ctx)
                    ext = await get_ext(ctx)
                    await pick_brand(ext, brand)

                    # 登录重试机制：点击后验证平台页面是否打开，最多5次，间隔递增
                    for login_attempt in range(5):
                        result = await click_store_platform(ext, acct['account'])
                        if result != 'ok':
                            L.step("store", f"跳过 {acct['account']} (result={result})")
                            return result, None
                        await asyncio.sleep(4 + login_attempt * 2)

                        found_page = False
                        if p == 'meituan':
                            found_page = any('waimai.meituan.com' in x.url and 'chrome-extension' not in x.url for x in ctx.pages)
                        elif p == 'eleme':
                            found_page = any('ele.me' in x.url and 'melody' in x.url for x in ctx.pages)

                        if found_page:
                            return 'ok', True
                        else:
                            L.step("store", f"登录后未检测到{p_name}页面，第{login_attempt+1}次重试")
                            await close_store_pages(ctx)
                            ext = await get_ext(ctx)
                            await pick_brand(ext, brand)
                    return 'ok', False  # 5次都没打开

                try:
                    result, login_ok = await _do_login_and_get_page()

                    if result != 'ok':
                        continue
                    if not login_ok:
                        L.error("store", f"5次登录均未打开{p_name}页面: {acct['account']}")
                        _log_error("store_login", f"5次重试仍未打开平台页面", {"brand": brand, "account": acct.get('account',''), "platform": p_name})
                        all_issues.setdefault(display_name(), []).append({"platform":p_name,"type":"error","msg":f"登录5次未成功","details":[]})
                        continue

                    await restore_user_focus(user_page)  # 还焦点

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
                        # 检查是否需要验证码
                        from plugin_helper import check_verification
                        blocked, block_msg = await check_verification(pg)
                        if blocked:
                            all_issues.setdefault(display_name(), []).append({"platform":p_name,"type":"auth","msg":f"需要验证: {block_msg}","details":[]})
                            try: await pg.close()
                            except: pass
                        else:
                            # 存cookie快照（供cookie预警使用）
                            try:
                                _all_ck = await ctx.cookies()
                                _mt_ck = [c for c in _all_ck if 'meituan' in c.get('domain', '')]
                                _key_vals = {}
                                for _c in _mt_ck:
                                    if _c['name'] in ('wmPoiId', 'acctId', 'token', 'JSESSIONID'):
                                        _key_vals[_c['name']] = _c['value']
                                _cookie_snapshots.append({
                                    "store": display_name(),
                                    "brand": brand,
                                    "account": acct['account'],
                                    "platform": "meituan",
                                    "key_vals": _key_vals,
                                    "cookies": _mt_ck,
                                })
                            except Exception:
                                pass
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
                                err_msg = str(e)
                                if 'ERR_ABORTED' in err_msg or 'ERR_CONNECTION' in err_msg:
                                    L.step("scrape", f"美团页面加载失败，刷新重试")
                                    try:
                                        await pg.reload(wait_until="commit", timeout=15000)
                                        await asyncio.sleep(3)
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
                                    except Exception as e2:
                                        all_issues.setdefault(display_name(), []).append({"platform":p_name,"type":"error","msg":f"重试仍失败: {str(e2)[:30]}","details":[]})
                                elif 'Target page' in err_msg or 'context' in err_msg.lower():
                                    # context销毁，重新通过goku登录
                                    L.step("scrape", f"美团页面context失效，重新登录重试")
                                    try:
                                        result2, login_ok2 = await _do_login_and_get_page()
                                        if result2 == 'ok' and login_ok2:
                                            pg2 = None
                                            for x in ctx.pages:
                                                if 'waimai.meituan.com' in x.url and 'chrome-extension' not in x.url: pg2=x; break
                                            if pg2:
                                                issues = await fast_mt(pg2)
                                                name = issues.pop('name','')
                                                if name and '*' not in name: real_name = name
                                                for k, v in issues.items():
                                                    if k=='bad':
                                                        all_issues.setdefault(display_name(), []).append({"platform":p_name,"type":"bad_review","msg":f"近3日中差评{len(v)}条","details":v})
                                                    elif k=='notices':
                                                        all_issues.setdefault(display_name(), []).append({"platform":p_name,"type":"notice","msg":f"{len(v)}条通知","details":v})
                                                    elif k=='promo':
                                                        all_issues.setdefault(display_name(), []).append({"platform":p_name,"type":"promo","msg":f"推广余额不足：{v['balance']}元/日消费{v['median']}元","details":[]})
                                                try: await pg2.close()
                                                except: pass
                                            pg = None  # 避免下面再close
                                        else:
                                            all_issues.setdefault(display_name(), []).append({"platform":p_name,"type":"error","msg":f"重新登录失败","details":[]})
                                    except Exception as e2:
                                        all_issues.setdefault(display_name(), []).append({"platform":p_name,"type":"error","msg":f"重试仍失败: {str(e2)[:30]}","details":[]})
                                else:
                                    all_issues.setdefault(display_name(), []).append({"platform":p_name,"type":"error","msg":f"检查出错: {err_msg[:30]}","details":[]})
                            try:
                                if pg: await pg.close()
                            except: pass

                elif p == 'eleme':
                    pg = None
                    for x in ctx.pages:
                        if 'ele.me' in x.url and 'melody' in x.url: pg=x; break
                    if pg:
                        from plugin_helper import check_verification
                        blocked, block_msg = await check_verification(pg)
                        if blocked:
                            all_issues.setdefault(display_name(), []).append({"platform":p_name,"type":"auth","msg":f"需要验证: {block_msg}","details":[]})
                            try: await pg.close()
                            except: pass
                        else:
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
                                err_msg = str(e)
                                if 'ERR_ABORTED' in err_msg or 'ERR_CONNECTION' in err_msg:
                                    L.step("scrape", f"饿了么页面加载失败，刷新重试")
                                    try:
                                        await pg.reload(wait_until="commit", timeout=15000)
                                        await asyncio.sleep(3)
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
                                    except Exception as e2:
                                        all_issues.setdefault(display_name(), []).append({"platform":p_name,"type":"error","msg":f"重试仍失败: {str(e2)[:30]}","details":[]})
                                elif 'Target page' in err_msg or 'context' in err_msg.lower():
                                    L.step("scrape", f"饿了么页面context失效，重新登录重试")
                                    try:
                                        result2, login_ok2 = await _do_login_and_get_page()
                                        if result2 == 'ok' and login_ok2:
                                            pg2 = None
                                            for x in ctx.pages:
                                                if 'ele.me' in x.url and 'melody' in x.url: pg2=x; break
                                            if pg2:
                                                issues = await fast_ele(pg2)
                                                name = issues.pop('name','')
                                                if name: real_name = name
                                                for k, v in issues.items():
                                                    if k=='bad':
                                                        all_issues.setdefault(display_name(), []).append({"platform":p_name,"type":"bad_review","msg":f"近3日中差评{len(v)}条","details":v})
                                                    elif k=='exp':
                                                        all_issues.setdefault(display_name(), []).append({"platform":p_name,"type":"expiring","msg":f"{len(v)}个活动即将到期","details":v})
                                                    elif k=='promo':
                                                        all_issues.setdefault(display_name(), []).append({"platform":p_name,"type":"promo","msg":f"推广余额不足：{v['balance']}元/日消费{v['median']}元","details":[]})
                                                try: await pg2.close()
                                                except: pass
                                            pg = None
                                        else:
                                            all_issues.setdefault(display_name(), []).append({"platform":p_name,"type":"error","msg":f"重新登录失败","details":[]})
                                    except Exception as e2:
                                        all_issues.setdefault(display_name(), []).append({"platform":p_name,"type":"error","msg":f"重试仍失败: {str(e2)[:30]}","details":[]})
                                else:
                                    all_issues.setdefault(display_name(), []).append({"platform":p_name,"type":"error","msg":f"检查出错: {err_msg[:30]}","details":[]})
                            try:
                                if pg: await pg.close()
                            except: pass

        print(f"{time.time()-t_brand:.0f}s")

        # 每完成一个品牌，立刻推送进度给popup
        _post_brand_progress(brand, all_issues, brand_stores, all_stores, bi+1, len(brands))

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
            "ts": datetime.now(_CN_TZ).strftime("%Y-%m-%d %H:%M"),
            "operator": args.operator,
            "brands": len(brands),
            "duration": int(total),
            "all_stores": dict(all_stores),
            "brand_stores": dict(brand_stores),
            "issues": {store: items for store, items in all_issues.items()},
        }
        with open(result_file, "w", encoding="utf-8") as f:
            json.dump(result_data, f, ensure_ascii=False, indent=2)
        print(f"结果已保存: {result_file}")
    except Exception as e:
        print(f"保存结果失败: {e}")

    # 保存cookie快照供预警使用
    if _cookie_snapshots:
        snap_file = os.path.join(os.path.dirname(__file__), "ops-logger", "_cookie_snapshots.json")
        try:
            with open(snap_file, "w", encoding="utf-8") as f:
                json.dump(_cookie_snapshots, f, ensure_ascii=False, indent=2)
            print(f"Cookie快照已保存: {len(_cookie_snapshots)}个店铺")
        except Exception as e:
            print(f"Cookie快照保存失败: {e}")

    # 自动记录
    from learn import log_interaction
    issue_count = sum(len(items) for items in all_issues.values())
    log_interaction("usage", f"全量巡检 {len(brands)}品牌，{issue_count}个问题，{total:.0f}秒")

    # 上报巡检结果+错误日志到远程（管理员实时可查）
    try:
        _report_to_remote("patrol")
        _report_to_remote("error")
    except Exception:
        pass

    await stop_hider()
    if args.headless: kill_headless()
    await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
