"""浏览器连接模块 — 只连接，不启动。浏览器由运营手动打开。"""
import subprocess
import json
import os

PORT = int(os.environ.get("CHROME_PORT", "9222"))


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
    """检查端口上的浏览器是否加载了悟空插件"""
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


async def launch(pw, port=None):
    """
    连接已有浏览器，返回 (browser, context)。
    不启动浏览器——运营通过双击start.sh或手动打开。
    找不到时抛异常，由调用方引导运营操作。
    """
    if port is None:
        port = PORT

    ws = _check_port(port)
    if not ws:
        raise BrowserNotFound("没找到浏览器，请先打开盯店浏览器")

    if not _has_extension(port):
        raise ExtensionNotFound("浏览器在跑但没看到悟空插件")

    browser = await pw.chromium.connect_over_cdp(ws)
    print(f"✅ 已连接浏览器 (端口{port})")
    return browser, browser.contexts[0]


class BrowserNotFound(Exception):
    """浏览器未运行"""
    pass


class ExtensionNotFound(Exception):
    """浏览器在跑但没有插件"""
    pass
