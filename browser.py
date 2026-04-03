"""浏览器模块 — 直接跑二进制启动（不用playwright launch，它会加--disable-extensions）"""
import asyncio
import subprocess
import glob
import json
import os
import sys
from pathlib import Path

EXT_PATH = str(Path(__file__).parent / "goku")
CHROME_USER_DIR = os.path.expanduser("~/Library/Application Support/Chrome-Debug")
CHROMIUM_USER_DIR = os.path.expanduser("~/chromium-debug")
PORT = int(os.environ.get("CHROME_PORT", "9222"))


def _find_chrome():
    """优先系统Chrome"""
    if sys.platform == "darwin":
        path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        if os.path.exists(path):
            return path, CHROME_USER_DIR
    elif sys.platform == "win32":
        for base in [os.environ.get("PROGRAMFILES", ""), os.environ.get("PROGRAMFILES(X86)", "")]:
            path = os.path.join(base, "Google", "Chrome", "Application", "chrome.exe")
            if os.path.exists(path):
                return path, os.path.join(os.environ.get("LOCALAPPDATA", ""), "Chrome-Debug")
    return None, None


def _find_pw_chromium():
    """playwright自带chromium做fallback"""
    if sys.platform == "darwin":
        paths = glob.glob(os.path.expanduser(
            "~/Library/Caches/ms-playwright/chromium-*/chrome-mac*/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"
        ))
        if paths:
            return sorted(paths)[-1], CHROMIUM_USER_DIR
    elif sys.platform == "win32":
        paths = glob.glob(os.path.join(
            os.environ.get("LOCALAPPDATA", ""), "ms-playwright", "chromium-*", "chrome-win", "chrome.exe"
        ))
        if paths:
            return sorted(paths)[-1], CHROMIUM_USER_DIR
    return None, None


def _check_port(port):
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


async def launch(pw, port=None):
    """
    启动浏览器并连接。
    用subprocess.Popen直接跑二进制（不用playwright launch，避免--disable-extensions）。
    然后用playwright connect_over_cdp连上去操作。
    """
    if port is None:
        port = PORT

    # 1. 已有浏览器在跑 → 直接连
    ws = _check_port(port)
    if ws:
        try:
            browser = await pw.chromium.connect_over_cdp(ws)
            print(f"✅ 已连接浏览器 (端口{port})")
            return browser, browser.contexts[0]
        except Exception:
            pass

    # 2. 找浏览器二进制
    binary, user_dir = _find_chrome()
    label = "Chrome"
    if not binary:
        binary, user_dir = _find_pw_chromium()
        label = "chromium"
    if not binary:
        raise Exception("找不到Chrome或chromium，请运行: playwright install chromium")

    # 3. 直接跑二进制（不走playwright launch）
    print(f"启动{label}...")
    os.makedirs(user_dir, exist_ok=True)
    subprocess.Popen([
        binary,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_dir}",
        f"--disable-extensions-except={EXT_PATH}",
        f"--load-extension={EXT_PATH}",
        "--no-first-run",
        "--disable-default-apps",
        "--disable-sync",
        "--no-default-browser-check",
        "--proxy-server=direct://",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # 4. 等端口就绪
    for i in range(20):
        await asyncio.sleep(1)
        ws = _check_port(port)
        if ws:
            try:
                browser = await pw.chromium.connect_over_cdp(ws)
                # 等插件加载
                await asyncio.sleep(3)
                print(f"✅ {label}已启动 (端口{port})")
                return browser, browser.contexts[0]
            except Exception:
                pass

    raise Exception(f"{label}启动超时")
