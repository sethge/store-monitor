#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成竞对分析报告（自包含HTML文件，双击打开，不需要服务器）
用法: python3 deploy.py --data /tmp/competitor_data.json
输出: HTML文件路径
"""
import argparse, json, os, sys
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).parent
TEMPLATE = SCRIPT_DIR / "web" / "index.html"


def main():
    parser = argparse.ArgumentParser(description='生成竞对分析报告')
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

    # 读模板
    template_html = TEMPLATE.read_text(encoding='utf-8')

    # 把数据直接嵌入HTML（替换掉从URL hash读数据的逻辑）
    json_str = json.dumps(competitors, ensure_ascii=False, indent=2)

    # 替换 loadData 函数，直接返回嵌入的数据
    embedded_html = template_html.replace(
        'const COMPETITORS = loadData();',
        f'const COMPETITORS = {json_str};'
    )

    # CDN 换国内源
    embedded_html = embedded_html.replace(
        'https://cdn.jsdelivr.net/npm/exceljs@4.4.0/dist/exceljs.min.js',
        'https://unpkg.com/exceljs@4.4.0/dist/exceljs.min.js'
    )
    embedded_html = embedded_html.replace(
        'https://cdn.jsdelivr.net/npm/file-saver@2.0.5/dist/FileSaver.min.js',
        'https://unpkg.com/file-saver@2.0.5/dist/FileSaver.min.js'
    )
    embedded_html = embedded_html.replace(
        'https://cdn.jsdelivr.net/npm/lz-string@1.5.0/libs/lz-string.min.js',
        'https://unpkg.com/lz-string@1.5.0/libs/lz-string.min.js'
    )

    # 生成文件名
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    shop_names = [c.get('店铺名称', '竞对') for c in competitors[:3]]
    name_str = '+'.join(shop_names)[:30]
    output_path = os.path.expanduser(f"~/Desktop/竞对分析_{name_str}_{ts}.html")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(embedded_html)

    print(output_path)
    print(f"报告已保存到桌面", file=sys.stderr)


if __name__ == '__main__':
    main()
