#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""走路占位帧集生成器：assets/character.png → assets/walk_f00..f07.png

依赖只用 Pillow（与本仓既有素材脚本 去背景.py / 生成占位角色.py / _dev/gen_full_idle_frames.py
一致；不引入 numpy，也不新增任何第三方依赖）。

【为什么需要这套帧】
v2.11.0 的主题是「走路也播帧动画」。本项目没有人能画图，用户对此的裁决是「先用占位，
占位必须是代码生成或从现有素材派生」。所以这套帧**不做新形象**：它把现有侧身图
assets/character.png 程序化派生成 8 帧小幅摆动，轮廓/配色/比例一律不动——换形象是另一件事，
不在"占位"这三个字的范围里。它同时是「无帧集角色继续走静态兜底」这条回退的对照物：
有帧集就播，没有就退回原图。

【沿用哪套工程标准（先例：_dev/gen_full_idle_frames.py）】
确定性（无随机数、无时间戳、无环境依赖）· --check 只比对不写盘 · alpha bleed 防黑边 ·
不裁切不贴边（四边 alpha 恒 0）· 枢轴固定 · 循环首尾无缝 · docstring 写清"变换公式 + 理由"。
本脚本是那份标杆在"走路"这个动作上的同构复制：连 --out/--src/--count/--check 的命令行形状、
MAD 度量口径、扩边算法都保持一致，读的人不必学第二套。

【变换公式】
对第 i 帧（i = 0..N-1，N = FRAME_COUNT = 8），令 a = 2π·i/N：

    s_i   = sin(a)                    # 纵向起伏分量：**整周期一个来回**（上→下→上）
    c_i   = cos(a)                    # 前后倾斜分量，与起伏差 1/4 周期（正交）
    alt_i = +1（i 偶） / -1（i 奇）    # 交替挤压：一帧压、一帧伸

    ty_i   = BOB_PX · s_i                       # 纵向平移（像素）
    θ_i    = TILT_DEG · c_i                     # 前后倾斜（度）
    sy_i   = 1 + SQUASH · alt_i                 # 纵向挤压 ±SQUASH
    sx_i   = 1 − SQUASH_X · alt_i               # 横向反向，近似体积守恒

输出像素 (x, y) 反查源坐标（PIL AFFINE 的 (a,b,c,d,e,f) 布局，src = A·out）：

    u = x − cx − tx,  v = y − cy − ty
    qx = cosθ·u + sinθ·v,   qy = −sinθ·u + cosθ·v      # 先反旋转（绕质心 C）
    src_x = px + (qx + cx − px) / sx                   # 再反缩放（绕枢轴 P）
    src_y = py + (qy + cy − py) / sy
    ⇒ a = cosθ/sx   b = sinθ/sx   c = px + (cx−px)/sx − (a·(cx+tx) + b·(cy+ty))
      d = −sinθ/sy  e = cosθ/sy   f = py + (cy−py)/sy − (d·(cx+tx) + e·(cy+ty))

正向的复合顺序是"绕 P 缩放 → 绕 C 旋转 → 平移 T"。C = **原图 alpha 质心**（149.46, 143.99），
P = (C.x, 底边) = (149.46, 252)：**倾斜绕质心、挤压绕"脚"**。两个枢轴都是常数（由原图算一次，
8 帧共用），所以"枢轴固定"这条成立；逐帧质心只在 y 上按 ty_i + (C.y−P.y)(sy_i−1) 移动
（前半是起伏、后半是"脚不动导致的缩放位移"），x 上不动。重采样用双三次（BICUBIC）。

为什么挤压绕"脚"、倾斜绕质心：
  旋转绕质心是任务要求的（"前后倾斜 ±1.5°~2°，绕质心"）；而挤压的枢轴如果也放质心，
  +1% 的伸长会把底边往下推 (252−143.99)×1% ≈ 1.1px —— 这张图下方只剩 3px，实测那样会
  直接让边框 alpha 从 0 变 2（贴边）。把枢轴放在脚上，伸长只往上长（上方有 20+px 余量），
  而且走路本来就该是"脚踩地、身体弹"，不是整个身子在画布里往下滑。

