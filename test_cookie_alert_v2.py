#!/usr/bin/env python3
"""
验证cookie切店预警方案：
1. goku登录一个运营的所有店 → 存每个店的cookie快照
2. 关闭所有店铺页面
3. 用Playwright切cookie + 复用tab访问通知页 → 验证能否拿到通知数据
4. 模拟cookie失效 → 检测失败 → goku重新登录
"""
import asyncio, json, sys, os, time, re
sys.path.insert(0, os.path.dirname(__file__))

from playwright.async_api import async_playwright
from plugin_helper import get_ext, pick_brand, get_stores, click_store_platform, close_store_pages
from browser import launch_headless, kill_headless


async def save_store_cookies(ctx, store_name, platform):
    """从浏览器context抓当前店铺的关键cookie"""
    all_cookies = await ctx.cookies()
    mt_cookies = [c for c in all_cookies if 'meituan' in c.get('domain', '')]

    # 提取关键标识
    key_vals = {}
    for c in mt_cookies:
        if c['name'] in ('wmPoiId', 'acctId', 'token', 'JSESSIONID', 'set_info', 'pushToken'):
            key_vals[c['name']] = c['value']

    return {
        "store": store_name,
        "platform": platform,
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "key_vals": key_vals,
        "cookies": mt_cookies,
    }


async def switch_cookies(ctx, cookie_snapshot):
    """用Playwright API切换到指定店铺的cookie"""
    cookies_to_set = []
    for c in cookie_snapshot['cookies']:
        item = {
            "name": c['name'],
            "value": c['value'],
            "domain": c['domain'],
            "path": c.get('path', '/'),
        }
        if c.get('httpOnly'):
            item['httpOnly'] = True
        if c.get('secure'):
            item['secure'] = True
        if c.get('sameSite'):
            item['sameSite'] = c['sameSite']
        cookies_to_set.append(item)

    await ctx.add_cookies(cookies_to_set)


async def check_notifications(page):
    """在已打开的通知页上拦截API响应，返回通知列表"""
    captured = {}

    async def on_resp(resp):
        try:
            ct = resp.headers.get('content-type', '')
            if 'json' not in ct:
                return
            if 'message/category/list' in resp.url:
                captured['msgs'] = await resp.json()
        except:
            pass

    page.on("response", on_resp)
    try:
        # 先清掉页面状态，避免缓存导致API不重新请求
        await page.goto("about:blank", wait_until="commit", timeout=5000)
        await asyncio.sleep(0.3)
        await page.goto(
            "https://e.waimai.meituan.com/new_fe/business_gw#/msgbox",
            wait_until="commit", timeout=15000
        )
        await asyncio.sleep(3)
    except Exception as e:
        print(f"    goto失败: {e}")
    page.remove_listener("response", on_resp)

    # 检测是否被重定向到登录页
    if 'login' in page.url.lower() or 'passport' in page.url.lower():
        return None, "redirected_to_login"

    msgs_data = captured.get('msgs', {}).get('data', {}).get('wmENoticeResults', [])
    if not captured.get('msgs'):
        # 没拦截到API响应，可能cookie失效
        return None, "no_api_response"

    # 过滤通知（和watch_mt相同逻辑）
    from datetime import datetime, timedelta
    cutoff = int((datetime.now() - timedelta(days=3)).timestamp())
    notices = []
    for m in msgs_data:
        if m.get('ctime', 0) < cutoff:
            continue
        t = m.get('title', '')
        if any(k in t for k in ['活动到期提醒', '发票', '预订单', '粉丝群']):
            continue
        content = re.sub(r'<[^>]+>', '', m.get('content', m.get('preView', ''))).strip()
        notices.append({"title": t, "content": content[:80]})

    return notices, "ok"


