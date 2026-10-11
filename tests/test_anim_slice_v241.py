# -*- coding: utf-8 -*-
"""v2.4.1 分片解码状态机回归（找茬 M3/M4）。

背景：分片路径（_anim_start_async / _anim_chunk_step / _anim_pending / _FRAME_SLICE_MS）
此前**一次都没跑过**——现成的测试角色 idle 只有 1 帧，整批永远落在首片里。M3 的漏
（同步臂先跑完却不作废在途分片 → 那颗 QTimer 到点把整批 jobs 再走一遍、再 add_set、
_anim_ready 因 _anim_pending_restart 仍为 True 而强制 _play_idle，帧动画从第 0 帧重跳）
就是这么漏出来的。

这里的用例一律用"**冷缓存 + ≥8 张 512px 噪声帧**"把分片真的跑起来：
  M4  冷缓存 → (a) 确实分片 (b) 跑完帧集齐、指纹收敛 (c) 每片解了几张 ≤ 预算÷单位成本+1
      (d) 不多起播
  M3  分片在途时同步臂先跑完 → 在途批必须被作废（pump 期间零 add_set、零 anim.play）

v2.5.2（公开 CI 红门禁）：本模块的判据原先全都建立在"真实解码耗时能撞破 12ms 预算"这条
**机器相关**的假定上——开发机（慢）全绿，windows-latest（快）上 CI #46~#50 连续五红：
  · test_cold_big_frame_set_is_sliced_and_completes 的 (c) 是"最慢一步 < 总时长"的**自指
    墙钟**判据，两边都由同一台机器测出来，机器一快必然假红（CI 实测 `9.339 < 9.339`）；
  · test_async_window_does_not_play_the_previous_roles_frames 的前提"进了异步分支"在快机器
    上不成立——整批帧同步解完，用例自己承认"没有区分力"。
现在一律**注入每单位固定变慢的 spy**（_install_slow_frame_decode：每次取帧固定 5ms），
于是 帧数 × 5ms ≫ 12ms 预算 ⇒ 分片/异步分支**必然**发生（与机器快慢无关，真解码再快也
只是让单位成本更接近 5ms），判据同时换成**结构性计数**：每片解了几张、至少切几片、
异步批取帧总数守恒、真解码张数守恒。阈值一律由"预算 ÷ 单位成本"推出来，没有手调常数。
"""
import math
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


# ---------------- v2.5.2：把"机器快慢"从分片判据里摘出去 ----------------
# 每次取帧注入固定 unit_ms 成本 ⇒ **每单位成本 ≥ unit_ms**（真解码再快也快不过下界）。
# 于是"整批活能不能落进一个 12ms 切片"由**结构**（帧数 × unit_ms）决定，而不是由机器决定：
# 帧数 × 5ms ≫ 12ms ⇒ 首片必然解不完 ⇒ 分片/异步分支必然发生，任何机器上都一样。
_SLOW_FRAME_MS = 5.0


def _spin_ms(ms):
    """忙等固定毫秒。不用 time.sleep：Windows 上 sleep 粒度 ~15.6ms，"每片几张"会失真。"""
    t0 = time.perf_counter()
    while (time.perf_counter() - t0) * 1000.0 < ms:
        pass


def _install_slow_frame_decode(win, monkeypatch, unit_ms=_SLOW_FRAME_MS):
    """给**每一次** _frame_pix 调用注入固定毫秒成本 → 单位成本 ≥ unit_ms（与机器无关）。

    返回 calls："n" = 本用例里取了几次帧 = 消耗了几个"单位"。
    **缓存命中也照样计费**是有意的：分片循环的预算检查只看墙钟，命中缓存的帧几乎不花时间
    ——机器一快，异步批就会"一次走完"（CI #50 的 `9.339 < 9.339` 正是这一步）。把"取一帧"
    本身定成固定成本，预算断点才由**单位数**决定，而不是由机器决定。
    """
    real = win._frame_pix
    calls = {"n": 0}

    def slow(path, *a, **k):
        calls["n"] += 1
        _spin_ms(unit_ms)
        return real(path, *a, **k)

    monkeypatch.setattr(win, "_frame_pix", slow)
    return calls


def _count_real_decodes(win, monkeypatch):
    """统计**真解码**过的帧数：_cap_role_pix 只在 _frame_pix 缓存未命中时被调用。

    用来反证分片不是"只忙等、没解帧"的空转（冷缓存下必须每张都真解），顺带钉住
    "同一张帧在同步臂与异步臂之间不重复解码"（缓存跨臂生效）。
    """
    real = win._cap_role_pix
    seen = {"n": 0}

    def spy(pix, path=None, *a, **k):
        seen["n"] += 1
        return real(pix, path, *a, **k)

    monkeypatch.setattr(win, "_cap_role_pix", spy)
    return seen


