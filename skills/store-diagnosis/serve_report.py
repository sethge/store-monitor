#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
竞对分析网页服务
用法:
  python3 serve_report.py --data competitors.json [--port 8080]
  python3 serve_report.py --data '<inline json>' [--port 8080]

启动后浏览器自动打开，运营填完分析后点击下载生成Excel。
"""

import argparse
import json
import os
import sys
import tempfile
import webbrowser
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

SCRIPT_DIR = Path(__file__).parent
TEMPLATE_PATH = SCRIPT_DIR / "web" / "template.html"
WRITE_EXCEL_PATH = SCRIPT_DIR / "write_excel.py"
SAVE_REF_PATH = SCRIPT_DIR / "save_reference.py"

# 全局存储竞对数据
COMPETITORS = []


class ReportHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # 静默日志，只打印关键信息
        pass

    def do_GET(self):
        path = urlparse(self.path).path
        if path == '/' or path == '/index.html':
            self.serve_page()
        else:
            self.send_error(404)

    def do_POST(self):
        path = urlparse(self.path).path
        if path == '/api/download':
            self.handle_download()
        else:
            self.send_error(404)

    def serve_page(self):
        """提供填写分析的网页"""
        template = TEMPLATE_PATH.read_text(encoding='utf-8')
        # 注入竞对数据
        html = template.replace('__COMPETITORS_JSON__', json.dumps(COMPETITORS, ensure_ascii=False))

        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))

    def handle_download(self):
        """接收分析数据，生成Excel返回"""
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)
        payload = json.loads(body)

        competitors = payload.get('competitors', [])
        analysis = payload.get('analysis', None)
        references = payload.get('references', [])

        # 生成Excel
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"竞对分析_{timestamp}.xlsx"
        output_path = os.path.join(tempfile.gettempdir(), filename)

        # 也存一份到桌面
        desktop_path = os.path.expanduser(f"~/Desktop/{filename}")

        try:
            # 调用 write_excel.py
            import subprocess
            data_json = json.dumps({
                'competitors': competitors,
                'analysis': analysis,
            }, ensure_ascii=False)

            result = subprocess.run(
                [sys.executable, str(WRITE_EXCEL_PATH), '-o', desktop_path],
                input=data_json, capture_output=True, text=True
            )

            if result.returncode != 0:
                raise RuntimeError(result.stderr)

            # 存参考店铺
            for ref in references:
                if ref.get('店铺名称') and ref.get('参考原因'):
                    ref['日期'] = datetime.now().strftime('%Y-%m-%d')
                    subprocess.run(
                        [sys.executable, str(SAVE_REF_PATH), json.dumps(ref, ensure_ascii=False)],
                        capture_output=True, text=True
                    )

            # 返回Excel文件
            with open(desktop_path, 'rb') as f:
                excel_data = f.read()

            self.send_response(200)
            self.send_header('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
            self.send_header('X-Filename', filename)
            self.send_header('Content-Length', str(len(excel_data)))
            self.end_headers()
            self.wfile.write(excel_data)

            print(f"  ✅ Excel已生成: {desktop_path}")
            if references:
                print(f"  📌 已存入{len(references)}家参考店铺")

        except Exception as e:
            error_msg = str(e)
            self.send_response(500)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write(f"生成失败: {error_msg}".encode('utf-8'))
            print(f"  ❌ 生成失败: {error_msg}")


def main():
    global COMPETITORS

    parser = argparse.ArgumentParser(description='竞对分析网页服务')
    parser.add_argument('--data', required=True, help='竞对数据JSON文件路径或内联JSON')
    parser.add_argument('--port', type=int, default=8080, help='端口号（默认8080）')
    parser.add_argument('--no-open', action='store_true', help='不自动打开浏览器')
    args = parser.parse_args()

    # 加载数据
    data_str = args.data
    if os.path.exists(data_str):
        with open(data_str, 'r', encoding='utf-8') as f:
            data = json.load(f)
    else:
        data = json.loads(data_str)

    # 兼容格式
    if isinstance(data, list):
        COMPETITORS = data
    else:
        COMPETITORS = data.get('competitors', data.get('竞对', [data]))

    if not COMPETITORS:
        print("错误: 无竞对数据")
        sys.exit(1)

    # 启动服务器
    port = args.port
    server = HTTPServer(('127.0.0.1', port), ReportHandler)
    url = f"http://127.0.0.1:{port}"

    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"  竞对分析报告")
    print(f"  {len(COMPETITORS)} 个竞对店铺")
    print(f"  {url}")
    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"  运营打开链接填写分析，填完点下载")
    print(f"  按 Ctrl+C 关闭服务\n")

    if not args.no_open:
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已关闭")
        server.server_close()


if __name__ == '__main__':
    main()
