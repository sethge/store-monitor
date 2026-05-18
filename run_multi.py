#!/usr/bin/env python3
"""多店铺巡检 - 通过悟空插件切换"""

import asyncio, json, re, subprocess, sys, time
from datetime import datetime, timedelta
from pathlib import Path
from playwright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).parent))

BRANDS = [
    "冰拾叁（三河店）",
    "冰拾叁（静安路店）",
    "yogreat酸奶（五角场&复兴店）",
    "未来茶餐厅（观澜店）",
    "品川小厨（秦淮店）",
]

EXT_ID = "ekplipencnmccmaogdfnenioilpgfmab"

def sd(d):
    m = re.match(r'\d{4}-(\d{2})-(\d{2})', str(d))
    return f"{int(m.group(1))}月{int(m.group(2))}日" if m else str(d)

def sdt(d):
    m = re.match(r'\d{4}[.-](\d{2})[.-](\d{2})\s+(\d{2}):\d{2}', str(d))
    return f"{int(m.group(1))}月{int(m.group(2))}日{int(m.group(3))}点" if m else sd(d)


async def close_store_pages(ctx):
    for p in ctx.pages:
        if ('waimai.meituan.com' in p.url or ('ele.me' in p.url and 'melody' in p.url)) and 'chrome-extension' not in p.url:
            try: await p.close()
            except: pass
    await asyncio.sleep(0.5)


async def get_ext(ctx):
    for p in ctx.pages:
        if EXT_ID in p.url:
            await p.bring_to_front()
            return p
    p = await ctx.new_page()
    await p.goto(f"chrome-extension://{EXT_ID}/index.html", wait_until="commit", timeout=10000)
    await asyncio.sleep(1.5)
    return p


async def pick_brand(ext, brand):
    """选品牌并展开，返回 (成功, 状态文字)"""
    await ext.evaluate("() => document.querySelectorAll('button,span').forEach(e=>{if(e.textContent.trim()==='重 置')e.click()})")
    await asyncio.sleep(0.5)
    await ext.evaluate("() => {const s=document.querySelectorAll('.ant-select-selector');s[s.length-1].dispatchEvent(new MouseEvent('mousedown',{bubbles:true}))}")
    await asyncio.sleep(0.8)
    kw = brand.split("（")[0]
    sub = brand.split("（")[1].split("）")[0] if "（" in brand else ""
    found = await ext.evaluate(f"""() => {{
        const opts = document.querySelectorAll('.ant-select-item-option');
        for (const o of opts) {{
            const t = o.textContent.trim();
            if (t.includes('{kw}') && t.includes('{sub}')) {{ o.click(); return t; }}
        }}
        return null;
    }}""")
    if not found: return False, "品牌未找到"
    await asyncio.sleep(0.5)
    await ext.keyboard.press("Escape")
    await asyncio.sleep(0.5)

    # 读取品牌状态
    body_text = await ext.evaluate("() => document.body.innerText")
    if "包含未授权" in body_text:
        status = "包含未授权"
    elif "全部授权" in body_text:
        status = "全部授权"
    else:
        status = "未知"

    # 展开
    await ext.evaluate("() => document.querySelectorAll('.ant-table-row-expand-icon,[class*=expand]').forEach(b=>b.click())")
    await asyncio.sleep(1)
    return True, status


