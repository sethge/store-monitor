#!/usr/bin/env python3
"""极速摘要 - 目标15秒/店"""
import asyncio, json, subprocess, re, sys, time, statistics
from datetime import datetime, timedelta
from collections import OrderedDict
from playwright.async_api import async_playwright

sys.path.insert(0, '/Users/seth/Downloads/store-monitor')
from plugin_helper import get_ext, pick_brand, get_stores, click_store_platform, close_store_pages
from promo_check import parse_promo_data, check_promo

THREE_DAYS = (datetime.now() - timedelta(days=3)).strftime('%Y-%m-%d')
CUTOFF = datetime.now().timestamp() - 3*86400

def sd(d):
    m = re.match(r'\d{4}-(\d{2})-(\d{2})', str(d))
    return f"{int(m.group(1))}月{int(m.group(2))}日" if m else str(d)


async def fast_mt(page):
    """美团极速检查 ~15s"""
    issues = {}
    captured = {}
    checked = {"msgs": False, "reviews": False, "promo": False}  # 跟踪是否成功

    async def on_resp(resp):
        url = resp.url
        try:
            ct = resp.headers.get('content-type','')
            if 'json' not in ct: return
            if 'message/category/list' in url:
                captured['msgs'] = await resp.json()
            elif 'comment/list?' in url:
                d = await resp.json()
                if d.get('success'):
                    captured.setdefault('reviews', []).extend(d['data'].get('list', []))
            elif 'account/info' in url:
                captured['balance'] = await resp.json()
        except: pass

    page.on("response", on_resp)

    # 1. 消息
    await page.goto("https://e.waimai.meituan.com/new_fe/business_gw#/msgbox", wait_until="commit", timeout=15000)
    await asyncio.sleep(1)

    # 2. 评价 - 直接去评价页，用Flutter PointerEvent点差评tab (8s)
    await page.goto("https://e.waimai.meituan.com/#https://waimaieapp.meituan.com/frontweb/ffw/userComment_gw", wait_until="commit", timeout=15000)
    await asyncio.sleep(1)
    # Flutter点击评价列表tab + 差评筛选
    for f in page.frames:
        try:
            has = await f.evaluate("() => !!document.querySelector('flt-glass-pane')")
            if not has: continue
            # 点评价列表
            await f.evaluate("""() => {
                const glass = document.querySelector('flt-glass-pane');
                const spans = glass.shadowRoot.querySelectorAll('flt-span, span');
                for (const s of spans) {
                    if (s.textContent?.trim() === '外卖评价列表') {
                        const r = s.getBoundingClientRect();
                        glass.dispatchEvent(new PointerEvent('pointerdown',{clientX:r.x+r.width/2,clientY:r.y+r.height/2,bubbles:true,pointerId:1,pointerType:'mouse'}));
                        glass.dispatchEvent(new PointerEvent('pointerup',{clientX:r.x+r.width/2,clientY:r.y+r.height/2,bubbles:true,pointerId:1,pointerType:'mouse'}));
                        return;
                    }
                }
            }""")
            await asyncio.sleep(1.5)
            # 点差评筛选
            for filter_name in ['差评(含1-2星打分项)', '中评(含3星打分项)']:
                await f.evaluate(f"""() => {{
                    const glass = document.querySelector('flt-glass-pane');
                    const spans = glass.shadowRoot.querySelectorAll('flt-span, span');
                    for (const s of spans) {{
                        if (s.textContent?.trim() === '{filter_name}') {{
                            const r = s.getBoundingClientRect();
                            glass.dispatchEvent(new PointerEvent('pointerdown',{{clientX:r.x+r.width/2,clientY:r.y+r.height/2,bubbles:true,pointerId:1,pointerType:'mouse'}}));
                            glass.dispatchEvent(new PointerEvent('pointerup',{{clientX:r.x+r.width/2,clientY:r.y+r.height/2,bubbles:true,pointerId:1,pointerType:'mouse'}}));
                            return;
                        }}
                    }}
                }}""")
                await asyncio.sleep(1)
            break
        except: pass

    # 3. 推广 - 等iframe加载后点消费记录
    await page.goto("https://e.waimai.meituan.com/#https://waimaieapp.meituan.com/ad/v1/pc", wait_until="commit", timeout=15000)
    for attempt in range(6):
        await asyncio.sleep(1)
        for f in page.frames:
            if 'ad' in f.url and 'waimaieapp' in f.url:
                try:
                    text = await f.evaluate("() => document.body.innerText")
                    if '消费记录' in text:
                        await f.evaluate("""() => {
                            document.querySelectorAll('*').forEach(el => {
                                if (el.textContent?.trim() === '消费记录' && el.children.length === 0 && el.offsetParent) el.click();
                            });
                        }""")
                        await asyncio.sleep(1)
                        captured['promo_text'] = await f.evaluate("() => document.body.innerText")
                except: pass
                break
        if 'promo_text' in captured: break

    page.remove_listener("response", on_resp)

    # 标记成功
    checked['msgs'] = 'msgs' in captured
    checked['reviews'] = len(captured.get('reviews', [])) > 0
    checked['promo'] = 'promo_text' in captured and len(captured.get('promo_text', '')) > 100

    # 解析
    name = ""
    for r in captured.get('reviews', []):
        if r.get('poiName'): name = r['poiName']; break

    # 差评
    bad = []
    for r in captured.get('reviews', []):
        star = r.get('orderCommentScore', 5)
        if star <= 3:
            create = r.get('createTime', '')
            if create >= THREE_DAYS:
                bad.append({'stars': star, 'time': create,
                           'comment': r.get('cleanComment', r.get('comment', '')),
                           'foods': [f.get('foodName','') for f in r.get('orderDetails', [])]})
    if bad: issues['bad'] = bad

    # 通知
    msgs_data = captured.get('msgs', {}).get('data', {}).get('wmENoticeResults', [])
    imp = []
    for m in msgs_data:
        if m.get('ctime', 0) < CUTOFF: continue
        t, c = m.get('title',''), m.get('categoryName','')
        if '活动到期提醒' in t: continue
        if '发票' in t: continue
        content = re.sub(r'<[^>]+>', '', m.get('content', m.get('preView', ''))).strip()
        if content.startswith('http'): content = m.get('preView', '')
        from datetime import datetime as _dt
        mtime = _dt.fromtimestamp(m.get('ctime',0)).strftime('%Y-%m-%d') if m.get('ctime') else ''
        if c == '店铺动态':
            if re.search(r'【.+】', t) or any(k in t for k in ['招商','上线','升级','覆盖']): continue
            imp.append({"title": t, "content": content[:80], "category": c, "time": mtime})
        elif any(k in t for k in ['到期','失败','超时','变更']):
            imp.append({"title": t, "content": content[:80], "category": c, "time": mtime})
    if imp: issues['notices'] = imp

    # 推广
    pt = captured.get('promo_text', '')
    if pt:
        bal, spends = parse_promo_data(pt)
        need, bal, median = check_promo(bal, spends)
        if need: issues['promo'] = {'balance': bal, 'median': median}

    # 未成功加载的项目标记
    missing = [k for k, v in checked.items() if not v]
    if missing: issues['incomplete'] = missing

    issues['name'] = name
    return issues


