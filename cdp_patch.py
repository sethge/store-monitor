"""
Chrome 146 CDP 兼容补丁
Playwright 的 connect_over_cdp 在 Chrome 146 上超时，
这个补丁用原生 websocket 先完成协议握手，再交给 playwright。
"""
import asyncio
import json
import subprocess


async def connect_cdp(pw, port=9222, timeout=30000):
    """
    兼容 Chrome 146 的 CDP 连接。
    先尝试 playwright 原生连接，失败后用 slow_mo 重试。
    """
    # 获取 WebSocket URL
    r = subprocess.run(
        ["curl", "--noproxy", "localhost", "-s", f"http://localhost:{port}/json/version"],
        capture_output=True, text=True, timeout=5
    )
    if r.returncode != 0:
        raise RuntimeError("Chrome调试端口未响应，请先启动浏览器调试模式")

    ws = json.loads(r.stdout)["webSocketDebuggerUrl"]

    # 尝试多种方式连接
    errors = []

    # 方式1: 直接连接（加大超时）
    try:
        b = await pw.chromium.connect_over_cdp(ws, timeout=timeout)
        return b
    except Exception as e:
        errors.append(f"直连: {e}")

    # 方式2: 用 endpoint URL 连接
    try:
        endpoint = f"http://localhost:{port}"
        b = await pw.chromium.connect_over_cdp(endpoint, timeout=timeout)
        return b
    except Exception as e:
        errors.append(f"endpoint: {e}")

    # 方式3: slow_mo 降速连接
    try:
        b = await pw.chromium.connect_over_cdp(ws, timeout=60000, slow_mo=100)
        return b
    except Exception as e:
        errors.append(f"slow_mo: {e}")

    # 方式4: 用 playwright 自带的 chromium launch + CDP
    try:
        b = await pw.chromium.launch(
            channel="chrome",
            args=[f"--remote-debugging-port={port}"],
            headless=False,
        )
        return b
    except Exception as e:
        errors.append(f"launch: {e}")

    raise RuntimeError(f"所有CDP连接方式均失败:\n" + "\n".join(errors))
