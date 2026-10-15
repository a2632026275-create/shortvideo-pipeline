#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自动识别并去除视频水印（针对 AI 生成视频角落的「AI 生成 / 视频由AI生成」等半透明文字水印）。

设计目标
--------
1. 自动识别：用 OpenCV 在画面四角检测半透明浅色文字水印，精确定位边界框；
2. 保留主体：delogo 区域紧贴水印文字（小 padding），只抹水印、不动画面主体与关键信息；
3. 无感回退：自动检测不到时，回退到「默认角落区域」；也可用 --region 手动指定兜底；
4. 保持规格：输出与源视频同分辨率、同帧率，无拉伸、无黑边。

用法
----
    python watermark_auto_remove.py <视频文件|目录> [选项]

选项
----
    --region X,Y,W,H   手动指定水印矩形（绝对像素，覆盖自动检测）
    --corner br|bl|tr|tl   水印所在角落（默认 br 右下角；自动检测会扫全部四角）
    --out DIR          输出目录（默认在源旁生成 *_无印.mp4）
    --no-detect        跳过自动检测，直接用默认角落区域
    --keep-files       目录模式下同时保留无印与原文件（默认覆盖式输出到 --out）

依赖：ffmpeg（PATH 或 imageio_ffmpeg）+ opencv-python + numpy
"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

# ----------------------------- ffmpeg 探测 -----------------------------
_FF_CANDIDATES = [
    r"C:\Users\26320\.workbuddy\binaries\ffmpeg\ffmpeg.exe",
    r"C:\Users\26320\.workbuddy\binaries\python\envs\default\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe",
]


def find_ffmpeg():
    for c in _FF_CANDIDATES:
        if os.path.exists(c):
            return c
    which = shutil.which("ffmpeg")
    return which or "ffmpeg"


FFMPEG = find_ffmpeg()


# ----------------------------- 水印检测 -----------------------------
def _read_first_frame(video: str) -> np.ndarray:
    """读取视频第一帧（BGR）。"""
    cap = cv2.VideoCapture(video)
    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        raise RuntimeError(f"无法读取视频帧: {video}")
    return frame


def _corner_roi(frame: np.ndarray, corner: str) -> tuple:
    """返回指定角落的 ROI 切片与其在整帧中的偏移 (x0, y0)。"""
    h, w = frame.shape[:2]
    # 角落区域：宽 30% / 高 12%，覆盖常见 AI 水印
    cw, ch = int(w * 0.30), int(h * 0.12)
    if corner == "br":
        x0, y0 = w - cw, h - ch
    elif corner == "bl":
        x0, y0 = 0, h - ch
    elif corner == "tr":
        x0, y0 = w - cw, 0
    else:  # tl
        x0, y0 = 0, 0
    return frame[y0:y0 + ch, x0:x0 + cw], (x0, y0)


def _detect_text_bbox(roi: np.ndarray) -> tuple:
    """在 ROI 内用顶帽变换检测浅色半透明文字，返回 (x, y, w, h) 相对 ROI，失败返回 None。"""
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    ksize = max(9, min(gray.shape) // 8)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (ksize, ksize))
    tophat = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, kernel)

    # 顶帽结果里，水印文字是「比局部背景亮」的细结构
    thresh_val = max(6.0, float(tophat.max()) * 0.45)
    _, th = cv2.threshold(tophat, thresh_val, 255, cv2.THRESH_BINARY)
    th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))

    contours, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    boxes = []
    rh, rw = roi.shape[:2]
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        # 过滤噪点：面积过小 / 细长线 / 铺满整块的都排除
        area = w * h
        if area < (rw * rh) * 0.0008:
            continue
        if h < 6 or w < 12:
            continue
        if w > rw * 0.95 and h > rh * 0.95:
            continue
        boxes.append((x, y, w, h))

    if not boxes:
        return None
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[0] + b[2] for b in boxes)
    y1 = max(b[1] + b[3] for b in boxes)
    return (x0, y0, x1 - x0, y1 - y0)


