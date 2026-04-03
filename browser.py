"""浏览器启动模块 — 优先用系统Chrome（调试模式），chromium做fallback"""
import asyncio
import subprocess
import json
import os
import sys
from pathlib import Path

EXT_PATH = str(Path(__file__).parent / "goku")

# Chrome调试模式用户目录
CHROME_USER_DIR = os.path.expanduser("~/Library/Application Support/Chrome-Debug")
CHROMIUM_USER_DIR = os.path.expanduser("~/chromium-debug")


async def launch(pw, port=9222):
    """
    启动浏览器并返回 (browser, context)。
    优先级：1.已运行的浏览器 → 2.系统Chrome调试模式 → 3.playwright自带chromium
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

    # 2. 尝试用系统Chrome调试模式启动
    chrome_path = _find_chrome()
    if chrome_path:
        try:
            print(f"启动Chrome调试模式...")
            os.makedirs(CHROME_USER_DIR, exist_ok=True)
            subprocess.Popen([
                chrome_path,
                f"--remote-debugging-port={port}",
                f"--user-data-dir={CHROME_USER_DIR}",
                f"--disable-extensions-except={EXT_PATH}",
                f"--load-extension={EXT_PATH}",
                "--no-first-run",
                "--disable-default-apps",
                "--disable-sync",
                "--no-default-browser-check",
                "--proxy-server=direct://",
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            # 等Chrome启动并监听端口
            for _ in range(10):
                await asyncio.sleep(1)
                try:
                    r = subprocess.run(
                        ["curl", "--noproxy", "localhost", "-s", f"http://localhost:{port}/json/version"],
                        capture_output=True, text=True, timeout=3
                    )
                    if r.returncode == 0 and r.stdout.strip():
                        ws = json.loads(r.stdout)["webSocketDebuggerUrl"]
                        browser = await pw.chromium.connect_over_cdp(ws)
                        print(f"✅ Chrome已启动 (端口{port})")
                        return browser, browser.contexts[0]
                except Exception:
                    pass
            print("⚠️ Chrome启动超时，降级到chromium")
        except Exception as e:
            print(f"⚠️ Chrome启动失败({e})，降级到chromium")

    # 3. Fallback: 用playwright自带chromium
    print("启动chromium...")
    os.makedirs(CHROMIUM_USER_DIR, exist_ok=True)

    ctx = await pw.chromium.launch_persistent_context(
        user_data_dir=CHROMIUM_USER_DIR,
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
    print(f"✅ chromium已启动 (端口{port})")
    return ctx, ctx


def _find_chrome():
    """查找系统Chrome路径"""
    if sys.platform == "darwin":
        path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        if os.path.exists(path):
            return path
    elif sys.platform == "win32":
        for base in [os.environ.get("PROGRAMFILES", ""), os.environ.get("PROGRAMFILES(X86)", "")]:
            path = os.path.join(base, "Google", "Chrome", "Application", "chrome.exe")
            if os.path.exists(path):
                return path
    return None
