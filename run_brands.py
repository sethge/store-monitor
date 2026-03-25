#!/usr/bin/env python3
"""多品牌多店铺巡检 - 表格样式输出"""
import asyncio, json, subprocess, re, sys, time
from datetime import datetime, timedelta
from collections import defaultdict
from playwright.async_api import async_playwright

sys.path.insert(0, '/Users/seth/Downloads/store-monitor')
import monitor
from monitor_eleme import scrape_eleme
from plugin_helper import get_ext, pick_brand, get_stores, click_store_platform, close_store_pages
from promo_check import parse_promo_data, check_promo

def sd(d):
    m = re.match(r'\d{4}-(\d{2})-(\d{2})', str(d))
    return f"{int(m.group(1))}月{int(m.group(2))}日" if m else str(d)
def sdt(d):
    m = re.match(r'\d{4}[.-](\d{2})[.-](\d{2})\s+(\d{2}):\d{2}', str(d))
    return f"{int(m.group(1))}月{int(m.group(2))}日{int(m.group(3))}点" if m else sd(d)

YESTERDAY = (datetime.now().replace(hour=0,minute=0,second=0) - timedelta(days=1)).strftime('%Y-%m-%d')
THREE_DAYS = (datetime.now() - timedelta(days=3)).strftime('%Y-%m-%d')
CUTOFF = datetime.now().timestamp() - 3*86400

def get_mt_data(scores, msgs, acts):
    """提取美团报告数据"""
    reviews = scores.get("评价列表",[])
    bad = [r for r in scores.get("中差评",[]) if r.get('time','')>=THREE_DAYS]
    yg = len([r for r in reviews if r.get('time')==YESTERDAY and r['stars']>=4])
    ym = len([r for r in reviews if r.get('time')==YESTERDAY and r['stars']==3])
    yb = len([r for r in reviews if r.get('time')==YESTERDAY and r['stars']<=2])
    exp = [a for a in acts.get("items",[]) if a.get("days_left") is not None and a["days_left"]<=7 and not a.get("auto_extend")]
    imp = []
    for m in msgs:
        if m.get("ctime",0)<CUTOFF: continue
        t,c = m.get('title',''),m.get('category','')
        if '活动到期提醒' in t: continue
        if c=='店铺动态':
            if re.search(r'【.+】',t) or any(k in t for k in ['招商','上线','升级','覆盖']): continue
            imp.append(m)
        elif any(k in t for k in ['到期','失败','超时','变更']): imp.append(m)
    return {"bad": bad, "yg": yg, "ym": ym, "yb": yb, "exp": exp, "imp": imp, "acts": acts}

def get_elm_data(ed):
    """提取饿了么报告数据"""
    reviews = ed.get("评价列表",[])
    bad = [r for r in ed.get("中差评",[]) if r.get('time','')>=THREE_DAYS]
    yg = len([r for r in reviews if r.get('time')==YESTERDAY and r['stars']>=4])
    ym = len([r for r in reviews if r.get('time')==YESTERDAY and r['stars']==3])
    yb = len([r for r in reviews if r.get('time')==YESTERDAY and r['stars']<=2])
    acts = ed.get("活动",[])
    exp = [a for a in acts if a.get('days_left') is not None and a['days_left']<=7 and a.get('status')=='进行中']
    return {"bad": bad, "yg": yg, "ym": ym, "yb": yb, "exp": exp, "acts": acts}

W1, W2 = 10, 25  # column widths