为什么倾斜要单独占一个分量（而不是继续只调一个标量）：
  只用 sin 的话，sin(45°)=sin(135°)、sin(225°)=sin(315°) —— 第 1 与第 3、第 5 与第 7 帧会
  **完全一样**，循环里表现为"卡一下"。标杆脚本 gen_full_idle_frames 用"+1/4 格相位"打散
  同一件事；这里把第二个自由度用在倾斜上：8 个 (s_i, c_i) 是单位圆上的等角距采样，
  两两不同，而且 7→0 这一接缝与其余相邻步进是**同一个角步长**，所以循环处不跳。

为什么倾斜用 AFFINE 而不是 Image.rotate(resample=BICUBIC, expand=False)：
  rotate() 能把中心指定在质心（center=(cx, cy)），但它只做旋转——旋转/挤压/起伏要分三次
  重采样，每一次都再模糊一轮，8 帧的锐度会肉眼可见地掉。这里把三者合成**一个**反查矩阵，
  只重采样一次；矩阵本身与 rotate() 的逆映射逐项相同，换的只是"一次算完"。

【幅度上界是**算出来的**，不是拍的】
原图 alpha 包围盒 (5, 25, 252, 253)，质心 (149.46, 143.99)，画布 256×256
⇒ 四边空白只有 上 25 / 下 3 / 左 5 / 右 4 像素。±1.5° 倾斜绕质心会把离质心最远的那一端
抬起/压下（(252−149.46)·sin1.5° ≈ 2.7px），所以硬约束卡住的是**下边 3px** 与**左右 4~5px**。
两条约束各由一件事保证：
  · 左右靠 TILT_DEG 取 1.5°（任务区间的下限）。实测 1.8° 还能过（右余量 1px），
    1.9° 就不行了——边框 alpha 变 2；
  · 上下靠"挤压绕脚"（见上）。绕质心的对照实测会让边框 alpha 变 2，绕脚则是 0。
safe_bob_limit() 把"四边 alpha 恒 0"这句话直接当判据**二分**：给定 bob，逐帧变换 alpha，
任何一帧的可见内容离四边不足 1px 就判不安全。实测（tilt 1.5°、挤压 ±1%）安全上限 **2.26px**，
本脚本取 **2.0px**（1.13 倍余量）。逐档实测：tilt 1.5/1.8 边框 alpha 0，1.9 变 2；
bob 2.26 边框 alpha 0，2.3 变 1——改到这些值再重跑，磁盘帧的四边就不再全透明，
tests/test_walk_frames_v2110.py::test_every_frame_has_a_fully_transparent_border 会红。

【为什么先"扩边"再重采样（防黑边）】
character.png 是 RGBA，透明区 RGB = (0,0,0)。若直接对 RGB 做双三次插值，轮廓外的采样点会把
透明区的黑按权重混进颜色 ⇒ **黑边**（8 位整数下也没法先预乘再除回来：Pillow 的 ImageChops
不支持 'F' 模式的乘除）。这里改用通行的**扩边（alpha bleed）**：把透明区用"最近可见像素的
真实颜色"逐环填满（8 方向膨胀 BLEED_RADIUS 轮），再重采样 RGB。双三次在轮廓附近取到的就都是
真颜色，透明区的黑进不来；可见像素的 RGB 一个都没被改动。

【幂等】
输出只由 (原图像素, 上面的公式) 决定：无随机数、无时间戳、无环境依赖、不读系统区域设置。
重复运行逐字节一致（两次独立运行逐文件 SHA-256 相同，读数见收工报告）。
--check 只比对不写盘，有差异退出码 1（tests/test_walk_frames_v2110.py 会跑它）。

【实测基线（2026-10，Pillow 12.1.1，256×256）】
  逐帧 MAD vs 原图：8.33 / 9.81 / 4.79 / 10.42 / 8.21 / 5.93 / 11.02 / 6.45
  相邻步进 MAD：12.30 / 8.11 / 8.64 / 12.13 / 6.11 / 11.08 / 10.27
  首尾接缝（f07→f00）MAD 6.31 = 0.64× 平均步进 9.81（首尾那一步与 f04→f05 的 6.11 同级，
  不是"卡一下"：接缝落在其余 7 步的 [6.11, 12.30] 区间里）
  四边余量 (l,t,r,b)：f0 (7,23,7,1) · f1 (4,29,7,1) · f2 (5,25,6,2) · f3 (4,29,3,3)
                      f4 (6,23,3,5) · f5 (4,26,3,6) · f6 (5,21,6,6) · f7 (4,26,7,4)
                      ⇒ 最小 1px（底边，f0/f1），四边 alpha 恒 0
  bob 安全上限 2.26px（取 2.0px）
  凭空黑像素：0/帧。⚠ 这条读数对掩码半径很敏感：测试用的是"源图原位 + 膨胀 11px"
  （暗描边密，半径小了会把真描边位移误报成凭空黑）。我用"按同一矩阵搬过去的暗部掩码
  （可见 & L<32，膨胀 1px）"复核：扩边开着 0/帧，**关掉扩边是 3/3/3/6/1/6/3/1** ——
  扩边确实在起作用；而半径 11 的口径下关掉扩边只剩 ~1 个，判据基本失明。

