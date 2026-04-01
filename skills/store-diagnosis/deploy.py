#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成竞对分析链接
用法: python3 deploy.py --data '<json或文件路径>'
输出: 带数据的唯一URL，每次分析一个独立链接
"""
import argparse, json, os, sys

# LZString Python实现（URI安全压缩）
# 与前端 LZString.compressToEncodedURIComponent 兼容
try:
    import lzstring
    def compress(s):
        return lzstring.LZString().compressToEncodedURIComponent(s)
except ImportError:
    # 内联最小实现
    import base64, zlib
    def compress(s):
        compressed = zlib.compress(s.encode('utf-8'))
        return base64.urlsafe_b64encode(compressed).decode('ascii').rstrip('=')

BASE_URL = "https://sethge.github.io/store-monitor/"

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

    json_str = json.dumps(competitors, ensure_ascii=False, separators=(',',':'))
    encoded = compress(json_str)
    url = f"{BASE_URL}#{encoded}"

    print(url)

if __name__ == '__main__':
    main()
