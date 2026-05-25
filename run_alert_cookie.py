#!/usr/bin/env python3
"""
Cookie切店预警 — 复用巡检存的cookie快照，不开新页面
流程：加载cookie快照 → 复用1个tab逐店切cookie+检查通知 → 失败的走goku重登
"""
import asyncio, json, sys, os, re, time
sys.path.insert(0, os.path.dirname(__file__))

from datetime import datetime, timedelta, timezone
_CN_TZ = timezone(timedelta(hours=8))
from collections import OrderedDict
from playwright.async_api import async_playwright
from plugin_helper import get_ext, pick_brand, get_stores, click_store_platform, close_store_pages
from browser import launch_headless, kill_headless
import patrol_log as L

OPS_DIR = os.path.join(os.path.dirname(__file__), "ops-logger")
SNAP_FILE = os.path.join(OPS_DIR, "_cookie_snapshots.json")
CUTOFF = int((datetime.now(_CN_TZ) - timedelta(days=3)).timestamp())


def _post_progress(brand, issues, done, total):
    """通知server增量进度"""
    import requests as _req
    try:
        s = _req.Session()
        s.trust_env = False
        s.post("http://127.0.0.1:5500/api/patrol/progress", json={
            "brand": brand, "issues": issues,
            "brand_stores": {}, "all_stores": {},
            "done": done, "total": total,
        }, timeout=3)
    except Exception:
        pass


async def switch_cookies(ctx, snapshot):
    """切换到指定店铺的cookie"""
    cookies_to_set = []
    for c in snapshot['cookies']:
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
    """访问通知页，拦截API，返回 (notices_list | None, status)"""
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
        await page.goto("about:blank", wait_until="commit", timeout=5000)
        await asyncio.sleep(0.3)
        await page.goto(
            "https://e.waimai.meituan.com/new_fe/business_gw#/msgbox",
            wait_until="commit", timeout=15000
        )
        await asyncio.sleep(3)
    except Exception:
        pass
    page.remove_listener("response", on_resp)

    if 'login' in page.url.lower() or 'passport' in page.url.lower():
        return None, "login_redirect"

    if not captured.get('msgs'):
        return None, "no_api_response"

    msgs_data = captured.get('msgs', {}).get('data', {}).get('wmENoticeResults', [])
    notices = []
    for m in msgs_data:
        if m.get('ctime', 0) < CUTOFF:
            continue
        t, c = m.get('title', ''), m.get('categoryName', '')
        if any(k in t for k in ['活动到期提醒', '发票', '预订单', '粉丝群']):
            continue
        content = re.sub(r'<[^>]+>', '', m.get('content', m.get('preView', ''))).strip()
        if content.startswith('http'):
            content = m.get('preView', '')
        mtime = datetime.fromtimestamp(m.get('ctime', 0)).strftime('%Y-%m-%d %H:%M') if m.get('ctime') else ''
        if c == '店铺动态':
            if re.search(r'【.+】', t) or any(k in t for k in ['招商', '上线', '升级', '覆盖']):
                continue
            notices.append({"title": t, "content": content[:80], "time": mtime})
        elif any(k in t for k in ['到期', '失败', '超时', '变更']):
            notices.append({"title": t, "content": content[:80], "time": mtime})
    return notices, "ok"


async def goku_relogin(ctx, ext, brand, account):
    """Goku重新登录单家店，返回新cookie快照或None"""
    try:
        await close_store_pages(ctx)
        ok, _ = await pick_brand(ext, brand)
        if not ok:
            return None
        await get_stores(ext)
        result = await click_store_platform(ext, account)
        if result != 'ok':
            return None
        await asyncio.sleep(3)

        mt_page = None
        for p in ctx.pages:
            if 'waimai.meituan.com' in p.url and 'chrome-extension' not in p.url:
                mt_page = p
                break
        if not mt_page:
            return None

        all_ck = await ctx.cookies()
        mt_ck = [c for c in all_ck if 'meituan' in c.get('domain', '')]
        key_vals = {}
        for c in mt_ck:
            if c['name'] in ('wmPoiId', 'acctId', 'token', 'JSESSIONID'):
                key_vals[c['name']] = c['value']

        try:
            await mt_page.close()
        except:
            pass

        return {
            "brand": brand,
            "account": account,
            "platform": "meituan",
            "key_vals": key_vals,
            "cookies": mt_ck,
        }
    except Exception as e:
        print(f"  goku重登异常: {e}")
        return None