def _per_step_cap(unit_ms=_SLOW_FRAME_MS):
    """每片**单位数**上界 = ceil(预算 ÷ 单位成本) + 1。

    推导：循环是"取一帧 → 追加 → 检查已耗时 ≥ 预算"，每单位成本 ≥ unit_ms ⇒ 第 k 次检查时
    已耗时 ≥ k×unit_ms ⇒ 最迟第 ceil(预算/单位成本) 个单位就跳出。+1 是给收尾那一步顺带
    多取一次素材留的余量（旧口径"预算 + 一帧 + 25ms"的墙钟余量在确定性注入下可以收紧，
    判据因此**更强**：上界直接由预算与注入成本推出来，机器再快也松不动它）。
    """
    return int(math.ceil(main._FRAME_SLICE_MS / float(unit_ms))) + 1


def _drain_counting(win, calls, limit=400):
    """同步驱动在途分片 → 返回**每一步消耗的单位数**（这一片解了几张，不是花了多少毫秒）。"""
    per_step = []
    guard = 0
    while getattr(win, "_anim_pending", None) is not None and guard < limit:
        guard += 1
        before = calls["n"]
        win._anim_chunk_step()
        per_step.append(calls["n"] - before)
    QApplication.processEvents()      # 让残留的 0-timer 也到点（此时应当什么都不做）
    return per_step


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
    """M4（找茬）：冷缓存 + 10 张 512px 帧必须走分片，且 (a)~(d) 四条同时成立。

    v2.5.2（公开 CI 红门禁）：(c) 原本是"最慢一步 < 总时长"的**自指墙钟**判据——两边都由
    同一台机器测出来，机器一快必然假红（CI #50 实测 `9.339 < 9.339`）。现在判据一律是
    "这一片解了几张"：注入每单位固定 5ms 的慢速解码后，单位成本 ≥ 5ms、预算 12ms ⇒ 每片
    至多 ceil(12/5)+1 = 4 张，10 张 ⇒ 至少 3 片。这两个数字只由**结构**（预算 ÷ 注入成本）
    决定，与机器快慢无关；更快的机器只会让单位成本更贴近 5ms，上界方向不变。
    """
    win = pet
    rid, paths = _prep_big_role(win, 10, "bigslice10", "big_s10")
    total_units = len(paths)
    # 冷缓存：原地重写 + 推 mtime（Qt 内部 pixmap 缓存失效）+ 清解码缓存
    _make_frames_cold(win, paths, seed=12)
    assert win._anim_pending is None, "前提不成立：进用例时还有在途分片"
    plays = _count_plays(monkeypatch)
    decodes = _count_real_decodes(win, monkeypatch)
    calls = _install_slow_frame_decode(win, monkeypatch)
    t0 = time.perf_counter()
    win._wire_anim_sets()
    first_ms = (time.perf_counter() - t0) * 1000.0
    sync_units = calls["n"]
    # (a) 真的分片了（不是"首片把整批解完"）——前提由注入成本**构造性**保证，不看机器脸色
    assert win._anim_pending is not None, (
        "(a) 首片就把 %d 帧全解完了：每单位注入 %.1fms（整批合计 %.1fms、预算 %.1fms）——"
        "分片路径没被覆盖到（首片同步段 %.1fms、取了 %d 次帧）"
        % (total_units, _SLOW_FRAME_MS, total_units * _SLOW_FRAME_MS, main._FRAME_SLICE_MS,
           first_ms, sync_units))
    per_step = _drain_counting(win, calls)
    assert win._anim_pending is None, "分片没跑完（drain 上限到了？）"
    # (b) 帧集齐 + 指纹收敛
    idle = win.anim._sets.get("idle") or []
    assert len(idle) == len(paths), "(b) 分片跑完帧集不齐：%d/%d" % (len(idle), len(paths))
    assert win._wire_key == win._wire_anim_key(), "(b) 指纹没收敛到当前状态"
    # (c) 结构性判据（取代旧的自指墙钟）：每片**解了几张**
    cap = _per_step_cap()
    assert per_step, "(c) 一片都没跑：分片状态机没被驱动"
    assert max(per_step) <= cap, (
        "(c) 有一片解了 %d 张（上界 %d = ceil(预算 %.1fms ÷ 单位成本 %.1fms) + 1）："
        "要么分片循环的预算检查没生效、要么注入的解码 spy 没生效（逐片 %r）"
        % (max(per_step), cap, main._FRAME_SLICE_MS, _SLOW_FRAME_MS, per_step))
    assert max(per_step) < sum(per_step),         "(c) 最慢一片就是全部（%d 张）：根本没分摊开" % max(per_step)
    min_steps = int(math.ceil(total_units / float(cap)))
    assert len(per_step) >= min_steps, (
        "(c) 只切了 %d 片：%d 张 ÷ 每片至多 %d 张 ⇒ 至少 %d 片（逐片 %r）"
        % (len(per_step), total_units, cap, min_steps, per_step))
    assert sum(per_step) == total_units, (
        "(c) 异步批总共取了 %d 次帧，应当恰好 %d 次（每帧一次）" % (sum(per_step), total_units))
    # (c2) 首片**同步段**同样只允许吃掉有界的单位数（旧版这里是"首片耗时 ≤ 预算"的墙钟判据）
    assert sync_units <= cap, (
        "(c2) 首片同步段取了 %d 次帧（> %d）：首片不是分片前缀，而是想一口吃下整批"
        % (sync_units, cap))
    # (c3) 真的解了码：10 张冷帧各解一次，且同步臂/异步臂之间不重复解（不是"只忙等"的空转）
    assert decodes["n"] == total_units, (
        "(c3) 真解码 %d 张，应为 %d 张（每张恰好一次：首片解一部分 + 异步批解剩下的）"
        % (decodes["n"], total_units))
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

    v2.5.2（公开 CI 红门禁）：前提"进了异步分支"以前同样靠真实解码耗时去撞预算——CI 上机器快、
    8 帧在一个切片里同步解完，用例自己承认"没进异步分支，没有区分力"而红（#46~#50）。现在先
    注入每单位固定 5ms 的慢速解码：8 张 × 5ms = 40ms ≫ 12ms 预算 ⇒ 首片必然解不完 ⇒ 异步分支
    必然发生；窗口期那三条自损断言因此**每次都有区分力**，收尾分片也顺带按同一套计数口径钉住。
    """
    from helpers_roles import install_big_frame_role, rewrite_big_frames
    win = pet
    win.apply_role("inv1")
    win._play_idle()
    old_frames = list(win.anim._sets.get("idle") or [])
    assert old_frames, "前提不成立：没有旧角色的 idle 帧集"
    rid, paths = install_big_frame_role(win, win.role_lib._dir, n=8, rid="bigwin8", prefix="big_w8")
    rewrite_big_frames(paths, seed=41)
    win._clear_frame_cache()
    calls = _install_slow_frame_decode(win, monkeypatch)   # ← 前提从此由**结构**保证
    win.apply_role(rid)                     # 内部走 _reload_sprites → 分片
    assert win._anim_pending is not None, (
        "前提不成立：没进异步分支（每单位 %.1fms × %d 张 = %.1fms，预算 %.1fms）"
        % (_SLOW_FRAME_MS, len(paths), len(paths) * _SLOW_FRAME_MS, main._FRAME_SLICE_MS))
    assert win.anim._sets.get("idle") == [], \
        "窗口期 idle 槽还挂着旧角色的帧集（_play_idle 会拿它起播）"
    assert win.anim._timer.isActive() is False, "窗口期帧定时器还在跑：旧角色还在动"
    per_step = _drain_counting(win, calls)
    assert win._anim_pending is None, "分片没跑完（drain 上限到了？）"
    idle = win.anim._sets.get("idle") or []
    assert len(idle) == len(paths), "分片收尾后新角色帧集不齐：%d/%d" % (len(idle), len(paths))
    assert win.anim._frames is win.anim._sets.get("idle"), "新角色帧集没起播"
    # v2.5.2：收尾分片仍要按同一套**结构性计数**分片（与 M4 的 (c) 同一口径，不再看墙钟）
    cap = _per_step_cap()
    assert per_step and max(per_step) <= cap, (
        "收尾分片逐片解了 %r 张（上界 %d = ceil(预算 %.1fms ÷ 单位成本 %.1fms) + 1）："
        "要么分片循环的预算检查没生效、要么注入的解码 spy 没生效"
        % (per_step, cap, main._FRAME_SLICE_MS, _SLOW_FRAME_MS))
    assert sum(per_step) == len(paths), (
        "异步批总共取了 %d 次帧，应当恰好 %d 次（每帧一次）" % (sum(per_step), len(paths)))
