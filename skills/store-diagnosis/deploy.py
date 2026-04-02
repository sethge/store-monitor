#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成竞对分析报告 → 保存到桌面 + JSON数据存本地
用法: python3 deploy.py --data /tmp/competitor_data.json
输出: 桌面HTML路径
"""
import argparse, json, os, sys
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).parent
TEMPLATE = SCRIPT_DIR / "web" / "index.html"
DATA_DIR = SCRIPT_DIR.parent.parent / "memory" / "diagnosis"


def save_local(competitors, filename):
    """保存JSON数据到本地（积累店铺数据库）"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    data_file = DATA_DIR / filename
    with open(data_file, 'w', encoding='utf-8') as f:
        json.dump(competitors, f, ensure_ascii=False, indent=2)
    return str(data_file)


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

    # 读模板 + 嵌入数据
    template_html = TEMPLATE.read_text(encoding='utf-8')
    json_str = json.dumps(competitors, ensure_ascii=False, indent=2)
    embedded_html = template_html.replace(
        'const COMPETITORS = loadData();',
        'const COMPETITORS = {};'.format(json_str)
    )

    # CDN 换国内源（jsdelivr国内不稳定）
    embedded_html = embedded_html.replace(
        'https://cdn.jsdelivr.net', 'https://unpkg.com'
    )

    # 文件名
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    shop_names = [c.get('店铺名称', '竞对') for c in competitors[:3]]
    name_str = '+'.join(shop_names)[:30]

    # 1. 保存JSON数据（积累店铺数据库）
    local_filename = "{}_{}.json".format(name_str, ts)
    local_path = save_local(competitors, local_filename)
    print("  数据已保存: {}".format(local_path), file=sys.stderr)

    # 2. 保存HTML到桌面（运营双击打开）
    desktop_filename = "竞对分析_{}_{}.html".format(name_str, ts)
    desktop_path = os.path.expanduser("~/Desktop/{}".format(desktop_filename))
    with open(desktop_path, 'w', encoding='utf-8') as f:
        f.write(embedded_html)
    print(desktop_path)
    print("  ✅ 报告已保存到桌面，双击打开", file=sys.stderr)


if __name__ == '__main__':
    main()
