#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
提帧 + OCR（不做解析，解析交给 agent）
用法: python3 extract_ocr.py 视频1.mp4 视频2.mp4 ...
输出: 每张图的OCR文字（JSON到stdout）
"""
import json
import os
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))


def main():
    if len(sys.argv) < 2:
        print("用法: python3 extract_ocr.py 视频1.mp4 视频2.mp4 ...", file=sys.stderr)
        sys.exit(1)

    videos = [os.path.abspath(v) for v in sys.argv[1:]]
    for v in videos:
        if not os.path.exists(v):
            print(f"[错误] 文件不存在: {v}", file=sys.stderr)
            sys.exit(1)

    # Step 1: 提帧
    print("=" * 50, file=sys.stderr)
    print("Step 1/2: 提取关键帧", file=sys.stderr)
    print("=" * 50, file=sys.stderr)
    from extract_frames import extract_keyframes, sample_frames

    all_frames = []
    for v in videos:
        name = os.path.basename(v)
        print(f"  [{name}] 提帧中...", file=sys.stderr)
        try:
            frame_dir, total = extract_keyframes(v)
            sampled = sample_frames(frame_dir)
            all_frames.extend(sampled)
            print(f"  [{name}] {total}帧, 采样{len(sampled)}张", file=sys.stderr)
        except Exception as e:
            print(f"  [{name}] 错误: {e}", file=sys.stderr)

    if not all_frames:
        print("所有视频提帧失败", file=sys.stderr)
        sys.exit(1)

    # Step 2: 腾讯云 OCR
    print("", file=sys.stderr)
    print("=" * 50, file=sys.stderr)
    print(f"Step 2/2: OCR识别（{len(all_frames)}张）", file=sys.stderr)
    print("=" * 50, file=sys.stderr)

    from gemini_ocr import _load_config
    cfg = _load_config()
    has_tencent = bool(cfg.get('tencent_secret_id') or os.environ.get('TENCENT_SECRET_ID'))

    if has_tencent:
        try:
            from tencent_ocr import ocr_all_images
            ocr_result = ocr_all_images(all_frames)
            if ocr_result:
                total_lines = sum(len(v) for v in ocr_result.values())
                print(f"  OCR完成: {total_lines}行文字", file=sys.stderr)

                # 输出格式化的OCR文字
                output = []
                for fname in sorted(ocr_result.keys()):
                    texts = ocr_result[fname]
                    output.append(f"--- {fname} ---")
                    output.extend(texts)

                print("\n".join(output))
                return
        except Exception as e:
            print(f"  腾讯OCR失败: {e}", file=sys.stderr)

    # fallback: 用 EasyOCR 或 opencv 本地OCR
    print("  降级到本地OCR...", file=sys.stderr)
    try:
        from ocr_images import ocr_images
        ocr_result = ocr_images(all_frames)
        output = []
        for fname in sorted(ocr_result.keys()):
            items = ocr_result[fname]
            output.append(f"--- {fname} ---")
            for item in items:
                output.append(item["text"])
        print("\n".join(output))
    except Exception as e:
        print(f"  本地OCR也失败: {e}", file=sys.stderr)
        print("  请检查是否安装了 opencv 或 easyocr", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
