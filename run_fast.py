#!/usr/bin/env python3
"""极速摘要 - 目标15秒/店
支持 --watch 预警模式：定时循环巡检，同一条问题当天不重复报
支持 --watch-once 单轮预警：跑一轮就退出（供cron调度使用）

用法:
  python3 run_fast.py 品牌1 品牌2                          # 跑一次
  python3 run_fast.py --watch 09:00-22:00 品牌1 品牌2       # 预警模式，默认10分钟一轮
  python3 run_fast.py --watch 09:00-22:00 -i 5 品牌1        # 5分钟一轮
  python3 run_fast.py --watch-once 品牌1 品牌2               # 单轮预警（cron调度用）
"""
import asyncio, json, subprocess, re, sys, time, statistics, argparse, os
from datetime import datetime, timedelta
from pathlib import Path
from collections import OrderedDict
from pathlib import Path
from playwright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).parent))
from plugin_helper import get_ext, pick_brand, get_stores, click_store_platform, close_store_pages, check_verification
from promo_check import parse_promo_data, check_promo

THREE_DAYS = (datetime.now() - timedelta(days=3)).strftime('%Y-%m-%d')
CUTOFF = datetime.now().timestamp() - 3*86400

WATCH_SNAPSHOT = Path(__file__).parent / "data" / "last_watch.json"

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


async def watch_mt(page):
    """美团预警 - 只抓通知，不跑评价/活动/推广，~3s"""
    captured = {}

    async def on_resp(resp):
        try:
            ct = resp.headers.get('content-type', '')
            if 'json' not in ct: return
            if 'message/category/list' in resp.url:
                captured['msgs'] = await resp.json()
        except: pass

    page.on("response", on_resp)
    await page.goto("https://e.waimai.meituan.com/new_fe/business_gw#/msgbox", wait_until="commit", timeout=15000)
    await asyncio.sleep(2)
    page.remove_listener("response", on_resp)

    # 用和 fast_mt 完全相同的过滤规则
    msgs_data = captured.get('msgs', {}).get('data', {}).get('wmENoticeResults', [])
    notices = []
    for m in msgs_data:
        if m.get('ctime', 0) < CUTOFF: continue
        t, c = m.get('title', ''), m.get('categoryName', '')
        if '活动到期提醒' in t: continue
        if '发票' in t: continue
        content = re.sub(r'<[^>]+>', '', m.get('content', m.get('preView', ''))).strip()
        if content.startswith('http'): content = m.get('preView', '')
        mtime = datetime.fromtimestamp(m.get('ctime', 0)).strftime('%Y-%m-%d %H:%M') if m.get('ctime') else ''
        if c == '店铺动态':
            if re.search(r'【.+】', t) or any(k in t for k in ['招商', '上线', '升级', '覆盖']): continue
            notices.append({"title": t, "content": content[:80], "time": mtime})
        elif any(k in t for k in ['到期', '失败', '超时', '变更']):
            notices.append({"title": t, "content": content[:80], "time": mtime})
    return notices


async def watch_ele(page):
    """饿了么预警 - 只抓首页重要待办，~3s"""
    m = re.search(r'/shop/(\d+)/', page.url)
    shop_id = m.group(1) if m else ""
    if not shop_id: return []

    await page.goto(f"https://melody.shop.ele.me/app/shop/{shop_id}/dashboard#app.shop.dashboard", wait_until="commit", timeout=15000)
    await asyncio.sleep(2)

    todos = []
    for f in page.frames:
        try:
            text = await f.evaluate("() => document.body.innerText")
            if '重要待办' in text or '待办' in text:
                lines = text.split('\n')
                in_todo = False
                for line in lines:
                    line = line.strip()
                    if '重要待办' in line:
                        in_todo = True
                        continue
                    if in_todo and line and len(line) > 2 and line != '暂无待办':
                        if any(kw in line for kw in ['商家成长', '平台消息', '活动中心', '今日营业']):
                            break
                        if '查看' not in line and len(line) > 3:
                            todos.append({"title": line, "content": "", "time": ""})
                if '暂无待办' in text:
                    break
                break
        except: pass
    return todos


