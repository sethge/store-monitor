#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
提取视频关键帧 + 采样
优先用 ffmpeg（快），没有就用 opencv（纯Python，不需要额外装系统工具）
用法: python3 extract_frames.py 视频1.mp4 视频2.mp4 ...
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


def _has_ffmpeg():
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)
        return True
    except:
        return False


def extract_keyframes_ffmpeg(video_path, frame_dir):
    """ffmpeg 提取关键帧（场景变化检测）"""
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vf", "select='gt(scene,0.15)'",
        "-vsync", "vfr", "-q:v", "2",
        os.path.join(frame_dir, "scene_%03d.jpg")
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg失败: {result.stderr[:200]}")


def extract_keyframes_opencv(video_path, frame_dir):
    """OpenCV 提取关键帧（不需要ffmpeg，纯Python）"""
    try:
        import cv2
    except ImportError:
        # 自动安装 opencv（清华镜像）
        print("  安装 opencv...", file=sys.stderr)
        subprocess.run([
            sys.executable, "-m", "pip", "install",
            "-i", "https://pypi.tuna.tsinghua.edu.cn/simple",
            "--trusted-host", "pypi.tuna.tsinghua.edu.cn",
            "opencv-python-headless", "--break-system-packages"
        ], capture_output=True)
        import cv2

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"无法打开视频: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    # 场景变化检测：比较相邻帧的直方图差异
    prev_hist = None
    frame_idx = 0
    saved = 0
    threshold = 0.4  # 直方图差异阈值

    # 至少每2秒取一帧，确保覆盖
    min_interval = int(fps * 2)
    last_saved_idx = -min_interval

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        # 转灰度计算直方图
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        hist = cv2.calcHist([gray], [0], None, [64], [0, 256])
        cv2.normalize(hist, hist)

        save_this = False

        if prev_hist is None:
            save_this = True  # 第一帧必存
        else:
            diff = cv2.compareHist(prev_hist, hist, cv2.HISTCMP_BHATTACHARYYA)
            if diff > threshold:
                save_this = True  # 场景变化
            elif frame_idx - last_saved_idx >= min_interval:
                save_this = True  # 超过最小间隔

        if save_this:
            out_path = os.path.join(frame_dir, f"scene_{saved + 1:03d}.jpg")
            cv2.imwrite(out_path, frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
            saved += 1
            last_saved_idx = frame_idx

        prev_hist = hist
        frame_idx += 1

    cap.release()

    if saved == 0:
        raise RuntimeError("未提取到关键帧")


def extract_keyframes(video_path):
    """提取关键帧，返回帧目录"""
    video_path = os.path.abspath(video_path)
    hash_str = md5_short(video_path)
    frame_dir = f"/tmp/store_{hash_str}"

    # Windows 用临时目录
    if sys.platform == "win32":
        frame_dir = os.path.join(os.environ.get("TEMP", "/tmp"), f"store_{hash_str}")

    # 清理旧帧
    if os.path.exists(frame_dir):
        for f in Path(frame_dir).glob("scene_*.jpg"):
            f.unlink()
    os.makedirs(frame_dir, exist_ok=True)

    # 优先 ffmpeg，没有就用 opencv
    if _has_ffmpeg():
        extract_keyframes_ffmpeg(video_path, frame_dir)
    else:
        print("  ffmpeg未安装，使用opencv提帧", file=sys.stderr)
        extract_keyframes_opencv(video_path, frame_dir)

    frames = sorted(Path(frame_dir).glob("scene_*.jpg"))
    if not frames:
        raise RuntimeError("未提取到关键帧")

    return frame_dir, len(frames)


def sample_frames(frame_dir, max_frames=50):
    """前半全取，后半稀疏。确保热销菜区完整覆盖。"""
    frames = sorted(Path(frame_dir).glob("scene_*.jpg"))
    if not frames:
        return []

    if len(frames) <= max_frames:
        return [str(f) for f in frames]

    split = int(len(frames) * 0.6)
    front = frames[:split]
    back = frames[split:]

    sampled = list(front) + list(back[::3])

    if len(sampled) > max_frames:
        sampled = sampled[:max_frames]

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

    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
