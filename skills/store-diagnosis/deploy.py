#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成竞对分析链接
方案：本地临时服务器，不依赖任何外部平台
用法: python3 deploy.py --data '<json或文件路径>'
输出: 本地链接（自动打开浏览器）
"""
import argparse, json, os, sys, threading, time
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler

try:
    import lzstring
    def compress(s):
        return lzstring.LZString().compressToEncodedURIComponent(s)
except ImportError:
    import base64, zlib
    def compress(s):
        compressed = zlib.compress(s.encode('utf-8'))
        return base64.urlsafe_b64encode(compressed).decode('ascii').rstrip('=')

WEB_DIR = Path(__file__).parent / "web"
PORT = 18890


def find_free_port():
    """找一个可用端口"""
    import socket
    for port in range(PORT, PORT + 100):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind(('127.0.0.1', port))
            s.close()
            return port
        except OSError:
            continue
    return PORT


def start_server(port):
    """在后台启动本地服务器"""
    os.chdir(str(WEB_DIR))
    handler = SimpleHTTPRequestHandler
    handler.log_message = lambda *args: None  # 静默日志
    server = HTTPServer(('127.0.0.1', port), handler)
    server.serve_forever()


def main():
    parser = argparse.ArgumentParser(description='生成竞对分析链接')
    parser.add_argument('--data', required=True, help='竞对JSON数据（文件路径或内联JSON）')
    args = parser.parse_args()

    if os.path.exists(args.data):
        with open(args.data, 'r', encoding='utf-8') as f:
            data = json.load(f)
    else:
        data = json.loads(args.data)

    competitors = data if isinstance(data, list) else data.get('competitors', data.get('竞对', [data]))
    if not competitors:
        print("错误: 无竞对数据", file=sys.stderr)
        sys.exit(1)

    json_str = json.dumps(competitors, ensure_ascii=False, separators=(',', ':'))
    encoded = compress(json_str)

    port = find_free_port()

    # 启动本地服务器
    t = threading.Thread(target=start_server, args=(port,), daemon=True)
    t.start()
    time.sleep(0.3)

    url = f"http://127.0.0.1:{port}/index.html#{encoded}"

    # 输出链接
    print(url)

    # 如果是直接运行（不是被其他脚本调用），自动打开浏览器并保持服务器运行
    if os.isatty(sys.stdout.fileno()):
        import webbrowser
        webbrowser.open(url)
        print(f"\n服务器运行中（端口 {port}）。运营用完后按 Ctrl+C 关闭。", file=sys.stderr)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