用法：
    python _dev/gen_walk_frames.py                # 写入 assets/
    python _dev/gen_walk_frames.py --out DIR      # 写到别处（测试用）
    python _dev/gen_walk_frames.py --check        # 只比对，不写盘；有差异退出码 1
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
SRC_NAME = "character.png"
OUT_FMT = "walk_f%02d.png"

FRAME_COUNT = 8       # 走路循环 8 帧（pet_anim.load_frame_set(..., "walk", 8)）
TILT_DEG = 1.5        # 前后倾斜 ±1.5°（任务要求 1.5°~2°；实测 1.8° 会吃掉左右各 1px 余量）
BOB_PX = 2.0          # 纵向起伏 ±2.0px（上界由 safe_bob_limit 反解，见文件头）
SQUASH = 0.010        # 交替纵向挤压 ±1.0%
SQUASH_X = 0.004      # 横向反向 ∓0.4%（近似体积守恒）
BLEED_RADIUS = 4      # 扩边轮数：双三次核半径 2px + 1px 缩放位移，4 轮足够

_SHIFTS = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))


# ---------------- 纯函数（可单测） ----------------

def bob_phase(i, count=FRAME_COUNT):
    """第 i 帧的纵向起伏分量 s_i = sin(2π i/count)：**一整个周期一个来回**。

    起点取 sin(0)=0（而不是峰值）：走路循环从"过中点"起帧，接缝（最后一帧 → 第 0 帧）
    与其余每步走得一样远，循环处不会突然弹一下。
    """
    return math.sin(2.0 * math.pi * float(i) / float(count))


def tilt_phase(i, count=FRAME_COUNT):
    """第 i 帧的倾斜分量 c_i = cos(2π i/count)，与起伏差 1/4 周期。

    这个正交分量存在的理由是**帧必须两两不同**（只用 sin 会得到 4 对重复帧）；
    顺带它才是"走路"该有的样子：重心过中点时身体最前倾/最后仰，到最高/最低点时回正。
    """
    return math.cos(2.0 * math.pi * float(i) / float(count))


def squash_at(i, squash=SQUASH, squash_x=SQUASH_X):
    """第 i 帧的 (sx, sy)：纵向挤压逐帧取反（交替），横向反向近似体积守恒。

    取反（而不是跟着 sin 走）是为了把"踏步"读出来：8 帧里 4 压 4 伸，每帧换一次。
    符号取"偶伸 / 奇压"是实测选出来的：反向（偶压）也能过"四边 alpha 恒 0"，但左右余量
    会从 3px 掉到 1px、bob 安全上限从 2.26px 掉到 2.07px——同一组幅度下离画布边更近。
    """
    alt = 1.0 if int(i) % 2 == 0 else -1.0
    return 1.0 - squash_x * alt, 1.0 + squash * alt


def frame_transform(i, count=FRAME_COUNT, tilt=TILT_DEG, bob=BOB_PX,
                    squash=SQUASH, squash_x=SQUASH_X):
    """第 i 帧的 (sx, sy, angle_deg, ty)——build_frames 与度量函数共用这一个真源。"""
    sx, sy = squash_at(i, squash, squash_x)
    return sx, sy, tilt * tilt_phase(i, count), bob * bob_phase(i, count)


