# -*- coding: utf-8 -*-
"""v2.5.0（A3）_start_petting 的帧集守卫：自定义角色别在摸头路径上同步解用不到的默认帧集。

背景（v2.4.3 同类问题的**第二个入口**）：
  · v2.4.3 给 feed() 加了 not self._custom_role 守卫，理由与实测写在 test_relay_v243 的
    test_custom_role_first_feed_does_not_decode_default_sets 里（首喂同步解 idle/idle_full/
    eat 共 62.07ms，而自定义角色的吃帧走 forms[i].animations，那三组一张都用不到）；
  · _start_petting 是**同一个源头**却漏了：它调 _ensure_default_frames()（不传组名 = 补齐
    全部四组）。自定义角色真正用得到的只有 assets/fx/petpet（四组里唯一共用的那组，见
    _startup_frame_sets），idle/idle_full/eat 一张都不会被消费；
  · 修法直接复用**已有的角色口径**：_ensure_default_frames(self._startup_frame_sets())。
    默认角色下 _startup_frame_sets() 返回四组全名 → 与旧的"不传组名"逐位等价
    （_ensure_default_frames 内部就是按 _DEFAULT_FRAME_SETS 顺序按键名过滤）；
    自定义角色下只补 petpet → 摸头照播，但不再顺带解三组用不到的帧。

能真失败：把 _start_petting 里的 _ensure_default_frames(self._startup_frame_sets())
改回 _ensure_default_frames() → 下面第 1 条的 banned 命中、第 3 条的 _frames_loaded 都会红。
"""
import json
import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import 桌宠 as main  # noqa: E402
import pet_anim  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


# ---------------- 夹具 ----------------

def _snapshot():
    import pet_log
    return (main.DATA_DIR, main.CONFIG_PATH, main.USAGE_PATH, main.MEMORY_PATH,
            getattr(pet_log, "_data_dir", None))


def _point_data_dir(tmp_path):
    import pet_log
    main.DATA_DIR = str(tmp_path)
    main.CONFIG_PATH = str(tmp_path / "config.json")
    main.USAGE_PATH = str(tmp_path / "usage.json")
    main.MEMORY_PATH = str(tmp_path / "memory.json")
    pet_log.set_data_dir(str(tmp_path))


def _restore(snap):
    import pet_log
    (main.DATA_DIR, main.CONFIG_PATH, main.USAGE_PATH, main.MEMORY_PATH,
     pet_log._data_dir) = snap


def _decode_spy(monkeypatch):
    """记录 QPixmap(路径) 解码（两个模块都包：帧集在 pet_anim 里解）。"""
    seen = []

    def make(real):
        def counting(*a, **k):
            if a and isinstance(a[0], str):
                seen.append(a[0])
            return real(*a, **k)
        return counting

    monkeypatch.setattr(main, "QPixmap", make(main.QPixmap), raising=False)
    monkeypatch.setattr(pet_anim, "QPixmap", make(pet_anim.QPixmap), raising=False)
    return seen


def _names(paths):
    return sorted({os.path.basename(p) for p in paths})


def _default_frame_names():
    """自定义角色"不该出现"的默认素材名（四组里去掉 petpet——摸头特效是共用的）。"""
    out = set()
    for _k, _sub, prefix, count, _attr in main._DEFAULT_FRAME_SETS:
        if prefix == "petpet":
            continue
        out |= {"%s_f%02d.png" % (prefix, i) for i in range(count)}
    return out


