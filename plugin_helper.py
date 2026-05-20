"""悟空插件操作辅助模块"""
import asyncio
import json
import sys
import subprocess as _sp
from collections import defaultdict
import patrol_log as L

_IS_WIN = sys.platform == 'win32'
_IS_MAC = sys.platform == 'darwin'


def _get_frontmost_app():
    """获取当前前台窗口（macOS返回app名，Windows返回HWND）"""
    if _IS_MAC:
        try:
            r = _sp.run(["osascript", "-e", 'tell application "System Events" to get name of first process whose frontmost is true'],
                         capture_output=True, text=True, timeout=3)
            return r.stdout.strip()
        except Exception:
            return None
    elif _IS_WIN:
        try:
            import ctypes
            return ctypes.windll.user32.GetForegroundWindow()
        except Exception:
            return None
    return None


def _activate_app(handle):
    """激活指定app到前台（macOS传app名，Windows传HWND）"""
    if not handle:
        return
    if _IS_MAC:
        try:
            _sp.Popen(["osascript", "-e", f'tell application "{handle}" to activate'],
                       stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
        except Exception:
            pass
    elif _IS_WIN:
        try:
            import ctypes
            ctypes.windll.user32.SetForegroundWindow(handle)
        except Exception:
            pass

# 悟空插件ID（手动加载时Chrome会分配新ID，这里列已知的，自动检测兜底）
KNOWN_EXT_IDS = [
    "imnjpdamkohlnjmnlfngaoogfnahlldd",
    "ghppggbdmkaicdgohkkdaebbpcochkfe",
    "kocmiihdllcmbjanolpggoafghdfnglg",
    "jhmgkfkfdojnpccjiihkdfjinbkcfhfc",
]
EXT_ID = KNOWN_EXT_IDS[0]

# 运行时缓存发现的ID，避免每次都扫
_discovered_ext_id = None


async def get_ext(ctx):
    global _discovered_ext_id

    # 构建搜索顺序：已发现的ID优先，然后是已知列表
    search_ids = list(KNOWN_EXT_IDS)
    if _discovered_ext_id and _discovered_ext_id not in search_ids:
        search_ids.insert(0, _discovered_ext_id)
    elif _discovered_ext_id:
        search_ids.remove(_discovered_ext_id)
        search_ids.insert(0, _discovered_ext_id)

    pages_info = [p.url[:60] for p in ctx.pages]
    L.step("plugin", f"查找悟空插件 ({len(ctx.pages)}个页面)", detail=str(pages_info))

    # 先找已打开的悟空页面（按已知ID匹配）
    for p in ctx.pages:
        for eid in search_ids:
            if eid in p.url:
                _discovered_ext_id = eid
                L.step("plugin", f"找到悟空(已知ID): {eid[:8]}...")
                return p

    # 兜底：找任何chrome-extension页面，检查是否是悟空（含"品牌"/"重 置"文字）
    for p in ctx.pages:
        if 'chrome-extension://' in p.url:
            try:
                text = await p.evaluate("() => document.body.innerText.substring(0,100)")
                if '品牌' in text or '重 置' in text or '授权' in text:
                    # 缓存这个新发现的ID
                    import re as _re
                    m = _re.search(r'chrome-extension://([a-z]+)/', p.url)
                    if m:
                        _discovered_ext_id = m.group(1)
                        L.step("plugin", f"发现悟空插件ID: {_discovered_ext_id}")
                    return p
            except:
                pass

    # 从service_workers/background_pages发现扩展ID（headless模式下扩展没有打开的页面）
    import re as _re
    sw_ids = set()
    for sw in getattr(ctx, 'service_workers', []):
        m = _re.search(r'chrome-extension://([a-z]+)/', sw.url)
        if m: sw_ids.add(m.group(1))
    for bp in getattr(ctx, 'background_pages', []):
        m = _re.search(r'chrome-extension://([a-z]+)/', bp.url)
        if m: sw_ids.add(m.group(1))
    if sw_ids:
        L.step("plugin", f"从service_workers发现扩展ID: {sw_ids}")
        for eid in sw_ids:
            if eid not in search_ids:
                search_ids.insert(0, eid)

    # 尝试用已知ID打开
    L.step("plugin", f"尝试打开悟空 ({len(search_ids)}个ID)")
    front_app = _get_frontmost_app()
    for eid in search_ids:
        p = await ctx.new_page()
        _activate_app(front_app)  # 立刻还焦点
        try:
            await p.goto(f"chrome-extension://{eid}/index.html", wait_until="commit", timeout=10000)
            await asyncio.sleep(2)
            _discovered_ext_id = eid
            L.step("plugin", f"悟空插件打开成功: {eid[:8]}...")
            return p
        except:
            await p.close()
    L.error("plugin", f"找不到悟空插件", detail=f"tried {len(search_ids)} IDs, pages={pages_info}")
    raise Exception(f"找不到悟空插件(tried {len(search_ids)} IDs, pages={[p.url[:50] for p in ctx.pages]})")


async def pick_brand(ext, brand):
    """搜索并选择品牌，返回 (成功, 状态)"""
    L.step("plugin", f"选择品牌: {brand}")
    # 等插件页面就绪（selector出现）
    for _wait in range(5):
        ready = await ext.evaluate("() => document.querySelectorAll('.ant-select-selector').length > 0")
        if ready:
            break
        await asyncio.sleep(1)
    if not ready:
        L.error("plugin", f"插件未就绪(等了5秒)")
        return False, "插件未就绪"

    await ext.evaluate("() => document.querySelectorAll('button,span').forEach(e=>{if(e.textContent.trim()==='重 置')e.click()})")
    await asyncio.sleep(0.5)
    kw = brand.split("（")[0]
    sub = brand.split("（")[1].split("）")[0] if "（" in brand else ""
    # 纯JS操作：打开下拉→nativeInputValueSetter输入→等搜索→点选
    found = await ext.evaluate(f"""() => new Promise(resolve => {{
        const sel = document.querySelectorAll('.ant-select-selector');
        if (!sel.length) {{ resolve(null); return; }}
        sel[sel.length-1].dispatchEvent(new MouseEvent('mousedown', {{bubbles:true}}));
        setTimeout(() => {{
            const inp = document.querySelectorAll('input.ant-select-selection-search-input');
            if (!inp.length) {{ resolve(null); return; }}
            const el = inp[inp.length-1];
            el.focus();
            const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
            nativeSetter.call(el, '{kw}');
            el.dispatchEvent(new Event('input', {{bubbles:true}}));
            el.dispatchEvent(new Event('change', {{bubbles:true}}));
            setTimeout(() => {{
                const opts = document.querySelectorAll('.ant-select-item-option');
                for (const o of opts) {{
                    const t = o.textContent.trim();
                    if (t.includes('{kw}') && t.includes('{sub}')) {{ o.click(); resolve(t); return; }}
                }}
                document.activeElement && document.activeElement.blur();
                resolve(null);
            }}, 1500);
        }}, 500);
    }})""")
    if not found:
        L.error("plugin", f"品牌未找到: {brand}")
        return False, "品牌未找到"
    L.step("plugin", f"品牌已选中: {found}")
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
    L.step("plugin", f"品牌状态: {status}, 展开行数: {has_rows}")
    return True, status


async def get_stores(ext):
    """解析展开后的账号列表，按店铺名分组，返回 {storeName: [{platform, account, action}]}"""
    L.step("plugin", "解析店铺列表")
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

    result = dict(named)
    store_info = {k: [r['platform'] + '/' + r['action'] for r in v] for k, v in result.items()}
    L.step("plugin", f"找到{len(result)}家店铺", detail=str(store_info))
    return result


async def click_store_platform(ext, account):
    """点击指定账号的一键登录，返回 'ok'/'need_auth'/'not_found'"""
    L.step("plugin", f"点击一键登录: {account}")
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
            L.step("plugin", f"一键登录结果: {r} (account={account})")
            return r
        await ext.evaluate("() => document.querySelectorAll('.ant-table-row-expand-icon,[class*=expand]').forEach(b=>b.click())")
        await asyncio.sleep(1)
    L.error("plugin", f"账号未找到: {account}")
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


_user_app = None


async def save_user_focus(ctx):
    """记住运营当前前台app"""
    global _user_app
    _user_app = _get_frontmost_app()
    return None


async def stop_hider():
    """兼容接口，不再需要"""
    pass


async def restore_user_focus(page):
    """还焦点给用户之前的app"""
    _activate_app(_user_app)


async def close_store_pages(ctx):
    for p in ctx.pages:
        if ('waimai.meituan.com' in p.url or 'verify.meituan.com' in p.url or ('ele.me' in p.url and 'melody' in p.url)) and 'chrome-extension' not in p.url:
            try:
                await p.close()
            except:
                pass
    await asyncio.sleep(0.5)
