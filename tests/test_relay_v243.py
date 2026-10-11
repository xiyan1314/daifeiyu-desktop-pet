# -*- coding: utf-8 -*-
"""v2.4.3（第三轮找茬）启动接力遗留 + 一行兼容修复的回归。

本模块钉七件事，每条都能真失败（括号里是"把修复拿掉"的变异）：

  1. 停止配音不再用 SND_PURGE（改回 `PlaySound(None, SND_PURGE)` → 红）；
  2. 撒钱帧集预载是**分片**的，且与一次性 load_frame_set 逐张相同（改回一次解完 → 红）；
  3. 预载中途被消费点抢跑时在途批次作废（删掉 _fx_celebrate 里的作废 → 红）；
  4. 帧集接力支真的按时间预算分片（去掉 _load_frame_sets_slice 里的预算判断 → 红）；
  5. 自定义角色不再解默认四组帧集，但 petpet 照解、摸头照播（_startup_frame_sets 去掉
     角色判断 → 红）；
  6. 接力链抛错后收口（去掉 _startup_assets_step 的 finally 置位 → 红）；
  7. 状态图分片"零推进"时自锁清 pending（去掉自锁 → 链永不收敛 → 红）。

与 test_startup_defer_v242.py 的分工：那份钉"默认角色的延迟装载语义不变"，本份钉
"v2.4.3 之后新增的角色口径 / 分片预算 / 异常收口 / 一行兼容修复"。
"""
import ast
import inspect
import json
import os
import sys
import textwrap
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import 桌宠 as main  # noqa: E402
import pet_anim  # noqa: E402
from PySide6.QtGui import QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


# ---------------- 夹具 ----------------

@pytest.fixture
def pet(tmp_path):
    """真 PetWindow（默认角色）+ 临时数据目录；不驱动接力装载（用例自己决定）。"""
    import pet_log

    snap = _snapshot()
    _point_data_dir(tmp_path)
    QApplication.instance() or QApplication([])
    win = main.PetWindow()
    from helpers_roles import quiet_pet_timers, shutdown_pet
    quiet_pet_timers(win)
    yield win
    shutdown_pet(win)
    _restore(snap)


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
    """造一个自定义角色（真 PNG）+ roles.json（active 指向它）+ config.json（role=它）。

    必须**在 PetWindow() 之前**落盘：本组用例测的就是"构造期就已经是自定义角色"。
    """
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


# ---------------- 1. 停止配音：不再用已废弃的 SND_PURGE ----------------

def test_stop_voice_clip_uses_modern_stop_flags(pet, monkeypatch):
    """停止异步播放必须用 PlaySound(NULL, 0)：SND_PURGE 在 Win10/11 上是 no-op。

    能真失败：把调用改回 `winsound.PlaySound(None, winsound.SND_PURGE)` →
    下面记录到的 flags 立刻从 0 变成 64，两条断言同时红。
    """
    calls = []

    class _FakeWinsound:
        SND_PURGE = 64
        SND_ASYNC = 1
        SND_FILENAME = 131072
        SND_NODEFAULT = 2
        SND_NOWAIT = 8192

        @staticmethod
        def PlaySound(sound, flags):
            calls.append((sound, flags))

    monkeypatch.setitem(sys.modules, "winsound", _FakeWinsound)
    pet._stop_voice_clip()
    assert calls == [(None, 0)], (
        "停止调用的参数不对：%r（应为 (None, 0)——pszSound=NULL 即停播，flags=0；"
        "SND_PURGE 已废弃，现代 Windows 上是 no-op）" % (calls,))
    flags = calls[0][1]
    assert not (flags & _FakeWinsound.SND_PURGE), "仍在用已废弃的 SND_PURGE"

    # 结构判据走 AST（不抠文本）：注释里可以解释"为什么不用 SND_PURGE"，
    # 但只要代码里还**访问**这个常量就红。
    src = textwrap.dedent(inspect.getsource(main.PetWindow._stop_voice_clip))
    tree = ast.parse(src)
    ps_calls = [n for n in ast.walk(tree)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "PlaySound"]
    assert len(ps_calls) == 1, "PlaySound 调用数不对：%d" % len(ps_calls)
    assert [ast.literal_eval(a) for a in ps_calls[0].args] == [None, 0],         "停止调用的实参不是 (None, 0)"
    _attrs = [n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)]
    assert "SND_PURGE" not in _attrs, "源码里仍在使用已废弃的 SND_PURGE"