def affine_matrix(cx, cy, sx, sy, angle_deg, tx=0.0, ty=0.0, px=None, py=None):
    """PIL AFFINE 的 (a,b,c,d,e,f)：缩放（枢轴 (px,py)）→ 绕 (cx,cy) 旋转 → 平移的反查矩阵。

    两个枢轴分开是**有意的**，理由见文件头"为什么挤压绕脚、倾斜绕质心"：
    旋转枢轴是质心，缩放枢轴默认也是质心，但走路帧把它换成脚（底边中点）。
    与 Image.rotate(angle, center=..., resample=BICUBIC, expand=False) 的逆映射逐项相同，
    区别只是这里把缩放/平移一起合进同一个矩阵（只需重采样一次）。
    """
    if px is None:
        px = cx
    if py is None:
        py = cy
    r = math.radians(angle_deg)
    cos_a = math.cos(r)
    sin_a = math.sin(r)
    a = cos_a / sx
    b = sin_a / sx
    d = -sin_a / sy
    e = cos_a / sy
    nx = cx + tx
    ny = cy + ty
    # 复合顺序（正向）：先绕 P 缩放 → 再绕 C 旋转 → 最后平移 T。
    # 逆映射里 (cx − px)/sx 这一项不能省：缩放是**关于 P 的**，不是关于 C 的向量缩放，
    # 少了它 P≠C 时会整体平移 (P−C)（第一版就踩了这个坑：脚在 252，图上却整体下移 108px）。
    return (a, b, px + (cx - px) / sx - (a * nx + b * ny),
            d, e, py + (cy - py) / sy - (d * nx + e * ny))


def squash_pivot(alpha, cx):
    """挤压的缩放枢轴 = alpha 包围盒底边中点（通俗说就是"脚踩的那条线"）。

    为什么不是质心：画布下方只剩 3px（见文件头），绕质心做 +1% 的伸长会把底边往下推
    约 1.1px，叠上起伏就贴到画布边（实测边框 alpha 从 0 变 2）。把枢轴放在脚上，伸长只会
    往上长（上方有 20+px 余量）；走路本来就该是"脚不动、身体弹"，不是整个身子在画布里滑。
    """
    box = alpha.getbbox()
    if box is None:
        return cx, (alpha.size[1] - 1) / 2.0
    return cx, float(box[3] - 1)


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


def alpha_margins(im):
    """可见内容到画布四边的**空白像素数** (left, top, right, bottom)；全透明返回 0 四元组。

    "四边 alpha 恒 0" 等价于这四个数都 ≥ 1；它比"边框采样最大值"更好读：
    哪一侧快贴边了，一眼看得出是几像素。
    """
    box = im.getchannel("A").getbbox()
    if box is None:
        return (0, 0, 0, 0)
    w, h = im.size
    x0, y0, x1, y1 = box
    return (x0, y0, w - x1, h - y1)


# ---------------- 主流程 ----------------

def frame_matrices(base, count=FRAME_COUNT, tilt=TILT_DEG, bob=BOB_PX,
                   squash=SQUASH, squash_x=SQUASH_X):
    """base（RGBA）→ [每帧的 AFFINE 矩阵]。

    抽出来是为了让"把源图的某个掩码搬到帧坐标"这类事（测试里的"凭空黑"判据）与
    build_frames 走**同一个**矩阵：枢轴/质心/相位只在这里算一次，不会两处漂移。
    """
    alpha = base.getchannel("A")
    cx, cy = alpha_centroid(alpha)
    px, py = squash_pivot(alpha, cx)
    out = []
    for i in range(count):
        sx, sy, angle, ty = frame_transform(i, count, tilt, bob, squash, squash_x)
        out.append(affine_matrix(cx, cy, sx, sy, angle, 0.0, ty, px, py))
    return out


def build_frames(src_path=None, count=FRAME_COUNT, tilt=TILT_DEG, bob=BOB_PX,
                 squash=SQUASH, squash_x=SQUASH_X, bleed=True):
    """原图 → [PIL.Image]，长度 count，全部与原图同尺寸 / RGBA。

    bleed=False 只给测试做**对照组**用（证明"没有凭空黑"这条判据在关掉扩边时真的会红），
    生产路径永远走 True。
    """
    src_path = src_path or os.path.join(ASSETS_DIR, SRC_NAME)
    with Image.open(src_path) as im:
        base = im.convert("RGBA")
    size = base.size
    alpha = base.getchannel("A")
    rgb = base.convert("RGB")
    filled = bleed_edges(rgb, alpha) if bleed else rgb
    blank = Image.new("RGB", size, (0, 0, 0))

    frames = []
    for mat in frame_matrices(base, count, tilt, bob, squash, squash_x):
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


