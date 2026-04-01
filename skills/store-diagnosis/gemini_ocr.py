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


def read_images_with_gemini(api_key, image_paths, model='gemini-2.5-flash'):
    """用Gemini读图提取数据"""
    from google import genai

    client = genai.Client(api_key=api_key, http_options={'api_version': 'v1beta'})

    # 构建内容：所有图片 + prompt
    contents = []
    for path in image_paths:
        with open(path, 'rb') as f:
            img_data = f.read()
        contents.append(genai.types.Part.from_bytes(data=img_data, mime_type='image/jpeg'))

    contents.append(PROMPT)

    resp = client.models.generate_content(model=model, contents=contents)
    text = resp.text.strip()

    # 提取JSON（可能被```包裹）
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