def test_stop_voice_clip_still_stops_the_media_player(pet):
    """真 winsound 路径不许影响第二条链路：QMediaPlayer 预览必须照停（且不抛）。"""
    class _Player:
        def __init__(self):
            self.stopped = 0

        def stop(self):
            self.stopped += 1

    pet._preview_player = _Player()
    pet._stop_voice_clip()  # 真 winsound.PlaySound(None, 0)：无声卡也是 no-op，不抛
    assert pet._preview_player.stopped == 1, "QMediaPlayer 链路没被停"
    pet._preview_player = None


# ---------------- 2/3. 撒钱帧集：分片预载 ----------------

def _money_decode_spy(monkeypatch, per_frame_ms=0.5):
    """记录并**拖慢** money 帧解码：本机 Qt 缓存命中时单帧 <0.1ms，整批会落进一片，
    分片判据就测不出来（与 helpers_roles.rewrite_big_frames 的"让分片确定发生"同思路）。
    0.5ms/帧 ≈ 真实冷解码量级（86 帧 ≈50~100ms）。"""
    real = main.QPixmap
    seen = []

    def counting(*a, **k):
        if a and isinstance(a[0], str) and "money_f" in a[0]:
            seen.append(a[0])
            t0 = time.perf_counter()
            while (time.perf_counter() - t0) * 1000.0 < per_frame_ms:
                pass
        return real(*a, **k)

    monkeypatch.setattr(main, "QPixmap", counting, raising=False)
    return seen


def test_money_preload_is_sliced_and_matches_eager_load(pet, monkeypatch):
    """撒钱帧集预载必须分片，且素材与一次性全解**逐张相同**。

    v2.4.4（C-2）：分片判据是可数的量——**每片解了几帧**（用例注入 0.5ms/帧的人为成本），
    不再是"单片 < 120ms"那条墙钟（本机实测只剩约 17ms 余量，负载一抖就假红）。

    能真失败：把 _preload_money_fx 改回"一次 load_frame_set(.., 86)" → 入口调用后
    `pet._fx_money` 直接是 86 帧、`seen` 里 86 条 → 前两条断言红；
    把 _money_preload_step 的预算判断拿掉 → 一片解完 86 帧 → 每片帧数上界红。
    """
    per_frame_ms = 0.5
    seen = _money_decode_spy(monkeypatch, per_frame_ms=per_frame_ms)
    pet._fx_money = []
    pet._money_preload = None
    pet._preload_money_fx()
    assert pet._fx_money == [], "预载入口就把整批解完了（不是分片）"
    assert seen == [], "入口就解了 %d 帧" % len(seen)
    assert pet._money_preload is not None, "入口没登记在途状态"

    per_step, steps = [], []
    guard = 0
    while pet._money_preload is not None and guard < 500:
        guard += 1
        before = len(seen)
        t0 = time.perf_counter()
        pet._money_preload_step()
        per_step.append(len(seen) - before)
        steps.append((time.perf_counter() - t0) * 1000.0)

    assert len(seen) == main._MONEY_FRAME_COUNT, "预载共解了 %d 帧" % len(seen)
    assert len(per_step) >= 2,         "只用了 %d 片：不是分片（%d 帧都在一片里，单片 %.1fms）" % (
            len(per_step), len(seen), max(steps) if steps else -1)
    # v2.4.4（C-2）：主判据是**每片解了几帧**（确定性、负载无关），不再卡墙钟。
    # 用例自己注入 0.5ms/帧的人为成本 → 预算 12ms 的一片最多 ceil(12/0.5)+2 = 26 帧；
    # 负载只会让同一个墙钟预算**更早**用光（每片更少），所以"每片 ≤ N"在并发负载下不会
    # 假红。旧口径"单片 < 120ms"在本机实测只剩约 17ms 余量（审查记过的那次抖动），
    # 一片 86 帧的退化会直接突破这条上界（M-R10/M-V6 的变异验证就是它）。
    # C-2（质量审查 M1）：这条上界是**从被测预算算出来的**，所以预算本身由
    # test_slice_budget_is_pinned_so_the_bounds_cannot_be_loosened 钉住（12.0）；
    # 否则"预算放宽 8 倍"会让上界跟着放宽、判据自己吸收掉退化。
    per_step_limit = int(main._FRAME_SLICE_MS / per_frame_ms) + 2
    assert max(per_step) <= per_step_limit,         "单片解了 %d 帧（预算 %.0fms ÷ 每帧 %.1fms 的上界是 %d 帧）：不是分片" % (
            max(per_step), main._FRAME_SLICE_MS, per_frame_ms, per_step_limit)

    want = pet_anim.load_frame_set(pet._fx_money_dir, main._MONEY_FRAME_PREFIX,
                                   main._MONEY_FRAME_COUNT)
    assert len(pet._fx_money) == len(want) == main._MONEY_FRAME_COUNT
    assert all(a.toImage() == b.toImage() for a, b in zip(pet._fx_money, want)),         "分片预载的素材与一次性全解不一致"


