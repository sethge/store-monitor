"""悟空插件操作辅助模块"""
import asyncio
import json
import subprocess
from collections import defaultdict

EXT_ID = "kocmiihdllcmbjanolpggoafghdfnglg"


async def get_ext(ctx):
    # 先找已打开的悟空页面（按已知ID或页面内容匹配）
    for p in ctx.pages:
        if EXT_ID in p.url: return p
    # 兜底：找任何chrome-extension页面，检查是否是悟空（含"品牌选择"文字）
    for p in ctx.pages:
        if 'chrome-extension://' in p.url:
            try:
                text = await p.evaluate("() => document.body.innerText.substring(0,100)")
                if '品牌' in text or '重 置' in text or '授权' in text:
                    return p
            except:
                pass
    # 尝试用已知ID打开
    p = await ctx.new_page()
    try:
        await p.goto(f"chrome-extension://{EXT_ID}/index.html", wait_until="commit", timeout=10000)
        await asyncio.sleep(2)
        return p
    except:
        await p.close()
    raise Exception("找不到悟空插件，请在Chrome中手动打开悟空插件页面")


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


async def check_verification(page):
    """检测页面是否被平台验证拦截（滑块/短信/安全验证等），返回 (被拦截, 描述)"""
    try:
        url = page.url.lower()
        # URL级别检测 — verify.meituan.com 等专用验证域名
        verify_domains = ['verify.meituan.com', 'captcha.', 'security.']
        for vd in verify_domains:
            if vd in url:
                return True, "平台安全验证"

        # 页面内容检测
        text = await page.evaluate("() => document.body ? document.body.innerText.substring(0, 2000) : ''")
        verify_keywords = [
            '滑动验证', '请完成验证', '安全验证', '身份验证', '身份核实', '短信验证',
            '请输入验证码', '图形验证', '拖动滑块', '请拖动', '向右拖动', '请向右拖动',
            '人机验证', '操作过于频繁', '账号异常', '风控', '请先验证',
            '扫码验证', '扫码登录', '请用手机扫码',
        ]
        for kw in verify_keywords:
            if kw in text:
                return True, f"平台验证拦截({kw})"

        # 检测常见验证码iframe（美团/饿了么的验证弹窗）
        has_verify_frame = await page.evaluate("""() => {
            for (const f of document.querySelectorAll('iframe')) {
                const src = (f.src || '').toLowerCase();
                if (src.includes('captcha') || src.includes('verify') || src.includes('slider'))
                    return src;
            }
            return null;
        }""")
        if has_verify_frame:
            return True, "平台验证弹窗"

    except Exception:
        pass
    return False, ""


async def close_store_pages(ctx):
    for p in ctx.pages:
        if ('waimai.meituan.com' in p.url or 'verify.meituan.com' in p.url or ('ele.me' in p.url and 'melody' in p.url)) and 'chrome-extension' not in p.url:
            try:
                await p.close()
            except:
                pass
    await asyncio.sleep(0.5)
