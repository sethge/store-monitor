"""湘湖知味 — 用locator切换前10%"""
import asyncio
from playwright.async_api import async_playwright

PORT = 9222

async def cdp_ws():
    import subprocess, json
    r = subprocess.run(["curl", "--noproxy", "localhost", "-s", f"http://localhost:{PORT}/json/version"],
                       capture_output=True, text=True, timeout=3)
    return json.loads(r.stdout).get("webSocketDebuggerUrl")

async def get_frame_and_page(browser):
    for c in browser.contexts:
        for p in c.pages:
            if 'chrome-extension' in p.url: continue
            for f in p.frames:
                if 'waimaieapp.meituan.com' in f.url and 'flowrate' in f.url and 'token=' in f.url:
                    try:
                        if await f.evaluate("() => document.body.innerText.substring(0,10)"): return f, p
                    except: pass
    return None, None

async def read_funnel(frame):
    text = await frame.evaluate("() => document.body.innerText")
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    out, cap = [], False
    for l in lines:
        if '流量转化' in l: cap = True
        if cap: out.append(l)
        if cap and '想提升' in l: break
    return '\n'.join(out[:25])

async def main():
    ws = await cdp_ws()
    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(ws)
        frame, page = await get_frame_and_page(browser)
        if not frame: print("找不到frame"); return

        # 近30日
        await frame.locator("text=近30日").first.click()
        await asyncio.sleep(2)

        for tab_name in ["全部顾客", "新客", "老客"]:
            # 点tab
            await frame.locator(f"text={tab_name}").first.click()
            await asyncio.sleep(2)

            # 点开下拉（第二个has-icon是商圈选择下拉）
            dropdown = frame.locator(".roo-input-group.has-icon").nth(1)
            await dropdown.click()
            await asyncio.sleep(0.5)

            # 点前10%选项（用locator找roo-popup里的选项）
            try:
                opt = frame.locator(".roo-popup .roo-dropdown-item, .roo-popup li, .roo-popup div").filter(has_text="商圈同行前10%均值")
                await opt.first.click(timeout=3000)
                await asyncio.sleep(2)
                print(f"{tab_name}: 切换成功")
            except Exception as e:
                print(f"{tab_name}: 切换失败 - {e}")
                # 备选：用JS在popup中点
                await frame.evaluate("""() => {
                    const popup = document.querySelector('.roo-popup, .roo-dropdown-menu');
                    if (!popup) return;
                    const items = popup.querySelectorAll('*');
                    for (const item of items) {
                        if (item.textContent.trim() === '商圈同行前10%均值') {
                            item.dispatchEvent(new MouseEvent('click', {bubbles: true}));
                            return;
                        }
                    }
                }""")
                await asyncio.sleep(2)

            # 截图
            await page.screenshot(path=f"/tmp/xh_{tab_name}.png")

            # 读数据
            print(f"\n=== {tab_name} ===")
            print(await read_funnel(frame))

asyncio.run(main())
