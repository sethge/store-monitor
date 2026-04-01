#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
读取图片并输出base64，绕过sandbox限制
用法:
  python3 read_images.py image1.jpg image2.jpg ...
  python3 read_images.py /tmp/store_xxx/scene_*.jpg

输出JSON到stdout:
[
  {"file": "scene_001.jpg", "base64": "data:image/jpeg;base64,..."},
  ...
]

Agent拿到base64后可以作为图片内容传给模型读取。
"""

import base64
import json
import os
import sys


def read_image_base64(path):
    """读取图片文件，返回data URI格式的base64"""
    path = os.path.abspath(path)
    if not os.path.exists(path):
        return None

    ext = os.path.splitext(path)[1].lower()
    mime = {
        '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
        '.png': 'image/png', '.gif': 'image/gif',
        '.webp': 'image/webp', '.bmp': 'image/bmp',
    }.get(ext, 'image/jpeg')

    with open(path, 'rb') as f:
        data = base64.b64encode(f.read()).decode('ascii')

    return {
        "file": os.path.basename(path),
        "path": path,
        "mime": mime,
        "base64": data,
        "size": os.path.getsize(path),
    }


def main():
    if len(sys.argv) < 2:
        print("用法: python3 read_images.py image1.jpg image2.jpg ...", file=sys.stderr)
        sys.exit(1)

    results = []
    for path in sys.argv[1:]:
        path = os.path.abspath(path)
        if not os.path.exists(path):
            print(f"[跳过] 不存在: {path}", file=sys.stderr)
            continue

        info = read_image_base64(path)
        if info:
            results.append(info)
            print(f"[OK] {info['file']} ({info['size']} bytes)", file=sys.stderr)

    print(json.dumps(results, ensure_ascii=False))


if __name__ == '__main__':
    main()