def test_slice_budget_is_pinned_so_the_bounds_cannot_be_loosened():
    """C-2（v2.4.4 质量审查 M1）：切片预算必须钉死——C-2 的每片上界是从它自己算出来的。

    `test_money_preload_is_sliced_and_matches_eager_load` 与
    `test_startup_task_is_chunked_not_one_shot` 的 per_step_limit 都是
    "int(_FRAME_SLICE_MS / 每单位成本) + 常数"：预算一放宽，上界跟着放宽（审查实测
    _FRAME_SLICE_MS 12→100（8×）时两条用例**全绿**）——"分片变粗"这类退化会被判据自己
    吸收掉。这里把预算钉成常量：要动预算就必须**同时**动这一条与那两条判据，而不是静默地
    把判据一起放宽（见 M-V8：把 12.0 改成 100.0 必须被这条抓住）。

    能真失败：把 桌宠.py 的 _FRAME_SLICE_MS 改成 100.0 → 第一条断言红。
    """
    assert main._FRAME_SLICE_MS == 12.0,         "切片预算被放宽了（C-2 的每片上界是从它算出来的，判据会跟着放宽）：%r" % (
            main._FRAME_SLICE_MS,)
    assert main._EXPORT_SLICE_MS == 12.0,         "导出切片预算被改了：%r（test_compat_v242_fixes 里那句 '与 _EXPORT_SLICE_MS 同值' 也跟着失效）" % (
            main._EXPORT_SLICE_MS,)


def test_money_preload_is_sliced_even_with_a_zero_budget(pet, monkeypatch):
    """单片预算口径：预算 0 也必须**至少解一帧**（否则链永远推不动）。"""
    _money_decode_spy(monkeypatch, per_frame_ms=0.0)
    pet._fx_money = []
    pet._money_preload = None
    monkeypatch.setattr(main, "_FRAME_SLICE_MS", 0.0, raising=False)
    pet._preload_money_fx()
    pet._money_preload_step()
    _st = pet._money_preload
    assert _st is not None and _st["k"] == 1, "预算 0 时一帧都没解（链会卡死）：%r" % (_st,)


def test_money_preload_defers_to_the_consumer(pet):
    """预载中途用户真撒钱了（_fx_celebrate 同步解整批）→ 在途批次作废、不留半截帧集。"""
    pet._fx_money = []
    pet._money_preload = None
    pet._preload_money_fx()
    pet._money_preload_step()
    assert pet._money_preload is not None, "第一片就解完了？用例失去区分力"
    pet._fx_celebrate()
    assert len(pet._fx_money) == main._MONEY_FRAME_COUNT, "消费点没把整批解出来"
    assert pet._money_preload is None, "消费点抢跑后在途批次没作废（会再解一遍）"


# ---------------- 4. 帧集接力支的时间预算 ----------------

def test_frame_relay_slice_is_exactly_one_group_per_round(pet, monkeypatch):
    """帧集支一轮**只解一组**：组是原子单位，合并会把单轮最坏从"一组"抬到"预算+一组"。

    判据（都能真失败）：
      · 三组都很便宜时也不许并进同一轮（改成"预算内尽量多解"→ 三组同一轮 → 红）；
      · 一组本身超过预算时也必须**至少解一组**（写成"未超预算才解下一组"而漏掉首组 →
        一组都没解 → 红）。后者保证 pending 一定推进（不会卡死）。
    """
    cheap = []
    monkeypatch.setattr(pet, "_load_default_frame_set", lambda name: cheap.append(name) or [])
    pet._load_frame_sets_slice(["idle_full", "eat", "petpet"])
    assert cheap == ["idle_full"], (
        "单轮解了 %d 组：粒度退化成合并批次（单轮最坏从一组抬到预算+一组）%r"
        % (len(cheap), cheap))

    slow = []
    real = main.PetWindow._load_default_frame_set      # 类上的原方法（实例已被打补丁）

    def slow_load(name):
        t0 = time.perf_counter()
        while (time.perf_counter() - t0) * 1000.0 < 20.0:
            pass  # 模拟"一组 20ms"（真实一组实测 5~16ms）
        slow.append(name)
        return real(pet, name)

    monkeypatch.setattr(pet, "_load_default_frame_set", slow_load)
    pet._load_frame_sets_slice(["idle_full", "eat", "petpet"])
    assert slow == ["idle_full"], (
        "超预算时解了 %d 组（应恰好一组、且至少一组保证推进）：%r" % (len(slow), slow))


