# -*- coding: utf-8 -*-
"""v2.4.1 帧集注册指纹缓存回归（UI 卡顿收口）。

背景：_play_idle 每次待机都会重查帧集（_wire_anim_sets），此前**无条件**把当前形态的
整批帧重新解码一遍。实测（_dev/probe_ui_freeze.py，60 帧真实美术 512px）：
_play_idle 12 次共 690 ms、单次最大 199.5 ms；一次 apply_role 解 69 个 PNG。
帧集内容由**路径列表**唯一决定，指纹一致 = 注册结果逐位相同 → 直接返回。

钉四件事（每条都能真失败）：
  1. 指纹一致时重复注册**一帧都不取**（_frame_pix 一次都不调）；
  2. 反例对照：清掉指纹（= 旧行为）必须重新取帧，证明第 1 条不是"本来就没活干"；
  3. 形态切换 / 换角色必须重新注册（否则会播错形态的帧）；
  4. 走指纹跳过的帧集与重新注册的**逐位相同**（cacheKey 全等，且 idle 不是空集）。

v2.4.1 修订（B 区）：帧解码新增了**单帧缓存**（_frame_pix）后，"重复注册"未必再
构造 QPixmap（缓存命中），所以"有没有真的重新取帧"要用 _frame_pix 的**调用次数**量，
PNG 构造次数作为第二口径一起钉。这不是放宽断言——见 test_repeated_wiring 的对照臂：
清指纹后取帧次数必须**整好回到基准**，比原先只看 QPixmap 构造更严。
"""
import os
import sys
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import 桌宠 as main  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="module")
def pet(tmp_path_factory):
    """真 PetWindow + 临时数据目录（隔离套路与 test_dialogs_more_v24.py 一致）。"""
    import pet_log

    tmp = tmp_path_factory.mktemp("wirecache241")
    snap = (main.DATA_DIR, main.CONFIG_PATH, main.USAGE_PATH, main.MEMORY_PATH,
            getattr(pet_log, "_data_dir", None))
    main.DATA_DIR = str(tmp)
    main.CONFIG_PATH = str(tmp / "config.json")
    main.USAGE_PATH = str(tmp / "usage.json")
    main.MEMORY_PATH = str(tmp / "memory.json")
    pet_log.set_data_dir(str(tmp))
    QApplication.instance() or QApplication([])
    win = main.PetWindow()
    from helpers_roles import install_three_form_role, quiet_pet_timers
    install_three_form_role(win, tmp)
    quiet_pet_timers(win)   # 用例要确定性的起播计数：停掉会自行调 _play_idle 的周期表
    yield win
    # L4（v2.4.1）：统一收尾——先停掉全部 QTimer 再 hide/close/deleteLater
    from helpers_roles import active_timer_count, shutdown_pet
    shutdown_pet(win)
    assert active_timer_count(win) == 0, "拆完还有 %d 个活跃定时器" % active_timer_count(win)
    (main.DATA_DIR, main.CONFIG_PATH, main.USAGE_PATH, main.MEMORY_PATH,
     pet_log._data_dir) = snap


def _counters(monkeypatch):
    """两个口径一起量，返回 (decodes, fetches)。

      · decodes —— QPixmap(路径) 的真实构造次数（= PNG 解码次数，探针同口径）；
      · fetches —— PetWindow._frame_pix 的调用次数（= 取帧工作量，**含缓存命中**）。

    为什么要两个：v2.4.1 加了单帧解码缓存后，"重新注册"可能一次 QPixmap 都不构造
    （全命中缓存），单看 decodes 分不出"跳过了注册"和"注册了但全命中缓存"。
    fetches 才是"有没有重新干活"的直接证据。
    """
    real = main.QPixmap
    decodes = []

    def counting(*a, **k):
        if a and isinstance(a[0], str):
            decodes.append(a[0])
        return real(*a, **k)

    monkeypatch.setattr(main, "QPixmap", counting, raising=False)
    fetches = []
    real_fetch = main.PetWindow._frame_pix

    def counting_fetch(self, path, *a, **k):
        fetches.append(path)
        return real_fetch(self, path, *a, **k)

    monkeypatch.setattr(main.PetWindow, "_frame_pix", counting_fetch)
    return decodes, fetches


def _snapshot(win):
    """帧集内容快照：{动作键: [每帧 QPixmap.cacheKey()]}。"""
    return {k: [p.cacheKey() for p in v] for k, v in win.anim._sets.items()}


