#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""吃饱形态 idle 帧集生成器：assets/character_full.png → assets/idle_full_f00..f09.png

依赖只用 Pillow（与本仓既有素材脚本 去背景.py / 生成占位角色.py 一致；不引入 numpy）。

【为什么需要这套帧】
v2.2.5 之后，默认角色的**非首形态**（= 吃饱形态 full）一律走"静态形态图"分支——那修好了
"常态 idle 帧盖住吃饱图"，代价是吃饱形态**完全静止**。正解不是把它改回播常态 idle 帧
（那会用常态形象盖住吃饱图），而是给吃饱形态一套**自己的**极小幅呼吸帧：形象仍是
character_full.png，只是逐帧微动。本脚本负责程序化产出这 10 帧。

【变换公式】
对第 i 帧（i = 0..N-1，N = FRAME_COUNT = 10）：

    s_i  = sin(2π · (i + 0.25) / N)           # 呼吸主分量（相位偏 1/4 格，见下）
    sy_i = 1 + AMP_Y · s_i                    # 纵向（呼吸）缩放，AMP_Y = 0.016
    sx_i = 1 − AMP_X · s_i                    # 横向反向缩放（近似体积守恒），AMP_X = 0.006

输出像素 (x, y) 反查源坐标（PIL AFFINE 的 (a,b,c,d,e,f) 布局）：

    src_x = cx + (x − cx) / sx_i   →   a = 1/sx_i, b = 0, c = cx·(1 − 1/sx_i)
    src_y = cy + (y − cy) / sy_i   →   d = 0, e = 1/sy_i, f = cy·(1 − 1/sy_i)

(cx, cy) = **原图 alpha 质心**（由原图算出，10 帧共用同一个值）⇒ 缩放枢轴固定，
逐帧质心不变（要求里的"质心不变"）。重采样用双三次（BICUBIC）。

为什么相位偏 **1/4 格（9°）而不是半格**：
  sin 在这 10 个采样点上，只有当相位是 1/2 格的整数倍时，采样点集合才关于 90°/270° 镜像对称
  ⇒ sin 值成对相等 ⇒ 10 帧里会出现 4 对**完全一样**的图（呼吸升程与降程经过同一姿势），
  循环里表现为"卡一下"。取 1/4 格打破镜像对称：10 帧两两不同（最小间隔 |Δs| = 0.097），
  同时每帧步进依旧均匀（|Δs| ∈ [0.097, 0.610]），首尾接缝 |s_9 − s_0| = 0.610 与最大步进
  同量级 ⇒ 循环处没有跳变。峰值 |s| = sin(81°) = 0.98769 ⇒ 实测幅度 0.016 × 0.98769
  = 1.58%，仍在"±1~2%"内。

【为什么这么小】
1) 这是"呼吸/晃动"，不是形变动画。±1.58% 纵向在 256px 画布上约 ±1.9px，肉眼是"轻轻起伏"，
   角色比例/脸型/配色全不变，用户不会觉得换了个形象。
2) 上界受画布硬约束：原图 alpha 包围盒 y ∈ [25, 252]、质心 y = 130.77，最大力臂
   121.2px ⇒ 纵向系数超过约 2.05% 时底边就被 256px 画布切掉（"不裁切"硬要求）。
   实测峰值 1.58% 留足余量（底边最远到 y = 254），任何一帧都不裁切、不贴边。
3) 下界由"看得出在动"定：底边位移 121.2 × 1.58% ≈ 1.9px，跨过 1px 阈值，
   逐帧 MAD 与既有 assets/idle_f* 帧集同一量级（见运行输出）。

【为什么先"扩边"再重采样（防黑边）】
character_full.png 是 RGBA，透明区 RGB = (0,0,0)。若直接对 RGB 做双三次插值，轮廓外的
采样点会把透明区的黑按权重混进颜色 ⇒ **黑边**（8 位整数下也无法先预乘再除回来：Pillow 的
ImageChops 不支持 'F' 模式的乘除）。这里改用通行的**扩边（alpha bleed）**：把透明区用
"最近可见像素的真实颜色"逐环填满（8 方向膨胀 BLEED_RADIUS 轮），再重采样 RGB。
双三次在轮廓附近取到的就都是真颜色，透明区的黑进不来；可见像素的 RGB 一个都没被改动。

【幂等】
输出只由 (原图像素, 上面的公式) 决定：无随机数、无时间戳、无环境依赖。
重复运行逐字节一致（tests/test_full_form_frames_v24.py 会跑两遍比 SHA-256）。

用法：
    python _dev/gen_full_idle_frames.py            # 写入 assets/
    python _dev/gen_full_idle_frames.py --out DIR  # 写到别处（测试用）
    python _dev/gen_full_idle_frames.py --check    # 只比对，不写盘；有差异退出码 1
