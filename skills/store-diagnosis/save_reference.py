#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
存入参考店铺库
用法:
  python3 save_reference.py '<json>'
  python3 save_reference.py --list              # 查看全部
  python3 save_reference.py --list --category 轻食  # 按品类查
"""

import argparse
import json
import os
import sys
from datetime import datetime

# 参考店铺库路径（QClaw knowledge目录下）
DB_PATHS = [
    os.path.expanduser("~/.qclaw/workspace/knowledge/reference_stores.json"),
    os.path.join(os.path.dirname(__file__), "../../knowledge/reference_stores.json"),
]


def get_db_path():
    """找到或创建数据库文件"""
    for p in DB_PATHS:
        if os.path.exists(p):
            return p
    # 默认用第一个路径
    p = DB_PATHS[0]
    os.makedirs(os.path.dirname(p), exist_ok=True)
    return p


def load_db(path):
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []


def save_db(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def add_store(store_data):
    """添加一个参考店铺"""
    db_path = get_db_path()
    stores = load_db(db_path)

    # 必填字段检查
    required = ["店铺名称", "参考原因"]
    for field in required:
        if field not in store_data:
            print(f"错误: 缺少必填字段 '{field}'", file=sys.stderr)
            sys.exit(1)

    # 补全默认值
    store_data.setdefault("日期", datetime.now().strftime("%Y-%m-%d"))
    store_data.setdefault("平台", "未知")
    store_data.setdefault("品类", "未知")

    # 检查是否已存在（按店铺名称去重）
    for i, existing in enumerate(stores):
        if existing.get("店铺名称") == store_data["店铺名称"]:
            stores[i] = store_data  # 更新
            save_db(db_path, stores)
            print(f"已更新: {store_data['店铺名称']}")
            print(f"库中共 {len(stores)} 家参考店铺")
            return

    stores.append(store_data)
    save_db(db_path, stores)
    print(f"已添加: {store_data['店铺名称']}")
    print(f"库中共 {len(stores)} 家参考店铺")
    print(f"存储位置: {db_path}")


def list_stores(category=None):
    """查看参考店铺"""
    db_path = get_db_path()
    stores = load_db(db_path)

    if not stores:
        print("参考店铺库为空")
        return

    if category:
        stores = [s for s in stores if category in s.get("品类", "")]
        if not stores:
            print(f"没有品类包含 '{category}' 的参考店铺")
            return

    print(f"=== 参考店铺库（{len(stores)}家）===\n")
    for s in stores:
        print(f"  {s.get('店铺名称', '?')} | {s.get('平台', '?')} | {s.get('品类', '?')}")
        print(f"    月销: {s.get('月销', '?')}  评分: {s.get('评分', '?')}")
        print(f"    参考原因: {s.get('参考原因', '?')}")
        print(f"    标记人: {s.get('标记人', '?')}  日期: {s.get('日期', '?')}")
        if s.get("关键数据"):
            print(f"    关键数据: {json.dumps(s['关键数据'], ensure_ascii=False)}")
        print()


def main():
    parser = argparse.ArgumentParser(description='参考店铺库管理')
    parser.add_argument('json_data', nargs='?', help='店铺JSON数据')
    parser.add_argument('--list', action='store_true', help='查看全部参考店铺')
    parser.add_argument('--category', default=None, help='按品类筛选')
    args = parser.parse_args()

    if args.list:
        list_stores(args.category)
    elif args.json_data:
        data = json.loads(args.json_data)
        add_store(data)
    else:
        # 从stdin读取
        data = json.load(sys.stdin)
        if isinstance(data, list):
            for item in data:
                add_store(item)
        else:
            add_store(data)


if __name__ == '__main__':
    main()
