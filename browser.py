"""浏览器模块 — Popen启动 + connect_over_cdp连接"""
import asyncio
import subprocess
import json
import os
from pathlib import Path

EXT_PATH = str(Path(__file__).parent / "goku")
USER_DIR = os.path.expanduser("~/chrome-debug")
PORT = 9222


async def launch(pw, port=PORT):
    """连接已有浏览器，没有就启动一个"""

    # 已有浏览器 → 直接连
    ws = _cdp_ws(port)
    if ws:
        browser = await pw.chromium.connect_over_cdp(ws)
        return browser, browser.contexts[0]

    # 没有 → 启动
    chrome = _find_chrome()
    os.makedirs(USER_DIR, exist_ok=True)
    subprocess.Popen([
        chrome,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={USER_DIR}",
        f"--load-extension={EXT_PATH}",
        "--no-first-run",
        "--no-default-browser-check",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # 等端口就绪
    for _ in range(20):
        await asyncio.sleep(1)
        ws = _cdp_ws(port)
        if ws:
            browser = await pw.chromium.connect_over_cdp(ws)
            await asyncio.sleep(2)
            return browser, browser.contexts[0]

    raise Exception("浏览器启动超时")


def _cdp_ws(port):
    try:
        r = subprocess.run(
            ["curl", "--noproxy", "localhost", "-s", f"http://localhost:{port}/json/version"],
            capture_output=True, text=True, timeout=3
        )
        if r.returncode == 0 and r.stdout.strip():
            return json.loads(r.stdout).get("webSocketDebuggerUrl")
    except Exception:
        pass
    return None


def _find_chrome():
    """找Chrome"""
    candidates = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    # playwright chromium
    import glob
    paths = glob.glob(os.path.expanduser(
        "~/Library/Caches/ms-playwright/chromium-*/chrome-mac*/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"
    ))
    if paths:
        return sorted(paths)[-1]
    raise Exception("找不到Chrome，请安装Chrome或运行 playwright install chromium")
