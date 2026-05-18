#!/usr/bin/env python3
"""快速摘要模式 - 只输出有问题的"""
import asyncio, json, subprocess, re, sys, time, statistics
from datetime import datetime, timedelta
from collections import defaultdict, OrderedDict
from playwright.async_api import async_playwright

sys.path.insert(0, '/Users/seth/Downloads/store-monitor')
import monitor
from monitor_eleme import scrape_eleme
from plugin_helper import get_ext, pick_brand, get_stores, click_store_platform, close_store_pages
from promo_check import parse_promo_data, check_promo

YESTERDAY = (datetime.now().replace(hour=0,minute=0,second=0) - timedelta(days=1)).strftime('%Y-%m-%d')
THREE_DAYS = (datetime.now() - timedelta(days=3)).strftime('%Y-%m-%d')
CUTOFF = datetime.now().timestamp() - 3*86400

def sd(d):
    m = re.match(r'\d{4}-(\d{2})-(\d{2})', str(d))
    return f"{int(m.group(1))}月{int(m.group(2))}日" if m else str(d)

async def check_mt(mt):
    """美团快速检查，返回问题dict"""
    issues = {}
    try:
        # 消息
        msgs = await monitor.scrape_messages(mt)
        imp = [m for m in msgs if m.get("ctime",0)>=CUTOFF and '活动到期提醒' not in m.get('title','')
               and ((m.get('category')=='店铺动态' and not re.search(r'【.+】',m.get('title','')) and not any(k in m.get('title','') for k in ['招商','上线','升级','覆盖']))
                    or any(k in m.get('title','') for k in ['到期','失败','超时','变更']))]
        if imp: issues['notices'] = imp

        # 评价
        scores = await monitor.scrape_scores(mt)
        bad = [r for r in scores.get("中差评",[]) if r.get('time','')>=THREE_DAYS]
        if bad: issues['bad'] = bad

        # 活动
        acts = await monitor.scrape_activities(mt)
        exp = [a for a in acts.get("items",[]) if a.get("days_left") is not None and a["days_left"]<=7 and not a.get("auto_extend")]
        if exp: issues['exp'] = exp

        # 推广
        try:
            from promo_check import scrape_mt_promo
            bal, spends = await scrape_mt_promo(mt)
            need, bal, median = check_promo(bal, spends)
            if need: issues['promo'] = {'balance': bal, 'median': median}
        except: pass

        # 店名
        name = await monitor.get_store_name(mt)
        issues['name'] = re.sub(r'(营业中|休息中|歇业中|仅接受预订).*$','',name).strip()
    except Exception as e:
        issues['error'] = str(e)
    return issues

async def check_ele(ele):
    """饿了么快速检查"""
    issues = {}
    try:
        ed = await scrape_eleme(ele)
        if ed:
            issues['name'] = ed.get('店铺名','')
            bad = [r for r in ed.get("中差评",[]) if r.get('time','')>=THREE_DAYS]
            if bad: issues['bad'] = bad
            acts = ed.get("活动",[])
            exp = [a for a in acts if a.get('days_left') is not None and a['days_left']<=7 and a.get('status')=='进行中']
            if exp: issues['exp'] = exp
            # 推广
            try:
                from promo_check import scrape_ele_promo
                bal, spends = await scrape_ele_promo(ele)
                need, bal, median = check_promo(bal, spends)
                if need: issues['promo'] = {'balance': bal, 'median': median}
            except Exception as e:
                print(f"    饿了么推广检查失败: {e}")
    except Exception as e:
        issues['error'] = str(e)
    return issues

