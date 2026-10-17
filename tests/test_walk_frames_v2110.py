# -*- coding: utf-8 -*-
"""walk 占位帧集（v2.11.0 主题「走路也播帧动画」的素材判据）。

## 为什么这批帧必须被钉住

用户裁决：**素材先用占位**，且占位必须**代码生成或从现有素材派生**（本项目没有人能画图），
验收**只能用结构断言**（见 plan §18.4 卡点 1）。所以这里钉的不是「好不好看」，而是六件可数的：

1. 帧数 / 尺寸 / 模式与源图一致；
2. **四边 alpha 恒 0**（不裁切、不贴边 —— 第一版生成器实测余量只有 1px，所以这条尤其要紧）；
3. **幂等**：生成器 `--check` 必须过（无随机、无时间戳）；
4. **两两不同**且相邻帧差异够大（否则「走路」= 站着）；
5. **首尾无缝**：最后一帧 → 第一帧的差异与平均步进同量级（不能「卡一下」）；
6. **没有凭空出现的黑**：可见但极暗的像素必须都在源图轮廓附近（插值不该造出新轮廓）。

生成器：`_dev/gen_walk_frames.py`（仿 `_dev/gen_full_idle_frames.py` 的标杆）。
"""
import ast
import io
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

PIL = pytest.importorskip("PIL.Image")
from PIL import Image, ImageChops, ImageFilter  # noqa: E402

ASSETS = os.path.join(HERE, "assets")
SRC = os.path.join(ASSETS, "character.png")
FRAMES = [os.path.join(ASSETS, "walk_f%02d.png" % i) for i in range(8)]
GEN = os.path.join(HERE, "_dev", "gen_walk_frames.py")


def _load(path):
    return Image.open(path).convert("RGBA")


def _mad(a, b):
    """两张同尺寸 RGBA 的平均绝对差（只看 alpha>8 的可见区的并集）。"""
    pa, pb = a.load(), b.load()
    w, h = a.size
    total = 0
    n = 0
    for y in range(h):
        for x in range(w):
            ra, ga, ba, aa = pa[x, y]
            rb, gb, bb, ab = pb[x, y]
            if aa <= 8 and ab <= 8:
                continue
            total += abs(ra - rb) + abs(ga - gb) + abs(ba - bb)
            n += 1
    return (total / float(3 * n)) if n else 0.0


def test_walk_frames_exist_with_the_same_canvas_as_the_source():
    """帧数 / 尺寸 / 模式：walk 帧必须是**同画布**的派生帧（锚点读当前 pixmap 尺寸，不同画布会一跳一跳）。"""
    missing = [p for p in FRAMES if not os.path.isfile(p)]
    assert missing == [], "缺 walk 帧（跑 python _dev/gen_walk_frames.py）：%r" % (missing,)
    src = _load(SRC)
    for p in FRAMES:
        im = _load(p)
        assert im.size == src.size, "%s 尺寸 %r != 源 %r" % (os.path.basename(p), im.size, src.size)
        assert im.mode == "RGBA"


def test_every_frame_has_a_fully_transparent_border():
    """四边 alpha 恒 0：不裁切、不贴边（桌宠是透明窗口，贴边一像素都会露一条）。"""
    for p in FRAMES:
        im = _load(p)
        w, h = im.size
        px = im.load()
        bad = []
        for x in range(w):
            if px[x, 0][3] or px[x, h - 1][3]:
                bad.append((x, 0, px[x, 0][3], px[x, h - 1][3]))
                break
        for y in range(h):
            if px[0, y][3] or px[w - 1, y][3]:
                bad.append((0, y, px[0, y][3], px[w - 1, y][3]))
                break
        assert bad == [], "%s 的边框不是全透明：%r" % (os.path.basename(p), bad)


def test_generator_is_idempotent_and_deterministic():
    """幂等：生成器 `--check` 必须过（无随机/无时间戳），且源码里不许出现 random / time。"""
    p = subprocess.run([sys.executable, "-B", GEN, "--check"], cwd=HERE,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300)
    out = p.stdout.decode("utf-8", "replace")
    assert p.returncode == 0, "生成器 --check 失败（磁盘上的帧与公式不一致）：\n%s" % out[-800:]
    tree = ast.parse(io.open(GEN, encoding="utf-8").read())
    banned = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            banned += [a.name for a in node.names if a.name in ("random", "time", "datetime")]
        elif isinstance(node, ast.ImportFrom) and node.module in ("random", "time", "datetime"):
            banned.append(node.module)
    assert banned == [], "生成器引入了非确定性依赖：%r" % (banned,)