def print_store_table(store_name, platforms):
    """打印单店表格。platforms = {'meituan': data_or_status, 'eleme': data_or_status}"""
    cols = []
    headers = []
    for p in ['meituan', 'eleme']:
        d = platforms.get(p)
        if d is None: continue
        h = "美团" if p=='meituan' else "饿了么"
        if d == 'need_auth':
            h += " ⚠️授权失败"
        cols.append(p)
        headers.append(h)
    
    if not cols: return
    nc = len(cols)
    cw = W2
    sep_h = "─"*W1
    sep_c = "─"*cw
    
    # 店名
    print(f"\n┌{'─'*(W1+1+(cw+1)*nc+nc)}")
    print(f"│ {store_name}")
    print(f"├{'─'*W1}┬" + "┬".join(["─"*cw]*nc) + "┐" if nc>1 else f"├{'─'*W1}┬{'─'*cw}┐")
    # 平台行
    line = f"│{'':>{W1}}│"
    for h in headers: line += f" {h:<{cw-1}}│"
    print(line)
    print(f"├{sep_h}┼" + "┼".join([sep_c]*nc) + "┤" if nc>1 else f"├{sep_h}┼{sep_c}┤")
    
    # 评价行
    def eval_lines(p):
        d = platforms.get(p)
        if d == 'need_auth' or d is None: return ["—"]
        lines = []
        bad = d.get("bad",[])
        if bad:
            lines.append(f"⚠️ 近3日中差评{len(bad)}条")
            for r in bad:
                lines.append(f"[{r['stars']}星] {sd(r['time'])}")
                if r.get('comment'): lines.append(f"{r['comment'][:20]}")
        else:
            lines.append("✅ 无中差评")
        lines.append(f"昨日：好评{d['yg']} 中评{d['ym']} 差评{d['yb']}")
        return lines
    
    col_lines = [eval_lines(c) for c in cols]
    max_lines = max(len(l) for l in col_lines)
    for i in range(max_lines):
        label = "📊 评价" if i==0 else ""
        line = f"│{label:>{W1}}│"
        for cl in col_lines:
            txt = cl[i] if i<len(cl) else ""
            line += f" {txt:<{cw-1}}│"
        print(line)
    print(f"├{sep_h}┼" + "┼".join([sep_c]*nc) + "┤" if nc>1 else f"├{sep_h}┼{sep_c}┤")
    
    # 活动行
    def act_lines(p):
        d = platforms.get(p)
        if d == 'need_auth' or d is None: return ["—"]
        lines = []
        exp = d.get("exp",[])
        if exp:
            lines.append(f"⚠️ {len(exp)}个即将到期")
            for a in exp:
                if p=='meituan':
                    lines.append(f"{a['type']} 剩{a['days_left']}天")
                else:
                    lines.append(f"{a['title']} 剩{a['days_left']}天")
        else:
            lines.append("✅ 无最近7天到期活动")
        return lines
    
    col_lines = [act_lines(c) for c in cols]
    max_lines = max(len(l) for l in col_lines)
    for i in range(max_lines):
        label = "🎯 活动" if i==0 else ""
        line = f"│{label:>{W1}}│"
        for cl in col_lines:
            txt = cl[i] if i<len(cl) else ""
            line += f" {txt:<{cw-1}}│"
        print(line)
    print(f"├{sep_h}┼" + "┼".join([sep_c]*nc) + "┤" if nc>1 else f"├{sep_h}┼{sep_c}┤")
    
    # 通知行
    def notice_lines(p):
        d = platforms.get(p)
        if d == 'need_auth' or d is None: return ["—"]
        imp = d.get("imp", [])
        if imp:
            lines = [f"{len(imp)}条"]
            for m in imp[:3]:
                lines.append(f"{m['title'][:18]}")
            return lines
        return ["✅ 无重要通知"]
    
    col_lines = [notice_lines(c) for c in cols]
    max_lines = max(len(l) for l in col_lines)
    for i in range(max_lines):
        label = "📬 通知" if i==0 else ""
        line = f"│{label:>{W1}}│"
        for cl in col_lines:
            txt = cl[i] if i<len(cl) else ""
            line += f" {txt:<{cw-1}}│"
        print(line)
    print(f"├{sep_h}┼" + "┼".join([sep_c]*nc) + "┤" if nc>1 else f"├{sep_h}┼{sep_c}┤")

    # 推广余额行
    def promo_lines(p):
        d = platforms.get(p)
        if d == 'need_auth' or d is None: return ["—"]
        promo = d.get("promo")
        if not promo: return ["无推广数据"]
        bal, median, alert = promo['balance'], promo['median'], promo['alert']
        if alert:
            return [f"⚠️ 余额{bal}元/日消费{median}元"]
        elif median > 0:
            return [f"✅ 余额{bal}元/日消费{median}元"]
        else:
            return ["无消费记录"]

    col_lines = [promo_lines(c) for c in cols]
    max_lines = max(len(l) for l in col_lines)
    for i in range(max_lines):
        label = "💰 推广" if i==0 else ""
        line = f"│{label:>{W1}}│"
        for cl in col_lines:
            txt = cl[i] if i<len(cl) else ""
            line += f" {txt:<{cw-1}}│"
        print(line)
    print(f"└{sep_h}┴" + "┴".join([sep_c]*nc) + "┘" if nc>1 else f"└{sep_h}┴{sep_c}┘")


