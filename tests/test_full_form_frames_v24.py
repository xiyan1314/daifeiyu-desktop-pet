# -*- coding: utf-8 -*-
"""吃饱形态 idle 帧集（v2.4）：生成器幂等 + 帧素材质量 + 注册/回退 + 自定义角色回归。

背景：v2.2.5 之后，默认角色的**非首形态**（吃饱 full）一律走"静态形态图"分支——那修好了
"常态 idle 帧盖住吃饱图"，代价是吃饱形态**完全静止**。v2.4 给它一套**专属** idle 帧集
assets/idle_full_f*（由 _dev/gen_full_idle_frames.py 从 character_full.png 程序化生成，
极小幅呼吸：纵向 ±1.58%、质心不变）。本文件守住四件事：

  1 生成脚本可重复运行且逐字节幂等（含"仓库帧 == 脚本输出"）；
  2 帧素材：尺寸/RGBA/透明度比例/质心/边框/黑边 全部与基准图同口径；
  3 注册：form=full 走帧动画；帧集缺失时安全回退静态图且不崩；
  4 回归：自定义角色的 4 形态规则（f0/f1 有帧照播、f2/f3 无帧静态）不变。

度量口径与生成脚本的 diff_report 一致（ImageChops.difference + ImageStat）。
"""
import hashlib
import importlib.util
import itertools
import os
import subprocess
import sys

import pytest
from PIL import Image, ImageChops, ImageStat

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pet_anim  # noqa: E402

ASSETS = os.path.join(ROOT, "assets")
BASE_PNG = os.path.join(ASSETS, "character_full.png")
GEN_PATH = os.path.join(ROOT, "_dev", "gen_full_idle_frames.py")
FRAME_COUNT = 10

# 阈值：全部按实测值留余量（实测见文件末"实测基线"）
MAD_MIN = 0.5            # 每帧与基准图的 MAD 下限（证明真的动了）
MAD_MAX = 40.0           # 上限（证明没走形；实测最大 10.5）
FRAME_DIFF_MIN = 0.2     # 任意两帧的 MAD 下限（10 帧互不相同）
ALPHA_RATIO_TOL = 0.02   # 透明比例偏差上限（防黑底/防缩水；实测最大 0.0098）
CENTROID_TOL = 0.5       # 质心漂移上限 px（"质心不变"；实测最大 0.06）
BORDER_ALPHA_MAX = 0     # 画布四边必须全透明（不裁切、不贴边）
BLACK_MAX = 40           # 轮廓外"凭空黑像素"上限（防黑边；实测每帧 3~9，未扩边对照 22~73）


