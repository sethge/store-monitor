#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
竞对诊断一键流程
用法:
  python3 run_diagnosis.py --videos 视频1.mp4 视频2.mp4
  → 提帧 → 输出采样帧路径 → 等Agent把JSON写到 /tmp/competitor_data.json → 生成链接

  python3 run_diagnosis.py --generate-link /tmp/competitor_data.json
  → 直接从JSON生成链接
"""
import argparse
import json
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent


def step_extract(videos):
    """提帧+采样，返回所有采样帧路径"""
    from extract_frames import extract_keyframes, sample_frames

    all_sampled = {}
    for video in videos:
        video = os.path.abspath(video)
        if not os.path.exists(video):
            print(f"[跳过] 文件不存在: {video}", file=sys.stderr)
            continue
        try:
            name = os.path.basename(video)
            print(f"[提帧] {name}...", file=sys.stderr)
            frame_dir, total = extract_keyframes(video)
            sampled = sample_frames(frame_dir)
            print(f"[完成] {name}: {total}帧, 采样{len(sampled)}张", file=sys.stderr)
            all_sampled[name] = sampled
        except Exception as e:
            print(f"[错误] {name}: {e}", file=sys.stderr)

    return all_sampled


def step_read_images(sampled_paths):
    """把采样帧转base64输出"""
    from read_images import read_image_base64

    results = []
    for path in sampled_paths:
        info = read_image_base64(path)
        if info:
            results.append(info)
    return results


def step_generate_link(json_path):
    """从JSON文件生成公网链接"""
    try:
        import lzstring
        def compress(s):
            return lzstring.LZString().compressToEncodedURIComponent(s)
    except ImportError:
        import base64, zlib
        def compress(s):
            compressed = zlib.compress(s.encode('utf-8'))
            return base64.urlsafe_b64encode(compressed).decode('ascii').rstrip('=')

    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    competitors = data if isinstance(data, list) else data.get('competitors', [data])
    json_str = json.dumps(competitors, ensure_ascii=False, separators=(',', ':'))
    encoded = compress(json_str)
    return f"https://sethge.github.io/store-monitor/#{encoded}"


def main():
    parser = argparse.ArgumentParser(description='竞对诊断')
    sub = parser.add_subparsers(dest='cmd')

    # 子命令: extract
    p1 = sub.add_parser('extract', help='提帧+输出采样帧base64')
    p1.add_argument('videos', nargs='+', help='视频文件')

    # 子命令: link
    p2 = sub.add_parser('link', help='从JSON生成公网链接')
    p2.add_argument('json_file', help='竞对数据JSON文件路径')

    args = parser.parse_args()

    if args.cmd == 'extract':
        # 提帧
        all_sampled = step_extract(args.videos)
        if not all_sampled:
            print("错误: 所有视频提帧失败", file=sys.stderr)
            sys.exit(1)

        # 转base64
        print("\n请根据以下图片提取竞对数据：\n", file=sys.stderr)
        for video_name, paths in all_sampled.items():
            print(f"--- {video_name} ---", file=sys.stderr)
            images = step_read_images(paths)
            # 输出到stdout供Agent读取
            print(json.dumps({
                "video": video_name,
                "images": images,
            }, ensure_ascii=False))

        print(f"\n提帧完成。", file=sys.stderr)
        print(f"请将提取的竞对数据按JSON格式写入 /tmp/competitor_data.json", file=sys.stderr)
        print(f"然后执行: python3 {__file__} link /tmp/competitor_data.json", file=sys.stderr)

    elif args.cmd == 'link':
        url = step_generate_link(args.json_file)
        print(url)

    else:
        parser.print_help()


if __name__ == '__main__':
    main()
