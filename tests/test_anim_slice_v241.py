# -*- coding: utf-8 -*-
"""v2.4.1 分片解码状态机回归（找茬 M3/M4）。

背景：分片路径（_anim_start_async / _anim_chunk_step / _anim_pending / _FRAME_SLICE_MS）
此前**一次都没跑过**——现成的测试角色 idle 只有 1 帧，整批永远落在首片里。M3 的漏
（同步臂先跑完却不作废在途分片 → 那颗 QTimer 到点把整批 jobs 再走一遍、再 add_set、
_anim_ready 因 _anim_pending_restart 仍为 True 而强制 _play_idle，帧动画从第 0 帧重跳）
就是这么漏出来的。

这里的用例一律用"**冷缓存 + ≥8 张 512px 噪声帧**"把分片真的跑起来：
  M4  冷缓存 → (a) 确实分片 (b) 跑完帧集齐、指纹收敛 (c) 单次阻塞 ≤ 一个切片量级
      (d) 不多起播
  M3  分片在途时同步臂先跑完 → 在途批必须被作废（pump 期间零 add_set、零 anim.play）
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
    """真 PetWindow + 临时数据目录（隔离套路与 test_ui_wire_cache_v241.py 一致）。"""
    import pet_log

    tmp = tmp_path_factory.mktemp("animslic241")
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
    quiet_pet_timers(win)      # 用例要确定性的起播计数：停掉会自行调 _play_idle 的周期表
    yield win
    from helpers_roles import shutdown_pet
    shutdown_pet(win)
    (main.DATA_DIR, main.CONFIG_PATH, main.USAGE_PATH, main.MEMORY_PATH,
     pet_log._data_dir) = snap


def _count_plays(monkeypatch):
    """统计 FrameAnim.play(name) 的调用（起播次数）。"""
    plays = []
    real = main.pet_anim.FrameAnim.play

    def spy(anim_self, name, *a, **k):
        plays.append(name)
        return real(anim_self, name, *a, **k)

    monkeypatch.setattr(main.pet_anim.FrameAnim, "play", spy)
    return plays


def _count_add_sets(monkeypatch):
    """统计 FrameAnim.add_set(name, n) 的调用（重新注册帧集次数）。"""
    adds = []
    real = main.pet_anim.FrameAnim.add_set

    def spy(anim_self, name, pixmaps):
        adds.append((name, len(pixmaps)))
        return real(anim_self, name, pixmaps)

    monkeypatch.setattr(main.pet_anim.FrameAnim, "add_set", spy)
    return adds


def _prep_big_role(win, n, rid, prefix):
    """装 n 帧大角色 → 切过去 → 跑完它自己的分片 → 停在稳定待机态。

    rid/prefix 必须每个用例各不相同：pet 是 module 级 fixture，同名角色会被
    RoleLibrary.get() 命中**先装的那一个**（帧数就对不上了）。
    """
    from helpers_roles import install_big_frame_role, drain_anim_slices
    rid, paths = install_big_frame_role(win, win.role_lib._dir, n=n, rid=rid, prefix=prefix)
    win.apply_role(rid)
    drain_anim_slices(win)
    win._play_idle()
    return rid, paths


def _make_frames_cold(win, paths, seed):
    """让这批帧真的"冷"：原地重写 + 推 mtime（Qt 内部 pixmap 缓存失效）+ 清解码缓存。

    只清 win._frame_cache 是不够的——Qt 自己按 (文件名, mtime) 缓存解码结果，第二次
    QPixmap(path) 只要 0.2ms（实测），整批就永远落在一个 12ms 切片里，分片路径跑不到。
    """
    from helpers_roles import rewrite_big_frames
    rewrite_big_frames(paths, seed=seed)
    win._clear_frame_cache()


def test_cold_big_frame_set_is_sliced_and_completes(pet, monkeypatch):
    """M4（找茬）：冷缓存 + 10 张 512px 帧必须走分片，且 (a)~(d) 四条同时成立。"""
    from helpers_roles import drain_anim_slices
    win = pet
    rid, paths = _prep_big_role(win, 10, "bigslice10", "big_s10")
    # 单帧冷解码成本：下面 (c) 的余量基准（也顺手证明这批帧真的"贵"）
    _make_frames_cold(win, paths, seed=11)
    t0 = time.perf_counter()
    win._frame_pix(paths[0])
    one_frame_ms = (time.perf_counter() - t0) * 1000.0
    assert one_frame_ms > 1.0, "单帧只解了 %.2fms，本用例分不出片（帧集要更大/更慢）" % one_frame_ms
    # 再冷一次（上面那次把 paths[0] 解热了）→ 首片必然超预算，转分片
    _make_frames_cold(win, paths, seed=12)
    assert win._anim_pending is None
    plays = _count_plays(monkeypatch)
    t0 = time.perf_counter()
    win._wire_anim_sets()
    first_ms = (time.perf_counter() - t0) * 1000.0
    # (a) 真的分片了（不是"首片把整批解完"）
    assert win._anim_pending is not None, (
        "(a) 首片就把 %d 帧全解完了：单帧 %.1fms、首片 %.1fms —— 分片路径没被覆盖到"
        % (len(paths), one_frame_ms, first_ms))
    steps = drain_anim_slices(win)
    assert win._anim_pending is None, "分片没跑完（drain 上限到了？）"
    # (b) 帧集齐 + 指纹收敛
    idle = win.anim._sets.get("idle") or []
    assert len(idle) == len(paths), "(b) 分片跑完帧集不齐：%d/%d" % (len(idle), len(paths))
    assert win._wire_key == win._wire_anim_key(), "(b) 指纹没收敛到当前状态"
    # (c) 单次阻塞 ≤ 一个切片 + 一帧解码的量级（非分片实现会在这一步吃掉整批）
    budget = main._FRAME_SLICE_MS + one_frame_ms + 25.0
    worst = max(steps) if steps else 0.0
    total = sum(steps)
    assert worst <= budget, "(c) 单次阻塞 %.1fms 超预算 %.1fms（切片没生效）" % (worst, budget)
    assert first_ms <= budget, "(c) 首片同步阻塞 %.1fms 超预算 %.1fms" % (first_ms, budget)
    assert worst < total, "(c) 最慢一步就是全部（%.1fms vs 总 %.1fms）：根本没分摊开" % (worst, total)
    # (d) 不多起播：本批只该由 _anim_ready 起一次
    assert plays.count("idle") == 1, "(d) 起播了 %d 次：%r" % (plays.count("idle"), plays)


def test_sync_arm_cancels_the_inflight_slice_batch(pet, monkeypatch):
    """M3（找茬）：同步臂先跑完时必须作废在途分片，pump 期间不许再走一遍整批 jobs。

    复现审查实测的时序：① 冷缓存 → 首片超预算、转分片（_anim_pending 非 None）；
    ② 把剩下的帧预热进缓存（= 剩下的活刚好能落进一个切片）→ 下一次 _wire_anim_sets 走同步臂；
    ③ pump（那颗 QTimer(0) 到点 + 点名再调一次 _anim_chunk_step）→ 必须零 add_set、零 anim.play。
    HEAD 实测：③ 会再 add_set 4 次 + 再 play("idle") 一次（帧动画从第 0 帧重跳）。
    """
    from helpers_roles import drain_anim_slices
    win = pet
    rid, paths = _prep_big_role(win, 8, "bigslice8", "big_s8")
    _make_frames_cold(win, paths, seed=21)
    assert win._anim_pending is None
    win._wire_anim_sets()
    assert win._anim_pending is not None, "前提不成立：首片没超预算，本用例没有区分力"
    # ② 预热：剩下的帧全进解码缓存 → 下一次注册落在首片里（同步臂）
    for p in paths:
        win._frame_pix(p)
    adds = _count_add_sets(monkeypatch)
    plays = _count_plays(monkeypatch)
    win._wire_anim_sets()
    assert win._anim_pending is None, "同步臂装完帧集后没有作废在途分片（M3）"
    assert win.anim._frames is win.anim._sets.get("idle"), "同步臂装好后没起播新帧集"
    # ③ 那颗 QTimer(0) 到点：既走一遍事件循环，也点名调用一次（等价于定时器到点）
    adds[:] = []
    plays[:] = []
    QApplication.processEvents()
    win._anim_chunk_step()
    QApplication.processEvents()
    assert adds == [], "在途分片被重复走了一遍：又 add_set %r" % (adds,)
    assert plays == [], "在途分片被重复走了一遍：又起播 %r" % (plays,)
    drain_anim_slices(win)
    assert adds == [] and plays == [], "残留定时器仍会重装帧集/重起播：%r %r" % (adds, plays)


def test_chunk_step_failure_does_not_strand_the_batch(pet, monkeypatch):
    """L7（质量审查）：_anim_chunk_step 抛错时必须清 _anim_pending，不能把本批永久挂住。

    HEAD：异常经 _gslot 只记一条日志，_anim_pending 留着 → 本批帧集永远装不上，要等下一次
    指纹变化才自愈（配合 M2(2) 的"自损"，idle 槽还是空的 → 画面永久停在静态图）。
    能真失败：把 _anim_chunk_step 里 finally 那段兜底删掉，第一条断言红。
    """
    win = pet
    rid, paths = _prep_big_role(win, 8, "bigslice8b", "big_s8b")
    _make_frames_cold(win, paths, seed=31)
    win._wire_anim_sets()
    st = win._anim_pending
    assert st is not None, "前提不成立：首片没超预算，本用例没有区分力"
    real_fetch = win._frame_pix
    calls = {"n": 0}

    def bad_once(p, *a, **k):
        calls["n"] += 1
        if calls["n"] <= 1:
            raise RuntimeError("坏素材")     # 只坏一次：后面要能正常收尾
        return real_fetch(p, *a, **k)

    monkeypatch.setattr(win, "_frame_pix", bad_once)
    with pytest.raises(RuntimeError):
        win._anim_chunk_step()               # 直接调用：异常必须原样抛给调用方（_gslot 才吞它）
    assert win._anim_pending is not st, \
        "(L7) 抛错后旧批还挂在 _anim_pending 上：本批永远装不上、画面停在自损后的静态图"
    from helpers_roles import drain_anim_slices
    drain_anim_slices(win)
    idle = win.anim._sets.get("idle") or []
    assert len(idle) == len(paths), "兜底之后 idle 槽没被重新装上：%d/%d" % (len(idle), len(paths))


def test_async_window_does_not_play_the_previous_roles_frames(pet, monkeypatch):
    """M2（质量审查）：分片窗口期不许继续播**上一个角色**的帧动画。

    审查实测：小角色 → 4形态×60帧512px，apply_role 同步返回 159.8ms、帧集真正换新 542.7ms，
    其间 5/6 次采样仍是旧角色帧且 anim_mode=="idle"（旧角色还在动）；旧路径是"整屏卡 456ms
    后直接是新角色"，不会播错角色。修法：进异步分支就自损（停表 + idle 槽置空 + 贴新角色静态图），
    _anim_ready() 装好后照旧起播。
    能真失败：把 _anim_start_async 里那三行自损删掉，第一条断言红（旧角色的 idle 集还挂在
    anim 上，_play_idle 会拿它起播）。
    """
    from helpers_roles import install_big_frame_role, rewrite_big_frames, drain_anim_slices
    win = pet
    win.apply_role("inv1")
    win._play_idle()
    old_frames = list(win.anim._sets.get("idle") or [])
    assert old_frames, "前提不成立：没有旧角色的 idle 帧集"
    rid, paths = install_big_frame_role(win, win.role_lib._dir, n=8, rid="bigwin8", prefix="big_w8")
    rewrite_big_frames(paths, seed=41)
    win._clear_frame_cache()
    win.apply_role(rid)                     # 内部走 _reload_sprites → 分片
    assert win._anim_pending is not None, "前提不成立：没进异步分支，本用例没有区分力"
    assert win.anim._sets.get("idle") == [], \
        "窗口期 idle 槽还挂着旧角色的帧集（_play_idle 会拿它起播）"
    assert win.anim._timer.isActive() is False, "窗口期帧定时器还在跑：旧角色还在动"
    drain_anim_slices(win)
    idle = win.anim._sets.get("idle") or []
    assert len(idle) == len(paths), "分片收尾后新角色帧集不齐：%d/%d" % (len(idle), len(paths))
    assert win.anim._frames is win.anim._sets.get("idle"), "新角色帧集没起播"