async def run_brand(ctx, brand):
    """跑一个品牌下所有店铺，返回问题列表"""
    issues = []
    await close_store_pages(ctx)
    ext = await get_ext(ctx)
    ok, status = await pick_brand(ext, brand)
    if not ok:
        print(f"  ❌ {status}")
        return [f"❌ {brand} — {status}"]

    stores = await get_stores(ext)
    total_platforms = sum(len(v) for v in stores.values())
    auth_fail = sum(1 for v in stores.values() for a in v if a['action']=='立刻授权')

    print(f"\n{'='*60}")
    print(f"【{brand}】巡检报告 | {len(stores)}家店铺 {total_platforms}个平台" + (f" {auth_fail}个授权失败" if auth_fail else ""))
    print(f"{'='*60}")

    for store_key, accounts in stores.items():
        platform_data = {}
        real_name = store_key if not store_key.startswith('_auto_') else ""
        
        for acct in accounts:
            p = acct['platform']
            if acct['action'] == '立刻授权':
                platform_data[p] = 'need_auth'
                continue
            if acct['action'] != '一键登录':
                continue
            
            await close_store_pages(ctx)
            ext = await get_ext(ctx)
            await pick_brand(ext, brand)
            result = await click_store_platform(ext, acct['account'])
            if result != 'ok':
                continue
            await asyncio.sleep(6)
            
            if p == 'meituan':
                mt = None
                for pg in ctx.pages:
                    if 'waimai.meituan.com' in pg.url and 'chrome-extension' not in pg.url: mt=pg; break
                if mt:
                    try:
                        msgs = await monitor.scrape_messages(mt)
                        scores = await monitor.scrape_scores(mt)
                        acts = await monitor.scrape_activities(mt)
                        name = await monitor.get_store_name(mt)
                        name = re.sub(r'(营业中|休息中|歇业中|仅接受预订).*$','',name).strip()
                        if '*' not in name and '上传' not in name and len(name)>2:
                            real_name = name
                        d = get_mt_data(scores, msgs, acts)
                        # 推广余额检查
                        try:
                            await mt.goto("https://e.waimai.meituan.com/#https://waimaieapp.meituan.com/ad/v1/pc", wait_until="commit", timeout=15000)
                            await asyncio.sleep(5)
                            for f2 in mt.frames:
                                if 'ad' in f2.url and 'waimaieapp' in f2.url:
                                    promo_text = await f2.evaluate("() => document.body.innerText")
                                    bal, spends = parse_promo_data(promo_text)
                                    need, bal, median = check_promo(bal, spends)
                                    d['promo'] = {'balance': bal, 'median': median, 'alert': need}
                                    break
                        except:
                            pass
                        platform_data[p] = d
                    except Exception as e:
                        print(f"  美团出错: {e}")
                    try: await mt.close()
                    except: pass
            
            elif p == 'eleme':
                ele = None
                for pg in ctx.pages:
                    if 'ele.me' in pg.url and 'melody' in pg.url: ele=pg; break
                if ele:
                    try:
                        ed = await scrape_eleme(ele)
                        if ed:
                            if ed.get('店铺名'): real_name = ed['店铺名']
                            d = get_elm_data(ed)
                            d['imp'] = []
                            # 推广余额检查
                            try:
                                shop_m = re.search(r'/shop/(\d+)/', ele.url)
                                if shop_m:
                                    sid = shop_m.group(1)
                                    await ele.goto(f"https://melody.shop.ele.me/app/shop/{sid}/vas#app.shop.vas", wait_until="commit", timeout=15000)
                                    await asyncio.sleep(5)
                                    for f2 in ele.frames:
                                        try:
                                            pt = await f2.evaluate("() => document.body.innerText")
                                            if '推广消费' in pt and '消费记录' in pt:
                                                bal, spends = parse_promo_data(pt)
                                                need, bal, median = check_promo(bal, spends)
                                                d['promo'] = {'balance': bal, 'median': median, 'alert': need}
                                                break
                                        except:
                                            pass
                            except:
                                pass
                            platform_data[p] = d
                    except Exception as e:
                        print(f"  饿了么出错: {e}")
                    try: await ele.close()
                    except: pass
        
        print_store_table(real_name, platform_data)

        # 收集问题
        for p_key, d in platform_data.items():
            p_name = "美团" if p_key=='meituan' else "饿了么"
            if d == 'need_auth':
                issues.append(f"⚠️ {real_name} | {p_name} 授权失败")
            elif isinstance(d, dict):
                if d.get('bad'):
                    issues.append({"store": real_name, "platform": p_name, "type": "bad_review",
                                   "msg": f"近3日中差评{len(d['bad'])}条", "details": d['bad']})
                if d.get('exp'):
                    issues.append({"store": real_name, "platform": p_name, "type": "expiring",
                                   "msg": f"{len(d['exp'])}个活动即将到期",
                                   "details": [{"name": a.get('type', a.get('title','')), "days": a.get('days_left','')} for a in d['exp']]})
                if d.get('imp'):
                    issues.append({"store": real_name, "platform": p_name, "type": "notice",
                                   "msg": f"{len(d['imp'])}条通知",
                                   "details": [m.get('title','')[:20] for m in d['imp']]})
                promo = d.get('promo', {})
                if promo.get('alert'):
                    issues.append({"store": real_name, "platform": p_name, "type": "promo",
                                   "msg": f"推广余额不足：{promo['balance']}元 / 日消费{promo['median']}元", "details": []})

    return issues