async def click_platform_login(ext, platform, retry=2):
    """点击指定平台的一键登录，返回 'ok'/'need_auth'/'not_found'"""
    for attempt in range(retry + 1):
        result = await ext.evaluate(f"""() => {{
            const trs = document.querySelectorAll('tr');
            for (const tr of trs) {{
                const directImgs = tr.querySelectorAll(':scope > td img');
                if (directImgs.length === 0) continue;
                let match = false;
                let other = false;
                directImgs.forEach(img => {{
                    if (img.src && img.src.includes('{platform}')) match = true;
                    if (img.src && !img.src.includes('{platform}') && (img.src.includes('meituan') || img.src.includes('eleme'))) other = true;
                }});
                if (match && !other) {{
                    const btns = tr.querySelectorAll('button, a, span');
                    for (const b of btns) {{
                        if (b.textContent.trim() === '一键登录') {{
                            b.click();
                            return 'ok';
                        }}
                        if (b.textContent.trim() === '立刻授权') {{
                            return 'need_auth';
                        }}
                    }}
                }}
            }}
            return 'not_found';
        }}""")
        if result == 'ok':
            return 'ok'
        if result == 'need_auth':
            return 'need_auth'
        if attempt < retry:
            await ext.evaluate("() => document.querySelectorAll('.ant-table-row-expand-icon,[class*=expand]').forEach(b=>b.click())")
            await asyncio.sleep(1.5)
    return 'not_found'


def print_mt_report(name, scores, msgs, acts):
    yesterday = (datetime.now().replace(hour=0,minute=0,second=0) - timedelta(days=1)).strftime('%Y-%m-%d')
    three_days_ago = (datetime.now() - timedelta(days=3)).strftime('%Y-%m-%d')
    cutoff_ts = datetime.now().timestamp() - 3*86400

    reviews = scores.get("评价列表", [])
    bad = scores.get("中差评", [])
    yg = len([r for r in reviews if r.get('time')==yesterday and r['stars']>=4])
    ym = len([r for r in reviews if r.get('time')==yesterday and r['stars']==3])
    yb = len([r for r in reviews if r.get('time')==yesterday and r['stars']<=2])

    print(f"\n  美团【{name}】")

    # 评价
    expiring_acts = [a for a in acts.get("items",[]) if a.get("days_left") is not None and a["days_left"]<=7 and not a.get("auto_extend")]
    if bad:
        recent = [r for r in bad if r.get('time','')>=three_days_ago]
        if recent:
            print(f"  📊 评价：⚠️ 近3日中差评{len(recent)}条")
            for r in recent:
                print(f"      [{r['stars']}星] {sd(r['time'])} — {r['comment']}")
                if r.get('foods'): print(f"        菜品: {', '.join(r['foods'][:3])}")
                if r.get('appeal_status'): print(f"        申诉: {r['appeal_status']}")
        else:
            print(f"  📊 评价：近3日无新增，历史中差评{len(bad)}条")
            for r in bad:
                print(f"      [{r['stars']}星] {sd(r['time'])} — {r['comment']}")
    else:
        print(f"  📊 评价：无中差评")
    print(f"    昨日：好评{yg} 中评{ym} 差评{yb}")

    # 活动
    if expiring_acts:
        print(f"  🎯 活动：⚠️ {len(expiring_acts)}个即将到期")
        for a in expiring_acts:
            print(f"      {a['type']}「{a['preview']}」还剩{a['days_left']}天 到期{sd(a['end_date'])}")
    else:
        print(f"  🎯 活动：无最近7天到期活动")
    for a in acts.get("items",[]):
        s=""
        if a.get("days_left") is not None:
            s = f"自动延期 到期{sd(a['end_date'])}" if a.get("auto_extend") else f"到期{sd(a['end_date'])}"
        op=""
        if a.get("op_logs"):
            l=a["op_logs"][-1]; op=f"| {l['操作类型']}{sdt(l['操作时间'])}"
        print(f"    [{a['index']}] {a.get('type','')} | {a.get('preview','')} | 7日:{a.get('sales_7d','-')} | {s} {op}")

    # 通知
    imp=[]
    for m in msgs:
        if m.get("ctime",0)<cutoff_ts: continue
        t,c=m.get('title',''),m.get('category','')
        if '活动到期提醒' in t: continue  # 只过滤"活动到期提醒"，其他到期保留
        if c=='店铺动态':
            if re.search(r'【.+】',t) or any(k in t for k in ['招商','上线','升级','覆盖']): continue
            imp.append(m)
        elif any(k in t for k in ['到期','失败','超时','变更']): imp.append(m)
    if imp:
        print(f"  📬 近3日通知：{len(imp)}条")
        for m in imp:
            print(f"      [{m.get('category','')}] {m['title']} — {sd(m['time'])}")
            d=re.sub(r'<[^>]+>','',m.get('content',m.get('summary',''))).strip()
            if d and not d.startswith('http'): print(f"        {d[:120]}")
    else:
        print(f"  📬 近3日通知：无重要通知")


