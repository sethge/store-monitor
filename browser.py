"""浏览器模块 — Popen启动 + connect_over_cdp连接"""
import asyncio
import subprocess
import json
import os
import sys
from pathlib import Path

_IS_WIN = sys.platform == 'win32'
_IS_MAC = sys.platform == 'darwin'


def _get_front_app():
    if _IS_MAC:
        try:
            r = subprocess.run(["osascript", "-e", 'tell application "System Events" to get name of first process whose frontmost is true'],
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
    if not handle:
        return
    if _IS_MAC:
        try:
            subprocess.Popen(["osascript", "-e", f'tell application "{handle}" to activate'],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
    elif _IS_WIN:
        try:
            import ctypes
            ctypes.windll.user32.SetForegroundWindow(handle)
        except Exception:
            pass


def _hide_chrome():
    """隐藏/最小化Chrome，防止tab操作抢焦点"""
    if _IS_MAC:
        try:
            subprocess.Popen(["osascript", "-e", 'tell application "System Events" to set visible of process "Google Chrome" to false'],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
    elif _IS_WIN:
        try:
            import ctypes
            from ctypes import wintypes
            SW_MINIMIZE = 6
            user32 = ctypes.windll.user32

            @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            def _cb(hwnd, _):
                if user32.IsWindowVisible(hwnd):
                    buf = ctypes.create_unicode_buffer(256)
                    user32.GetClassNameW(hwnd, buf, 256)
                    if buf.value == 'Chrome_WidgetWin_1':
                        user32.ShowWindow(hwnd, SW_MINIMIZE)
                return True

            user32.EnumWindows(_cb, 0)
        except Exception:
            pass


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

    # 没有 → 启动（记住当前前台app，启动后还焦点）
    chrome = _find_chrome()
    os.makedirs(USER_DIR, exist_ok=True)
    front_app = _get_front_app()
    subprocess.Popen([
        chrome,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={USER_DIR}",
        f"--load-extension={EXT_PATH}",
        "--no-first-run",
        "--no-default-browser-check",
        "--proxy-server=direct://",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # 等端口就绪
    for _ in range(20):
        await asyncio.sleep(1)
        ws = _cdp_ws(port)
        if ws:
            browser = await pw.chromium.connect_over_cdp(ws)
            await asyncio.sleep(2)
            _hide_chrome()
            _activate_app(front_app)
            return browser, browser.contexts[0]

    raise Exception("浏览器启动超时")


def _cdp_ws(port):
    """获取CDP WebSocket地址"""
    try:
        if _IS_WIN:
            # Windows没有curl，用urllib
            import urllib.request
            r = urllib.request.urlopen(f"http://localhost:{port}/json/version", timeout=3)
            data = json.loads(r.read().decode())
            return data.get("webSocketDebuggerUrl")
        else:
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
    if _IS_WIN:
        candidates = [
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        ]
    else:
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        ]
    for p in candidates:
        if os.path.exists(p):
            return p
    if not _IS_WIN:
        # playwright chromium (macOS)
        import glob
        paths = glob.glob(os.path.expanduser(
            "~/Library/Caches/ms-playwright/chromium-*/chrome-mac*/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"
        ))
        if paths:
            return sorted(paths)[-1]
    raise Exception("找不到Chrome，请安装Chrome")
