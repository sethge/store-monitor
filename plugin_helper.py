"""悟空插件操作辅助模块"""
import asyncio
from collections import defaultdict

EXT_ID = "ekplipencnmccmaogdfnenioilpgfmab"


async def get_ext(ctx):
    for p in ctx.pages:
        if EXT_ID in p.url: return p
    p = await ctx.new_page()
    await p.goto(f"chrome-extension://{EXT_ID}/index.html", wait_until="commit", timeout=10000)
    await asyncio.sleep(2)
    return p


async def pick_brand(ext, brand):
    """搜索并选择品牌，返回 (成功, 状态)"""
    await ext.evaluate("() => document.querySelectorAll('button,span').forEach(e=>{if(e.textContent.trim()==='重 置')e.click()})")
    await asyncio.sleep(0.5)
    await ext.evaluate("() => {const s=document.querySelectorAll('.ant-select-selector');s[s.length-1].dispatchEvent(new MouseEvent('mousedown',{bubbles:true}))}")
    await asyncio.sleep(0.5)
    inputs = await ext.query_selector_all('input.ant-select-selection-search-input')
    target = inputs[-1] if inputs else None
    if not target:
        return False, "搜索框未找到"
    kw = brand.split("（")[0]
    sub = brand.split("（")[1].split("）")[0] if "（" in brand else ""
    await target.fill("")
    await target.type(kw, delay=30)
    await asyncio.sleep(1)
    found = await ext.evaluate(f"""() => {{
        const opts = document.querySelectorAll('.ant-select-item-option');
        for (const o of opts) {{ const t=o.textContent.trim(); if(t.includes('{kw}') && t.includes('{sub}')) {{ o.click(); return t }} }}
        return null
    }}""")
    if not found:
        await ext.keyboard.press("Escape")
        return False, "品牌未找到"
    await asyncio.sleep(0.5)
    await ext.keyboard.press("Escape")
    await asyncio.sleep(0.5)
    body = await ext.evaluate("() => document.body.innerText")
    status = "全部授权" if "全部授权" in body else "包含未授权" if "未授权" in body else "未知"
    # 展开 — 检查是否已展开（有平台img说明已展开）
    for _ in range(3):
        has_rows = await ext.evaluate(r"""() => {
            const trs = document.querySelectorAll('tr');
            for (const tr of trs) {
                const imgs = tr.querySelectorAll(':scope > td img');
                if (imgs.length > 0) return true;
            }
            return false;
        }""")
        if has_rows:
            break
        await ext.evaluate("""() => {
            document.querySelectorAll('.ant-table-row-expand-icon, .ant-table-row-expand-icon-collapsed').forEach(b => {
                if (b.className.includes('collapsed') || b.getAttribute('aria-expanded') === 'false' || b.textContent === '+') b.click();
            });
        }""")
        await asyncio.sleep(1)
    return True, status


async def get_stores(ext):
    """解析展开后的账号列表，按店铺名分组，返回 {storeName: [{platform, account, action}]}"""
    rows = await ext.evaluate(r"""() => {
        const results = [];
        const trs = document.querySelectorAll('tr');
        for (const tr of trs) {
            const imgs = tr.querySelectorAll(':scope > td img');
            let platform = '', pCount = 0;
            imgs.forEach(img => {
                if (img.src && img.src.includes('meituan')) { platform = 'meituan'; pCount++; }
                if (img.src && img.src.includes('eleme')) { platform = 'eleme'; pCount++; }
            });
            if (pCount !== 1) continue;
            const nameInput = tr.querySelector('td:nth-child(2) input');
            const storeName = nameInput ? nameInput.value : '';
            const accountTd = tr.querySelector('td:nth-child(3)');
            const account = accountTd ? accountTd.innerText.trim() : '';
            let action = '';
            tr.querySelectorAll('button,a,span').forEach(b => {
                const t = b.textContent.trim();
                if (t === '一键登录' || t === '立刻授权') action = t;
            });
            results.push({platform, storeName, account, action});
        }
        return results;
    }""")

    # 按店铺名分组
    named = defaultdict(list)
    unnamed = []
    for r in rows:
        if r['storeName']:
            named[r['storeName']].append(r)
        else:
            unnamed.append(r)

    # 空名称的按平台配对（美团+饿了么配成一家店）
    if unnamed:
        mt_unnamed = [r for r in unnamed if r['platform'] == 'meituan']
        elm_unnamed = [r for r in unnamed if r['platform'] == 'eleme']
        pairs = max(len(mt_unnamed), len(elm_unnamed))
        for i in range(pairs):
            key = f"_auto_{i}"
            if i < len(mt_unnamed):
                named[key].append(mt_unnamed[i])
            if i < len(elm_unnamed):
                named[key].append(elm_unnamed[i])

    return dict(named)


async def click_store_platform(ext, account):
    """点击指定账号的一键登录，返回 'ok'/'need_auth'/'not_found'"""
    for attempt in range(3):
        r = await ext.evaluate(f"""() => {{
            const trs = document.querySelectorAll('tr');
            for (const tr of trs) {{
                const accountTd = tr.querySelector('td:nth-child(3)');
                if (accountTd && accountTd.innerText.trim() === '{account}') {{
                    const btns = tr.querySelectorAll('button, a, span');
                    for (const b of btns) {{
                        if (b.textContent.trim() === '一键登录') {{ b.click(); return 'ok'; }}
                        if (b.textContent.trim() === '立刻授权') {{ return 'need_auth'; }}
                    }}
                }}
            }}
            return 'not_found';
        }}""")
        if r != 'not_found':
            return r
        await ext.evaluate("() => document.querySelectorAll('.ant-table-row-expand-icon,[class*=expand]').forEach(b=>b.click())")
        await asyncio.sleep(1)
    return 'not_found'


async def close_store_pages(ctx):
    for p in ctx.pages:
        if ('waimai.meituan.com' in p.url or ('ele.me' in p.url and 'melody' in p.url)) and 'chrome-extension' not in p.url:
            try:
                await p.close()
            except:
                pass
    await asyncio.sleep(0.5)
