#!/usr/bin/env python3
"""启动Tabbit浏览器并暴露CDP端口，供agent巡检/预警使用。

不修改原browser.py，通过以下方式兼容：
1. 启动Tabbit时用 --remote-debugging-port=9222（和browser.py默认端口一致）
2. browser.py的launch()会自动连到9222端口
3. Goku和ops-logger扩展通过 --load-extension 或手动安装加载

用法:
  python3 launch_tabbit.py          # 启动Tabbit
  python3 launch_tabbit.py --port 9333  # 指定CDP端口
  python3 launch_tabbit.py --check  # 只检查Tabbit是否在运行
"""
import subprocess
import json
import os
import sys
import time
from pathlib import Path

TABBIT_PATHS = [
    "/Applications/Tabbit Browser.app/Contents/MacOS/Tabbit Browser",
    "/Applications/Tabbit.app/Contents/MacOS/Tabbit",
    os.path.expanduser("~/Applications/Tabbit Browser.app/Contents/MacOS/Tabbit Browser"),
]

# DevToolsActivePort 文件位置（Tabbit官方）
DEVTOOLS_PORT_FILES = [
    os.path.expanduser("~/Library/Application Support/Tabbit/DevToolsActivePort"),
    os.path.expanduser("~/Library/Application Support/Tabbit Browser/DevToolsActivePort"),
]

USER_DIR = os.path.expanduser("~/tabbit-debug")
DEFAULT_PORT = 9222

# 扩展路径
OPS_LOGGER_DIR = str(Path(__file__).parent / "extension")
GOKU_DIR = str(Path(__file__).parent.parent / "goku")


def find_tabbit():
    for p in TABBIT_PATHS:
        if os.path.exists(p):
            return p
    return None


def read_devtools_port():
    """从DevToolsActivePort文件读取CDP端口"""
    for f in DEVTOOLS_PORT_FILES:
        if os.path.exists(f):
            try:
                with open(f) as fh:
                    port = int(fh.readline().strip())
                    return port
            except (ValueError, IOError):
                continue
    return None


def check_cdp(port):
    """检查CDP端口是否可连"""
    try:
        r = subprocess.run(
            ["curl", "--noproxy", "localhost", "-s", f"http://localhost:{port}/json/version"],
            capture_output=True, text=True, timeout=3
        )
        if r.returncode == 0 and r.stdout.strip():
            info = json.loads(r.stdout)
            return info
    except Exception:
        pass
    return None


def launch(port=DEFAULT_PORT):
    """启动Tabbit，返回CDP端口号"""

    # 1. 检查是否已有Tabbit在跑（先试指定端口，再试DevToolsActivePort）
    info = check_cdp(port)
    if info:
        browser = info.get("Browser", "")
        print(f"  Tabbit已在运行 (port={port}, {browser})")
        return port

    auto_port = read_devtools_port()
    if auto_port and auto_port != port:
        info = check_cdp(auto_port)
        if info:
            print(f"  Tabbit已在运行 (port={auto_port}, 从DevToolsActivePort读取)")
            return auto_port

    # 2. 找Tabbit可执行文件
    tabbit = find_tabbit()
    if not tabbit:
        print("  ERROR: 找不到Tabbit Browser，请先安装")
        print("  下载: https://www.tabbit-ai.com/")
        sys.exit(1)

    # 3. 启动
    os.makedirs(USER_DIR, exist_ok=True)

    args = [
        tabbit,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={USER_DIR}",
        "--no-first-run",
        "--no-default-browser-check",
        "--proxy-server=direct://",
    ]

    # 加载扩展（如果目录存在）
    extensions = []
    if os.path.exists(GOKU_DIR):
        extensions.append(GOKU_DIR)
    if os.path.exists(OPS_LOGGER_DIR):
        extensions.append(OPS_LOGGER_DIR)
    if extensions:
        args.append(f"--load-extension={','.join(extensions)}")

    print(f"  启动Tabbit (port={port})...")
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # 4. 等待就绪
    for i in range(20):
        time.sleep(1)
        info = check_cdp(port)
        if info:
            print(f"  Tabbit就绪 ({info.get('Browser', '')})")
            return port

    # 5. fallback: 检查DevToolsActivePort
    auto_port = read_devtools_port()
    if auto_port:
        info = check_cdp(auto_port)
        if info:
            print(f"  Tabbit就绪 (port={auto_port}, 自动分配)")
            return auto_port

    print("  ERROR: Tabbit启动超时")
    sys.exit(1)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="启动Tabbit浏览器")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--check", action="store_true", help="只检查是否在运行")
    args = parser.parse_args()

    if args.check:
        info = check_cdp(args.port)
        if info:
            print(f"Tabbit在运行: port={args.port}, {info.get('Browser', '')}")
        else:
            auto_port = read_devtools_port()
            if auto_port:
                info = check_cdp(auto_port)
                if info:
                    print(f"Tabbit在运行: port={auto_port}, {info.get('Browser', '')}")
                    sys.exit(0)
            print("Tabbit未运行")
            sys.exit(1)
    else:
        port = launch(args.port)
        print(f"CDP端口: {port}")
