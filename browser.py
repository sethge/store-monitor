"""浏览器模块 — 连接运营自己的Chrome，不开新实例"""
import asyncio
import subprocess
import json
import os
import sys
from pathlib import Path

_IS_WIN = sys.platform == 'win32'
_IS_MAC = sys.platform == 'darwin'

EXT_PATH = str(Path(__file__).parent / "goku")
PORT = 9222


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



def _chrome_is_running():
    """检查Chrome是否在运行"""
    if _IS_MAC:
        try:
            r = subprocess.run(["pgrep", "-f", "Google Chrome"], capture_output=True)
            return r.returncode == 0
        except Exception:
            return False
    elif _IS_WIN:
        try:
            r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq chrome.exe"],
                               capture_output=True, text=True)
            return "chrome.exe" in r.stdout.lower()
        except Exception:
            return False
    return False


def _kill_chrome():
    """关闭Chrome"""
    if _IS_MAC:
        subprocess.run(["pkill", "-f", "Google Chrome"], capture_output=True)
    elif _IS_WIN:
        subprocess.run(["taskkill", "/F", "/IM", "chrome.exe"],
                       capture_output=True)


async def launch(pw, port=PORT):
    """连接运营的Chrome。优先直连，连不上就重启Chrome带debug端口"""

    # 1. 已有debug端口 → 直连
    ws = _cdp_ws(port)
    if ws:
        browser = await pw.chromium.connect_over_cdp(ws)
        return browser, browser.contexts[0]

    # 2. Chrome在跑但没debug端口 → 关掉重开
    chrome = _find_chrome()
    front_app = _get_front_app()

    if _chrome_is_running():
        print("  Chrome需要重启以启用调试端口...")
        _kill_chrome()
        await asyncio.sleep(2)

    # 3. 启动Chrome，用默认profile（运营自己的），带debug端口
    #    不传 --user-data-dir，Chrome用默认profile
    #    不传 --load-extension，运营Chrome里已经装了Goku和ops-logger
    cmd = [
        chrome,
        f"--remote-debugging-port={port}",
        "--no-first-run",
        "--no-default-browser-check",
        "--proxy-server=direct://",
    ]
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # 等端口就绪
    for _ in range(20):
        await asyncio.sleep(1)
        ws = _cdp_ws(port)
        if ws:
            browser = await pw.chromium.connect_over_cdp(ws)
            await asyncio.sleep(2)
            _activate_app(front_app)
            return browser, browser.contexts[0]

    raise Exception("浏览器启动超时")


def _cdp_ws(port):
    """获取CDP WebSocket地址"""
    try:
        if _IS_WIN:
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
    raise Exception("找不到Chrome，请安装Chrome")