"""
import argparse
import math
import os
import sys

from PIL import Image, ImageChops, ImageStat

try:  # Pillow >= 9.1
    _BICUBIC = Image.Resampling.BICUBIC
    _NEAREST = Image.Resampling.NEAREST
except AttributeError:  # pragma: no cover - 兼容老 Pillow
    _BICUBIC = Image.BICUBIC  # type: ignore[attr-defined]
    _NEAREST = Image.NEAREST  # type: ignore[attr-defined]

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS_DIR = os.path.join(ROOT, "assets")
SRC_NAME = "character_full.png"
OUT_FMT = "idle_full_f%02d.png"

FRAME_COUNT = 10      # 与既有 idle_f00..f09 帧数一致（桌宠.py: load_frame_set(.., "idle", 10)）
AMP_Y = 0.016         # 纵向呼吸幅度 ±1.6%（实测峰值 1.58%；硬上界约 ±2.05%，见文件头第 2 条）
AMP_X = 0.006         # 横向反向幅度 ∓0.6%
BLEED_RADIUS = 4      # 扩边轮数：双三次核半径 2px + 1px 缩放位移，4 轮足够

_SHIFTS = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))


# ---------------- 纯函数（可单测） ----------------

def frame_phase(i, count=FRAME_COUNT):
    """第 i 帧的呼吸主分量 s_i = sin(2π(i + 0.25)/count)。

    +0.25 = 相位偏 1/4 格：让 count 个采样点**不**关于 90°/270° 镜像对称，于是每个 sin 值
    两两不同（偏半格/整格时会出现 4 对完全相同的帧，见文件头说明）。
    """
    return math.sin(2.0 * math.pi * (float(i) + 0.25) / float(count))


def scale_at(i, count=FRAME_COUNT, amp_y=AMP_Y, amp_x=AMP_X):
    """第 i 帧的 (sx, sy)：纵向呼吸 + 横向反向（近似体积守恒）。"""
    s = frame_phase(i, count)
    return 1.0 - amp_x * s, 1.0 + amp_y * s  # (sx, sy)


def affine_matrix(cx, cy, sx, sy):
    """PIL AFFINE 的 (a,b,c,d,e,f)：绕 (cx, cy) 缩放 (sx, sy) 的**反查**矩阵。"""
    return (1.0 / sx, 0.0, cx * (1.0 - 1.0 / sx),
            0.0, 1.0 / sy, cy * (1.0 - 1.0 / sy))


def _binary(v):
    """L 通道阈值化：>0 → 255（可见/已知），否则 0。"""
    return 255 if v > 0 else 0


def alpha_centroid(alpha):
    """'L' alpha 图的灰度质心 (cx, cy)，0 起像素坐标。

    Pillow-only 实现：逐像素加权求和（256×256 = 65536 次，约 20ms）。
    全透明图（不可能出现）回退到画布中心。
    """
    w, h = alpha.size
    total = 0
    sx = 0
    sy = 0
    for idx, v in enumerate(alpha.tobytes()):
        if v:
            y, x = divmod(idx, w)
            total += v
            sx += v * x
            sy += v * y
    if total <= 0:
        return (w - 1) / 2.0, (h - 1) / 2.0
    return sx / float(total), sy / float(total)


def _shift(im, dx, dy):
    """整像素平移，画布外补 0（**不回卷**：ImageChops.offset 会绕边，可能把对侧颜色搬过来）。"""
    return im.transform(im.size, Image.AFFINE, (1, 0, -dx, 0, 1, -dy), resample=_NEAREST)


def bleed_edges(rgb, alpha, radius=BLEED_RADIUS):
    """把完全透明区的 RGB 用"最近可见像素的真实颜色"填满（8 方向膨胀 radius 轮）。

    可见像素的 RGB 保持不变（composite 只在 take=255 处替换）；只填不计 alpha。
    """
    known = alpha.point(_binary)
    filled = rgb.copy()
    for _ in range(max(0, int(radius))):
        for dx, dy in _SHIFTS:
            nb_fill = _shift(filled, dx, dy)
            nb_known = _shift(known, dx, dy)
            take = ImageChops.subtract(nb_known, known)  # 邻居已知 & 本像素未知 → 255
            if take.getbbox() is None:
                continue
            filled = Image.composite(nb_fill, filled, take)
            known = ImageChops.lighter(known, nb_known)
    return filled


# ---------------- 主流程 ----------------

def build_frames(src_path=None, count=FRAME_COUNT, amp_y=AMP_Y, amp_x=AMP_X):
    """原图 → [PIL.Image]，长度 count，全部与原图同尺寸 / RGBA。"""
    src_path = src_path or os.path.join(ASSETS_DIR, SRC_NAME)
    with Image.open(src_path) as im:
        base = im.convert("RGBA")
    size = base.size
    alpha = base.getchannel("A")
    rgb = base.convert("RGB")
    cx, cy = alpha_centroid(alpha)
    filled = bleed_edges(rgb, alpha)
    blank = Image.new("RGB", size, (0, 0, 0))

    frames = []
    for i in range(count):
        sx, sy = scale_at(i, count, amp_y, amp_x)
        mat = affine_matrix(cx, cy, sx, sy)
        out_a = alpha.transform(size, Image.AFFINE, mat, resample=_BICUBIC)
        out_rgb = filled.transform(size, Image.AFFINE, mat, resample=_BICUBIC)
        # 全透明像素的 RGB 归零：与"透明=黑底但 alpha=0"的通行 RGBA 口径一致
        out_rgb = Image.composite(out_rgb, blank, out_a.point(_binary))
        out = out_rgb.convert("RGBA")
        out.putalpha(out_a)
        frames.append(out)
    return frames


def out_paths(out_dir, count=FRAME_COUNT):
    return [os.path.join(out_dir, OUT_FMT % i) for i in range(count)]


def generate(out_dir=None, src_path=None, count=FRAME_COUNT):
    """生成并写盘，返回写出的绝对路径列表（顺序 = 帧序）。"""
    out_dir = out_dir or ASSETS_DIR
    os.makedirs(out_dir, exist_ok=True)
    frames = build_frames(src_path=src_path, count=count)
    paths = out_paths(out_dir, count)
    for img, p in zip(frames, paths):
        img.save(p, format="PNG", optimize=True)
    return paths


# ---------------- 度量（Pillow-only，报告与测试共用口径） ----------------

def mad(a, b, visible_only=False):
    """平均绝对像素差（4 通道）。visible_only=True 时只在"任一图该像素可见"处统计。"""
    w, h = a.size
    diff = ImageChops.difference(a, b)
    if not visible_only:
        return sum(ImageStat.Stat(diff).sum) / float(w * h * 4)
    vis = ImageChops.lighter(a.getchannel("A"), b.getchannel("A")).point(_binary)
    n = sum(1 for v in vis.tobytes() if v)
    if not n:
        return 0.0
    masked = Image.composite(diff, Image.new("RGBA", (w, h), (0, 0, 0, 0)), vis)
    return sum(ImageStat.Stat(masked).sum) / float(n * 4)


def diff_report(src_path=None, count=FRAME_COUNT):
    """逐帧差异度量：(i, MAD(all), MAD(vis), MAD(prev))，供人工核对。"""
    src_path = src_path or os.path.join(ASSETS_DIR, SRC_NAME)
    with Image.open(src_path) as im:
        base = im.convert("RGBA")
    rows = []
    prev = None
    for i, img in enumerate(build_frames(src_path=src_path, count=count)):
        rows.append((i, mad(img, base), mad(img, base, True),
                     None if prev is None else mad(img, prev)))
        prev = img
    return rows


def _main(argv=None):
    ap = argparse.ArgumentParser(description="生成吃饱形态 idle 帧集（幂等）")
    ap.add_argument("--out", default=None, help="输出目录（默认 assets/）")
    ap.add_argument("--src", default=None, help="基准图（默认 assets/character_full.png）")
    ap.add_argument("--count", type=int, default=FRAME_COUNT, help="帧数（默认 10）")
    ap.add_argument("--check", action="store_true",
                    help="只比对磁盘上的帧是否与重算结果一致，不写盘")
    args = ap.parse_args(argv)

    out_dir = args.out or ASSETS_DIR
    if args.check:
        frames = build_frames(src_path=args.src, count=args.count)
        bad = 0
        for img, p in zip(frames, out_paths(out_dir, args.count)):
            if not os.path.isfile(p):
                print("MISSING %s" % p)
                bad += 1
                continue
            with Image.open(p) as on_disk:
                same = on_disk.convert("RGBA").size == img.size and \
                    ImageChops.difference(on_disk.convert("RGBA"), img).getbbox() is None
            if not same:
                print("DIFF %s" % os.path.basename(p))
                bad += 1
        print("check: %d/%d ok" % (args.count - bad, args.count))
        return 1 if bad else 0

    paths = generate(out_dir=out_dir, src_path=args.src, count=args.count)
    print("wrote %d frames -> %s" % (len(paths), out_dir))
    print("%-18s %10s %10s %12s" % ("frame", "MAD(all)", "MAD(vis)", "MAD(prev)"))
    for i, m_all, m_vis, m_prev in diff_report(src_path=args.src, count=args.count):
        print("%-18s %10.4f %10.4f %12s"
              % (OUT_FMT % i, m_all, m_vis, "-" if m_prev is None else "%.4f" % m_prev))
    return 0


if __name__ == "__main__":
    sys.exit(_main())