def test_repeated_wiring_decodes_nothing(pet, monkeypatch):
    """指纹一致 → 一次都不重新取帧（待机热路径），且不构造任何 QPixmap。"""
    win = pet
    win.apply_role("inv1")
    win._set_form("f0", display_only=True)
    win._wire_key = None                 # 强制重新注册一次，作为基准
    decodes, fetches = _counters(monkeypatch)
    win._wire_anim_sets()
    base = len(fetches)
    assert base > 0, ("基准注册居然一帧都没取：sets=%r custom=%r role=%r cur=%r dir=%r"
                      % (list(win.anim._sets), win._custom_role, win.cfg.get("role"),
                         win._cur_form_anim(), getattr(win.role_lib, "_dir", None)))
    # 基准这一臂的帧在 apply_role 时就进了解码缓存 → 应当一次 QPixmap 都不构造
    assert decodes == [], "基准注册真解了 PNG（缓存没热？）：%r" % (decodes[:5],)

    decodes[:] = []
    fetches[:] = []
    win._wire_anim_sets()
    win._wire_anim_sets()
    win._play_idle()                     # 真正热的那条路径
    assert fetches == [], "重复注册又取了 %d 帧：%r" % (len(fetches), fetches[:5])
    assert decodes == [], "重复注册又解码了 %d 帧：%r" % (len(decodes), decodes[:5])

    # 反例对照①：清掉指纹 = 旧行为（每次重新取帧）→ 取帧次数必须**整好回到 base**
    decodes[:] = []
    fetches[:] = []
    win._wire_key = None
    win._wire_anim_sets()
    assert len(fetches) == base, "对照组失效：清指纹后取帧 %d 次，基准 %d 次" % (len(fetches), base)
    assert decodes == [], "解码缓存还热着，清指纹不该再解 PNG（%d 次）" % (len(decodes),)

    # 反例对照②：连解码缓存一起清掉 → 这一次必须**真的重新解 PNG**。它证明两件事：
    # 计数器有效（不是恒为 0），且"重复注册不解码"确实是缓存+指纹的功劳、不是"本来就没图可解"。
    decodes[:] = []
    fetches[:] = []
    win._wire_key = None
    win._frame_cache.clear()
    win._wire_anim_sets()
    assert len(fetches) == base, "清缓存后取帧 %d 次，基准 %d 次" % (len(fetches), base)
    assert decodes, "清缓存后一帧 PNG 都没解：计数器失效，本用例没有区分力"
    assert len(decodes) <= base, "解码次数(%d)多于取帧次数(%d)（同一路径一次注册内只该解一次）" \
        % (len(decodes), base)


def test_wiring_survives_cache_and_matches_fresh_registration(pet, monkeypatch):
    """走指纹跳过的帧集与"重新注册"的逐位相同——不是少注册、也不是空集。"""
    win = pet
    win.apply_role("inv1")
    win._set_form("f0", display_only=True)
    win._wire_key = None
    win._wire_anim_sets()
    fresh = _snapshot(win)
    assert fresh.get("idle"), "idle 帧集是空的（自定义角色应该按形态注册）"
    win._wire_anim_sets()                # 走指纹跳过
    assert _snapshot(win) == fresh, "跳过后的帧集与首次注册不一致"
    # 真·重新注册（清指纹）也必须是同一份内容：否则"跳过"就是在掩盖差异
    win._wire_key = None
    win._wire_anim_sets()
    assert _snapshot(win) == fresh, "重新注册的帧集与跳过的不是同一份内容"


def test_form_switch_still_re_wires(pet, monkeypatch):
    """形态切换必须重新注册（不同形态的帧集不同，指纹不许把它吃掉）。"""
    win = pet
    win.apply_role("inv1")
    win._set_form("f0", display_only=True)
    win._wire_key = None
    win._wire_anim_sets()
    f0 = _snapshot(win)
    _decodes, fetches = _counters(monkeypatch)
    win._set_form("f1", display_only=True)
    win._wire_anim_sets()
    f1 = _snapshot(win)
    assert fetches, "形态切换一帧都没重新取（说明指纹没把形态算进去）"
    assert f0.get("idle") != f1.get("idle"), "两个形态的 idle 帧集居然一样，用例没有区分力"


def test_role_change_still_re_wires(pet, monkeypatch):
    """换角色（含切回默认角色）必须重新注册。"""
    win = pet
    win.apply_role("inv1")
    decodes, _fetches = _counters(monkeypatch)
    win.apply_role("")                   # 回默认角色
    assert decodes, "回默认角色没有重新加载贴图（默认角色的帧集与自定义角色不同）"
    d = _snapshot(win)
    assert d.get("idle"), "默认角色 idle 帧集是空的"
    decodes[:] = []
    win._wire_anim_sets()                # 默认角色再注册一次：指纹一致 → 不重来
    assert decodes == [], "默认角色重复注册又解码了 %d 帧" % (len(decodes),)
    win.apply_role("inv1")
    assert decodes, "切回自定义角色没有重新取帧"


# ---------------- v2.4.1 找茬 M2/M5：素材换名/换内容与缓存上界 ----------------

