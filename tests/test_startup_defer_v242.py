# -*- coding: utf-8 -*-
"""v2.4.2 启动耗时 P2：首屏非必需素材的**延迟装载**回归。

背景（_dev/probe_startup_cost.py 实测，默认角色）：
  构造期原本同步解 21 张 PNG —— 4 张角色贴图 + 17 张状态图（≈23 ms）+ idle/idle_full/
  eat/petpet 四组帧集 37 帧（≈36 ms），合计约占 PetWindow() 构造的 65%。其中首屏真正
  用到的只有「4 张角色贴图 + 开场表情 laugh 那一张」。
  改动：构造期只解 idle 帧集 + laugh 状态图；idle_full/eat/petpet 与其余状态图由
  _startup_assets_step 在**首帧之后**按片接力装载，_ensure_default_frames /
  _ensure_state_pix 是同步兜底。
  实测（_dev/compare_startup_baseline.py，交替 A/B）：构造 95.3 ms → 48.2 ms。

本模块钉五件事，每条都能真失败（括号里是"把修复拿掉"的变异）：
  1. 构造期**不再**解非首屏素材，但首屏该有的一个不少（把四组帧集/全量状态图搬回构造期 → 红）；
  2. 交接完成后素材与"一次性全解"**逐位相同**（删掉接力收尾那次 _wire_anim_sets → eat 槽红）；
  3. 交接是**分片**的，不是"换个地方一次做完"（把 _startup_assets_step 改成一次做完全部 → 红）；
  4. 首屏画面没变：构造返回时 item 上就是 laugh 状态图（把 _state_pix 的按需补建去掉 → 红）；
  5. 同步兜底真的兜得住：_play_idle / feed / _start_petting 在接力跑完前被调用时
     就地补齐（删掉各自那行 ensure → 红）。
"""
import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import 桌宠 as main  # noqa: E402
import pet_anim  # noqa: E402
from PySide6.QtGui import QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture
def pet(tmp_path):
    """真 PetWindow + 临时数据目录；**不**驱动接力装载（用例自己决定什么时候驱动）。"""
    import pet_log

    snap = (main.DATA_DIR, main.CONFIG_PATH, main.USAGE_PATH, main.MEMORY_PATH,
            getattr(pet_log, "_data_dir", None))
    main.DATA_DIR = str(tmp_path)
    main.CONFIG_PATH = str(tmp_path / "config.json")
    main.USAGE_PATH = str(tmp_path / "usage.json")
    main.MEMORY_PATH = str(tmp_path / "memory.json")
    pet_log.set_data_dir(str(tmp_path))
    QApplication.instance() or QApplication([])
    win = main.PetWindow()
    from helpers_roles import quiet_pet_timers, shutdown_pet
    quiet_pet_timers(win)          # 用例要确定性：停掉会自行插进 _play_idle 的周期表
    yield win
    shutdown_pet(win)
    (main.DATA_DIR, main.CONFIG_PATH, main.USAGE_PATH, main.MEMORY_PATH,
     pet_log._data_dir) = snap


def _names(pix):
    return sorted({os.path.basename(p) for p in pix})


def _decode_spy(monkeypatch):
    """记录构造期 QPixmap(路径) 的解码。

    **两个模块都要包**：桌宠.py 与 pet_anim.py 各自 import 了 QPixmap，只包 main.QPixmap
    会漏掉 load_frame_set 里的帧解码（那样"帧集推迟了没有"根本测不出来）。
    """
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


# ---------------- 1. 构造期只解首屏要的 ----------------