async def main():
    import argparse
    parser = argparse.ArgumentParser(description='Cookie切店预警')
    parser.add_argument('brands', nargs='*', help='品牌名（过滤用，空=全部）')
    parser.add_argument('--headless', action='store_true')
    parser.add_argument('--operator', default='')
    args = parser.parse_args()

    L.start()

    # 加载cookie快照
    if not os.path.exists(SNAP_FILE):
        print("无cookie快照，需先运行巡检")
        sys.exit(1)

    with open(SNAP_FILE) as f:
        snapshots = json.load(f)

    # 按品牌过滤
    if args.brands:
        snapshots = [s for s in snapshots if s.get('brand') in args.brands]

    if not snapshots:
        print("无匹配的cookie快照")
        sys.exit(1)

    print(f"Cookie预警: {len(snapshots)}家店")
    t_start = time.time()

    pw = await async_playwright().start()
    browser, ctx = await launch_headless(pw)

    # 开一个复用tab
    reuse_page = await ctx.new_page()
    ext = None  # 懒加载，只在需要goku时初始化

    all_issues = OrderedDict()
    success = 0
    fail = 0
    goku_count = 0
    updated_snapshots = list(snapshots)  # 可能更新的快照

    for i, snap in enumerate(snapshots):
        store = snap.get('store', '?')
        brand = snap.get('brand', '?')
        poi_id = snap.get('key_vals', {}).get('wmPoiId', '?')

        print(f"  [{store}] (poi={poi_id})", end=" ", flush=True)

        await switch_cookies(ctx, snap)
        notices, status = await check_notifications(reuse_page)

        if status == "ok":
            print(f"OK — {len(notices)}条通知")
            if notices:
                all_issues.setdefault(store, []).append({
                    "platform": "美团",
                    "type": "notice",
                    "msg": f"{len(notices)}条通知",
                    "details": notices,
                })
            success += 1
        else:
            # cookie失效 → goku兜底（只登这一家）
            account = snap.get('account', '')
            print(f"FAIL({status}) → goku重登 {brand}...", end=" ", flush=True)

            if not ext:
                ext = await get_ext(ctx)

            new_snap = await goku_relogin(ctx, ext, brand, account)
            if new_snap:
                new_snap['store'] = store
                updated_snapshots[i] = new_snap
                await switch_cookies(ctx, new_snap)
                notices2, status2 = await check_notifications(reuse_page)
                if status2 == "ok":
                    print(f"OK(重登) — {len(notices2)}条通知")
                    if notices2:
                        all_issues.setdefault(store, []).append({
                            "platform": "美团",
                            "type": "notice",
                            "msg": f"{len(notices2)}条通知",
                            "details": notices2,
                        })
                    success += 1
                    goku_count += 1
                else:
                    print(f"重登后仍失败({status2})")
                    fail += 1
            else:
                print(f"goku重登失败")
                fail += 1

        # 每完成一个品牌组，推送进度
        _post_progress(brand, dict(all_issues), i + 1, len(snapshots))

    try:
        await reuse_page.close()
    except:
        pass

    total_time = time.time() - t_start
    print(f"\n预警完成: {success}成功 {fail}失败 {goku_count}次goku兜底 {total_time:.0f}秒")

    # 更新cookie快照（goku重登的已更新）
    if goku_count > 0:
        with open(SNAP_FILE, 'w') as f:
            json.dump(updated_snapshots, f, ensure_ascii=False, indent=2)
        print(f"Cookie快照已更新({goku_count}个重登)")

    # 保存预警结果
    result_file = os.path.join(OPS_DIR, "patrol_result.json")
    try:
        # 合并到现有结果（不覆盖巡检数据，只更新通知）
        existing = {}
        if os.path.exists(result_file):
            with open(result_file) as f:
                existing = json.load(f)

        # 更新通知类issue
        existing_issues = existing.get("issues", {})
        for store, items in all_issues.items():
            # 替换该店的通知类issue
            store_items = existing_issues.get(store, [])
            store_items = [it for it in store_items if it.get("type") != "notice"]
            store_items.extend(items)
            existing_issues[store] = store_items

        existing["issues"] = existing_issues
        existing["alert_ts"] = datetime.now(_CN_TZ).strftime("%Y-%m-%d %H:%M")
        with open(result_file, "w") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"保存结果失败: {e}")

    kill_headless()
    await pw.stop()


if __name__ == '__main__':
    asyncio.run(main())