def test_default_relay_keeps_one_phase_per_round(pet, monkeypatch):
    """端到端：默认角色接力**每轮恰好一个阶段**（帧集 1 组 / 状态图 1 片）。

    判据是**结构性**的（v2.4.3 质量审查 M3 改法）：直接数每一轮里两个分支各被调用了几次，
    不再拿墙钟阈值卡——那个 60ms 在影子副本（冷缓存 + 机器上还有别的会话跑 pytest）里
    实测抖到 109.9ms，把"环境"记成了"回归"（_mutate_lib.py 的基线重跑就是为它加的）。
    每轮计数是确定的：一轮里 (帧集次数 + 状态图片数) 恒 ≤ 1，且总轮数 ≥ 4。

    能真失败：让帧集支做完不 return、直接落到状态图支（= 合并阶段）→ 某一轮计数变成 2 → 红；
    或把"一组一轮"改成"预算内尽量多解"→ 帧集次数 > 1 → 红。
    """
    FRAME_SETS = ("idle", "idle_full", "eat", "petpet")
    rounds = []
    real_fs = pet._load_default_frame_set
    real_state = pet._build_state_pix_slice

    def counted_fs(name):
        rounds[-1]["frame_sets"].append(name)
        return real_fs(name)

    def counted_state():
        rounds[-1]["state_slices"] += 1
        return real_state()

    monkeypatch.setattr(pet, "_load_default_frame_set", counted_fs)
    monkeypatch.setattr(pet, "_build_state_pix_slice", counted_state)
    pending_at_start = list(pet._startup_frames_pending())
    guard = 0
    while not pet._startup_assets_done and guard < 40:
        guard += 1
        rounds.append({"frame_sets": [], "state_slices": 0})
        t0 = time.perf_counter()
        pet._startup_assets_step()
        rounds[-1]["ms"] = (time.perf_counter() - t0) * 1000.0
    assert pet._startup_assets_done, "接力没收敛（跑了 %d 轮）" % len(rounds)
    per_round = [(len(r["frame_sets"]), r["state_slices"]) for r in rounds]
    bad = [(i, p) for i, p in enumerate(per_round) if sum(p) > 1]
    assert not bad, ("这些轮里一个阶段都没守住（(帧集数, 状态图片数) 必须至多一项为 1）：%r"
                     "（全部轮次 %r）" % (bad, per_round))
    assert len(rounds) >= 4, ("接力只剩 %d 轮：帧集支与状态图支被并进了同一轮（%r）"
                              % (len(rounds), per_round))
    decoded = [n for r in rounds for n in r["frame_sets"]]
    assert decoded == pending_at_start, \
        "帧集支解的组不对（开工时待解 %r，实际解了 %r——每组恰好一轮）" % (
            pending_at_start, decoded)
    # 只留一条"离谱"兜底上界（真阈值交给可复跑的探针，见 _dev/probe_money_preload_gap.py）
    worst = max(r["ms"] for r in rounds[1:]) if len(rounds) > 1 else 0.0
    assert worst < 500.0, "非首轮单步占了 %.1f ms（离谱，接力退化回一次性装载）：%r" % (
        worst, [round(r["ms"], 1) for r in rounds])


# ---------------- 5. 自定义角色：不解默认素材，但 petpet 照解 ----------------

