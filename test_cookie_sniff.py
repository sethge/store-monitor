#!/usr/bin/env python3
"""
抓取美团差评API和通知API的真实URL
用playwright打开页面，拦截所有API请求，记录完整URL+headers
"""
import asyncio, json, sys, os
sys.path.insert(0, os.path.dirname(__file__))

from playwright.async_api import async_playwright
from plugin_helper import get_ext, pick_brand, get_stores, click_store_platform, close_store_pages
from browser import launch_headless, kill_headless


async def main():
    brand = sys.argv[1] if len(sys.argv) > 1 else None
    if not brand:
        ops_file = os.path.join(os.path.dirname(__file__), "ops-logger", "operators.json")
        with open(ops_file) as f:
            ops = json.load(f)
        for op, brands in ops.items():
            brand = list(brands.keys())[0]
            break

    print(f"=== API抓包 === 品牌: {brand}\n")

    pw = await async_playwright().start()
    browser, ctx = await launch_headless(pw)

    ext = await get_ext(ctx)
    ok, _ = await pick_brand(ext, brand)
    stores = await get_stores(ext)

    # 找美团账号
    target_acct = None
    for store_key, accounts in stores.items():
        for acct in accounts:
            if acct['platform'] == 'meituan' and acct['action'] == '一键登录':
                target_acct = acct
                break
        if target_acct: break

    await click_store_platform(ext, target_acct['account'])
    await asyncio.sleep(4)

    mt_page = None
    for p in ctx.pages:
        if 'waimai.meituan.com' in p.url and 'chrome-extension' not in p.url:
            mt_page = p
            break

    if not mt_page:
        print("美团页面未打开")
        kill_headless()
        await pw.stop()
        return

    # 拦截所有API请求
    captured = []

    async def on_request(req):
        url = req.url
        if any(k in url for k in ['comment', 'message', 'notice', 'rating', 'account/info']):
            captured.append({
                'url': url,
                'method': req.method,
                'headers': dict(req.headers),
            })
            print(f"  REQ: {req.method} {url[:120]}")

    async def on_response(resp):
        url = resp.url
        if any(k in url for k in ['comment', 'message', 'notice', 'rating', 'account/info']):
            ct = resp.headers.get('content-type', '')
            body = ''
            try:
                if 'json' in ct:
                    body = json.dumps(await resp.json(), ensure_ascii=False)[:200]
            except:
                pass
            print(f"  RESP: {resp.status} {url[:120]}")
            if body:
                print(f"        {body}")

    mt_page.on("request", on_request)
    mt_page.on("response", on_response)

    # 1. 去消息页
    print("--- 通知页 ---")
    await mt_page.goto("https://e.waimai.meituan.com/new_fe/business_gw#/msgbox", wait_until="commit", timeout=15000)
    await asyncio.sleep(3)

    # 2. 去评价页
    print("\n--- 评价页 ---")
    await mt_page.goto("https://e.waimai.meituan.com/#https://waimaieapp.meituan.com/frontweb/ffw/userComment_gw", wait_until="commit", timeout=15000)
    await asyncio.sleep(5)

    # 点差评tab (Flutter)
    for f in mt_page.frames:
        try:
            has = await f.evaluate("() => !!document.querySelector('flt-glass-pane')")
            if not has: continue
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
            await asyncio.sleep(2)
            break
        except:
            pass

    mt_page.remove_listener("request", on_request)
    mt_page.remove_listener("response", on_response)

    # 保存抓到的API信息
    print(f"\n=== 共捕获 {len(captured)} 个API请求 ===")
    for c in captured:
        print(f"\n  URL: {c['url']}")
        print(f"  Method: {c['method']}")
        # 只显示关键headers
        for h in ['cookie', 'x-requested-with', 'content-type', 'referer', 'origin']:
            if h in c['headers']:
                val = c['headers'][h]
                if h == 'cookie':
                    val = val[:80] + '...'
                print(f"  {h}: {val}")

    out = os.path.join(os.path.dirname(__file__), "ops-logger", "_api_captures.json")
    with open(out, 'w') as f:
        json.dump(captured, f, ensure_ascii=False, indent=2)
    print(f"\n已保存到 {out}")

    kill_headless()
    await pw.stop()


if __name__ == '__main__':
    asyncio.run(main())
