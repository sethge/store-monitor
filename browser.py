"""浏览器启动模块 — 用playwright自带的Chrome for Testing，版本锁死不受系统Chrome升级影响"""
import asyncio
import subprocess
import json
import os
from pathlib import Path

EXT_PATH = str(Path(__file__).parent / "goku")


async def launch(pw, port=9222):
    """
    启动浏览器并返回 (browser, context)。
    优先连接已有的调试端口，没有则用playwright自带chromium启动。
    """
    # 1. 先检查是否已有浏览器在跑
    try:
        r = subprocess.run(
            ["curl", "--noproxy", "localhost", "-s", f"http://localhost:{port}/json/version"],
            capture_output=True, text=True, timeout=3
        )
        if r.returncode == 0 and r.stdout.strip():
            ws = json.loads(r.stdout)["webSocketDebuggerUrl"]
            browser = await pw.chromium.connect_over_cdp(ws)
            print(f"✅ 已连接浏览器 (端口{port})")
            return browser, browser.contexts[0]
    except Exception:
        pass

    # 2. 用playwright自带chromium启动（版本锁定，不受系统Chrome升级影响）
    print("启动浏览器...")
    user_dir = os.path.expanduser("~/chromium-debug")
    os.makedirs(user_dir, exist_ok=True)

    ctx = await pw.chromium.launch_persistent_context(
        user_data_dir=user_dir,
        headless=False,
        args=[
            f"--remote-debugging-port={port}",
            f"--disable-extensions-except={EXT_PATH}",
            f"--load-extension={EXT_PATH}",
            "--no-first-run",
            "--disable-default-apps",
            "--disable-sync",
            "--no-default-browser-check",
        ],
    )
    await asyncio.sleep(3)
    browser = ctx.browser
    print(f"✅ 浏览器已启动 (端口{port})")
    return browser, ctx