def test_custom_role_skips_default_frame_sets_but_keeps_petpet(tmp_path, monkeypatch):
    """自定义角色一个默认素材都用不到（帧集走 forms[i].animations），只该解 petpet。

    能真失败：把 _startup_frame_sets 改成无条件返回四组（或把构造期那行
    _load_default_frame_set("idle") 的角色判断拿掉）→ 解码清单里立刻出现
    idle_f_/idle_full_f_/eat_f_ → 红。
    """
    from helpers_roles import drain_startup_assets, shutdown_pet

    rid = _mk_custom_role(tmp_path)
    snap = _snapshot()
    _point_data_dir(tmp_path)
    QApplication.instance() or QApplication([])
    seen = _decode_spy(monkeypatch)
    win = None
    try:
        win = main.PetWindow()
        assert win._custom_role and win.cfg.get("role") == rid, "夹具没让窗口进自定义角色路径"
        banned = _default_frame_names()
        at_ctor = set(_names(seen))
        assert not (at_ctor & banned),             "构造期就解了默认素材：%r（自定义角色一个都用不到）" % sorted(at_ctor & banned)
        assert win._idle_frames == [] and win._frames_loaded.get("idle") is None,             "自定义角色不该在构造期解 idle 帧集"

        seen.clear()
        assert drain_startup_assets(win), "接力装载没跑完"
        relayed = set(_names(seen))
        assert not (relayed & banned),             "接力装载仍解了默认素材：%r" % sorted(relayed & banned)
        assert {"petpet_f%02d.png" % i for i in range(10)} <= relayed,             "petpet 没被接力解出来（摸头会静默失效）：%r" % sorted(relayed)
        assert win._startup_assets_done
        assert win._frames_loaded.get("petpet") and len(win._fx_petpet) == 10
        assert not win._frames_loaded.get("idle_full") and not win._frames_loaded.get("eat")

        # 摸头仍然正常：petpet 帧集已就位 → 真的播起来
        win.busy = False
        win._petting = False
        win._press_dist = 0
        win._start_petting()
        assert win._petting and win._fx_petpet_on, "自定义角色摸头没播起来"
        assert len(win._fx_petpet) == 10
        win._end_petting()
    finally:
        if win is not None:
            shutdown_pet(win)
        _restore(snap)


def test_custom_role_switching_back_to_default_loads_idle(tmp_path, monkeypatch):
    """自定义角色启动 → 切回默认角色：idle 帧集必须由**同步兜底**补齐（延迟装载不失效）。

    这条钉的是"构造期对自定义角色跳过 idle"的安全边界：跳过之后切回默认角色，靠
    _play_idle → _ensure_default_frames(("idle",)) 就地补，绝不能留下"该有却没有"的空帧集。

    能真失败：删掉 _play_idle 里那行 _ensure_default_frames(...) → 切回后 _idle_frames 仍空、
    has_frames 仍是 False、idle 槽是空集 → 三条断言全红。
    """
    from helpers_roles import shutdown_pet

    _mk_custom_role(tmp_path)
    snap = _snapshot()
    _point_data_dir(tmp_path)
    QApplication.instance() or QApplication([])
    win = None
    try:
        win = main.PetWindow()
        assert win._custom_role and win._idle_frames == [], "夹具前提：自定义角色启动且没解 idle"
        win.apply_role("")
        assert not win._custom_role, "没切回默认角色"
        assert len(win._idle_frames) == 10 and win._frames_loaded.get("idle"), \
            "切回默认角色后 idle 帧集没被同步兜底补齐（切角色会静默变静态图）"
        assert win.has_frames and len(win.anim._sets.get("idle") or []) == 10, \
            "切回默认角色后 idle 槽不是 10 帧：%r" % (len(win.anim._sets.get("idle") or []),)
    finally:
        if win is not None:
            shutdown_pet(win)
        _restore(snap)


def test_default_role_still_relays_all_four_sets(pet):
    """反向对照：默认角色口径逐位不变——四组全解（别把角色判断写反）。"""
    from helpers_roles import drain_startup_assets
    assert pet._startup_frame_sets() == ("idle", "idle_full", "eat", "petpet")
    assert drain_startup_assets(pet)
    assert all(pet._frames_loaded.get(k) for k in ("idle", "idle_full", "eat", "petpet"))


# ---------------- 5b. 复审 M3：自定义角色首喂不许在前台补默认帧集 ----------------

