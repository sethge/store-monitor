"""湘湖知味 — 抓当前满减活动数据"""
import asyncio
from playwright.async_api import async_playwright

PORT = 9222

async def cdp_ws():
    import subprocess, json
    r = subprocess.run(["curl", "--noproxy", "localhost", "-s", f"http://localhost:{PORT}/json/version"],
                       capture_output=True, text=True, timeout=3)
    return json.loads(r.stdout).get("webSocketDebuggerUrl")

async def get_mt_page(browser):
    for c in browser.contexts:
        for p in c.pages:
            if 'chrome-extension' in p.url: continue
            if 'waimaieapp.meituan.com' in p.url or 'e.waimai.meituan.com' in p.url:
                return p
            for f in p.frames:
                if 'waimaieapp.meituan.com' in f.url:
                    return p
    return None

async def main():
    ws = await cdp_ws()
    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(ws)
        page = await get_mt_page(browser)
        if not page:
            print("找不到美团后台页面，请先在Chrome打开美团商家后台")
            return

        # 点左侧活动中心菜单
        await page.evaluate("""() => {
            const els = document.querySelectorAll('*');
            for (const el of els) {
                if (el.textContent.trim() === '活动中心' && el.children.length <= 2 && el.offsetParent) {
                    el.click(); return;
                }
            }
        }""")
        await asyncio.sleep(4)
        await page.screenshot(path="/tmp/xh_activity_clicked.png")

        # 找活动相关frame
        target_frame = None
        for f in page.frames:
            if 'waimaieapp.meituan.com' in f.url:
                try:
                    text = await f.evaluate("() => document.body.innerText")
                    if len(text.strip()) > 50:
                        target_frame = f
                        print(f"frame url: {f.url}")
                        break
                except:
                    pass

        if not target_frame:
            print("找不到活动frame")
            return

        text = await target_frame.evaluate("() => document.body.innerText")
        lines = [l.strip() for l in text.split('\n') if l.strip()]

        print("=== 活动中心内容 ===")
        keywords = ['满', '减', '活动', '折扣', '优惠', '券', '神抢手', '配送', '立减', '进行中', '已结束']
        for l in lines:
            if any(k in l for k in keywords):
                print(l)

        print("\n=== 截图已保存 /tmp/xh_activity.png ===")
        await page.screenshot(path="/tmp/xh_activity.png")

asyncio.run(main())
