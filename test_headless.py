#!/usr/bin/env python3
"""测试headless模式下扩展加载情况"""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import patrol_log as L

async def test():
    L.start()
    from playwright.async_api import async_playwright
    from browser import launch_headless, kill_headless

    pw = await async_playwright().start()

    print("=== 启动headless ===")
    try:
        b, ctx = await launch_headless(pw)
    except Exception as e:
        print(f"启动失败: {e}")
        await pw.stop()
        return

    print(f"\n=== 连接成功, {len(ctx.pages)} 页面 ===")
    for p in ctx.pages:
        print(f"  page: {p.url[:80]}")

    # Service Workers
    print("\n=== Service Workers ===")
    ext_ids = set()
    for sw in ctx.service_workers:
        print(f"  sw: {sw.url[:80]}")
        if "chrome-extension://" in sw.url:
            eid = sw.url.split("://")[1].split("/")[0]
            ext_ids.add(eid)

    # Background Pages
    print("\n=== Background Pages ===")
    for bg in ctx.background_pages:
        print(f"  bg: {bg.url[:80]}")

    # Try known + discovered IDs
    known_id = "ljplecgkabpaemhfnmffajlpheeflocb"
    ext_ids.add(known_id)
    print(f"\n=== 测试打开扩展页面 ({len(ext_ids)} IDs) ===")

    for eid in ext_ids:
        url = f"chrome-extension://{eid}/index.html"
        print(f"\n  尝试: {eid[:16]}...")
        try:
            p = await ctx.new_page()
            resp = await p.goto(url, wait_until="commit", timeout=5000)
            status = resp.status if resp else "no response"
            print(f"  状态: {status}")
            print(f"  URL: {p.url[:80]}")
            content = await p.evaluate("() => document.body?.innerText?.substring(0,200) || 'empty'")
            print(f"  内容: {content[:100]}")
            await p.close()
        except Exception as e:
            print(f"  错误: {str(e)[:150]}")
            try:
                await p.close()
            except:
                pass

    # Check what ID headless actually assigned to loaded extensions
    print("\n=== 检查加载的扩展实际ID ===")
    try:
        p = await ctx.new_page()
        await p.goto("chrome://version", wait_until="commit", timeout=5000)
        await asyncio.sleep(1)
        text = await p.evaluate("() => document.body.innerText")
        # Find command line to see --load-extension
        for line in text.split("\n"):
            if "load-extension" in line.lower() or "command" in line.lower():
                print(f"  {line.strip()[:200]}")
        await p.close()
    except Exception as e:
        print(f"  chrome://version 错误: {e}")

    # Try listing extensions via CDP
    print("\n=== CDP Target查询 ===")
    import subprocess, json
    try:
        r = subprocess.run(
            ["curl", "--noproxy", "localhost", "-s", "http://localhost:9333/json"],
            capture_output=True, text=True, timeout=3
        )
        targets = json.loads(r.stdout)
        for t in targets:
            ttype = t.get("type", "")
            turl = t.get("url", "")[:80]
            ttitle = t.get("title", "")[:40]
            if "extension" in turl or "extension" in ttype or "service_worker" in ttype:
                print(f"  [{ttype}] {ttitle} — {turl}")
    except Exception as e:
        print(f"  CDP查询错误: {e}")

    # Also check /json/list for service workers
    try:
        r = subprocess.run(
            ["curl", "--noproxy", "localhost", "-s", "http://localhost:9333/json/list"],
            capture_output=True, text=True, timeout=3
        )
        targets = json.loads(r.stdout)
        ext_targets = [t for t in targets if "extension" in t.get("url", "")]
        if ext_targets:
            print(f"\n  扩展相关targets: {len(ext_targets)}")
            for t in ext_targets:
                print(f"    [{t.get('type','')}] {t.get('url','')[:80]}")
    except:
        pass

    kill_headless()
    await pw.stop()
    print("\n=== 测试完成 ===")

if __name__ == "__main__":
    asyncio.run(test())