def test_custom_role_first_feed_does_not_decode_default_sets(tmp_path, monkeypatch):
    """自定义角色首喂：**不许**同步解默认三组帧，且吃帧仍能播（走角色自己的动画表）。

    复审实测：feed() 此前无条件调 _ensure_default_frames()（_play_idle 早就有
    not _custom_role 守卫，feed 没有）→ 首次投喂同步解 idle 20.12 / idle_full 18.79 /
    eat 17.20 共 62.07ms，而 anim._sets["eat"] 仍是空集（自定义角色的吃帧走
    forms[i].animations）——三组帧一张都不会被消费，等于把成本从"启动后台接力"
    搬到了"首次交互前台"。

    能真失败：把 feed() 的 not self._custom_role 守卫拿掉 → 首次 feed 的同步解码清单里
    立刻出现 idle_f_/idle_full_f_/eat_f_ → 第一条断言红。
    """
    from helpers_roles import drain_startup_assets, shutdown_pet

    _mk_custom_role(tmp_path, animations=("idle", "eat"))
    snap = _snapshot()
    _point_data_dir(tmp_path)
    QApplication.instance() or QApplication([])
    win = None
    try:
        win = main.PetWindow()
        assert win._custom_role and drain_startup_assets(win), "夹具没让窗口进自定义角色路径"
        win.busy = False
        seen = _decode_spy(monkeypatch)
        t0 = time.perf_counter()
        win.feed("小鱼干")
        main_ms = (time.perf_counter() - t0) * 1000.0
        banned = _default_frame_names()
        hit = sorted(set(_names(seen)) & banned)
        assert hit == [], ("首喂在前台同步解了默认素材（自定义角色一张都用不到）：%r"
                           "（feed 同步占了 %.1fms）" % (hit, main_ms))
        assert win.busy is True, "喂食没进入吃东西状态"
        # 吃帧仍能播：走角色自己的 forms[i].animations，而不是默认 eat 帧集
        assert win.anim._sets.get("eat"), "自定义角色的吃帧没注册进 anim._sets"
        assert not win._frames_loaded.get("eat"), "默认 eat 帧集不该被动过"
    finally:
        if win is not None:
            shutdown_pet(win)
        _restore(snap)


# ---------------- 6. 接力链异常收口 ----------------

def test_relay_chain_closes_when_a_step_raises(pet, monkeypatch):
    """接力链抛错时 _gslot 只记日志、不重排 → 必须靠 finally 收口（置位而不是永久 False）。

    能真失败：去掉 _startup_assets_step 的 try/finally → 异常被 _gslot 吞掉后
    _startup_assets_done 仍是 False → 红。
    """
    pet._startup_assets_done = False

    def boom(_name):
        raise RuntimeError("boom: 坏素材")

    monkeypatch.setattr(pet, "_load_default_frame_set", boom)
    pet._gslot("startup_assets", pet._startup_assets_step)()   # 生产路径就是这么调的
    assert pet._startup_assets_done,         "链抛错后没收口：_startup_assets_done 恒 False（接力永不收敛）"
    # 再调一次也不该再抛/再排（幂等收口）
    pet._gslot("startup_assets", pet._startup_assets_step)()
    assert pet._startup_assets_done


# ---------------- 7. 状态图分片：零推进收口 ----------------

def test_state_slice_selflocks_on_zero_progress(pet):
    """pending 里全是不可建的名字时，本轮必须把 pending 收干净（否则 QTimer(0) 链永久自排）。

    v2.4.4（A-2）：收口方式从"整表清空"改成"判死不可建的名字并摘掉"（_state_pix_dead），
    本用例的断言口径不变（pending 必须空），另外钉住"判死的是哪个名字"。

    能真失败：去掉 _build_state_pix_slice 的零推进收口 → pending 原样留着 → 红。
    """
    pet._state_pix_pending = {"normal": {"__no_such_state__"}}
    pet._state_pix_dead = set()
    pet._build_state_pix_slice()
    assert pet._state_pix_pending == {},         "零推进时没收口：pending=%r（接力链会永久自排空转）" % (pet._state_pix_pending,)
    assert pet._state_pix_dead == {"__no_such_state__"},         "判死的名单不对（应当只有那个走不到的名字）：%r" % (pet._state_pix_dead,)


def test_relay_terminates_with_unbuildable_pending(pet):
    """端到端：pending 不可建时接力链也必须收敛（而不是无限自排）。"""
    pet._startup_assets_done = False
    pet._state_pix_pending = {"normal": {"__no_such_state__"}}
    pet._state_pix_dead = set()
    rounds = 0
    while not pet._startup_assets_done and rounds < 12:
        rounds += 1
        pet._startup_assets_step()
    assert pet._startup_assets_done,         "接力链没有收敛（跑了 %d 轮仍是 pending=%r）" % (rounds, pet._state_pix_pending)
    assert rounds < 12, "收敛用了 %d 轮：太慢" % rounds


