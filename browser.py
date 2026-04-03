"""浏览器启动模块 — 直接跑二进制+CDP连接，不用playwright的launch（它会加--disable-extensions）"""
import asyncio
import subprocess
import glob
import json
import os
import sys
from pathlib import Path

EXT_PATH = str(Path(__file__).parent / "goku")

# 用户数据目录（和日常Chrome隔离）
CHROME_USER_DIR = os.path.expanduser("~/Library/Application Support/Chrome-Debug")
CHROMIUM_USER_DIR = os.path.expanduser("~/chromium-debug")

PORT = int(os.environ.get("CHROME_PORT", "9222"))


def _find_chrome():
    """查找系统Chrome"""
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


def _find_pw_chromium():
    """查找playwright自带的chromium"""
    if sys.platform == "darwin":
        paths = glob.glob(os.path.expanduser(
            "~/Library/Caches/ms-playwright/chromium-*/chrome-mac*/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"
        ))
        if paths:
            return sorted(paths)[-1]
    elif sys.platform == "win32":
        paths = glob.glob(os.path.join(
            os.environ.get("LOCALAPPDATA", ""), "ms-playwright", "chromium-*", "chrome-win", "chrome.exe"
        ))
        if paths:
            return sorted(paths)[-1]
    return None


def _check_port(port):
    """检查端口是否有CDP响应，返回ws地址或None"""
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


def _has_extension(port):
    """检查端口上的浏览器是否加载了扩展"""
    try:
        r = subprocess.run(
            ["curl", "--noproxy", "localhost", "-s", f"http://localhost:{port}/json/list"],
            capture_output=True, text=True, timeout=3
        )
        if r.returncode == 0 and r.stdout.strip():
            for p in json.loads(r.stdout):
                if "chrome-extension://" in p.get("url", ""):
                    return True
    except Exception:
        pass
    return False


def _start_browser(binary, user_dir, port):
    """直接启动浏览器二进制（不走playwright的launch，避免--disable-extensions）"""
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


async def launch(pw, port=None):
    """
    启动浏览器并返回 (browser, context)。
    所有方式都是：启动二进制 → 等CDP端口 → connect_over_cdp连接。
    绝不用playwright的launch_persistent_context（它会注入--disable-extensions）。
    """
    if port is None:
        port = PORT

    # 1. 检查是否已有浏览器在跑且带扩展
    ws = _check_port(port)
    if ws:
        if _has_extension(port):
            try:
                browser = await pw.chromium.connect_over_cdp(ws)
                print(f"✅ 已连接浏览器 (端口{port})")
                return browser, browser.contexts[0]
            except Exception:
                pass
        else:
            # 端口被占但没有我们的扩展，换端口
            print(f"⚠️ 端口{port}被占用（无插件），换{port+1}")
            port += 1

    # 2. 找浏览器二进制：优先系统Chrome，没有就用playwright的chromium
    chrome = _find_chrome()
    if chrome:
        label = "Chrome"
        user_dir = CHROME_USER_DIR
    else:
        chrome = _find_pw_chromium()
        label = "chromium"
        user_dir = CHROMIUM_USER_DIR

    if not chrome:
        raise Exception("找不到Chrome或chromium，请运行: playwright install chromium")

    # 3. 启动
    print(f"启动{label}...")
    _start_browser(chrome, user_dir, port)

    # 4. 等CDP端口就绪（最多20秒，首次创建profile慢）
    for i in range(20):
        await asyncio.sleep(1)
        ws = _check_port(port)
        if ws:
            try:
                browser = await pw.chromium.connect_over_cdp(ws)
                print(f"✅ {label}已启动 (端口{port})")
                # 再等几秒让插件加载
                await asyncio.sleep(3)
                return browser, browser.contexts[0]
            except Exception:
                pass

    raise Exception(f"{label}启动超时，端口{port}无响应")