async def fast_ele(page):
    """饿了么极速检查 ~12s"""
    issues = {}
    captured = {}
    checked = {"reviews": False, "acts": False, "promo": False}
    m = re.search(r'/shop/(\d+)/', page.url)
    shop_id = m.group(1) if m else ""

    async def on_resp(resp):
        url = resp.url
        try:
            ct = resp.headers.get('content-type','')
            if 'json' not in ct: return
            if 'getRateResult' in url:
                captured['reviews'] = await resp.json()
            elif 'getShopRateStatsV2' in url:
                captured['stats'] = await resp.json()
            elif 'method=MarketingCenterService.getActivities' in url and 'ByDate' not in url and 'Entrance' not in url:
                captured['acts'] = await resp.json()
            elif 'getActivitiesByDate' in url:
                captured['acts_date'] = await resp.json()
        except: pass

    page.on("response", on_resp)

    # 1. 评价 (4s)
    await page.goto(f"https://melody.shop.ele.me/app/shop/{shop_id}/comments#app.shop.comments", wait_until="commit", timeout=15000)
    await asyncio.sleep(1.5)

    # 2. 活动 - 我的活动 (4s)
    await page.goto(f"https://melody.shop.ele.me/app/shop/{shop_id}/activity__index#app.shop.activity.index", wait_until="commit", timeout=15000)
    await asyncio.sleep(1)
    for f in page.frames:
        try:
            await f.evaluate("""() => {
                document.querySelectorAll('span, a, div').forEach(el => {
                    if (el.textContent?.trim() === '我的活动' && el.offsetParent) el.click();
                });
            }""")
        except: pass
    await asyncio.sleep(1)
    # 还要点"进行中"tab
    for f in page.frames:
        try:
            await f.evaluate("""() => {
                document.querySelectorAll('span, div').forEach(el => {
                    if (el.textContent?.trim() === '进行中' && el.offsetParent) el.click();
                });
            }""")
        except: pass
    await asyncio.sleep(1)

    page.remove_listener("response", on_resp)

    # 3. 推广 (4s)
    await page.goto(f"https://melody.shop.ele.me/app/shop/{shop_id}/vas#app.shop.vas", wait_until="commit", timeout=15000)
    await asyncio.sleep(1.5)
    promo_text = ""
    for f in page.frames:
        try:
            text = await f.evaluate("() => document.body.innerText")
            if '消费记录' in text:
                await f.evaluate("""() => {
                    document.querySelectorAll('*').forEach(el => {
                        if (el.textContent?.trim() === '消费记录' && el.children.length === 0 && el.offsetParent) el.click();
                    });
                }""")
                await asyncio.sleep(1)
                promo_text = await f.evaluate("() => document.body.innerText")
                break
        except: pass

    # 标记成功
    checked['reviews'] = 'reviews' in captured
    checked['acts'] = 'acts' in captured or 'acts_date' in captured
    checked['promo'] = len(promo_text) > 100

    # 解析
    name = ""
    reviews = captured.get('reviews', {}).get('result', {}).get('rateInfos', [])
    if reviews:
        name = reviews[0].get('shopName', '')

    bad = []
    for r in reviews:
        oi = r.get('orderRateInfos', [{}])[0]
        star = oi.get('qualityRating', 5)
        rtime = (oi.get('ratingAt','') or '')[:10]
        if star <= 3 and rtime >= THREE_DAYS:
            bad.append({'stars': star, 'time': rtime, 'comment': oi.get('ratingContent','') or '', 'foods': r.get('itemNames') or []})
    if bad: issues['bad'] = bad

    # 活动到期 — 优先getActivities，fallback getActivitiesByDate
    act_list = captured.get('acts', {}).get('result', {}).get('activities', [])
    if not act_list:
        act_list = captured.get('acts_date', {}).get('result', {}).get('activities', [])
    exp = []
    for a in act_list:
        dm = re.search(r'至\s*(\d{4}-\d{2}-\d{2})', a.get('date',''))
        if dm:
            from datetime import date
            try:
                days = (date.fromisoformat(dm.group(1)) - datetime.now().date()).days
                if days <= 7:
                    exp.append({'name': a.get('title',''), 'days': days})
            except: pass
    if exp: issues['exp'] = exp

    # 推广
    if promo_text:
        bal, spends = parse_promo_data(promo_text)
        need, bal, median = check_promo(bal, spends)
        if need: issues['promo'] = {'balance': bal, 'median': median}

    missing = [k for k, v in checked.items() if not v]
    if missing: issues['incomplete'] = missing

    issues['name'] = name
    return issues