def test_construction_decodes_only_first_screen_assets(tmp_path, monkeypatch):
    """构造期解的张数必须只剩"角色贴图 4 + laugh 状态图 2"，其余全推迟。

    能真失败：把 __init__ 里的 _build_state_pix(only={}) 换回 _build_state_pix()、
    或把三组帧集的 load_frame_set 搬回 __init__ → 解码清单里立刻出现 idle_full/eat/petpet
    与 n_angry 之类。
    """
    import pet_log
    snap = (main.DATA_DIR, main.CONFIG_PATH, main.USAGE_PATH, main.MEMORY_PATH,
            getattr(pet_log, "_data_dir", None))
    main.DATA_DIR = str(tmp_path)
    main.CONFIG_PATH = str(tmp_path / "config.json")
    main.USAGE_PATH = str(tmp_path / "usage.json")
    main.MEMORY_PATH = str(tmp_path / "memory.json")
    pet_log.set_data_dir(str(tmp_path))
    QApplication.instance() or QApplication([])
    seen = _decode_spy(monkeypatch)
    try:
        win = main.PetWindow()
    finally:
        (main.DATA_DIR, main.CONFIG_PATH, main.USAGE_PATH, main.MEMORY_PATH,
         pet_log._data_dir) = snap
    try:
        dec = _names(seen)
        # 首屏必需的：4 张角色贴图（side/front × normal/full）+ laugh 状态图（常态/吃饱）
        #              + idle 帧集 10 帧（_verify_green.py 的成品检测要求构造返回时就在）
        want = {"character.png", "character_front.png",
                "character_full.png", "character_full_front.png",
                "n_laugh.png", "f_laugh.png"}
        want |= {"idle_f%02d.png" % i for i in range(10)}
        assert set(dec) == want, (
            "构造期解码清单不对；多了（没推迟）：%r；少了（首屏必需）：%r"
            % (sorted(set(dec) - want), sorted(want - set(dec))))
        assert len(dec) == 16, "构造期解码张数应为 16，实为 %d：%r" % (len(dec), dec)

        # 构造刚返回时的素材状态：首屏必需的在、其余不在
        assert win.has_frames and len(win._idle_frames) == 10, "idle 帧集必须仍在构造期就位"
        assert len(win.anim._sets.get("idle") or []) == 10, "idle 槽必须在构造期就注册好"
        assert win._idle_full_frames == [] and win._eat_frames == [] and win._fx_petpet == []
        assert win._state_pix_pending, "状态图必须留下待建清单（否则就是全量构建了）"
        assert sum(len(v) for v in win.state_pix.values()) == 2, \
            "构造期只该建 laugh 两张，实为 %d" % sum(len(v) for v in win.state_pix.values())
    finally:
        from helpers_roles import shutdown_pet
        shutdown_pet(win)


# ---------------- 2. 交接完成后与"一次性全解"逐位相同 ----------------

def test_deferred_assets_match_eager_load(pet):
    """接力装载跑完后，四组帧集与状态图必须与"旧版一次性全解"逐位相同。

    能真失败：删掉 _startup_assets_step 收尾那次 _wire_anim_sets() → eat 槽停在空集，
    下面 len(pet.anim._sets["eat"]) == 7 红；把 _build_state_pix_slice 的预算改成 0
    （永不推进）→ pending 清不掉，状态图红。
    """
    from helpers_roles import drain_startup_assets
    assert drain_startup_assets(pet), "接力装载没跑完"
    assets = main.resource_dir("assets")
    for attr, prefix, count, sub in (("_idle_frames", "idle", 10, ""),
                                     ("_idle_full_frames", "idle_full", 10, ""),
                                     ("_eat_frames", "eat", 7, ""),
                                     ("_fx_petpet", "petpet", 10, "fx")):
        got = getattr(pet, attr)
        want = pet_anim.load_frame_set(os.path.join(assets, sub) if sub else assets, prefix, count)
        assert len(got) == count == len(want), "%s 帧数不对：%d" % (attr, len(got))
        assert all(a.toImage() == b.toImage() for a, b in zip(got, want)), \
            "%s 与一次性全解的内容不一致" % attr
    # idle 槽的内容必须就是常态帧集（add_set 会 list() 浅拷贝，所以比**元素**身份），
    # eat 槽必须真的注册上了（不是空集）
    _slot = pet.anim._sets.get("idle") or []
    assert len(_slot) == 10 and all(a is b for a, b in zip(_slot, pet._idle_frames)),         "idle 槽没指向常态帧集"
    assert len(pet.anim._sets.get("eat") or []) == 7, \
        "eat 槽是空的（接力装载收尾没重注册）：%r" % (len(pet.anim._sets.get("eat") or []),)
    # 状态图：pending 清空 + 默认角色 10 常态 + 7 吃饱（缺的 3 张素材本来就没有）
    assert pet._state_pix_pending == {}, "状态图待建清单没清空"
    assert sum(len(v) for v in pet.state_pix.values()) == 17, \
        "状态图总数应为 17（旧版口径），实为 %d" % sum(len(v) for v in pet.state_pix.values())


def test_lazy_state_pix_is_identical_to_the_asset(pet):
    """按需补建出来的状态图必须就是那张素材图（不是空白、不是叠图兜底）。

    能真失败：把 _ensure_state_pix 从 _state_pix 里去掉 → 这里拿到 None（首屏的 laugh
    也会跟着变成"state image missing"）。
    """
    ref = QPixmap(main.resource_path("assets/n_angry.png"))
    assert not ref.isNull()
    got = pet._state_pix("angry")          # 构造期没建 → 走按需补建
    assert got is not None, "按需补建没生效（拿到 None）"
    assert got.toImage() == ref.toImage(), "补建出来的不是 assets/n_angry.png"
    assert not pet._state_pending("angry"), "补建后该状态仍被标成待建"
    assert pet._state_pending("sleep"), "补建粒度不对：一次把别的状态也建了"