def safe_bob_limit(src_path=None, count=FRAME_COUNT, tilt=TILT_DEG,
                   squash=SQUASH, squash_x=SQUASH_X, margin=1, step=0.01):
    """反解 BOB_PX 的安全上界（像素）：二分，判据就是"四边 alpha 恒 0"这条硬约束本身。

    做法：给定 bob，逐帧把 alpha 用与 build_frames **同一个**矩阵变换一遍；只要有任何一帧的
    可见内容离四边不足 margin 像素（等价于边框上出现 alpha>0），这个 bob 就不安全。二分到
    step 精度，返回仍然安全的那个值。

    为什么不用解析式：倾斜与挤压叠在一起后，底边位置由 alpha 的**实际形状**决定（这张图的
    尾鳍离下边只有 3px，但并不是 bbox 矩形那个角），解析式只能算矩形的保守上界；二分直接
    对着"四边 alpha 恒 0"这句话算，读数与测试判据是同一件事，不会出现"公式说安全、图却贴边"。
    """
    src_path = src_path or os.path.join(ASSETS_DIR, SRC_NAME)
    with Image.open(src_path) as im:
        base = im.convert("RGBA")
    size = base.size
    alpha = base.getchannel("A")

    def _safe(bob_value):
        for mat in frame_matrices(base, count, tilt, bob_value, squash, squash_x):
            box = alpha.transform(size, Image.AFFINE, mat, resample=_BICUBIC).getbbox()
            if box is None:
                continue
            x0, y0, x1, y1 = box
            if min(x0, y0, size[0] - x1, size[1] - y1) < margin:
                return False
        return True

    if not _safe(0.0):
        return 0.0
    lo, hi = 0.0, float(max(size))
    while hi - lo > step:
        mid = (lo + hi) / 2.0
        if _safe(mid):
            lo = mid
        else:
            hi = mid
    return lo


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
    """逐帧差异度量：(i, MAD(vs 原图), MAD(vs 原图·仅可见), MAD(上一帧))，供人工核对。"""
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
    ap = argparse.ArgumentParser(description="生成走路占位帧集（幂等）")
    ap.add_argument("--out", default=None, help="输出目录（默认 assets/）")
    ap.add_argument("--src", default=None, help="基准图（默认 assets/character.png）")
    ap.add_argument("--count", type=int, default=FRAME_COUNT, help="帧数（默认 8）")
    ap.add_argument("--check", action="store_true",
                    help="只比对磁盘上的帧是否与重算结果一致，不写盘")
    args = ap.parse_args(argv)

    out_dir = args.out or ASSETS_DIR
    if args.check:
        # 比对**像素**，不比文件字节：同一张图在不同 Pillow/libpng 版本下重编码，
        # 字节会变（压缩级别/filter/块顺序），按字节比会把"升级依赖"误判成"素材被改"。
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
    limit = safe_bob_limit(src_path=args.src, count=args.count)
    print("wrote %d frames -> %s" % (len(paths), out_dir))
    print("bob: 取 %.2fpx / 安全上限 %.2fpx（余量 %.2fx）"
          % (BOB_PX, limit, (limit / BOB_PX) if BOB_PX else float("inf")))
    print("%-18s %10s %10s %12s  %s"
          % ("frame", "MAD(all)", "MAD(vis)", "MAD(prev)", "margins(l,t,r,b)"))
    steps = []
    margins = []
    for i, m_all, m_vis, m_prev in diff_report(src_path=args.src, count=args.count):
        with Image.open(paths[i]) as im:
            m = alpha_margins(im.convert("RGBA"))
        margins.append(m)
        print("%-18s %10.4f %10.4f %12s  %s"
              % (OUT_FMT % i, m_all, m_vis, "-" if m_prev is None else "%.4f" % m_prev,
                 "%d,%d,%d,%d" % m))
        if m_prev is not None:
            steps.append(m_prev)
    # 首尾接缝：最后一帧 → 第 0 帧（循环真正跨过去的那一步）
    frames = build_frames(src_path=args.src, count=args.count)
    seam = mad(frames[-1], frames[0])
    mean_step = sum(steps) / float(len(steps)) if steps else 0.0
    print("seam(7->0) MAD %.4f / 平均步进 %.4f = %.3fx"
          % (seam, mean_step, (seam / mean_step) if mean_step else float("inf")))
    print("四边最小余量 %d（要求全部 >= 1）" % min(min(m) for m in margins))
    return 0


if __name__ == "__main__":
    sys.exit(_main())