async def main():
    brands = sys.argv[1:] if len(sys.argv)>1 else []
    if not brands:
        print("用法: python3 run_summary.py 品牌1 品牌2 ...")
        return

    from browser import launch as launch_browser
    pw = await async_playwright().start()
    b, ctx = await launch_browser(pw)

    t0 = time.time()
    print(f"盯店快速巡检 - {datetime.now().strftime('%Y-%m-%d %H:%M')} | {len(brands)}个品牌")

    all_issues = OrderedDict()  # store_name -> [{platform, type, msg, details}]

    for bi, brand in enumerate(brands):
        print(f"  [{bi+1}/{len(brands)}] {brand}...", end=" ", flush=True)
        await close_store_pages(ctx)
        ext = await get_ext(ctx)
        ok, status = await pick_brand(ext, brand)
        if not ok:
            print(f"❌ {status}")
            all_issues[brand] = [{"platform": "", "type": "error", "msg": status, "details": []}]
            continue

        stores = await get_stores(ext)
        store_count = len(stores)
        print(f"{store_count}家店铺", flush=True)

        for store_key, accounts in stores.items():
            real_name = store_key if not store_key.startswith('_auto_') else brand

            for acct in accounts:
                p = acct['platform']
                p_name = "美团" if p=='meituan' else "饿了么"

                if acct['action'] == '立刻授权':
                    all_issues.setdefault(real_name, []).append(
                        {"platform": p_name, "type": "auth", "msg": "授权失败", "details": []})
                    continue
                if acct['action'] != '一键登录':
                    continue

                await close_store_pages(ctx)
                ext = await get_ext(ctx)
                await pick_brand(ext, brand)
                result = await click_store_platform(ext, acct['account'])
                if result != 'ok': continue
                await asyncio.sleep(6)

                if p == 'meituan':
                    mt = None
                    for pg in ctx.pages:
                        if 'waimai.meituan.com' in pg.url and 'chrome-extension' not in pg.url: mt=pg; break
                    if mt:
                        issues = await check_mt(mt)
                        name = issues.pop('name', real_name)
                        if '*' not in name and '上传' not in name and len(name)>2: real_name = name
                        for itype, data in issues.items():
                            if itype == 'bad':
                                all_issues.setdefault(real_name, []).append(
                                    {"platform": p_name, "type": "bad_review", "msg": f"近3日中差评{len(data)}条", "details": data})
                            elif itype == 'exp':
                                all_issues.setdefault(real_name, []).append(
                                    {"platform": p_name, "type": "expiring", "msg": f"{len(data)}个活动即将到期",
                                     "details": [{"name": a.get('type',''), "days": a.get('days_left','')} for a in data]})
                            elif itype == 'notices':
                                all_issues.setdefault(real_name, []).append(
                                    {"platform": p_name, "type": "notice", "msg": f"{len(data)}条通知",
                                     "details": [m.get('title','')[:20] for m in data]})
                            elif itype == 'promo':
                                all_issues.setdefault(real_name, []).append(
                                    {"platform": p_name, "type": "promo",
                                     "msg": f"推广余额不足：{data['balance']}元/日消费{data['median']}元", "details": []})
                        try: await mt.close()
                        except: pass

                elif p == 'eleme':
                    ele = None
                    for pg in ctx.pages:
                        if 'ele.me' in pg.url and 'melody' in pg.url: ele=pg; break
                    if ele:
                        issues = await check_ele(ele)
                        name = issues.pop('name', '')
                        if name: real_name = name
                        for itype, data in issues.items():
                            if itype == 'bad':
                                all_issues.setdefault(real_name, []).append(
                                    {"platform": p_name, "type": "bad_review", "msg": f"近3日中差评{len(data)}条", "details": data})
                            elif itype == 'exp':
                                all_issues.setdefault(real_name, []).append(
                                    {"platform": p_name, "type": "expiring", "msg": f"{len(data)}个活动即将到期",
                                     "details": [{"name": a.get('title',''), "days": a.get('days_left','')} for a in data]})
                            elif itype == 'promo':
                                all_issues.setdefault(real_name, []).append(
                                    {"platform": p_name, "type": "promo",
                                     "msg": f"推广余额不足：{data['balance']}元/日消费{data['median']}元", "details": []})
                        try: await ele.close()
                        except: pass

    # 输出摘要
    total = time.time() - t0
    print(f"\n{'='*60}")
    print(f"摘要 | {len(brands)}个品牌 | {total:.0f}秒")
    print(f"{'='*60}")

    if all_issues:
        for store, items in all_issues.items():
            print(f"\n  ⚠️ {store}")
            for item in items:
                icon = {"promo":"💰","bad_review":"📊","expiring":"🎯","notice":"📬","auth":"🔒","error":"❌"}.get(item['type'],'⚠️')
                print(f"     {icon} {item['platform']} {item['msg']}")
                for d in item.get('details', []):
                    if isinstance(d, dict):
                        if d.get('comment'):
                            print(f"       [{d['stars']}星] {sd(d.get('time',''))} — {d['comment'][:30]}")
                        elif d.get('name'):
                            print(f"       {d['name']} 剩{d['days']}天")
                    elif isinstance(d, str) and d:
                        print(f"       {d}")
    else:
        print(f"\n  ✅ 所有店铺运营正常，无异常")

    print(f"\n巡检完成")
    await pw.stop()

if __name__ == "__main__":
    asyncio.run(main())