def test_dead_alias_does_not_block_a_still_pending_name(pet):
    """L2（兼容审查）：别名的判死不许连坐到**还活着的名字**上——pending 才是唯一真源。

    `_state_pix_dead={angry}` + `pending={hiss}`（hiss 是 angry 的吃饱别名）时，
    `_state_pending("hiss")` 此前恒 False → 这一轮一个名字都不试 → 零推进收口也摘不掉
    hiss（它在 _STATE_MARK_MAP 名单里、又"没试过"，两条判死理由都不成立）→ 接力链每轮
    排一个 QTimer(0)，30 轮都不收敛（审查用真窗口实测）。

    能真失败：把别名判死加回 `_state_pending` → 循环跑满 30 轮仍不收敛 → 第一条断言红。
    """
    pet._state_pix_pending = {"normal": {"hiss"}, "full": {"hiss"}}
    pet._state_pix_dead = {"angry"}
    pet._startup_assets_done = False
    rounds = 0
    while not pet._startup_assets_done and rounds < 30:
        rounds += 1
        pet._startup_assets_step()
    assert pet._startup_assets_done,         "接力链没收敛（跑了 %d 轮仍是 pending=%r）：别名判死把还在 pending 的 hiss 一起挡住了" % (
            rounds, pet._state_pix_pending)
    assert rounds < 30, "收敛用了 %d 轮：太慢" % rounds


# ---------------- 8. v2.4.4（A-2）：零推进只判死"建不出来"的名字（不许整表清空） ----------------

def test_zero_progress_retires_only_the_unbuildable_names(pet):
    """pending 里混着"能建的"与"走不到的"：只能判死走不到的那个，剩下的不许一起丢。

    能真失败：把零推进收口改回"pending = {}"（= v2.4.3 那次收口）→
    第一条断言红（可建的名字被顺手丢了）；把"不在名单里的判死"这条拿掉 → 最后一轮
    pending 清不掉 → 第三条断言红。
    """
    pet._state_pix_pending = {"normal": {"__no_such_state__", "angry"}, "full": {"angry"}}
    pet._state_pix_dead = set()
    pet._build_state_pix_slice()
    assert pet.state_pix["normal"].get("angry") is not None,         "可建的名字被当成'走不到'一起丢了"
    assert pet._state_pix_dead == set(),         "这一轮有推进（建出了 angry），不该判死任何名字：%r" % (pet._state_pix_dead,)
    assert pet._state_pix_pending.get("normal") == {"__no_such_state__"}         and not pet._state_pix_pending.get("full"),         "pending 里应当只剩走不到的那个名字（angry 两个形态都已建）：%r" % (pet._state_pix_pending,)
    # 第二轮：剩下的全是走不到的 → 零推进 → 判死并摘掉（链要能收敛）
    pet._build_state_pix_slice()
    assert pet._state_pix_pending == {}, "走不到的名字没被摘掉：接力链会永久自排"
    assert pet._state_pix_dead == {"__no_such_state__"},         "判死的名单不对：%r" % (pet._state_pix_dead,)


def test_zero_progress_with_a_zero_budget_keeps_the_untried_names(pet):
    """预算为 0 时这一轮一张都没试到：pending 必须原样留着（旧口径整表清空 → 名字丢失）。

    这是"整表清空"真正会咬人的那种轮次：第一个状态就不是待建 → 预算检查立刻返回 →
    本轮零推进，但 pending 里的名字**一次都没试过**。修复前（v2.4.3）这里会 pending = {}，
    那个名字从此永久缺失（_ensure_state_pix 开头的单向门）。

    能真失败：把零推进收口改回"pending = {}" → 第一条断言红（angry 被整表清空带走）。
    """
    pet._state_pix_pending = {"normal": {"angry"}, "full": {"angry"}}
    pet._state_pix_dead = set()
    pet._build_state_pix_slice(budget_ms=0.0)     # 第一个状态就不是待建 → 立刻超预算返回
    assert pet._state_pix_dead == set(),         "这一轮一个名字都没试（零推进），不该判死任何名字：%r" % (pet._state_pix_dead,)
    assert pet._state_pending("angry"),         "预算 0 的一轮把还没试过的 angry 整表清空了（旧口径：该状态永久缺失）"
    # 下一轮（正常预算）必须真的把它补建出来
    pet._build_state_pix_slice()
    assert pet._state_pix("angry") is not None, "留下的名字没有在下一轮被补建"


def test_tried_but_unbuilt_names_are_retired_so_the_relay_converges(pet, monkeypatch):
    """试过却一张都没建出来（_ensure_state_pix 空转）时也要收口，否则链永久自排。

    能真失败：把"tried 里仍在 pending 的算死"这条拿掉 → pending 永远清不掉 → 两条断言红。
    """
    pet._state_pix_dead = set()
    monkeypatch.setattr(pet, "_ensure_state_pix", lambda state: None)   # 试了，但什么都没建
    pet._startup_assets_done = False
    rounds = 0
    while not pet._startup_assets_done and rounds < 20:
        rounds += 1
        pet._startup_assets_step()
    assert pet._startup_assets_done, "接力链没收敛：pending=%r" % (pet._state_pix_pending,)
    assert pet._state_pix_pending == {} and pet._state_pix_dead,         "试过且没建出来的名字没被判死：pending=%r dead=%r" % (
            pet._state_pix_pending, pet._state_pix_dead)


