#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
提取视频关键帧 + 采样
用法: python3 extract_frames.py 视频1.mp4 视频2.mp4 ...
输出: 每个视频的采样帧路径列表（JSON格式打印到stdout）
"""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


def md5_short(filepath):
    h = hashlib.md5()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()[:4]


def extract_keyframes(video_path):
    """ffmpeg提取关键帧，返回帧目录"""
    video_path = os.path.abspath(video_path)
    hash_str = md5_short(video_path)
    frame_dir = f"/tmp/store_{hash_str}"

    # 清理旧帧
    if os.path.exists(frame_dir):
        for f in Path(frame_dir).glob("scene_*.jpg"):
            f.unlink()
    os.makedirs(frame_dir, exist_ok=True)

    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vf", "select='gt(scene,0.15)'",
        "-vsync", "vfr", "-q:v", "2",
        os.path.join(frame_dir, "scene_%03d.jpg")
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg失败: {result.stderr[:200]}")

    frames = sorted(Path(frame_dir).glob("scene_*.jpg"))
    if not frames:
        raise RuntimeError("未提取到关键帧")

    return frame_dir, len(frames)


def sample_frames(frame_dir, every_n=3, max_frames=40, min_frames=20):
    """间隔采样，返回图片路径列表"""
    frames = sorted(Path(frame_dir).glob("scene_*.jpg"))
    if not frames:
        return []

    sampled = frames[::every_n]

    if len(sampled) < min_frames and len(frames) >= min_frames:
        step = max(1, len(frames) // min_frames)
        sampled = frames[::step]

    if len(sampled) > max_frames:
        sampled = sampled[:max_frames]

    if len(frames) <= min_frames:
        sampled = frames

    return [str(f) for f in sampled]


def main():
    if len(sys.argv) < 2:
        print("用法: python3 extract_frames.py 视频1.mp4 视频2.mp4 ...")
        sys.exit(1)

    videos = sys.argv[1:]
    results = {}

    for video_path in videos:
        video_path = os.path.abspath(video_path)
        name = os.path.basename(video_path)

        if not os.path.exists(video_path):
            print(f"[跳过] 文件不存在: {name}", file=sys.stderr)
            continue

        try:
            print(f"[提帧] {name}...", file=sys.stderr)
            frame_dir, total = extract_keyframes(video_path)
            sampled = sample_frames(frame_dir)
            print(f"[完成] {name}: {total}帧, 采样{len(sampled)}张", file=sys.stderr)
            results[name] = {
                "video": video_path,
                "frame_dir": frame_dir,
                "total_frames": total,
                "sampled": sampled,
            }
        except Exception as e:
            print(f"[错误] {name}: {e}", file=sys.stderr)

    # JSON输出到stdout，供Agent读取
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