async def main():
    brands = sys.argv[1:] if len(sys.argv) > 1 else []
    if not brands:
        print("用法: python3 run_fast.py 品牌1 品牌2 ...")
        return

    r = subprocess.run(["curl","--noproxy","localhost","-s","http://localhost:9222/json/version"], capture_output=True, text=True, timeout=5)
    ws = json.loads(r.stdout)["webSocketDebuggerUrl"]
    pw = await async_playwright().start()
    b = await pw.chromium.connect_over_cdp(ws)
    ctx = b.contexts[0]

    t0 = time.time()
    print(f"盯店巡检 - {datetime.now().strftime('%Y-%m-%d %H:%M')} | {len(brands)}个品牌")

    all_issues = OrderedDict()

    for bi, brand in enumerate(brands):
        t_brand = time.time()
        print(f"  [{bi+1}/{len(brands)}] {brand}...", end=" ", flush=True)

        await close_store_pages(ctx)
        ext = await get_ext(ctx)
        ok, status = await pick_brand(ext, brand)
        if not ok:
            print(f"❌")
            all_issues[brand] = [{"platform":"","type":"error","msg":status,"details":[]}]
            continue

        stores = await get_stores(ext)
        print(f"{len(stores)}店", end=" ", flush=True)

        brand_short = brand.split("（")[0]  # "仙云居小笼包"

        for store_key, accounts in stores.items():
            real_name = store_key if not store_key.startswith('_auto_') else ""

            def display_name():
                """确保店名有品牌前缀，避免歧义"""
                n = real_name or brand
                # 如果名字太短或不含品牌关键词，加品牌前缀
                if n and len(n) <= 6 and brand_short not in n:
                    return f"{brand_short}·{n}"
                if n and '店' in n and brand_short not in n and len(n) < 15:
                    return f"{brand_short}·{n}"
                return n

            for acct in accounts:
                p, p_name = acct['platform'], "美团" if acct['platform']=='meituan' else "饿了么"

                if acct['action'] == '立刻授权':
                    all_issues.setdefault(display_name(), []).append(
                        {"platform": p_name, "type": "auth", "msg": "授权失败", "details": []})
                    continue
                if acct['action'] != '一键登录': continue

                await close_store_pages(ctx)
                ext = await get_ext(ctx)
                await pick_brand(ext, brand)
                result = await click_store_platform(ext, acct['account'])
                if result != 'ok': continue
                await asyncio.sleep(3)

                if p == 'meituan':
                    pg = None
                    for x in ctx.pages:
                        if 'waimai.meituan.com' in x.url and 'chrome-extension' not in x.url: pg=x; break
                    if pg:
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
                            elif k=='incomplete':
                                label = '/'.join({'msgs':'通知','reviews':'评价','promo':'推广'}.get(x,x) for x in v)
                                all_issues.setdefault(display_name(), []).append({"platform":p_name,"type":"incomplete","msg":f"数据未完整加载（{label}），需人工确认","details":[]})
                        try: await pg.close()
                        except: pass

                elif p == 'eleme':
                    pg = None
                    for x in ctx.pages:
                        if 'ele.me' in x.url and 'melody' in x.url: pg=x; break
                    if pg:
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
                            elif k=='incomplete':
                                label = '/'.join({'reviews':'评价','acts':'活动','promo':'推广'}.get(x,x) for x in v)
                                all_issues.setdefault(display_name(), []).append({"platform":p_name,"type":"incomplete","msg":f"数据未完整加载（{label}），需人工确认","details":[]})
                        try: await pg.close()
                        except: pass

        elapsed = time.time() - t_brand
        print(f"{elapsed:.0f}s")

    # === 清理：incomplete的如果只有推广没加载，标记为"推广无数据" ===
    # 不做补跑了，等待时间已加长，如果还是没加载就是真的没推广数据
    for store in list(all_issues.keys()):
        items = all_issues[store]
        new_items = [i for i in items if i['type'] != 'incomplete']
        if len(new_items) < len(items):
            # 有incomplete被移除了，如果没剩其他问题就删掉这个店
            if not new_items:
                del all_issues[store]
            else:
                all_issues[store] = new_items

    total = time.time() - t0
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
    await pw.stop()

if __name__ == "__main__":
    asyncio.run(main())