async def main():
    # 从operators.json取第一个运营
    ops_file = os.path.join(os.path.dirname(__file__), "ops-logger", "operators.json")
    with open(ops_file) as f:
        ops = json.load(f)

    # 指定运营或取第一个
    target_op = sys.argv[1] if len(sys.argv) > 1 else None
    test_operator = None
    test_brands = []
    for op, brands in ops.items():
        if target_op and op != target_op:
            continue
        test_operator = op
        test_brands = list(brands.keys())
        break

    print(f"=== Cookie切店预警测试 ===")
    print(f"运营: {test_operator}")
    print(f"测试品牌: {test_brands}\n")

    pw = await async_playwright().start()
    browser, ctx = await launch_headless(pw)
    ext = await get_ext(ctx)

    # ========== 阶段1: goku登录所有店，存cookie快照 ==========
    print("=" * 50)
    print("阶段1: Goku登录 + 存cookie快照")
    print("=" * 50)

    all_snapshots = []  # [{store, platform, cookies, key_vals}]

    for brand in test_brands:
        print(f"\n--- {brand} ---")
        ok, status = await pick_brand(ext, brand)
        if not ok:
            print(f"  品牌未找到，跳过")
            continue

        stores = await get_stores(ext)
        print(f"  {len(stores)}家店")

        for store_key, accounts in stores.items():
            for acct in accounts:
                if acct['platform'] != 'meituan' or acct['action'] != '一键登录':
                    continue

                print(f"  登录: {store_key} / {acct['account']}...", end=" ", flush=True)
                result = await click_store_platform(ext, acct['account'])
                if result != 'ok':
                    print(f"失败({result})")
                    continue

                await asyncio.sleep(3)

                # 找到新打开的美团页面
                mt_page = None
                for p in ctx.pages:
                    if 'waimai.meituan.com' in p.url and 'chrome-extension' not in p.url:
                        mt_page = p
                        break

                if not mt_page:
                    print("页面未打开")
                    continue

                # 存cookie快照
                snapshot = await save_store_cookies(ctx, f"{brand}/{store_key}", "meituan")
                snapshot['brand'] = brand
                snapshot['account'] = acct['account']
                poi_id = snapshot['key_vals'].get('wmPoiId', '?')
                acct_id = snapshot['key_vals'].get('acctId', '?')
                print(f"OK (poi={poi_id}, acct={acct_id}, {len(snapshot['cookies'])}cookies)")
                all_snapshots.append(snapshot)

                # 关闭页面
                try:
                    await mt_page.close()
                except:
                    pass

    print(f"\n共存了 {len(all_snapshots)} 个店铺的cookie快照")

    if not all_snapshots:
        print("没有可测试的店铺")
        kill_headless()
        await pw.stop()
        return

    # 关闭所有残留的店铺页面
    await close_store_pages(ctx)

    # ========== 阶段2: 用cookie切店 + 复用tab访问通知页 ==========
    print("\n" + "=" * 50)
    print("阶段2: Cookie切店 + 复用tab预警")
    print("=" * 50)

    # 开一个复用tab
    reuse_page = await ctx.new_page()
    print(f"复用tab已创建\n")

    success_count = 0
    fail_count = 0
    goku_fallback_count = 0

    for snap in all_snapshots:
        store = snap['store']
        poi_id = snap['key_vals'].get('wmPoiId', '?')
        print(f"  [{store}] (poi={poi_id})", end=" ", flush=True)

        t0 = time.time()

        # 切cookie
        await switch_cookies(ctx, snap)

        # 访问通知页
        notices, status = await check_notifications(reuse_page)

        elapsed = time.time() - t0

        if status == "ok":
            print(f"OK {elapsed:.1f}s — {len(notices)}条通知")
            for n in notices[:3]:
                print(f"    {n['title']}")
            success_count += 1
        else:
            # cookie失效 → goku兜底
            print(f"FAIL({status}) → goku重登...", end=" ", flush=True)
            brand_name = snap.get('brand', '')
            account = snap.get('account', '')
            if brand_name and account:
                ok2, _ = await pick_brand(ext, brand_name)
                if ok2:
                    await get_stores(ext)
                    r = await click_store_platform(ext, account)
                    if r == 'ok':
                        await asyncio.sleep(3)
                        # 找新页面，存新cookie
                        mt_page = None
                        for p in ctx.pages:
                            if 'waimai.meituan.com' in p.url and 'chrome-extension' not in p.url:
                                mt_page = p
                                break
                        if mt_page:
                            new_snap = await save_store_cookies(ctx, snap['store'], "meituan")
                            new_snap['brand'] = brand_name
                            new_snap['account'] = account
                            snap.update(new_snap)  # 更新快照
                            try:
                                await mt_page.close()
                            except:
                                pass
                            # 用新cookie重试
                            await switch_cookies(ctx, snap)
                            notices2, status2 = await check_notifications(reuse_page)
                            elapsed2 = time.time() - t0
                            if status2 == "ok":
                                print(f"OK(重登) {elapsed2:.1f}s — {len(notices2)}条通知")
                                success_count += 1
                                goku_fallback_count += 1
                                continue
                            else:
                                print(f"重登后仍失败({status2})")
                        else:
                            print(f"goku页面未打开")
                    else:
                        print(f"goku登录失败({r})")
                else:
                    print(f"品牌未找到")
            else:
                print(f"无brand/account信息")
            fail_count += 1

    # 关闭复用tab
    try:
        await reuse_page.close()
    except:
        pass

    # ========== 阶段3: 模拟cookie失效 ==========
    print("\n" + "=" * 50)
    print("阶段3: 模拟cookie失效 + 检测")
    print("=" * 50)

    # 用一个假的cookie测试失效检测
    fake_snap = {
        "store": "fake_store",
        "platform": "meituan",
        "cookies": [
            {"name": "wmPoiId", "value": "99999999", "domain": "e.waimai.meituan.com", "path": "/"},
            {"name": "acctId", "value": "99999999", "domain": "e.waimai.meituan.com", "path": "/"},
            {"name": "token", "value": "fake_expired_token", "domain": "e.waimai.meituan.com", "path": "/"},
            {"name": "JSESSIONID", "value": "fake_session", "domain": "e.waimai.meituan.com", "path": "/"},
        ],
        "key_vals": {"wmPoiId": "99999999"},
    }

    reuse_page2 = await ctx.new_page()
    await switch_cookies(ctx, fake_snap)
    notices, status = await check_notifications(reuse_page2)
    print(f"  假cookie结果: status={status}, notices={notices}")

    if status != "ok":
        print(f"  失效检测成功! 可以触发goku重新登录")
    else:
        print(f"  意外：假cookie也返回了数据?? notices={len(notices) if notices else 0}")

    try:
        await reuse_page2.close()
    except:
        pass

    # ========== 总结 ==========
    print("\n" + "=" * 50)
    print("总结")
    print("=" * 50)
    total = success_count + fail_count
    print(f"测试店铺: {total}")
    print(f"cookie切店成功: {success_count}")
    print(f"  其中goku兜底成功: {goku_fallback_count}")
    print(f"cookie切店失败: {fail_count}")
    print(f"失效检测: {'通过' if status != 'ok' else '未通过'}")

    if success_count > 0:
        print(f"\n结论: Cookie切店方案可行!")
        print(f"预计预警速度: {total}店 × 3s ≈ {total*3}s")
    else:
        print(f"\n结论: Cookie切店方案不可行，需要其他方案")

    # 保存快照供后续使用
    snap_file = os.path.join(os.path.dirname(__file__), "ops-logger", "_cookie_snapshots.json")
    with open(snap_file, 'w') as f:
        json.dump(all_snapshots, f, ensure_ascii=False, indent=2)
    print(f"\nCookie快照已保存: {snap_file}")

    kill_headless()
    await pw.stop()


if __name__ == '__main__':
    asyncio.run(main())