def detect_watermark(video: str, corner: str = "br") -> tuple:
    """自动检测水印，返回整帧坐标 (x, y, w, h)；检测不到返回 None。"""
    frame = _read_first_frame(video)
    h, w = frame.shape[:2]
    for c in (corner, "br", "bl", "tr", "tl"):
        roi, (x0, y0) = _corner_roi(frame, c)
        bbox = _detect_text_bbox(roi)
        if bbox is None:
            continue
        bx, by, bw, bh = bbox
        # 转回整帧坐标 + 少量 padding（2px）
        pad = 2
        x = max(0, x0 + bx - pad)
        y = max(0, y0 + by - pad)
        bw = min(w - x, bw + 2 * pad)
        bh = min(h - y, bh + 2 * pad)
        # 合理性校验：水印必须落在角落且不过大
        if bw < w * 0.5 and bh < h * 0.2:
            return (x, y, bw, bh)
    return None


def default_region(video: str, corner: str) -> tuple:
    """按分辨率比例给出默认角落水印区域（检测失败的兜底）。"""
    cap = cv2.VideoCapture(video)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    if w <= 0 or h <= 0:
        raise RuntimeError(f"无法获取分辨率: {video}")
    # AI 水印常驻底角：宽约 25% / 高约 3.5%，贴边
    mw, mh = int(w * 0.25), max(20, int(h * 0.035))
    if corner in ("br", "tr"):
        x = w - mw - 6
    else:
        x = 6
    if corner in ("br", "bl"):
        y = h - mh - 6
    else:
        y = 6
    return (x, y, mw, mh)


# ----------------------------- delogo 去除 -----------------------------
def delogo(video: str, region: tuple, out: str) -> bool:
    """用 ffmpeg delogo 邻域插值去除水印，输出同规格视频。"""
    x, y, w, h = (int(v) for v in region)
    cmd = [
        FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
        "-i", video,
        "-vf", f"delogo=x={x}:y={y}:w={w}:h={h}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
        "-preset", "veryfast", "-an", "-movflags", "+faststart",
        out,
    ]
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if r.returncode != 0 or not os.path.exists(out) or os.path.getsize(out) < 50 * 1024:
        print(f"  ❌ delogo 失败: {(r.stderr or '')[-200:]}")
        return False
    return True


# ----------------------------- 主流程 -----------------------------
def process_one(video: str, args) -> str:
    src = Path(video)
    out_dir = Path(args.out) if args.out else src.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{src.stem}_无印{src.suffix}"

    region = None
    if args.region:
        region = tuple(int(v) for v in args.region.split(","))
        if len(region) != 4:
            print(f"  ❌ --region 格式应为 X,Y,W,H: {args.region}")
            return None
        print(f"  · 使用手动区域: {region}")
    elif not args.no_detect:
        region = detect_watermark(video, args.corner)
        if region:
            print(f"  · 自动检测到水印: {region}")
        else:
            region = default_region(video, args.corner)
            print(f"  · 未检测到文字水印，回退默认区域: {region}")
    else:
        region = default_region(video, args.corner)
        print(f"  · 使用默认角落区域: {region}")

    ok = delogo(video, region, str(out))
    if ok:
        print(f"  ✅ 已输出: {out}")
        return str(out)
    return None


def main():
    ap = argparse.ArgumentParser(description="自动识别并去除视频水印（保留画面主体）")
    ap.add_argument("input", help="视频文件或目录")
    ap.add_argument("--region", help="手动水印矩形 X,Y,W,H（绝对像素）")
    ap.add_argument("--corner", default="br", choices=["br", "bl", "tr", "tl"], help="水印角落（默认右下）")
    ap.add_argument("--out", help="输出目录")
    ap.add_argument("--no-detect", action="store_true", help="跳过自动检测，直接用默认角落区域")
    args = ap.parse_args()

    sys.stdout.reconfigure(encoding="utf-8")
    src = Path(args.input)
    if src.is_dir():
        vids = sorted([p for p in src.iterdir() if p.suffix.lower() in (".mp4", ".mov", ".m4v", ".mkv", ".webm")])
        if not vids:
            print("目录里没有视频文件")
            return
        print(f"批量处理 {len(vids)} 个视频:")
        ok = 0
        for v in vids:
            print(f"[{v.name}]")
            if process_one(str(v), args):
                ok += 1
        print(f"完成: {ok}/{len(vids)}")
    else:
        print(f"[{src.name}]")
        process_one(str(src), args)


if __name__ == "__main__":
    main()
