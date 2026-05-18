#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
腾讯云高精度OCR + Gemini语义理解
策略：腾讯云负责精确文字识别，Gemini负责从OCR文字中提取结构化数据
"""
import base64
import json
import os
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
CONFIG_PATH = SCRIPT_DIR / "config.json"


def get_config():
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            return json.load(f)
    # 内置默认
    try:
        import base64
        from gemini_ocr import _DEFAULT_CFG
        return json.loads(base64.b64decode(_DEFAULT_CFG).decode())
    except:
        return {}


def ocr_one_image(client, image_path):
    """腾讯云高精度OCR识别一张图"""
    from tencentcloud.ocr.v20181119 import models

    with open(image_path, 'rb') as f:
        img_b64 = base64.b64encode(f.read()).decode()

    req = models.GeneralAccurateOCRRequest()
    req.ImageBase64 = img_b64
    resp = client.GeneralAccurateOCR(req)

    texts = []
    for item in resp.TextDetections:
        if item.Confidence >= 80:
            texts.append(item.DetectedText)
    return texts


def ocr_all_images(image_paths):
    """批量OCR所有图片"""
    from tencentcloud.common import credential
    from tencentcloud.ocr.v20181119 import ocr_client

    config = get_config()
    sid = config.get('tencent_secret_id') or os.environ.get('TENCENT_SECRET_ID')
    skey = config.get('tencent_secret_key') or os.environ.get('TENCENT_SECRET_KEY')

    if not sid or not skey:
        print("错误: 需要腾讯云SecretId/SecretKey", file=sys.stderr)
        return None

    cred = credential.Credential(sid, skey)
    client = ocr_client.OcrClient(cred, 'ap-guangzhou')

    all_texts = {}
    for i, path in enumerate(image_paths):
        fname = os.path.basename(path)
        print(f"    [{i+1}/{len(image_paths)}] OCR: {fname}", file=sys.stderr)
        try:
            texts = ocr_one_image(client, path)
            all_texts[fname] = texts
        except Exception as e:
            err = str(e)
            if 'RequestLimitExceeded' in err:
                print(f"    频率限制，等5秒...", file=sys.stderr)
                time.sleep(5)
                try:
                    texts = ocr_one_image(client, path)
                    all_texts[fname] = texts
                except:
                    print(f"    {fname} 重试失败", file=sys.stderr)
            else:
                print(f"    {fname} 失败: {e}", file=sys.stderr)
        time.sleep(0.5)  # 避免频率限制

    return all_texts


def gemini_parse(ocr_texts_str):
    """用Gemini从OCR文字中提取结构化数据"""
    from google import genai

    config = get_config()
    api_key = config.get('gemini_api_key') or os.environ.get('GEMINI_API_KEY')
    if not api_key:
        return None

    client = genai.Client(api_key=api_key, http_options={'api_version': 'v1beta'})

    prompt = f'''你是外卖数据分析专家。以下是对一家外卖店铺多张截图的OCR文字识别结果。请从中提取结构化数据。

OCR文字（按截图顺序排列）：
{ocr_texts_str}

请返回严格JSON：
{{
  "店铺名称": "完整店名(含分店)",
  "平台": "美团/饿了么",
  "店铺评分": 4.8,
  "营业时间": "未获取",
  "月销": "300+",
  "实际配送费": "0元",
  "配送方式": "蜂鸟准时达/美团快送",
  "评价数": 867,
  "差评数": "未获取",
  "差评率": "未获取",
  "满减档位": "38-3，49-5，65-7，78-11",
  "满减档位数": 4,
  "第一档满减力度": 0.079,
  "第二档满减力度": 0.102,
  "其他活动": "...",
  "热销菜": [
    {{"名称": "xxx", "月销": "61", "实际价格": 35.8, "折扣力度": 0}}
  ]
}}

热销菜提取规则：
- 找所有带"月售XX"或"月销XX"的菜品，按月销量从高到低排列
- 去掉"福利放送"分类下的菜品（特征：价格极低如¥0、¥1.77、¥2.1、¥3，标有"X份起购"）
- 去掉标有"单点不送"的
- 去掉蘸料/小料/饮料/米饭/调料
- 实际价格 = 菜品旁边的¥价格
- 折扣力度 = 有划线原价时为 折扣价÷原价，没有则为0
- 满减力度 = 减免额 ÷ 门槛
- 未出现的字段写 "未获取"

只返回JSON，不要其他文字。'''

    resp = client.models.generate_content(model='gemini-2.5-flash', contents=[prompt])
    text = resp.text.strip()

    if text.startswith('```'):
        lines = text.split('\n')
        json_lines = []
        inside = False
        for line in lines:
            if line.startswith('```') and not inside:
                inside = True; continue
            elif line.startswith('```') and inside:
                break
            elif inside:
                json_lines.append(line)
        text = '\n'.join(json_lines)

    return json.loads(text)


def read_images_with_tencent_gemini(image_paths):
    """腾讯OCR + Gemini理解"""

    # Step 1: 腾讯云OCR
    print(f"    阶段1: 腾讯云高精度OCR（{len(image_paths)}张）...", file=sys.stderr)
    all_texts = ocr_all_images(image_paths)
    if not all_texts:
        return None

    total_lines = sum(len(v) for v in all_texts.values())
    print(f"    OCR完成: {total_lines}行文字", file=sys.stderr)

    # 组装OCR文本
    ocr_str_parts = []
    for fname in sorted(all_texts.keys()):
        texts = all_texts[fname]
        ocr_str_parts.append(f"--- {fname} ---")
        ocr_str_parts.extend(texts)
    ocr_texts_str = "\n".join(ocr_str_parts)

    # Step 2: Gemini语义理解
    print(f"    阶段2: Gemini语义分析...", file=sys.stderr)
    result = gemini_parse(ocr_texts_str)

    if result:
        dishes = result.get("热销菜", [])
        print(f"    完成: {result.get('店铺名称','?')} | {len(dishes)}个热销菜", file=sys.stderr)

    return result


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('images', nargs='+')
    args = parser.parse_args()

    valid = [p for p in args.images if os.path.exists(p)]
    result = read_images_with_tencent_gemini(valid)
    if result:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
