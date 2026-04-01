#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本地OCR读图（免费，不需要API）
用法: python3 ocr_images.py image1.jpg image2.jpg ...
输出: 每张图的OCR文字结果（JSON格式）

Agent拿到OCR文字后，自己分析提取结构化数据。
"""
import json
import os
import sys


def ocr_images(image_paths):
    import easyocr
    reader = easyocr.Reader(['ch_sim', 'en'], gpu=False, verbose=False)

    results = {}
    for path in image_paths:
        path = os.path.abspath(path)
        if not os.path.exists(path):
            print(f"[跳过] 不存在: {path}", file=sys.stderr)
            continue

        name = os.path.basename(path)
        print(f"[OCR] {name}...", file=sys.stderr)

        ocr_result = reader.readtext(path)
        # 按置信度过滤，只保留>0.3的
        texts = []
        for (bbox, text, conf) in ocr_result:
            if conf > 0.3:
                # bbox坐标用于判断位置（上下左右）
                y_center = (bbox[0][1] + bbox[2][1]) / 2
                x_center = (bbox[0][0] + bbox[2][0]) / 2
                texts.append({
                    "text": text,
                    "confidence": round(conf, 2),
                    "y": round(y_center),
                    "x": round(x_center),
                })

        # 按y坐标排序（从上到下）
        texts.sort(key=lambda t: (t["y"], t["x"]))
        results[name] = texts
        print(f"[完成] {name}: {len(texts)}个文字块", file=sys.stderr)

    return results


def main():
    if len(sys.argv) < 2:
        print("用法: python3 ocr_images.py image1.jpg image2.jpg ...", file=sys.stderr)
        sys.exit(1)

    results = ocr_images(sys.argv[1:])
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
