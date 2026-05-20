"""浏览器模块 — 连接运营自己的Chrome，不开新实例；支持headless模式"""
import asyncio
import subprocess
import json
import os
import sys
import shutil
from pathlib import Path

_IS_WIN = sys.platform == 'win32'
_IS_MAC = sys.platform == 'darwin'

EXT_PATH = str(Path(__file__).parent / "goku")
OPS_LOGGER_PATH = str(Path(__file__).parent / "ops-logger" / "extension")
PORT = 9222
HEADLESS_PORT = 9333
HEADLESS_PROFILE = "/tmp/chrome-headless-patrol"
SOURCE_PROFILE = os.path.expanduser("~/chrome-debug")


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


def _sync_headless_profile():
    """同步headless profile的登录态。首次全拷，之后只增量同步Cookies"""
    import patrol_log as L
    src = Path(SOURCE_PROFILE)
    dst = Path(HEADLESS_PROFILE)

    if not src.exists():
        L.error("profile", f"Chrome profile不存在: {src}")
        raise Exception(f"Chrome profile不存在: {src}，请先用带debug端口的Chrome登录过")

    if not dst.exists():
        # 首次：全量拷贝
        L.step("profile", f"首次拷贝 {src} → {dst}")
        shutil.copytree(str(src), str(dst), symlinks=True,
                        ignore=shutil.ignore_patterns('Cache', 'Code Cache', 'Service Worker',
                                                       'GPUCache', 'DawnGraphiteCache', 'DawnWebGPUCache',
                                                       'GrShaderCache', 'ShaderCache', 'blob_storage'))
        # 删除锁文件
        for lock in dst.rglob("SingletonLock"):
            lock.unlink(missing_ok=True)
        for lock in dst.rglob("SingletonCookie"):
            lock.unlink(missing_ok=True)
        for lock in dst.rglob("SingletonSocket"):
            lock.unlink(missing_ok=True)
        L.step("profile", f"首次拷贝完成: {dst}")
    else:
        # 增量：只同步关键登录文件
        files_to_sync = [
            "Default/Cookies",
            "Default/Cookies-journal",
            "Default/Extension Cookies",
            "Default/Extension Cookies-journal",
            "Local State",
        ]
        for f in files_to_sync:
            s = src / f
            d = dst / f
            if s.exists():
                d.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(s), str(d))
        # 删除锁文件
        for lock in dst.rglob("SingletonLock"):
            lock.unlink(missing_ok=True)
        for lock in dst.rglob("SingletonCookie"):
            lock.unlink(missing_ok=True)
        for lock in dst.rglob("SingletonSocket"):
            lock.unlink(missing_ok=True)


async def launch_headless(pw, port=HEADLESS_PORT):
    """启动无头Chrome，零窗口巡检。返回 (browser, context)"""
    import patrol_log as L

    # 1. 已有headless在跑 → 直连
    ws = _cdp_ws(port)
    if ws:
        L.step("headless", f"复用已有headless (port {port})")
        browser = await pw.chromium.connect_over_cdp(ws)
        return browser, browser.contexts[0]

    # 2. 同步profile登录态
    _sync_headless_profile()

    # 3. 杀掉旧的headless进程（端口+进程名双重检查）
    killed = False
    try:
        r = subprocess.run(["lsof", "-i", f":{port}", "-t"], capture_output=True, text=True)
        pids = r.stdout.strip().split()
        if pids and pids[0]:
            for pid in pids:
                subprocess.run(["kill", "-9", pid], capture_output=True)
            L.step("headless", f"杀掉端口{port}旧进程: {pids}")
            killed = True
    except Exception:
        pass
    try:
        r = subprocess.run(["pgrep", "-f", "headless=new"], capture_output=True, text=True)
        pids = r.stdout.strip().split()
        if pids and pids[0]:
            for pid in pids:
                subprocess.run(["kill", "-9", pid], capture_output=True)
            if not killed:
                L.step("headless", f"杀掉残留headless进程: {pids}")
            killed = True
    except Exception:
        pass
    if killed:
        await asyncio.sleep(2)
    # 清理锁文件
    from pathlib import Path as _P
    for lock in _P(HEADLESS_PROFILE).glob("Singleton*"):
        try: lock.unlink()
        except: pass

    # 4. 启动headless Chrome
    chrome = _find_chrome()
    ext_load = f"{EXT_PATH},{OPS_LOGGER_PATH}"
    L.step("headless", f"启动 --headless=new port={port}", detail=f"extensions={ext_load}")
    cmd = [
        chrome,
        "--headless=new",
        f"--remote-debugging-port={port}",
        f"--user-data-dir={HEADLESS_PROFILE}",
        f"--load-extension={ext_load}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-gpu",
        "--proxy-server=direct://",
    ]
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # 等端口就绪
    for i in range(20):
        await asyncio.sleep(1)
        ws = _cdp_ws(port)
        if ws:
            browser = await pw.chromium.connect_over_cdp(ws)
            await asyncio.sleep(2)
            pages = [p.url[:60] for p in browser.contexts[0].pages]
            L.step("headless", f"连接成功 ({i+1}s), {len(pages)}个页面", detail=str(pages))
            return browser, browser.contexts[0]

    L.error("headless", "启动超时(20s)")
    raise Exception("Headless Chrome启动超时")


async def ensure_https(page):
    """Goku的一键登录会打开http://，在headless下会失败。检测并修正为https://"""
    url = page.url
    if url.startswith("http://e.waimai.meituan.com"):
        await page.goto(url.replace("http://", "https://"), wait_until="commit", timeout=15000)
    elif url.startswith("http://melody.shop.ele.me"):
        await page.goto(url.replace("http://", "https://"), wait_until="commit", timeout=15000)


async def check_headless_login(ctx):
    """检查headless的登录状态，返回 (ok, message)
    检查Goku插件是否有品牌（=已登录），检查美团/饿了么cookies是否有效"""
    from plugin_helper import get_ext
    try:
        ext = await get_ext(ctx)
    except Exception:
        return False, "找不到悟空插件，请确认Chrome已登录悟空"

    # 检查悟空是否有品牌数据
    for _ in range(3):
        ready = await ext.evaluate("() => document.querySelectorAll('.ant-select-selector').length > 0")
        if ready:
            break
        await asyncio.sleep(1)
    if not ready:
        return False, "悟空插件未就绪"

    # 打开下拉看有没有品牌
    await ext.evaluate("() => {const s=document.querySelectorAll('.ant-select-selector');if(s.length)s[s.length-1].dispatchEvent(new MouseEvent('mousedown',{bubbles:true}))}")
    await asyncio.sleep(1)
    count = await ext.evaluate("() => document.querySelectorAll('.ant-select-item-option').length")
    await ext.evaluate("() => document.activeElement && document.activeElement.blur()")

    if count == 0:
        return False, "悟空登录已过期，请在Chrome中重新打开悟空插件登录"

    return True, f"就绪（{count}个品牌）"


def kill_headless(port=HEADLESS_PORT):
    """关闭headless Chrome进程"""
    try:
        r = subprocess.run(["lsof", "-i", f":{port}", "-t"], capture_output=True, text=True)
        for pid in r.stdout.strip().split():
            if pid:
                subprocess.run(["kill", "-9", pid], capture_output=True)
    except Exception:
        pass