async def main():
    from browser import launch as launch_browser
    pw = await async_playwright().start()
    browser, ctx = await launch_browser(pw)

    import monitor
    from monitor_eleme import scrape_eleme, format_eleme_report

    print(f"\n{'#'*50}")
    print(f"盯店巡检 - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"共 {len(BRANDS)} 家店铺")
    print(f"{'#'*50}")

    t_start = time.time()
    summary = []

    for i, brand in enumerate(BRANDS):
        t_brand = time.time()
        print(f"\n{'='*50}")
        print(f"[{i+1}/{len(BRANDS)}] {brand}")
        print(f"{'='*50}")

        await close_store_pages(ctx)
        ext = await get_ext(ctx)
        ok, brand_status = await pick_brand(ext, brand)
        if not ok:
            print(f"  ❌ {brand_status}")
            summary.append(f"❌ {brand} — {brand_status}")
            continue
        print(f"  品牌状态: {brand_status}")

        # === 美团 ===
        mt_status = await click_platform_login(ext, 'meituan')
        if mt_status == 'need_auth':
            print(f"  ⚠️ 美团需要授权（立刻授权）")
        elif mt_status == 'not_found':
            print(f"  （未开通美团）")
        if mt_status == 'ok':
            await asyncio.sleep(6)
            mt = None
            for p in ctx.pages:
                if 'waimai.meituan.com' in p.url and 'chrome-extension' not in p.url:
                    mt = p; break
            if mt:
                try:
                    msgs = await monitor.scrape_messages(mt)
                    scores = await monitor.scrape_scores(mt)
                    acts = await monitor.scrape_activities(mt)
                    name = await monitor.get_store_name(mt)
                    name = re.sub(r'(营业中|休息中|歇业中|仅接受预订).*$', '', name).strip()
                    print_mt_report(name, scores, msgs, acts)
                except Exception as e:
                    print(f"  ❌ 美团出错: {e}")
                try: await mt.close()
                except: pass
        # === 饿了么 ===
        ext = await get_ext(ctx)
        ok2, _ = await pick_brand(ext, brand)
        if not ok2:
            print(f"  （饿了么品牌选择失败）")
        else:
            ele_status = await click_platform_login(ext, 'eleme')
            if ele_status == 'need_auth':
                print(f"  ⚠️ 饿了么需要授权（立刻授权）")
            elif ele_status == 'not_found':
                print(f"  （未开通饿了么）")
            elif ele_status == 'ok':
                await asyncio.sleep(6)
                ele = None
                for p in ctx.pages:
                    if 'ele.me' in p.url and 'melody' in p.url:
                        ele = p; break
                if ele:
                    try:
                        ed = await scrape_eleme(ele)
                        if ed: print(format_eleme_report(ed))
                    except Exception as e:
                        print(f"  ❌ 饿了么出错: {e}")
                    try: await ele.close()
                    except: pass
                else:
                    print(f"  （饿了么页面未打开）")

        elapsed = time.time() - t_brand
        summary.append(f"✅ {brand} ({elapsed:.0f}秒)")

    total = time.time() - t_start
    print(f"\n{'#'*50}")
    print(f"巡检完成 - 总耗时 {total:.0f}秒")
    for s in summary: print(f"  {s}")
    print(f"{'#'*50}")

    await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