def _center_rgb(pix):
    """QPixmap 中心像素 (r, g, b)——比较素材内容用（不看对象身份）。"""
    img = pix.toImage()
    return img.pixelColor(img.width() // 2, img.height() // 2).getRgb()[:3]


def _write_png(path, color, w=64, h=64):
    """原地重写一张纯色 PNG（同路径、同尺寸：只靠 mtime 判别时也能测出来）。"""
    from PySide6.QtGui import QColor, QImage
    img = QImage(w, h, QImage.Format.Format_ARGB32)
    img.fill(QColor(*color))
    img.save(path)


def test_in_place_material_swap_is_re_decoded_and_replayed(pet, monkeypatch):
    """M2（找茬）：同一路径原地换素材必须**重解**并**重新起播**。

    HEAD 实测：指纹只含路径 → 原地重写 roles/inv_a.png（改成绿色）后 _play_idle() 取帧 0 次、
    解码 0 次、画面仍旧；把 _wire_key=None 才变绿。用户直接替换数据目录里的 PNG 是既有用法。
    能真失败：① _wire_anim_key 里去掉 mtime/大小（退回纯路径）→ 取帧 0 次；
              ② _play_idle 里去掉 "anim._frames is not idle_frames" 那一句 → 帧集换了却不起播。
    """
    win = pet
    win.apply_role("inv1")
    win._set_form("f0", display_only=True)
    win._wire_key = None
    win._wire_anim_sets()
    win._play_idle()
    old = list(win.anim._sets.get("idle") or [])
    assert old, "idle 帧集是空的，用例前提不成立"
    path = win.role_lib.form_animations("inv1")[0]["idle"][0]
    assert os.path.isfile(path), path
    old_rgb = _center_rgb(old[0])
    assert old_rgb != (0, 255, 0), "原素材本来就是绿的，用例没有区分力：%r" % (old_rgb,)
    _write_png(path, (0, 255, 0, 255))
    time.sleep(0.02)
    st = os.stat(path)
    os.utime(path, ns=(st.st_atime_ns + 10 ** 9, st.st_mtime_ns + 10 ** 9))  # 时间戳粒度兜底
    fetches = []
    real_fetch = main.PetWindow._frame_pix

    def spy(self, p, *a, **k):
        fetches.append(p)
        return real_fetch(self, p, *a, **k)

    monkeypatch.setattr(main.PetWindow, "_frame_pix", spy)
    win._play_idle()
    new = list(win.anim._sets.get("idle") or [])
    assert fetches, "同路径换素材后一帧都没重取：指纹没把 mtime/大小算进去"
    assert new and new[0] is not old[0], "重新注册拿到的还是旧 QPixmap 对象"
    assert _center_rgb(new[0]) == (0, 255, 0), "画面还是旧素材（没重解）"
    assert win.anim._frames is win.anim._sets.get("idle"), "新帧集没被起播（画面挂在旧列表上）"


def test_frame_cache_is_bounded_by_bytes_not_entries(pet, monkeypatch):
    """M5（找茬）：缓存上界必须是**字节预算**——512 条 × 单帧最大 1MB = 最坏 512MB 常驻。

    实测（审查）：24 帧 512px 角色跑完 len=25 ≈ 25MB。这里把预算压到 4MB，看 8 张 512px 帧
    （每张 512×512×4 = 1MB）是否真的只留下 4 张、且计数器与实际内容一致。
    能真失败：把 _frame_pix 里的字节淘汰去掉（只留条目数上限），第一条断言红。
    """
    from helpers_roles import install_big_frame_role, drain_anim_slices
    win = pet
    rid, paths = install_big_frame_role(win, win.role_lib._dir, n=8, rid="bigcache1")
    win.apply_role(rid)
    drain_anim_slices(win)
    win._clear_frame_cache()
    monkeypatch.setattr(main, "_FRAME_CACHE_MAX_BYTES", 4 * 1024 * 1024)
    for p in paths:
        win._frame_pix(p)
    assert len(win._frame_cache) == 4, \
        "字节预算没生效：留下 %d 条（每张 1MB、预算 4MB）" % len(win._frame_cache)
    assert win._frame_cache_bytes <= 4 * 1024 * 1024, win._frame_cache_bytes
    assert win._frame_cache_bytes == sum(
        int(pix.width()) * int(pix.height()) * 4 for pix in win._frame_cache.values()), \
        "字节计数器与实际缓存内容不符"
    # 反例对照：预算放大到装得下 → 8 条全在（证明上面不是"根本没缓存"）
    monkeypatch.setattr(main, "_FRAME_CACHE_MAX_BYTES", 64 * 1024 * 1024)
    win._clear_frame_cache()
    for p in paths:
        win._frame_pix(p)
    assert len(win._frame_cache) == 8, len(win._frame_cache)


def test_role_change_drops_the_old_roles_frame_keys(pet):
    """M5（找茬）：换角色要清掉旧角色的键——旧素材不可能再命中，留着只占预算。

    能真失败：把 _reload_sprites 里的 _clear_frame_cache() 删掉，第二条断言红。
    """
    from helpers_roles import install_big_frame_role, drain_anim_slices
    win = pet
    rid, paths = install_big_frame_role(win, win.role_lib._dir, n=4, size=256, rid="bigclear1")
    win.apply_role(rid)
    drain_anim_slices(win)
    keys = {k[0] for k in win._frame_cache}
    assert keys & set(paths), "旧角色的帧没进缓存，用例前提不成立"
    win.apply_role("inv1")
    keys2 = {k[0] for k in win._frame_cache}
    assert not (keys2 & set(paths)), "换角色后旧角色的键还在缓存里：%r" % sorted(keys2 & set(paths))