async def main():
    brands = sys.argv[1:] if len(sys.argv)>1 else ["仙云居小笼包（宝山店）"]

    r = subprocess.run(["curl","--noproxy","localhost","-s","http://localhost:9222/json/version"], capture_output=True, text=True, timeout=5)
    ws = json.loads(r.stdout)["webSocketDebuggerUrl"]
    pw = await async_playwright().start()
    b = await pw.chromium.connect_over_cdp(ws)
    ctx = b.contexts[0]

    t0 = time.time()
    print(f"盯店巡检 - {datetime.now().strftime('%Y-%m-%d %H:%M')} | {len(brands)}个品牌")

    all_issues = []
    for brand in brands:
        issues = await run_brand(ctx, brand)
        all_issues.extend(issues)

    # 摘要 — 按店铺聚合
    print(f"\n{'='*60}")
    print(f"摘要")
    print(f"{'='*60}")
    if all_issues:
        # 按店铺分组
        from collections import OrderedDict
        grouped = OrderedDict()
        for issue in all_issues:
            if isinstance(issue, str):
                # 授权失败等简单字符串
                print(f"  {issue}")
                continue
            key = issue['store']
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(issue)

        for store, items in grouped.items():
            print(f"\n  ⚠️ {store}")
            for item in items:
                icon = "💰" if item['type']=='promo' else "📊" if item['type']=='bad_review' else "🎯" if item['type']=='expiring' else "📬"
                print(f"     {icon} {item['platform']} {item['msg']}")
                for d in item.get('details', []):
                    if isinstance(d, dict):
                        if d.get('comment'):
                            print(f"       [{d['stars']}星] {sd(d.get('time',''))} — {d['comment'][:25]}")
                        elif d.get('name'):
                            print(f"       {d['name']} 剩{d['days']}天")
                    elif isinstance(d, str) and d:
                        print(f"       {d}")
    else:
        print(f"  ✅ 所有店铺运营正常，无异常")
    print(f"\n巡检完成 - 总耗时{time.time()-t0:.0f}秒")
    await pw.stop()

if __name__ == "__main__":
    asyncio.run(main())
