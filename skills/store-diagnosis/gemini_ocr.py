#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用Gemini视觉模型读取店铺截图，提取结构化竞对数据
用法: python3 gemini_ocr.py --key <GEMINI_API_KEY> image1.jpg image2.jpg ...
输出: 结构化JSON到stdout
"""
import argparse
import json
import os
import sys


PROMPT = '''你是外卖店铺数据提取专家。请仔细查看这些外卖平台店铺截图，提取所有数据。

必须返回严格JSON格式，不要返回其他内容：
{
  "店铺名称": "xxx(xxx店)",
  "平台": "美团/饿了么",
  "店铺评分": 4.8,
  "营业时间": "10:00-22:00",
  "月销": "300+",
  "实际配送费": "0元",
  "配送方式": "蜂鸟准时达/美团快送/美团配送",
  "评价数": 867,
  "差评数": 0,
  "差评率": 0,
  "满减档位": "38-3，49-5，65-7，78-11",
  "满减档位数": 4,
  "第一档满减力度": 0.079,
  "第二档满减力度": 0.102,
  "其他活动": "折扣商品xx折起; 新人立减xx; ...",
  "热销菜": [
    {"名称": "xxx", "月销": "61", "实际价格": 35.8, "折扣力度": 0}
  ]
}

热销菜规则：
- 取月销量最高的Top10
- 去掉：福利放送分类里的所有菜品
- 去掉：蘸料/小料/调料包/米饭/饮料/配菜
- 去掉：标注"单点不送"的
- 实际价格 = 菜单上显示的售价
- 折扣力度 = 如果有划线原价，则为 折扣价/原价；没有划线价则为 0
- 月销量写原始显示值（如 "800+"、"61"）
- 满减力度 = 减免额 ÷ 门槛（如38减3 → 3÷38=0.079）

未在截图中出现的字段写 "未获取"。只返回JSON，不要其他文字。'''


def _parse_json(text):
    """从Gemini响应中提取JSON"""
    text = text.strip()
    if text.startswith('```'):
        lines = text.split('\n')
        json_lines = []
        inside = False
        for line in lines:
            if line.startswith('```') and not inside:
                inside = True
                continue
            elif line.startswith('```') and inside:
                break
            elif inside:
                json_lines.append(line)
        text = '\n'.join(json_lines)
    return json.loads(text)


def read_images_with_gemini(api_key, image_paths, model='gemini-2.5-flash', batch_size=10):
    """分批读图，合并结果。避免一次发太多图片导致漏数据。"""
    from google import genai

    client = genai.Client(api_key=api_key, http_options={'api_version': 'v1beta'})

    # 分批
    batches = [image_paths[i:i+batch_size] for i in range(0, len(image_paths), batch_size)]
    all_results = []

    for batch_idx, batch in enumerate(batches):
        contents = []
        for path in batch:
            with open(path, 'rb') as f:
                img_data = f.read()
            contents.append(genai.types.Part.from_bytes(data=img_data, mime_type='image/jpeg'))
        contents.append(PROMPT)

        print(f"    批次{batch_idx+1}/{len(batches)}（{len(batch)}张）...", file=sys.stderr)
        resp = client.models.generate_content(model=model, contents=contents)
        result = _parse_json(resp.text)
        all_results.append(result)

    if len(all_results) == 1:
        return all_results[0]

    # 合并多批结果：基础信息取第一批（店铺首页在前面），热销菜合并去重取Top10
    merged = all_results[0].copy()
    all_dishes = {}

    for result in all_results:
        # 补充基础信息（第一批没拿到的字段用后面批次补）
        for key in ["店铺名称", "平台", "店铺评分", "营业时间", "月销",
                     "实际配送费", "配送方式", "评价数", "差评数", "差评率",
                     "满减档位", "满减档位数", "第一档满减力度", "第二档满减力度", "其他活动"]:
            if merged.get(key) in [None, "未获取", 0, ""] and result.get(key) not in [None, "未获取", 0, ""]:
                merged[key] = result[key]

        # 合并热销菜（按菜名去重，取最大月销）
        for dish in result.get("热销菜", []):
            name = dish.get("名称", "")
            if not name:
                continue
            sales_str = str(dish.get("月销", "0"))
            sales_num = int(sales_str.replace("+", "").replace(",", "") or "0")

            if name not in all_dishes or sales_num > all_dishes[name]["_sales_num"]:
                all_dishes[name] = {**dish, "_sales_num": sales_num}

    # 按月销排序取Top10
    sorted_dishes = sorted(all_dishes.values(), key=lambda x: x["_sales_num"], reverse=True)
    merged["热销菜"] = [{k: v for k, v in d.items() if k != "_sales_num"} for d in sorted_dishes[:10]]

    return merged


def main():
    parser = argparse.ArgumentParser(description='Gemini视觉读图')
    parser.add_argument('images', nargs='+', help='图片文件路径')
    parser.add_argument('--key', default=None, help='Gemini API Key（或设环境变量GEMINI_API_KEY）')
    args = parser.parse_args()

    api_key = args.key or os.environ.get('GEMINI_API_KEY')
    if not api_key:
        print("错误: 需要Gemini API Key（--key或GEMINI_API_KEY环境变量）", file=sys.stderr)
        sys.exit(1)

    # 验证文件存在
    valid = [p for p in args.images if os.path.exists(p)]
    if not valid:
        print("错误: 没有有效的图片文件", file=sys.stderr)
        sys.exit(1)

    print(f"[Gemini] 读取{len(valid)}张图片...", file=sys.stderr)
    result = read_images_with_gemini(api_key, valid)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