def print_issues(all_issues):
    """打印问题摘要"""
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


def notices_to_keys(all_notices):
    """通知去重key：用标题+内容"""
    keys = set()
    for store, items in all_notices.items():
        for item in items:
            for n in item.get('notices', []):
                keys.add(f"{store}|{item['platform']}|{n['title']}")
    return keys


def load_watch_snapshot():
    """加载快照，隔天自动清空"""
    if WATCH_SNAPSHOT.exists():
        snap = json.loads(WATCH_SNAPSHOT.read_text())
        if snap.get('date') == datetime.now().strftime('%Y-%m-%d'):
            return set(snap.get('seen_keys', []))
    return set()


def save_watch_snapshot(seen_keys):
    WATCH_SNAPSHOT.parent.mkdir(exist_ok=True)
    WATCH_SNAPSHOT.write_text(json.dumps({
        "date": datetime.now().strftime('%Y-%m-%d'),
        "seen_keys": list(seen_keys),
        "_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }, ensure_ascii=False))


async def run_once(brands, ctx):
    """跑一轮巡检。先把品牌下所有店所有平台页面全部打开，再并行跑检查"""
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
        brand_short = brand.split("（")[0]

        # Phase 1: 全部打开 — 遍历所有店所有账号，依次点一键登录，不关页面
        all_opened = []  # [(store_key, real_name, platform, page)]
        first_click = True  # 第一次不需要重新pick_brand，外层已经pick过了
        for store_key, accounts in stores.items():
            real_name = store_key if not store_key.startswith('_auto_') else ""

            def _dn(n, bs=brand_short, b=brand):
                n = n or b
                if n and len(n) <= 6 and bs not in n: return f"{bs}·{n}"
                if n and '店' in n and bs not in n and len(n) < 15: return f"{bs}·{n}"
                return n

            for acct in accounts:
                p_name = "美团" if acct['platform']=='meituan' else "饿了么"
                if acct['action'] == '立刻授权':
                    all_issues.setdefault(_dn(real_name), []).append(
                        {"platform": p_name, "type": "auth", "msg": "授权失败", "details": []})
                    continue
                if acct['action'] != '一键登录': continue

                if first_click:
                    first_click = False
                else:
                    ext = await get_ext(ctx)
                    await pick_brand(ext, brand)
                result = await click_store_platform(ext, acct['account'])
                if result != 'ok': continue
                await asyncio.sleep(2)

                if acct['platform'] == 'meituan':
                    for x in ctx.pages:
                        if ('waimai.meituan.com' in x.url or 'verify.meituan.com' in x.url) and 'chrome-extension' not in x.url:
                            blocked, reason = await check_verification(x)
                            if blocked:
                                all_issues.setdefault(_dn(real_name), []).append(
                                    {"platform": p_name, "type": "verify", "msg": reason, "details": []})
                                try: await x.close()
                                except: pass
                            else:
                                all_opened.append((store_key, real_name, 'meituan', x))
                            break
                elif acct['platform'] == 'eleme':
                    for x in ctx.pages:
                        if 'ele.me' in x.url and 'melody' in x.url:
                            blocked, reason = await check_verification(x)
                            if blocked:
                                all_issues.setdefault(_dn(real_name), []).append(
                                    {"platform": p_name, "type": "verify", "msg": reason, "details": []})
                                try: await x.close()
                                except: pass
                            else:
                                all_opened.append((store_key, real_name, 'eleme', x))
                            break

        if not all_opened:
            print(f"{time.time()-t_brand:.0f}s")
            continue

        await asyncio.sleep(1)

        # Phase 2: 并行跑所有检查
        async def _check(store_key, rname, platform, pg):
            if platform == 'meituan':
                issues = await fast_mt(pg)
            else:
                issues = await fast_ele(pg)
            return store_key, rname, platform, issues

        tasks = [_check(sk, rn, p, pg) for sk, rn, p, pg in all_opened]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Phase 3: 收集结果
        # 先从结果中更新 real_name
        name_map = {}  # store_key -> real_name
        for r in results:
            if isinstance(r, Exception): continue
            sk, rn, p, issues = r
            name = issues.get('name', '')
            if name and (p == 'eleme' or '*' not in name):
                name_map[sk] = name
            elif rn:
                name_map.setdefault(sk, rn)

        for r in results:
            if isinstance(r, Exception): continue
            sk, rn, p, issues = r
            real_name = name_map.get(sk, rn)

            def display_name(n=real_name, bs=brand_short, b=brand):
                n = n or b
                if n and len(n) <= 6 and bs not in n: return f"{bs}·{n}"
                if n and '店' in n and bs not in n and len(n) < 15: return f"{bs}·{n}"
                return n

            p_name = "美团" if p == 'meituan' else "饿了么"
            issues.pop('name', '')

            for k, v in issues.items():
                if k=='bad':
                    all_issues.setdefault(display_name(), []).append({"platform":p_name,"type":"bad_review","msg":f"近3日中差评{len(v)}条","details":v})
                elif k=='notices':
                    all_issues.setdefault(display_name(), []).append({"platform":p_name,"type":"notice","msg":f"{len(v)}条通知","details":v})
                elif k=='exp':
                    all_issues.setdefault(display_name(), []).append({"platform":p_name,"type":"expiring","msg":f"{len(v)}个活动即将到期","details":v})
                elif k=='promo':
                    all_issues.setdefault(display_name(), []).append({"platform":p_name,"type":"promo","msg":f"推广余额不足：{v['balance']}元/日消费{v['median']}元","details":[]})
                elif k=='incomplete':
                    labels = {'msgs':'通知','reviews':'评价','promo':'推广','acts':'活动'}
                    label = '/'.join(labels.get(x,x) for x in v)
                    all_issues.setdefault(display_name(), []).append({"platform":p_name,"type":"incomplete","msg":f"数据未完整加载（{label}），需人工确认","details":[]})

        # 关闭所有页面
        for _, _, _, pg in all_opened:
            try: await pg.close()
            except: pass

        elapsed = time.time() - t_brand
        print(f"{elapsed:.0f}s")

    # 清理incomplete
    for store in list(all_issues.keys()):
        items = all_issues[store]
        new_items = [i for i in items if i['type'] != 'incomplete']
        if len(new_items) < len(items):
            if not new_items:
                del all_issues[store]
            else:
                all_issues[store] = new_items

    return all_issues


async def watch_open_all(brands, ctx):
    """预警第一轮：打开所有品牌所有店的页面，返回 (pages列表, 拦截列表)"""
    all_pages = []  # [(display_name, platform, page)]
    blocked_stores = []  # [(display_name, platform_name, reason)]

    for bi, brand in enumerate(brands):
        t_brand = time.time()
        print(f"  [{bi+1}/{len(brands)}] {brand}...", end=" ", flush=True)

        await close_store_pages(ctx)
        ext = await get_ext(ctx)
        ok, status = await pick_brand(ext, brand)
        if not ok:
            print("❌")
            continue

        stores = await get_stores(ext)
        print(f"{len(stores)}店", end=" ", flush=True)
        brand_short = brand.split("（")[0]

        first_click = True
        for store_key, accounts in stores.items():
            real_name = store_key if not store_key.startswith('_auto_') else ""

            def _dn(n=real_name, bs=brand_short, b=brand):
                n = n or b
                if n and len(n) <= 6 and bs not in n: return f"{bs}·{n}"
                if n and '店' in n and bs not in n and len(n) < 15: return f"{bs}·{n}"
                return n

            for acct in accounts:
                if acct['action'] != '一键登录': continue
                if first_click:
                    first_click = False
                else:
                    ext = await get_ext(ctx)
                    await pick_brand(ext, brand)
                result = await click_store_platform(ext, acct['account'])
                if result != 'ok': continue
                await asyncio.sleep(2)

                if acct['platform'] == 'meituan':
                    for x in ctx.pages:
                        if ('waimai.meituan.com' in x.url or 'verify.meituan.com' in x.url) and 'chrome-extension' not in x.url:
                            blocked, reason = await check_verification(x)
                            if blocked:
                                p_name = "美团"
                                print(f"⚠️{_dn()}({p_name}):{reason}", end=" ", flush=True)
                                blocked_stores.append((_dn(), p_name, reason))
                                try: await x.close()
                                except: pass
                            else:
                                all_pages.append((_dn(), 'meituan', x))
                            break
                elif acct['platform'] == 'eleme':
                    for x in ctx.pages:
                        if 'ele.me' in x.url and 'melody' in x.url:
                            blocked, reason = await check_verification(x)
                            if blocked:
                                p_name = "饿了么"
                                print(f"⚠️{_dn()}({p_name}):{reason}", end=" ", flush=True)
                                blocked_stores.append((_dn(), p_name, reason))
                                try: await x.close()
                                except: pass
                            else:
                                all_pages.append((_dn(), 'eleme', x))
                            break

        print(f"{time.time()-t_brand:.0f}s")

    print(f"  共打开 {len(all_pages)} 个页面\n")
    return all_pages, blocked_stores


async def watch_refresh(all_pages):
    """预警后续轮次：并行刷新所有已打开的页面，抓通知。返回 {店名: [{platform, notices}]}"""
    all_notices = OrderedDict()

    async def _refresh(display_name, platform, pg):
        try:
            if pg.is_closed(): return display_name, platform, []
            if platform == 'meituan':
                return display_name, platform, await watch_mt(pg)
            else:
                return display_name, platform, await watch_ele(pg)
        except Exception:
            return display_name, platform, []

    tasks = [_refresh(dn, p, pg) for dn, p, pg in all_pages]
    results = await asyncio.gather(*tasks)

    for dn, p, notices in results:
        if not notices: continue
        p_name = "美团" if p == 'meituan' else "饿了么"
        all_notices.setdefault(dn, []).append({"platform": p_name, "notices": notices})

    return all_notices


def print_watch_notices(all_notices):
    """打印预警通知"""
    for store, items in all_notices.items():
        print(f"⚠️ {store}")
        for item in items:
            print(f"  {item['platform']} {len(item['notices'])}条通知")
            for n in item['notices']:
                line = f"    {n['title']}"
                if n.get('time'): line += f" — {n['time']}"
                print(line)
                if n.get('content') and n['content'] != n['title']:
                    print(f"      {n['content']}")
        print()


async def main():
    parser = argparse.ArgumentParser(description='盯店巡检')
    parser.add_argument('brands', nargs='*', help='品牌名')
    parser.add_argument('--watch', action='store_true', help='预警模式，到18:00自动结束')
    parser.add_argument('--watch-once', action='store_true', help='单轮预警：跑一轮就退出（cron调度用）')
    parser.add_argument('-i', '--interval', type=int, default=10, help='预警间隔（分钟），默认10')
    args = parser.parse_args()

    brands = args.brands
    if not brands:
        print("用法:")
        print("  python3 run_fast.py 品牌1 品牌2                    # 跑一次")
        print("  python3 run_fast.py --watch 品牌1 品牌2             # 预警模式（到18:00结束）")
        print("  python3 run_fast.py --watch -i 5 品牌1              # 5分钟一轮")
        return

    port = int(os.environ.get("CHROME_PORT", "9222"))
    from browser import launch as launch_browser
    pw = await async_playwright().start()
    b, ctx = await launch_browser(pw, port)

    if args.watch_once:
        # === 单轮预警模式（cron调度用，跑一轮就退出） ===
        t0 = time.time()
        print(f"预警检查 — {len(brands)}个品牌 | {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        seen_keys = load_watch_snapshot()
        watch_pages, blocked_stores = await watch_open_all(brands, ctx)

        # 验证拦截的店铺立即报告
        if blocked_stores:
            print(f"\n⚠️ 验证拦截\n")
            for dn, p_name, reason in blocked_stores:
                print(f"  {dn}（{p_name}）— {reason}")
            print()

        all_notices = await watch_refresh(watch_pages)
        current_keys = notices_to_keys(all_notices)
        new_keys = current_keys - seen_keys

        if new_keys:
            new_notices = OrderedDict()
            for store, items in all_notices.items():
                new_items = []
                for item in items:
                    new_ns = [n for n in item['notices']
                              if f"{store}|{item['platform']}|{n['title']}" in new_keys]
                    if new_ns:
                        new_items.append({"platform": item['platform'], "notices": new_ns})
                if new_items:
                    new_notices[store] = new_items
            print(f"\n🔔 新增通知\n")
            print_watch_notices(new_notices)
            seen_keys |= current_keys
            save_watch_snapshot(seen_keys)
        elif not blocked_stores:
            print("✅ 无新增通知")

        # 关闭所有页面
        for _, _, pg in watch_pages:
            try: await pg.close()
            except: pass
        print(f"完成 ({time.time()-t0:.0f}s)")

    elif not args.watch:
        # === 单次模式（和原来完全一样） ===
        t0 = time.time()
        print(f"盯店巡检 - {datetime.now().strftime('%Y-%m-%d %H:%M')} | {len(brands)}个品牌")
        all_issues = await run_once(brands, ctx)
        total = time.time() - t0
        print(f"\n摘要\n")
        print_issues(all_issues)
        print(f"巡检完成 — {len(brands)}个品牌 总耗时{total:.0f}秒")
        await close_store_pages(ctx)
    else:
        # === 预警模式：只看通知，到18:00自动结束 ===
        interval = args.interval
        end_hour = 18
        print(f"盯店预警 — {len(brands)}个品牌 | 每{interval}分钟 | 到{end_hour}:00结束")
        print(f"Ctrl+C 提前停止\n")

        seen_keys = load_watch_snapshot()
        round_num = 0
        watch_pages = None  # 第一轮打开后保持

        while True:
            if datetime.now().hour >= end_hour:
                print(f"已过{end_hour}:00，预警结束")
                break

            round_num += 1
            t0 = time.time()
            now_str = datetime.now().strftime('%H:%M')
            print(f"── 第{round_num}轮 {now_str} ──")

            try:
                if watch_pages is None:
                    # 第一轮：打开所有页面
                    watch_pages, blocked = await watch_open_all(brands, ctx)
                    if blocked:
                        for dn, p_name, reason in blocked:
                            print(f"  ⚠️ {dn}（{p_name}）— {reason}")
                    all_notices = await watch_refresh(watch_pages)
                else:
                    # 后续轮次：直接刷新已有页面
                    # 清理已关闭的页面
                    watch_pages = [(dn, p, pg) for dn, p, pg in watch_pages if not pg.is_closed()]
                    all_notices = await watch_refresh(watch_pages)
            except Exception as e:
                print(f"  出错: {e}")
                await asyncio.sleep(interval * 60)
                continue

            current_keys = notices_to_keys(all_notices)
            new_keys = current_keys - seen_keys

            elapsed = time.time() - t0

            if new_keys:
                new_notices = OrderedDict()
                for store, items in all_notices.items():
                    new_items = []
                    for item in items:
                        new_ns = [n for n in item['notices']
                                  if f"{store}|{item['platform']}|{n['title']}" in new_keys]
                        if new_ns:
                            new_items.append({"platform": item['platform'], "notices": new_ns})
                    if new_items:
                        new_notices[store] = new_items

                print(f"\n🔔 新增通知 ({elapsed:.0f}s)\n")
                print_watch_notices(new_notices)
                seen_keys |= current_keys
                save_watch_snapshot(seen_keys)
            else:
                print(f"  ✅ 无新增 ({elapsed:.0f}s)")

            next_time = (datetime.now() + timedelta(minutes=interval)).strftime('%H:%M')
            print(f"  下一轮: {next_time}\n")
            await asyncio.sleep(interval * 60)

        # 预警结束，关闭所有保持的页面
        if watch_pages:
            for _, _, pg in watch_pages:
                try: await pg.close()
                except: pass

    await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