def _mk_custom_role(tmp_path, rid="crole1", n=3, animations=("idle",)):
    """造一个自定义角色（真 PNG）+ roles.json + config.json（role=它），**必须在建窗前落盘**。"""
    from PySide6.QtGui import QColor, QImage

    d = tmp_path / "roles"
    d.mkdir(exist_ok=True)
    names = []
    for i in range(n):
        name = "crole_%02d.png" % i
        img = QImage(96, 96, QImage.Format.Format_ARGB32)
        img.fill(QColor(40 + i * 30, 120, 200, 255))
        img.save(str(d / name))
        names.append(name)
    role = {"id": rid, "name": "自定义测试角色", "file": names[0], "form": "single",
            "file_full": "", "frames": list(names), "added": "",
            "forms": [{"name": "常态", "file": names[0],
                       "animations": {a: list(names) for a in animations},
                       "anim_interval_ms": 80}]}
    (tmp_path / "roles.json").write_text(
        json.dumps({"roles": [role], "active": rid}, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "config.json").write_text(
        json.dumps({"role": rid}, ensure_ascii=False), encoding="utf-8")
    return rid


def _reset_frame_sets(win):
    """把窗口打回"接力装载一组都没跑"的状态；用例自己决定随后怎么驱动。"""
    win._frames_loaded = {}
    win._idle_frames = []
    win._idle_full_frames = []
    win._eat_frames = []
    win._fx_petpet = []
    win._startup_assets_done = False
    win.busy = False
    win._petting = False
    win._press_dist = 0


# ---------------- 1. 自定义角色：只补 petpet ----------------

def test_custom_role_petting_does_not_decode_default_frame_sets(tmp_path, monkeypatch):
    """自定义角色摸头：只同步补 petpet，不许顺带解 idle/idle_full/eat。

    能真失败：把 _start_petting 的 _ensure_default_frames(self._startup_frame_sets())
    改回 _ensure_default_frames() → 同步解码清单里立刻出现 idle_f_/idle_full_f_/eat_f_，
    且 _frames_loaded 里会多出这三组 → 两条断言同时红。
    """
    from helpers_roles import shutdown_pet

    rid = _mk_custom_role(tmp_path)
    snap = _snapshot()
    _point_data_dir(tmp_path)
    QApplication.instance() or QApplication([])
    win = None
    try:
        win = main.PetWindow()
        assert win._custom_role and win.cfg.get("role") == rid, "夹具没让窗口进自定义角色路径"
        _reset_frame_sets(win)      # 明确的"接力还没跑完"
        seen = _decode_spy(monkeypatch)

        win._start_petting()

        banned = _default_frame_names()
        hit = sorted(set(_names(seen)) & banned)
        assert hit == [], ("自定义角色的摸头路径同步解了用不到的默认帧集：%r"
                           "（四组里它只用到 petpet）" % hit)
        assert win._petting and win._fx_petpet_on, "自定义角色摸头没播起来（petpet 帧集没被补齐）"
        assert len(win._fx_petpet) == 10, "petpet 帧数不对：%d" % len(win._fx_petpet)
        assert not win._frames_loaded.get("idle") and not win._frames_loaded.get("idle_full") \
            and not win._frames_loaded.get("eat"), \
            "摸头路径把三组用不到的帧集标成已解了：%r" % (sorted(win._frames_loaded),)
        win._end_petting()
    finally:
        if win is not None:
            shutdown_pet(win)
        _restore(snap)


# ---------------- 2. 默认角色：反向对照，口径逐位不变 ----------------

def test_default_role_petting_still_ensures_all_four_sets(tmp_path, monkeypatch):
    """默认角色摸头仍要补齐**四组全部**（别把角色判断写反 / 别顺手把默认角色也削了）。

    能真失败：把 _ensure_default_frames(self._startup_frame_sets()) 改成
    _ensure_default_frames(("petpet",)) 这类"一律只补 petpet" → 默认角色缺三组 → 红。
    """
    from helpers_roles import shutdown_pet

    snap = _snapshot()
    _point_data_dir(tmp_path)
    QApplication.instance() or QApplication([])
    win = None
    try:
        win = main.PetWindow()
        assert not win._custom_role, "夹具前提：默认角色"
        assert win._startup_frame_sets() == ("idle", "idle_full", "eat", "petpet")
        _reset_frame_sets(win)
        seen = _decode_spy(monkeypatch)

        win._start_petting()

        missing = [k for k in ("idle", "idle_full", "eat", "petpet")
                   if not win._frames_loaded.get(k)]
        assert missing == [], "默认角色摸头没有补齐全部四组：缺 %r" % missing
        got = set(_names(seen))
        assert {"idle_f00.png", "idle_full_f00.png", "eat_f00.png", "petpet_f00.png"} <= got, \
            "同步解码清单里缺组：%r" % sorted(got)
        assert len(win._fx_petpet) == 10 and win._petting
        win._end_petting()
    finally:
        if win is not None:
            shutdown_pet(win)
        _restore(snap)


# ---------------- 3. 结构判据：修法就是"传角色口径" ----------------

def test_petting_ensure_uses_the_role_scope():
    """结构判据（不抠注释，走 AST）：_start_petting 里那次补齐必须传组名，且是 _startup_frame_sets()。

    能真失败：把实参删掉（回到不传组名）或换成别的表达式 → 红。这条与上面两条行为用例
    互补：行为用例证明"现在没多解"，这条钉住"修法的形状"，防止有人把实参悄悄换掉又恰好
    被别的改动掩盖。
    """
    import ast
    import inspect
    import textwrap

    src = textwrap.dedent(inspect.getsource(main.PetWindow._start_petting))
    tree = ast.parse(src)
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == "_ensure_default_frames"]
    assert len(calls) == 1, "补齐调用有 %d 处（应为 1 处）" % len(calls)
    call = calls[0]
    assert len(call.args) == 1, "补齐没传组名（= 又变回「补全部四组」）：%s" % ast.unparse(call)
    assert ast.unparse(call.args[0]).strip() == "self._startup_frame_sets()", ast.unparse(call)
