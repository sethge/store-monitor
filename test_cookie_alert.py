#!/usr/bin/env python3
"""
测试：用cookie直接调美团API，不开浏览器页面
流程：goku登录一家店 → 抓cookie → 关页面 → 纯HTTP请求验证
"""
import asyncio, json, sys, os, re, time
sys.path.insert(0, os.path.dirname(__file__))

import requests
from playwright.async_api import async_playwright
from plugin_helper import get_ext, pick_brand, get_stores, click_store_platform, close_store_pages
from browser import launch_headless, kill_headless


async def main():
    brand = sys.argv[1] if len(sys.argv) > 1 else None
    if not brand:
        # 从operators.json取第一个品牌
        ops_file = os.path.join(os.path.dirname(__file__), "ops-logger", "operators.json")
        with open(ops_file) as f:
            ops = json.load(f)
        for op, brands in ops.items():
            brand = list(brands.keys())[0]
            print(f"自动选择: {op} / {brand}")
            break

    print(f"=== Cookie预警测试 === 品牌: {brand}\n")

    pw = await async_playwright().start()

    # 用headless Chrome（和巡店一样的方式）
    print("1. 启动headless Chrome + 同步cookie...")
    browser, ctx = await launch_headless(pw)
    print(f"   连接成功，{len(ctx.pages)}个页面\n")

    # 通过goku登录一家店
    print("2. Goku登录...")
    ext = await get_ext(ctx)
    ok, status = await pick_brand(ext, brand)
    if not ok:
        print(f"   品牌 {brand} 未找到")
        kill_headless()
        await pw.stop()
        return

    stores = await get_stores(ext)
    print(f"   {brand}: {len(stores)}家店")

    # 找第一个美团账号
    target_acct = None
    target_store = None
    for store_key, accounts in stores.items():
        for acct in accounts:
            if acct['platform'] == 'meituan' and acct['action'] == '一键登录':
                target_acct = acct
                target_store = store_key
                break
        if target_acct:
            break

    if not target_acct:
        print("   没找到美团店铺")
        kill_headless()
        await pw.stop()
        return

    print(f"   登录: {target_store} / {target_acct['account']}")
    result = await click_store_platform(ext, target_acct['account'])
    print(f"   结果: {result}")
    await asyncio.sleep(4)

    # 找到美团页面
    mt_page = None
    for p in ctx.pages:
        if 'waimai.meituan.com' in p.url and 'chrome-extension' not in p.url:
            mt_page = p
            break

    if not mt_page:
        print("   美团页面未打开")
        kill_headless()
        await pw.stop()
        return

    print(f"   美团页面: {mt_page.url[:60]}\n")

    # 3. 从浏览器context抓cookies
    print("3. 抓cookies...")
    all_cookies = await ctx.cookies()
    mt_cookies = [c for c in all_cookies if 'meituan' in c.get('domain', '')]
    print(f"   总cookies: {len(all_cookies)}, 美团cookies: {len(mt_cookies)}")

    # 显示美团cookie域名
    mt_domains = {}
    for c in mt_cookies:
        d = c.get('domain', '')
        mt_domains[d] = mt_domains.get(d, 0) + 1
    for d, n in sorted(mt_domains.items()):
        print(f"   {d}: {n}个")

    # 关键cookie
    for c in mt_cookies:
        if any(k in c['name'].lower() for k in ['token', 'session', 'poi', 'wmpoiid', 'acctid', 'wpush_server']):
            print(f"   KEY: {c['name']} = {c['value'][:60]}")

    # 4. 先用playwright跑一遍fast_mt拿到正确数据做对比
    print("\n4. Playwright对照组（fast_mt）...")
    from run_fast import fast_mt
    try:
        pl_issues = await fast_mt(mt_page)
        pl_notices = pl_issues.get('notices', [])
        pl_bad = pl_issues.get('bad', [])
        print(f"   通知: {len(pl_notices)}条, 差评: {len(pl_bad)}条")
        for n in pl_notices[:3]:
            print(f"     通知: {n.get('title','')}")
        for b in pl_bad[:3]:
            print(f"     差评: {b.get('stars','')}星 {b.get('comment','')[:30]}")
    except Exception as e:
        print(f"   fast_mt失败: {e}")
        pl_notices = []
        pl_bad = []

    # 5. 关闭页面，用纯HTTP请求测试
    print("\n5. 关闭页面，纯HTTP测试...")
    try:
        await mt_page.close()
    except:
        pass

    cookie_header = '; '.join(f"{c['name']}={c['value']}" for c in mt_cookies)
    headers = {
        'Cookie': cookie_header,
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Referer': 'https://e.waimai.meituan.com/new_fe/business_gw',
    }
    s = requests.Session()
    s.trust_env = False

    # 5a. 通知API
    print("\n   --- 美团通知API ---")
    notice_urls = [
        "https://e.waimai.meituan.com/gw/message/category/list",
        "https://e.waimai.meituan.com/api/v2/message/category/list",
        "https://e.waimai.meituan.com/new_fe/api/message/category/list",
    ]
    for url in notice_urls:
        try:
            resp = s.get(url, headers=headers, timeout=10)
            print(f"   {url.split('.com')[1]}")
            print(f"   状态: {resp.status_code}, 长度: {len(resp.text)}")
            if resp.status_code == 200 and 'json' in resp.headers.get('content-type', ''):
                data = resp.json()
                notices = data.get('data', {}).get('wmENoticeResults', [])
                print(f"   通知数: {len(notices)}")
                for n in notices[:3]:
                    print(f"     {n.get('title','')} [{n.get('categoryName','')}]")
                if notices:
                    print(f"   PASS - cookie有效!")
                    break
            elif resp.status_code == 200:
                # 可能是HTML重定向到登录页
                if '登录' in resp.text[:500] or 'login' in resp.text[:500].lower():
                    print(f"   FAIL - 被重定向到登录页（cookie无效）")
                else:
                    print(f"   响应: {resp.text[:200]}")
        except Exception as e:
            print(f"   异常: {e}")

    # 5b. 差评API
    print("\n   --- 美团差评API ---")
    review_urls = [
        "https://e.waimai.meituan.com/gw/comment/list",
        "https://waimaieapp.meituan.com/frontweb/comment/list",
    ]
    for url in review_urls:
        try:
            resp = s.get(url, headers=headers, timeout=10, params={'pageSize': 10, 'pageNum': 1})
            print(f"   {url.split('.com')[1]}")
            print(f"   状态: {resp.status_code}, 长度: {len(resp.text)}")
            if resp.status_code == 200 and 'json' in resp.headers.get('content-type', ''):
                data = resp.json()
                if data.get('data'):
                    reviews = data['data'].get('list', [])
                    print(f"   评价数: {len(reviews)}")
                    for r in reviews[:3]:
                        print(f"     {r.get('orderCommentScore','')}星 {r.get('cleanComment','')[:30]}")
                    if reviews:
                        print(f"   PASS!")
                        break
                else:
                    print(f"   data字段: {list(data.keys())}")
                    print(f"   响应: {json.dumps(data, ensure_ascii=False)[:300]}")
            else:
                ct = resp.headers.get('content-type', '')
                print(f"   content-type: {ct}")
                print(f"   响应: {resp.text[:200]}")
        except Exception as e:
            print(f"   异常: {e}")

    # 6. 保存cookies
    cookie_file = os.path.join(os.path.dirname(__file__), "ops-logger", "_store_cookies.json")
    cookie_data = {
        "brand": brand,
        "store": target_store,
        "platform": "meituan",
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "cookies": mt_cookies,
    }
    with open(cookie_file, 'w') as f:
        json.dump(cookie_data, f, ensure_ascii=False, indent=2)
    print(f"\n6. cookies已保存: {cookie_file} ({len(mt_cookies)}个)")

    # 7. 总结
    print(f"\n=== 总结 ===")
    print(f"品牌: {brand}, 店铺: {target_store}")
    print(f"美团cookies: {len(mt_cookies)}个")
    print(f"Playwright对照: {len(pl_notices)}通知, {len(pl_bad)}差评")

    kill_headless()
    await pw.stop()


if __name__ == '__main__':
    asyncio.run(main())