def test_state_pix_recovers_after_one_build_exception(pet, monkeypatch):
    """**A-2 验收核心**：建状态图抛过一次之后，恢复真方法再调 _state_pix(angry) 仍能补建。

    修复前（v2.4.3）：那一轮的 finally 见"零推进"就整表清空 pending，而 _ensure_state_pix
    开头是"pend 为空就 return"——单向门，该状态从此永久缺失（_show_state 只记一行日志后
    静默 no-op），直到重启。

    能真失败：把零推进收口改回"整表清空 pending" → 第二步 pending 已空 → _state_pix("angry")
    拿到 None → 红；把"异常那一轮不判死"（_raised 守卫）拿掉 → _state_pix_dead 非空 → 红。
    """
    real = pet._ensure_state_pix
    tried = []

    def boom(state):
        tried.append(state)
        raise RuntimeError("boom: 建状态图时炸了")

    pet._state_pix_pending = {"normal": {"angry"}, "full": {"angry"}}   # 这一轮零推进 + 抛错
    pet._state_pix_dead = set()
    monkeypatch.setattr(pet, "_ensure_state_pix", boom)
    with pytest.raises(RuntimeError):
        pet._build_state_pix_slice()
    assert tried == ["angry"], "夹具失效：这一轮试的不是 angry：%r" % (tried,)
    assert pet._state_pix_pending,         "异常那一轮把 pending 清空了（单向门：angry 从此永久缺失）"
    assert pet._state_pending("angry"),         "异常那一轮把 angry 从 pending 里摘掉了（它再也不会被补建）"
    assert pet._state_pix_dead == set(),         "异常说明不了任何名字建不出来，不许判死：%r" % (pet._state_pix_dead,)
    # 恢复真方法（异常只发生一次）→ 按需补建必须照常工作
    monkeypatch.setattr(pet, "_ensure_state_pix", real)
    ref = QPixmap(main.resource_path("assets/n_angry.png"))
    assert not ref.isNull(), "夹具前提：assets/n_angry.png 应当存在"
    pix = pet._state_pix("angry")
    assert pix is not None, "异常一次之后 angry 再也补不出来了（A-2 的核心症状：永久缺失）"
    assert pix.toImage() == ref.toImage(), "补出来的不是 assets/n_angry.png"
    assert not pet._state_pending("angry"), "补建后 angry 仍被标成待建"


def test_production_step_entry_keeps_pending_after_an_exception(pet, monkeypatch):
    """走生产入口（_gslot 包住接力步）：抛错那一轮也要留住 pending，之后按需补建仍可。

    能真失败：同上的"整表清空"变异 → 第一条断言红（pending 没了）。
    """
    pet._ensure_default_frames()      # 先把帧集支消化掉（本用例只关心状态图支）
    pet._wire_anim_sets()
    pet._startup_assets_done = False
    real = pet._ensure_state_pix
    calls, fired = [], []

    def boom_once(state):
        """只炸**一次**（就是接力那一轮）；之后同一条按需补建路径必须照常工作。"""
        calls.append(state)
        if not fired:
            fired.append(state)
            raise RuntimeError("boom: 第一次建状态图就失败（这一轮零推进）")
        return real(state)

    pet._state_pix_pending = {"normal": {"angry"}, "full": {"angry"}}
    pet._state_pix_dead = set()
    monkeypatch.setattr(pet, "_ensure_state_pix", boom_once)
    pet._gslot("startup_assets", pet._startup_assets_step)()   # 生产路径就是这么调的
    assert fired == ["angry"], "夹具失效：这一轮试的不是 angry：%r" % (fired,)
    assert pet._state_pix_pending, "抛错那一轮把 pending 弄丢了（之后按需补建全部失效）"
    assert pet._state_pending("angry"), "抛错那一轮把 angry 判死并摘掉了（单向门）"
    assert pet._state_pix_dead == set(), "异常不许判死任何名字：%r" % (pet._state_pix_dead,)
    assert pet._state_pix("angry") is not None, "抛错一次之后该状态再也补不出来了"
    assert not pet._state_pending("angry")