def _load_gen():
    """按路径加载生成脚本（它在 _dev/ 下，不是包内模块）。"""
    spec = importlib.util.spec_from_file_location("gen_full_idle_frames", GEN_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gen = _load_gen()


# ---------------- 度量工具（Pillow-only，与脚本同口径） ----------------

def _sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _pix_hash(path):
    """像素哈希（不是文件字节哈希）。

    v2.4.1：帧素材门禁该管的是"图变了"，不是"Pillow 换了编码器"。同一张图在不同
    Pillow/libpng 版本下重编码，文件字节完全不同（压缩级别/filter/块顺序都可能变），
    按字节比会把"升级依赖"误判成"素材被改"。这里比 (尺寸, 模式, 原始像素) —— 与
    _dev/gen_full_idle_frames.py --check 的口径一致（那里也是 ImageChops 比像素）。
    """
    from PIL import Image
    with Image.open(path) as im:
        im.load()
        return (im.size, im.mode, hashlib.sha256(im.tobytes()).hexdigest())


def _mad(a, b, size=None):
    """平均绝对像素差（RGBA 四通道平均）。"""
    w, h = size or a.size
    return sum(ImageStat.Stat(ImageChops.difference(a, b)).sum) / float(w * h * 4)


def _alpha_ratio(im):
    """alpha>0 的像素占比（"透明像素比例"）。"""
    data = im.getchannel("A").tobytes()
    return sum(1 for v in data if v) / float(len(data))


def _centroid(im):
    """alpha 质心 (cx, cy)。"""
    al = im.getchannel("A")
    w, _h = al.size
    total = sx = sy = 0
    for idx, v in enumerate(al.tobytes()):
        if v:
            y, x = divmod(idx, w)
            total += v
            sx += v * x
            sy += v * y
    return sx / float(total), sy / float(total)


def _border_alpha_max(im):
    """画布四边的 alpha 最大值（要求 0 = 不贴边/没被裁切）。"""
    w, h = im.size
    a = im.getchannel("A")
    top = list(a.crop((0, 0, w, 1)).tobytes())
    bottom = list(a.crop((0, h - 1, w, h)).tobytes())
    left = list(a.crop((0, 0, 1, h)).tobytes())
    right = list(a.crop((w - 1, 0, w, h)).tobytes())
    return max(top + bottom + left + right)


def _near_dark_mask(base, radius=3):
    """基准图"暗像素（L<16 且可见）"膨胀 radius 后的掩码（bytearray，1=命中）。

    原图有黑描边；缩放时描边位移会把黑带到轮廓外，那是**正确**的图形内容，
    不算"黑边"。只有"离原图任何暗像素都 >radius 却冒出来的黑"才是黑底混色。
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
    """可见却很暗（L<16）且远离原图描边的像素数 = "凭空出现的黑"。"""
    luma = im.convert("L").tobytes()
    alpha = im.getchannel("A").tobytes()
    return sum(1 for i in range(len(luma))
               if alpha[i] > 0 and luma[i] < 16 and not near_dark[i])


# ---------------- 素材 fixture ----------------

@pytest.fixture(scope="module")
def base():
    with Image.open(BASE_PNG) as im:
        return im.convert("RGBA")


@pytest.fixture(scope="module")
def frame_paths():
    paths = [os.path.join(ASSETS, "idle_full_f%02d.png" % i) for i in range(FRAME_COUNT)]
    missing = [p for p in paths if not os.path.isfile(p)]
    assert not missing, "缺少吃饱形态帧素材：%s（跑 python _dev/gen_full_idle_frames.py）" % missing
    return paths


@pytest.fixture(scope="module")
def frames(frame_paths):
    out = []
    for p in frame_paths:
        im = Image.open(p)
        assert im.mode == "RGBA", "%s 必须是 RGBA（带透明通道），实际 %s" % (p, im.mode)
        out.append(im.convert("RGBA"))
    return out


@pytest.fixture(scope="module")
def near_dark(base):
    return _near_dark_mask(base)


# ---------------- 1 生成脚本幂等 ----------------

def test_generator_idempotent_and_assets_are_its_output(tmp_path):
    """跑两遍哈希不变 + 仓库里的 10 张帧就是脚本的输出（改了图没重跑脚本会红）。"""
    out1 = str(tmp_path / "run1")
    proc = subprocess.run([sys.executable, GEN_PATH, "--out", out1],
                          cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    assert proc.returncode == 0, "生成脚本执行失败：%s" % proc.stdout.decode("utf-8", "replace")

    out2 = str(tmp_path / "run2")
    gen.generate(out2)  # 第二遍（同进程，省一次解释器启动）

    for i in range(FRAME_COUNT):
        name = "idle_full_f%02d.png" % i
        p1, p2, p3 = (os.path.join(out1, name), os.path.join(out2, name),
                      os.path.join(ASSETS, name))
        # 比**像素**（v2.4.1）：文件字节会随 Pillow/libpng 版本变，像素才是素材本身
        h1, h2, h3 = _pix_hash(p1), _pix_hash(p2), _pix_hash(p3)
        assert h1 == h2, "生成脚本不幂等：%s 两遍像素不同" % name
        assert h1 == h3, (
            "%s 与脚本输出像素不一致——素材被手改过（重跑 _dev/gen_full_idle_frames.py "
            "后提交）。仓库副本与脚本输出的字节哈希：%s vs %s"
            % (name, _sha256(p3)[:12], _sha256(p1)[:12]))

    # CLI 自检分支（--check）也必须通过
    assert gen._main(["--check", "--out", ASSETS]) == 0


def test_generator_is_pillow_only():
    """生成脚本不得引入 numpy/scipy 等未声明依赖（requirements 里只有 Pillow）。"""
    src = open(GEN_PATH, encoding="utf-8").read()
    assert "import numpy" not in src and "import scipy" not in src
    assert "from PIL import" in src


# ---------------- 2 变换幅度与帧独立性 ----------------

def test_amplitude_stays_minimal_and_frames_are_distinct_phases():
    """变换必须是"极小幅"：|AMP| 在 1%~2%，10 个相位两两不同（否则会有重复帧）。"""
    assert 0.01 <= gen.AMP_Y <= 0.02, "纵向呼吸幅度应在 ±1%~2%"
    assert 0.0 <= gen.AMP_X < gen.AMP_Y, "横向反向幅度应小于纵向（轻微 squash/stretch）"
    assert gen.FRAME_COUNT == FRAME_COUNT
    phases = [gen.frame_phase(i) for i in range(FRAME_COUNT)]
    gap = min(abs(a - b) for a, b in itertools.combinations(phases, 2))
    assert gap > 0.05, "相位采样对称了：会出现两帧完全一样（gap=%.4f）" % gap
    peak = max(abs(p) for p in phases)
    assert peak * gen.AMP_Y <= 0.02, "实测峰值幅度越界（%.4f）" % (peak * gen.AMP_Y)
    # 缩放矩阵：绕质心，且行列式为"sx*sy"（面积近似守恒 → |det-1| 很小）
    mat = gen.affine_matrix(10.0, 20.0, 1.0 + gen.AMP_Y, 1.0 - gen.AMP_X)
    assert abs(mat[0] * mat[4] - 1.0) < 0.02


# ---------------- 3 帧素材质量 ----------------

def test_frames_match_base_size_mode_and_alpha(base, frames, frame_paths):
    """尺寸/模式/透明比例/边框 与基准图同口径（防裁切、防黑底、防缩水）。"""
    base_ratio = _alpha_ratio(base)
    for i, im in enumerate(frames):
        assert im.size == base.size, "第 %d 帧尺寸 %s != 基准 %s" % (i, im.size, base.size)
        assert len(im.getbands()) == 4
        ratio = _alpha_ratio(im)
        assert abs(ratio - base_ratio) <= ALPHA_RATIO_TOL, (
            "第 %d 帧可见像素比例 %.4f 偏离基准 %.4f 过多（怀疑黑底/裁切）"
            % (i, ratio, base_ratio))
        assert _border_alpha_max(im) == BORDER_ALPHA_MAX, "第 %d 帧贴到画布边（被裁切了）" % i
        assert im.getbbox() is not None, "第 %d 帧全透明——不是真生成的图" % i


def test_frames_keep_centroid(base, frames):
    """质心不变：缩放枢轴 = 基准图 alpha 质心，逐帧漂移应远小于 1px。"""
    bcx, bcy = _centroid(base)
    for i, im in enumerate(frames):
        cx, cy = _centroid(im)
        assert abs(cx - bcx) <= CENTROID_TOL and abs(cy - bcy) <= CENTROID_TOL, (
            "第 %d 帧质心 (%.3f, %.3f) 偏离基准 (%.3f, %.3f) 超过 %.1fpx"
            % (i, cx, cy, bcx, bcy, CENTROID_TOL))


def test_frames_actually_move_but_do_not_deform(base, frames):
    """动起来了（MAD 有下界）但没走形（MAD 有上界）；10 帧两两不同、循环每一拍都在动。"""
    mads = [_mad(im, base) for im in frames]
    assert min(mads) >= MAD_MIN, "有帧几乎与基准图一样（没动）：%s" % mads
    assert max(mads) <= MAD_MAX, "有帧与基准图差太多（走形了）：%s" % mads
    hashes = {im.tobytes() for im in frames}
    assert len(hashes) == FRAME_COUNT, "10 帧里有重复图（动画会卡一下）"
    for i in range(FRAME_COUNT):
        nxt = (i + 1) % FRAME_COUNT
        step = _mad(frames[i], frames[nxt])
        assert step >= FRAME_DIFF_MIN, "第 %d→%d 帧几乎没变化（%.4f）" % (i, nxt, step)


def test_no_black_fringe(base, frames, near_dark):
    """防黑边：扩边后重采样不得在轮廓外凭空造出黑像素（未扩边对照 22~73/帧）。"""
    for i, im in enumerate(frames):
        bad = _invented_black(im, near_dark)
        assert bad <= BLACK_MAX, (
            "第 %d 帧轮廓外凭空黑像素 %d 个（> %d）：透明区的黑被重采样混进颜色了"
            % (i, bad, BLACK_MAX))


# ---------------- 4 注册 / 回退（默认角色） ----------------

@pytest.fixture(scope="module")
def pet(tmp_path_factory):
    """默认角色的 PetWindow（数据目录重定向到临时目录，退出时还原进程级全局）。"""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import 桌宠 as main
    import pet_log
    from PySide6.QtWidgets import QApplication

    tmp = tmp_path_factory.mktemp("fullform")
    snap = (main.DATA_DIR, main.CONFIG_PATH, main.USAGE_PATH, main.MEMORY_PATH,
            getattr(pet_log, "_data_dir", None))
    main.DATA_DIR = str(tmp)
    main.CONFIG_PATH = str(tmp / "config.json")
    main.USAGE_PATH = str(tmp / "usage.json")
    main.MEMORY_PATH = str(tmp / "memory.json")
    pet_log.set_data_dir(str(tmp))
    QApplication.instance() or QApplication([])
    win = main.PetWindow()
    # 角色素材必须落在 DATA_DIR/roles 下（RoleLibrary 按自己的库目录解析相对路径），
    # 所以把这份临时数据目录挂到窗口上，供安装自定义角色的测试使用。
    win._fixture_data_dir = str(tmp)
    try:
        yield win
    finally:
        # L4（v2.4.1）：统一收尾——先停掉全部 QTimer 再 hide/close/deleteLater
        from helpers_roles import active_timer_count, shutdown_pet
        shutdown_pet(win)
        assert active_timer_count(win) == 0, \
            "拆完还有 %d 个活跃定时器" % active_timer_count(win)
        (main.DATA_DIR, main.CONFIG_PATH, main.USAGE_PATH,
         main.MEMORY_PATH) = snap[0], snap[1], snap[2], snap[3]
        pet_log.set_data_dir(snap[4])


def _settle(win, form):
    """把窗口收敛到"默认角色 + 指定形态的待机动画"（显式走 _set_form，不靠定时器）。"""
    win._closing = False
    win.busy = False
    win._sleeping = False
    win._petting = False
    win._cancel_transform()
    win._stop_idle_hold()
    win._idle_active = False
    win._idle_form_active = False
    if win.form != form:
        win._set_form(form, display_only=True)
    win.anim_mode = ""      # 强制 _play_idle 重绘
    win._play_idle()


def test_default_role_full_form_plays_its_own_frames(pet):
    """帧集存在时 form=full 必须走帧动画（anim_mode=idle + 定时器在跑 + 帧来自 idle_full_f*）。"""
    assert not pet._custom_role
    assert len(pet._idle_full_frames) == FRAME_COUNT, "默认角色没加载到 idle_full 帧集"

    _settle(pet, "full")
    idle = pet.anim._sets.get("idle") or []
    assert len(idle) == FRAME_COUNT
    assert all(a is b for a, b in zip(idle, pet._idle_full_frames)), \
        "full 形态播的不是专属帧集（可能是常态 idle_f*）"
    # 复刻 _play_idle 的 _static_form 判据：必须为假
    assert not (pet.form != pet.form_keys[0] and not idle), "full 形态被判成静态"
    assert pet.anim_mode == "idle"
    assert pet.anim._timer.isActive(), "帧动画没在跑（吃饱形态还是静止的）"
    assert any(pet.anim.current() is f for f in pet._idle_full_frames)


def test_default_role_normal_form_keeps_original_idle_frames(pet):
    """首形态不受影响：仍播常态 idle_f*（10 帧）。"""
    _settle(pet, "normal")
    idle = pet.anim._sets.get("idle") or []
    assert len(idle) == FRAME_COUNT
    assert all(a is b for a, b in zip(idle, pet._idle_frames))
    assert pet.anim_mode == "idle" and pet.anim._timer.isActive()


def test_missing_frame_set_falls_back_to_static(pet, tmp_path):
    """帧集缺失（用户删图/旧版数据）→ 静态形态图 + 不崩；恢复后又能动。"""
    _settle(pet, "normal")
    saved = pet._idle_full_frames
    try:
        pet._idle_full_frames = []          # 模拟素材缺失
        pet._wire_anim_sets()
        _settle(pet, "full")
        assert pet._default_idle_frames() == [], "缺帧时该形态的专属帧集必须是空"
        assert (pet.anim._sets.get("idle") or []) == [], "缺帧时 idle 槽必须是空的"
        assert pet.anim_mode == "form_idle", "缺帧时必须回退静态形态图"
        assert not pet.anim._timer.isActive()
        assert pet.item.pixmap().toImage() == pet.sprites["full"]["side"].toImage(), \
            "缺帧时画的不是该形态的静态图"
    finally:
        pet._idle_full_frames = saved

    # 素材回来了：立刻恢复帧动画
    _settle(pet, "normal")
    _settle(pet, "full")
    assert pet.anim_mode == "idle" and pet.anim._timer.isActive()

    # 加载器面对不存在的目录只返回空表，不抛
    assert pet_anim.load_frame_set(str(tmp_path / "no_such_dir"), "idle_full", FRAME_COUNT) == []
    # 截断的帧集（只留 3 张）也能被接受，不抛
    part = tmp_path / "part"
    part.mkdir()
    for i in range(3):
        Image.open(os.path.join(ASSETS, "idle_full_f%02d.png" % i)).save(str(part / ("idle_full_f%02d.png" % i)))
    assert len(pet_anim.load_frame_set(str(part), "idle_full", FRAME_COUNT)) == 3


# ---------------- 5 自定义角色 4 形态规则回归 ----------------

def test_custom_role_four_form_rules_unchanged(pet):
    """自定义角色语义不变：f0/f1 有 idle 帧照播，f2/f3 无 idle 帧一律静态。"""
    from helpers_roles import install_three_form_role

    install_three_form_role(pet, pet._fixture_data_dir)
    try:
        assert pet._custom_role and pet.form_keys == ["f0", "f1", "f2", "f3"]

        for form, expect_frames in (("f0", True), ("f1", True), ("f2", False), ("f3", False)):
            _settle(pet, form)
            idle = pet.anim._sets.get("idle") or []
            if expect_frames:
                assert idle, "%s 有 idle 帧却注册成空集" % form
                assert pet.anim_mode == "idle" and pet.anim._timer.isActive(), \
                    "%s 该播帧动画" % form
                assert not (pet.form != pet.form_keys[0] and not idle)
            else:
                assert idle == [], "%s 没有 idle 帧，idle 槽必须是空的" % form
                assert pet.anim_mode == "form_idle", "%s 该走静态形态图" % form
                assert not pet.anim._timer.isActive()
                assert pet.item.pixmap().toImage() == pet.sprites[form]["side"].toImage()

        # 默认角色的 idle_full 帧集不得泄漏进自定义角色
        _settle(pet, "f0")
        leaked = [f for f in (pet.anim._sets.get("idle") or [])
                  if any(f is g for g in pet._idle_full_frames)]
        assert not leaked, "默认角色的吃饱帧集泄漏进了自定义角色"
    finally:
        pet.apply_role("")  # 还原默认角色，别污染同模块后续测试


# 实测基线（2026-xx，Pillow 12.1.1，256×256）：
#   MAD vs 基准图：3.29 / 8.32 / 10.12 / 9.58 / 6.16 / 3.29 / 8.57 / 10.51 / 9.96 / 6.28
#   相邻帧 MAD：5.77 / 3.66 / 1.31 / 5.04 / 7.90 / 6.00 / 3.68 / 1.28 / 5.29 / 5.86
#   alpha>0 比例：基准 0.3530，帧 0.3432~0.3503（最大偏差 0.0098）
#   质心漂移：最大 0.060px；边框 alpha：全 0
#   轮廓外凭空黑像素：每帧 3~9（未做扩边的对照实现：每帧 22~73）