def test_lazy_fill_only_touches_the_requested_state(pet):
    """按需补建是**逐状态**的：要一张就只建那张（否则等于换个时机的全量构建）。

    能真失败：把 _ensure_state_pix 改成"重建整个 state_pix"（例如直接调 _build_state_pix()）
    → 下面第一条断言红。
    """
    before = sum(len(v) for v in pet.state_pix.values())
    assert before == 2, "构造期应当只有 laugh 两张，实为 %d" % before
    pet._state_pix("blush")
    after = sum(len(v) for v in pet.state_pix.values())
    # blush 在常态 + 吃饱各一张（两张素材都在）
    assert after == before + 2, "按需补建多建了：%d → %d" % (before, after)


# ---------------- 3. 交接是分片的 ----------------

def test_startup_task_is_chunked_not_one_shot(pet):
    """接力装载必须**多轮**完成，且单轮只做一小片。

    能真失败：把 _startup_assets_step 改成"一轮把帧集和状态图都做完" → 步数掉到 1~2，
    第一条断言红；把三组帧集的解码塞回构造期 → 接力任务无事可做 → 步数 1，同样红。
    """
    steps = []
    guard = 0
    while not pet._startup_assets_done and guard < 60:
        guard += 1
        import time as _t
        t0 = _t.perf_counter()
        pet._startup_assets_step()
        steps.append((_t.perf_counter() - t0) * 1000.0)
    assert pet._startup_assets_done, "接力装载没有收敛（跑了 %d 步）" % len(steps)
    assert len(steps) >= 3, "接力装载只剩 %d 步：不是分片，是把一次做完换了个地方" % len(steps)
    assert max(steps) < 60.0, "单轮占了 %.1f ms，超过一个切片的量级：%r" % (max(steps), steps)


# ---------------- 4. 首屏画面没变 ----------------

def test_first_screen_still_shows_the_laugh_state(pet):
    """构造返回时 item 上必须是开场表情 laugh 的状态图（= 改动前的首屏）。

    能真失败：去掉 _state_pix 里的按需补建 → _show_state 找不到图、只记一行日志，
    item 上停在前贴图 → 红。
    """
    pix = pet.item.pixmap()
    assert not pix.isNull(), "首屏没有图（白屏）"
    assert pix.cacheKey() == pet._state_pix("laugh").cacheKey(), \
        "首屏画的不是 laugh 状态图"
    assert pet.anim_mode == "state", "构造返回时应当处在开场表情态"


# ---------------- 5. 同步兜底真的兜得住 ----------------

def test_play_idle_fills_the_full_forms_frames(pet):
    """接力没跑完就切到吃饱形态并起播：_play_idle 必须就地补齐专属帧集。

    能真失败：删掉 _play_idle 里那行 _ensure_default_frames(...) → _idle_full_frames
    仍是空集 → 吃饱形态回退静态图（anim_mode=form_idle、定时器不跑），红。
    """
    pet._set_form("full")
    pet._play_idle()
    assert len(pet._idle_full_frames) == 10, "吃饱形态专属帧集没被补齐"
    _slot = pet.anim._sets.get("idle") or []
    assert len(_slot) == 10 and all(a is b for a, b in zip(_slot, pet._idle_full_frames)), \
        "idle 槽不是吃饱形态的专属帧集"
    assert pet.anim_mode == "idle" and pet.anim._timer.isActive(), "吃饱形态没播起来"


def test_feed_fills_the_eat_frames(pet):
    """接力没跑完就喂食：吃帧必须就地补齐并注册（否则会错走"大笑表达"分支）。

    能真失败：删掉 feed 开头的 _ensure_default_frames()/_wire_anim_sets() →
    _eat_frames 空、anim._sets["eat"] 空 → 前两条断言红。
    """
    pet._show_state("laugh", 50)          # 结束开场表情，回到可控状态
    pet._state_timer.stop()
    pet._state_done()
    pet.feed("小鱼干")
    assert len(pet._eat_frames) == 7, "喂食没有补齐吃帧"
    assert len(pet.anim._sets.get("eat") or []) == 7, "吃帧没注册进 FrameAnim"
    assert pet.busy, "喂食应当进入 busy（走吃帧路径）"
    pet._state_timer.stop()
    pet.busy = False


def test_petting_fills_the_petpet_frames(pet):
    """接力没跑完就摸头：petpet 帧集必须就地补齐（否则特效静默不播）。

    能真失败：删掉 _start_petting 开头那行 _ensure_default_frames() →
    _fx_petpet 空 → _start_petting 早退，_petting 仍为 False，红。
    """
    pet.busy = False
    pet._petting = False
    pet._press_dist = 0
    pet._start_petting()
    assert len(pet._fx_petpet) == 10, "摸头没有补齐 petpet 帧集"
    assert pet._petting and pet._fx_petpet_on, "摸头没起来"
    pet._end_petting()
