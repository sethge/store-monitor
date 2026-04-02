#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
竞对诊断一键流程（全自动，不依赖视觉模型）
用法:
  python3 run_diagnosis.py 视频1.mp4 视频2.mp4 ...

全流程: 提帧 → OCR → 解析JSON → 生成公网链接
"""
import json
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))


def main():
    if len(sys.argv) < 2:
        print("用法: python3 run_diagnosis.py 视频1.mp4 视频2.mp4 ...", file=sys.stderr)
        print("      python3 run_diagnosis.py link /tmp/competitor_data.json", file=sys.stderr)
        sys.exit(1)

    # 子命令: link（直接从JSON生成链接）
    if sys.argv[1] == 'link' and len(sys.argv) >= 3:
        from deploy import main as deploy_main
        sys.argv = ['deploy.py', '--data', sys.argv[2]]
        deploy_main()
        return

    # 主流程: 视频 → 链接
    videos = [os.path.abspath(v) for v in sys.argv[1:]]
    for v in videos:
        if not os.path.exists(v):
            print(f"[错误] 文件不存在: {v}", file=sys.stderr)
            sys.exit(1)

    # Step 1: 提帧
    print("=" * 50, file=sys.stderr)
    print("Step 1/4: 提取关键帧", file=sys.stderr)
    print("=" * 50, file=sys.stderr)
    from extract_frames import extract_keyframes, sample_frames

    video_frames = {}
    for v in videos:
        name = os.path.basename(v)
        print(f"  [{name}] 提帧中...", file=sys.stderr)
        try:
            frame_dir, total = extract_keyframes(v)
            sampled = sample_frames(frame_dir)
            video_frames[name] = sampled
            print(f"  [{name}] {total}帧, 采样{len(sampled)}张", file=sys.stderr)
        except Exception as e:
            print(f"  [{name}] 错误: {e}", file=sys.stderr)

    if not video_frames:
        print("所有视频提帧失败", file=sys.stderr)
        sys.exit(1)

    # Step 2+3: 腾讯OCR+Gemini（最准） → 纯Gemini读图 → EasyOCR（fallback）
    competitors = []

    # 检查可用方案（从内置配置或config.json读取）
    from gemini_ocr import _load_config, get_api_key
    cfg = _load_config()

    has_tencent = bool(cfg.get('tencent_secret_id') or os.environ.get('TENCENT_SECRET_ID'))
    has_gemini = bool(get_api_key())

    for name, paths in video_frames.items():
        result = None

        # 方案1: 腾讯OCR + Gemini语义（最准）
        if has_tencent and has_gemini:
            print("", file=sys.stderr)
            print("=" * 50, file=sys.stderr)
            print(f"Step 2/3: 腾讯OCR+Gemini分析 [{name}]", file=sys.stderr)
            print("=" * 50, file=sys.stderr)
            try:
                from tencent_ocr import read_images_with_tencent_gemini
                result = read_images_with_tencent_gemini(paths)
            except Exception as e:
                print(f"  ❌ 腾讯OCR+Gemini失败: {e}", file=sys.stderr)

        # 方案2: 纯Gemini读图
        if not result and has_gemini:
            print(f"  降级到纯Gemini读图...", file=sys.stderr)
            try:
                from gemini_ocr import read_images_with_gemini, get_api_key
                result = read_images_with_gemini(get_api_key(), paths)
            except Exception as e:
                print(f"  ❌ Gemini失败: {e}", file=sys.stderr)

        # 方案3: EasyOCR fallback
        if not result:
            print(f"  降级到EasyOCR...", file=sys.stderr)
            from ocr_images import ocr_images
            from parse_ocr import parse_ocr_data
            ocr_result = ocr_images(paths)
            result = parse_ocr_data(ocr_result)

        if result:
            competitors.append(result)
            dishes = result.get('热销菜', [])
            print(f"  ✅ {result.get('店铺名称','?')} | 评分{result.get('店铺评分','?')} | 月销{result.get('月销','?')} | {len(dishes)}个热销菜", file=sys.stderr)

    # 保存JSON
    json_path = "/tmp/competitor_data.json"
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(competitors, f, ensure_ascii=False, indent=2)
    print(f"\n  数据已保存: {json_path}", file=sys.stderr)

    # Step 4: 生成链接
    print("", file=sys.stderr)
    print("=" * 50, file=sys.stderr)
    print("Step 4/4: 生成公网链接", file=sys.stderr)
    print("=" * 50, file=sys.stderr)

    try:
        import lzstring
        def compress(s):
            return lzstring.LZString().compressToEncodedURIComponent(s)
    except ImportError:
        import base64, zlib
        def compress(s):
            compressed = zlib.compress(s.encode('utf-8'))
            return base64.urlsafe_b64encode(compressed).decode('ascii').rstrip('=')

    json_str = json.dumps(competitors, ensure_ascii=False, separators=(',', ':'))
    encoded = compress(json_str)
    url = f"https://sethge.github.io/store-monitor/#{encoded}"

    print(f"\n  链接已生成", file=sys.stderr)
    print("", file=sys.stderr)

    # 唯一输出到stdout的是链接
    print(url)


if __name__ == '__main__':
    main()