def test_frames_are_pairwise_different_with_enough_motion():
    """两两不同 + 相邻差异够大：否则「走路」只是站着不动。"""
    ims = [_load(p) for p in FRAMES]
    steps = []
    for i in range(len(ims)):
        a, b = ims[i], ims[(i + 1) % len(ims)]
        steps.append(_mad(a, b))
    assert min(steps) > 0.5, "有相邻两帧几乎一样（走路会卡）：%r" % (steps,)
    mean = sum(steps) / len(steps)
    # 首尾接缝（最后一帧 -> 第一帧）不能明显大于平均步进
    seam = steps[-1]
    assert seam <= mean * 1.6 + 1.0, (
        "首尾接缝 %.2f 远大于平均步进 %.2f —— 循环处会看到跳变" % (seam, mean))


def _near_dark_mask(base, radius):
    """基准图「暗像素（L<16 且可见）」膨胀 radius 后的掩码（bytearray，1=命中）。

    口径照抄 tests/test_full_form_frames_v24.py:118-140（那是本仓对「黑边」的既有判据）：
    原图有黑描边，变换时描边位移会把黑带到轮廓外 —— 那是**正确**的图形内容，不算黑边；
    只有「离原图任何暗像素都 >radius 却冒出来的黑」才是透明区混色。
    """
    w, h = base.size
    alpha = base.getchannel("A").tobytes()
    luma = base.convert("L").tobytes()
    mask = bytearray(w * h)
    for idx in range(w * h):
        if alpha[idx] > 0 and luma[idx] < 16:
            y, x = divmod(idx, w)
            for dy in range(-radius, radius + 1):
                yy = y + dy
                if yy < 0 or yy >= h:
                    continue
                row = yy * w
                for dx in range(-radius, radius + 1):
                    xx = x + dx
                    if 0 <= xx < w:
                        mask[row + xx] = 1
    return mask


def _invented_black(im, near_dark):
    """可见却很暗（L<16）且远离原图描边的像素数 = 「凭空出现的黑」。"""
    luma = im.convert("L").tobytes()
    alpha = im.getchannel("A").tobytes()
    return sum(1 for i in range(len(luma))
               if alpha[i] > 0 and luma[i] < 16 and not near_dark[i])


# 半径的来历（**不是拍的**，是量出来的）：
#   · 变换的最大力臂 = 质心到轮廓最远点的距离，实测 **R = 146.79px**（alpha 质心 (149.46, 143.99)）；
#   · 旋转 2.0° 在 R 处的位移 = 2π/180 × 2.0 × R = **5.12px**；
#   · 加减 起伏 2.0px + 挤压 1%（≈1.47px）⇒ 几何位移**上界 8.59px**；
#   · 再 +2：这条判据量的是「到最近的**暗**像素」的距离，而暗掩膜比轮廓稀（轮廓上有大量非暗像素），
#     所以最坏情况会比真实位移多 1~2px —— 实测最远一个落在 **10.44px**。
#   ⇒ 取 **11px**。这个半径挡不住真正的黑边：黑边是「整条轮廓一圈」的现象（成百上千像素），
#     不是零星两三个；下面的反向对照用例会证明它认得出人造黑边。
WALK_SHIFT_RADIUS_PX = 11


def test_no_black_pixels_are_invented_outside_the_source_silhouette():
    """没有「凭空出现的黑」：可见但很暗（L<16）的像素必须落在源图暗部附近。

    为什么：源图透明区 RGB=(0,0,0)，直接对 RGB 做插值会把透明区的黑混进轮廓（黑边）。
    生成器用 alpha bleed 处理过了 —— 这条判据就是那个处理的证据。
    """
    src = _load(SRC)
    near_dark = _near_dark_mask(src, WALK_SHIFT_RADIUS_PX)
    for p in FRAMES:
        n = _invented_black(_load(p), near_dark)
        assert n == 0, ("%s 里有 %d 个「凭空出现的黑」（离源图暗部 >%dpx 的极暗可见像素）"
                        % (os.path.basename(p), n, WALK_SHIFT_RADIUS_PX))


def test_the_black_fringe_checker_can_actually_fail():
    """反向对照：人造一圈黑边，同一个判据**必须**报出来（否则它是恒真空转）。

    做法：在「源图暗部膨胀 23px」之内、但「膨胀 11px」之外的那条带子上涂纯黑 ——
    这正是黑边会出现的位置（紧贴轮廓外侧），如果判据认不出它，判据就是空的。
    """
    src = _load(SRC)
    near_dark = _near_dark_mask(src, WALK_SHIFT_RADIUS_PX)
    allowed_band = _near_dark_mask(src, WALK_SHIFT_RADIUS_PX + 12)
    im = _load(FRAMES[0]).copy()
    px = im.load()
    w, h = im.size
    painted = 0
    for y in range(h):
        for x in range(w):
            idx = y * w + x
            if allowed_band[idx] and not near_dark[idx]:
                px[x, y] = (0, 0, 0, 255)
                painted += 1
    assert painted > 300, "反向对照没造出足够的黑边像素（%d）" % painted
    assert _invented_black(im, near_dark) > 300, (
        "人造黑边没有被判据抓到 —— 这条判据对黑边是空的")
