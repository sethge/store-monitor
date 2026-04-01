#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
竞对数据写入Excel
用法: python3 write_excel.py [-o 输出路径] < data.json
或:   echo '{"competitors": [...]}' | python3 write_excel.py

输入JSON格式:
{
  "competitors": [
    {
      "店铺名称": "xxx",
      "店铺评分": 4.8,
      "营业时间": "10:00-22:00",
      "月销": "300+",
      "实际配送费": "0元",
      "配送方式": "蜂鸟准时达",
      "评价数": 867,
      "差评数": 0,
      "差评率": 0,
      "满减档位": "38-3，49-5，65-7，78-11",
      "满减档位数": 4,
      "第一档满减力度": 0.079,
      "第二档满减力度": 0.102,
      "其他活动": "...",
      "热销菜": [
        {"名称": "xxx", "月销": "61", "实际价格": 35.8, "折扣力度": 0},
        ...
      ]
    }
  ]
}
"""

import argparse
import json
import os
import sys
from datetime import datetime


def write_excel(competitors, output_path, analysis=None):
    """
    analysis 格式:
    {
      "结论": {"店铺评分": "...", "营业时间": "...", "月销": "...", "配送费": "...",
               "配送方式": "...", "菜单": "...", "评价": "...", "差评率": "...",
               "活动": "...", "活动丰富度": "..."},
      "调整措施": { 同上 },
      "目的": { 同上 }
    }
    """
    import xlsxwriter

    wb = xlsxwriter.Workbook(output_path)
    ws = wb.add_worksheet("竞对报告")

    # ── 列宽 ──
    for col, w in enumerate([5.64, 28.76, 25.47, 18.64, 17.0, 24.76, 20.47,
                              50.64, 10.88, 11.94, 13.12, 21.64, 14.12, 18.88,
                              19.64, 13.0, 13.0, 13.0, 31.64]):
        ws.set_column(col, col, w)

    # ── 格式 ──
    fmt_title = wb.add_format({
        'bold': True, 'font_size': 10, 'align': 'center', 'valign': 'vcenter',
        'border': 1,
    })
    fmt_cat = wb.add_format({
        'bold': True, 'font_size': 10, 'align': 'center', 'valign': 'vcenter',
        'text_wrap': True, 'border': 1, 'bg_color': '#FFC000',
    })
    fmt_field = wb.add_format({
        'bold': True, 'font_size': 10, 'align': 'center', 'valign': 'vcenter',
        'border': 1, 'bg_color': '#FFC000',
    })
    fmt_data = wb.add_format({
        'font_size': 10, 'align': 'center', 'valign': 'vcenter',
        'text_wrap': True, 'border': 1,
    })
    fmt_data_nw = wb.add_format({
        'font_size': 10, 'align': 'center', 'valign': 'vcenter', 'border': 1,
    })
    fmt_a = wb.add_format({
        'font_size': 12, 'align': 'center', 'valign': 'vcenter',
        'text_wrap': True, 'border': 1,
    })
    fmt_ah = wb.add_format({
        'bold': True, 'font_size': 10, 'align': 'center', 'valign': 'vcenter',
        'border': 1, 'bg_color': '#FFC000',
    })
    fmt_label = wb.add_format({
        'bold': True, 'font_size': 12, 'align': 'center', 'valign': 'vcenter',
        'border': 1,
    })
    fmt_acell = wb.add_format({
        'font_size': 12, 'align': 'center', 'valign': 'vcenter',
        'text_wrap': True, 'border': 1,
    })

    # ── Row 1: 标题 ──
    ws.set_row(0, 17.1)
    ws.merge_range('B1:S1', '基础信息数据表（地址：）', fmt_title)

    # ── Row 2: 分类 ──
    ws.set_row(1, 17.1)
    ws.merge_range('B2:E2', '基础', fmt_cat)
    ws.merge_range('F2:G2', '配送', fmt_cat)
    ws.merge_range('H2:K2', '菜单', fmt_cat)
    ws.merge_range('L2:N2', '评论', fmt_cat)
    ws.merge_range('O2:S2', '活动', fmt_cat)

    # ── Row 3: 字段 ──
    ws.set_row(2, 32.1)
    for col, name in [(1,'店铺名称'),(2,'店铺评分'),(3,'营业时间'),(4,'月销'),
                       (5,'实际配送费'),(6,'配送方式'),
                       (7,'热销菜名称'),(8,'菜品月销量'),(9,'实际价格'),(10,'折扣力度'),
                       (11,'商家评论数'),(12,'差评数'),(13,'差评率'),
                       (14,'满减档位'),(15,'满减档位数'),(16,'第一档满减力度'),
                       (17,'第二档满减力度'),(18,'其他营销活动')]:
        ws.write(2, col, name, fmt_field)

    # ── 竞对数据 ──
    row = 3
    total_rows = sum(max(len(c.get('热销菜', [])), 1) for c in competitors)

    # A列
    if total_rows == 1:
        ws.write(row, 0, '竞对品牌', fmt_a)
    elif total_rows > 1:
        ws.merge_range(row, 0, row + total_rows - 1, 0, '竞对品牌', fmt_a)

    def g(comp, key, default='未获取'):
        v = comp.get(key, default)
        return v if v is not None else default

    for comp in competitors:
        dishes = comp.get('热销菜', [])
        if not dishes:
            dishes = [{'名称': '未获取', '月销': '', '实际价格': '', '折扣力度': ''}]
        n = len(dishes)

        for r in range(row, row + n):
            ws.set_row(r, 30.0)

        # B-G, L-S 合并列
        merge_data = {
            1: g(comp, '店铺名称'), 2: g(comp, '店铺评分'),
            3: g(comp, '营业时间'), 4: g(comp, '月销'),
            5: g(comp, '实际配送费'), 6: g(comp, '配送方式'),
            11: g(comp, '评价数'), 12: g(comp, '差评数'), 13: g(comp, '差评率'),
            14: g(comp, '满减档位'), 15: g(comp, '满减档位数'),
            16: g(comp, '第一档满减力度'), 17: g(comp, '第二档满减力度'),
            18: g(comp, '其他活动'),
        }
        for col, val in merge_data.items():
            if n == 1:
                ws.write(row, col, val, fmt_data)
            else:
                ws.merge_range(row, col, row + n - 1, col, val, fmt_data)

        # H-K 热销菜
        for i, dish in enumerate(dishes):
            r = row + i
            ws.write(r, 7, dish.get('名称', ''), fmt_data_nw)
            ws.write(r, 8, dish.get('月销', ''), fmt_data_nw)
            ws.write(r, 9, dish.get('实际价格', ''), fmt_data_nw)
            ws.write(r, 10, dish.get('折扣力度', ''), fmt_data_nw)

        row += n

    # ── 分析区 ──
    row += 1

    # 标题行
    ws.set_row(row, 32.1)
    ws.write(row, 1, '竞对分析', fmt_ah)
    for col, name in [(2,'店铺评分'),(3,'营业时间'),(4,'月销'),(5,'配送费'),(6,'配送方式'),
                       (11,'评价数'),(18,'活动丰富度')]:
        ws.write(row, col, name, fmt_ah)
    ws.merge_range(row, 7, row, 10, '菜单版块（热销、定价、折扣）', fmt_ah)
    ws.merge_range(row, 12, row, 13, '差评率', fmt_ah)
    ws.merge_range(row, 14, row, 17, '活动版块（档位、自营销力度）', fmt_ah)
    row += 1

    # 分析区维度→列映射
    dim_col = {
        "店铺评分": [2], "营业时间": [3], "月销": [4],
        "配送费": [5], "配送方式": [6],
        "菜单": [7, 8, 9, 10],  # H:K合并
        "评价": [11],
        "差评率": [12, 13],      # M:N合并
        "活动": [14, 15, 16, 17],  # O:R合并
        "活动丰富度": [18],
    }

    # 结论/调整措施/目的
    for label in ['结论', '调整措施', '目的']:
        for r in range(row, row + 3):
            ws.set_row(r, 16.5)
        ws.merge_range(row, 1, row + 2, 1, label, fmt_label)

        # 获取该区块的运营填写内容
        section = {}
        if analysis and label in analysis:
            section = analysis[label]

        # 单列维度
        for dim, cols in dim_col.items():
            val = section.get(dim, '')
            if len(cols) == 1:
                ws.merge_range(row, cols[0], row + 2, cols[0], val, fmt_acell)
            else:
                ws.merge_range(row, cols[0], row + 2, cols[-1], val, fmt_acell)

        row += 3

    wb.close()


def main():
    parser = argparse.ArgumentParser(description='竞对数据写入Excel')
    parser.add_argument('-o', '--output', default=None, help='输出路径')
    parser.add_argument('json_file', nargs='?', default=None, help='JSON数据文件（不指定则从stdin读取）')
    args = parser.parse_args()

    # 读取JSON
    if args.json_file:
        with open(args.json_file, 'r') as f:
            data = json.load(f)
    else:
        data = json.load(sys.stdin)

    # 兼容两种格式：直接列表 或 {"competitors": [...], "analysis": {...}}
    analysis = None
    if isinstance(data, list):
        competitors = data
    else:
        competitors = data.get('competitors', data.get('竞对', [data]))
        analysis = data.get('analysis', data.get('分析', None))

    if not competitors:
        print("错误: 无竞对数据", file=sys.stderr)
        sys.exit(1)

    # 输出路径
    if args.output:
        out = os.path.abspath(args.output)
    else:
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        out = os.path.expanduser(f"~/Desktop/竞对分析_{ts}.xlsx")

    os.makedirs(os.path.dirname(out), exist_ok=True)
    write_excel(competitors, out, analysis=analysis)
    print(out)


if __name__ == '__main__':
    main()
