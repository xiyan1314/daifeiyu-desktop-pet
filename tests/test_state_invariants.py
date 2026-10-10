# -*- coding: utf-8 -*-
"""状态不变量：任何交互序列下，形态归属必须自洽、不得卡在"无主"的非用户形态。

探测器覆盖：待机吞形态 / 吃帧卡死 / 睡眠被静默清掉。
  1 form ∈ sprites，_user_form ∈ form_keys
  2 form != _user_form 时必须有主人（睡眠/变身/待机展示期/消化定时器）
  3 动作不得抛异常；4 打断类动作后待机展示期必须结束
  5 推进挂起的收尾回调后必须回到稳态（抓"回调后才卡死"的 bug）
"""
import itertools
import os
import sys
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import 桌宠 as main  # noqa: E402


@pytest.fixture(scope="module")
def pet(tmp_path_factory):
    """共享窗口 + 快照/还原进程级全局（否则污染其它测试文件）。"""
    import pet_log
    import pet_resources
    from PySide6.QtWidgets import QApplication
    tmp = tmp_path_factory.mktemp("inv")
    _snap = (main.DATA_DIR, main.CONFIG_PATH, main.USAGE_PATH, main.MEMORY_PATH,
             getattr(pet_log, "_data_dir", None), getattr(pet_log, "_redact_key", None),
             getattr(main, "_redact_key", None), getattr(pet_resources, "FRAME_MAX", None))
    main.DATA_DIR = str(tmp)
    main.CONFIG_PATH = str(tmp / "config.json")
    main.USAGE_PATH = str(tmp / "usage.json")
    main.MEMORY_PATH = str(tmp / "memory.json")
    main.pet_log.set_data_dir(str(tmp))
    QApplication.instance() or QApplication([])
    win = main.PetWindow()
    from helpers_roles import install_three_form_role
    install_three_form_role(win, tmp)
    yield win
    try:
        win._closing = True
        win.voice.stop()
        win.hide()
        win.deleteLater()
    except Exception:
        pass  # 有意忽略：测试收尾
    main.DATA_DIR, main.CONFIG_PATH, main.USAGE_PATH, main.MEMORY_PATH = _snap[0], _snap[1], _snap[2], _snap[3]
    pet_log.set_data_dir(_snap[4])
    main.set_redact_key(_snap[6] or "")
    if _snap[7] is not None:
        pet_resources.FRAME_MAX = _snap[7]


def _reset(win):
    """恢复到"用户形态 f0、无任何临时展示"的干净状态。"""
    win._closing = False
    win.busy = False
    win._petting = False
    win._sleeping = False
    win._sleep_home = None
    win._cancel_transform()
    win._stop_idle_hold()
    # M1：消化定时器也要停——否则它会一直 active，让"形态必有主人"的断言从第一次 feed 后失效
    if getattr(win, "_digest_timer", None) is not None:
        win._digest_timer.stop()
        win._digest_timer = None
    win._feed_form = ""
    win._behavior_gen = getattr(win, "_behavior_gen", 0) + 1
    win._behavior_seq = None
    win._behavior_is_idle = False
    win._idle_active = False
    win._idle_form_active = False
    win._idle_after_full_at = None
    win.cfg.pop("idle_form", None)
    win._user_form = "f0"
    win.anim.stop()
    win.anim_mode = "idle"
    win._set_form("f0", display_only=True)
    # L3（找茬 2026-10-09）：把无交互计时重置为"刚交互过"——否则 _settle() 泵事件循环时
    # 1s 的待机检查可能会真的触发待机并切走形态，让不变量测试出现被动改动。
    win._last_activity = time.monotonic()
    win._last_idle_at = time.monotonic()


def _owner(win):
    """非用户形态时的主人列表；空 = 卡死。只有真会恢复形态的才算：
    digest / sleeping / transform / idle-display。busy（自己会永久卡死）与
    state（只换贴图）都不算主人，否则等于给 bug 发豁免。"""
    owners = []
    if win._sleeping:
        owners.append("sleeping")
    if getattr(win, "_transform_home", None) is not None:
        owners.append("transform")
    if win._idle_form_active and (win._idle_active or win._idle_hold_timer is not None):
        owners.append("idle-display")
    if (getattr(win, "_digest_timer", None) is not None and win._digest_timer.isActive()
            and getattr(win, "_feed_form", "") == win.form):
        # 只有"喂食目标形态正在展示"时，消化定时器才算形态主人
        # （质量审查 L3：否则任意非用户形态都能拿 digest 当豁免，掩盖"消化窗口内形态被切走"）
        owners.append("digest")
    return owners


def _check(win, tag):
    assert win.form in win.sprites, "%s：form=%r 不在 sprites" % (tag, win.form)
    assert win._user_form in win.form_keys, "%s：user_form=%r 非法" % (tag, win._user_form)
    if win.form != win._user_form:
        owners = _owner(win)
        assert owners, ("%s：form=%r 与 user_form=%r 不一致，但没有任何主人（形态被吞/卡死）"
                        % (tag, win.form, win._user_form))


def _settle(win):
    """推进事件循环并把挂起的收尾回调依次触发，模拟时间流逝后的稳态。"""
    from PySide6.QtWidgets import QApplication
    QApplication.processEvents()
    try:
        if win.anim_mode == "state":
            win._state_done()
    except Exception:
        pass  # 有意忽略：终结器抛错由 _gslot 的 recover 覆盖，这里只求推进
    if win.busy:
        win._eat_done("settle")
    if getattr(win, "_transform_home", None) is not None:
        win._end_transform()
    if getattr(win, "_digest_timer", None) is not None and win._digest_timer.isActive():
        win._digest_timer.stop()
        win._digest()
    if win._idle_form_active:
        win._idle_end()
    QApplication.processEvents()


def _act_feed(win):
    win.feed("小鱼干")


def _act_transform(win):
    win._do_transform()


def _act_untransform(win):
    """已在变身形态时再点一次 = 提前变回（与 _act_transform 语义不同）。"""
    if getattr(win, "_transform_home", None) is not None:
        win._do_transform()


def _act_sleep(win):
    win._show_sleep()


def _act_wake(win):
    win._wake()


def _act_idle(win):
    win._start_idle("idle")


def _act_idle_end(win):
    win._idle_end()


def _act_click(win):
    win._touch_activity()
    win._wake()


def _act_user_form(win):
    win.set_user_form("f1")
    win.set_user_form("f0")


def _act_pet_head(win):
    win._touch_activity()
    win._show_state("happy")


def _act_digest(win):
    win._digest()


def _act_speak(win):
    win._idle_interrupt("speak")


ACTIONS = [_act_feed, _act_transform, _act_untransform, _act_sleep, _act_wake, _act_idle,
           _act_idle_end, _act_click, _act_user_form, _act_pet_head, _act_digest, _act_speak]


def test_single_actions_keep_invariants(pet):
    bad = []
    for fn in ACTIONS:
        _reset(pet)
        try:
            fn(pet)
        except Exception as e:  # noqa: BLE001
            bad.append("%s 抛异常 %r" % (fn.__name__, e))
            continue
        try:
            _check(pet, fn.__name__)
        except AssertionError as e:
            bad.append(str(e))
    assert not bad, "单动作不变量失败：\n" + "\n".join(bad)


def test_action_pairs_keep_invariants(pet):
    """两两组合（12×12=144）：第二个动作之后状态必须依然自洽。"""
    bad = []
    for a, b in itertools.product(ACTIONS, repeat=2):
        _reset(pet)
        try:
            a(pet)
            b(pet)
        except Exception as e:  # noqa: BLE001
            bad.append("%s → %s 抛异常 %r" % (a.__name__, b.__name__, e))
            continue
        try:
            _check(pet, "%s → %s" % (a.__name__, b.__name__))
        except AssertionError as e:
            bad.append(str(e))
    assert not bad, "组合不变量失败（%d 条）：\n%s" % (len(bad), "\n".join(bad[:25]))


def test_user_form_is_authoritative(pet):
    """用户显式选形态后：_user_form 立即生效；无更高优先级展示时形态必须跟随。"""
    bad = []
    for fn in ACTIONS:
        for target in ("f0", "f1", "f2"):
            _reset(pet)
            try:
                fn(pet)
                pet.set_user_form(target)
            except Exception as e:  # noqa: BLE001
                bad.append("%s → set_user_form(%s) 抛异常 %r" % (fn.__name__, target, e))
                continue
            if pet._user_form != target:
                bad.append("%s → set_user_form(%s)：_user_form=%r" % (fn.__name__, target, pet._user_form))
            if pet.busy or pet._sleeping or getattr(pet, "_transform_home", None) is not None:
                continue
            if pet.form != target:
                bad.append("%s → set_user_form(%s)：形态还是 %r" % (fn.__name__, target, pet.form))
    assert not bad, "用户形态权威性失败（%d 条）：\n%s" % (len(bad), "\n".join(bad[:15]))


def test_three_action_sequences_keep_invariants(pet):
    """三动作组合（12³=1728）：每步之后都自洽。"""
    bad = []
    for seq in itertools.product(ACTIONS, repeat=3):
        _reset(pet)
        try:
            for fn in seq:
                fn(pet)
                _check(pet, " → ".join(f.__name__ for f in seq))
        except AssertionError as e:
            bad.append(str(e))
        except Exception as e:  # noqa: BLE001
            bad.append("%s 抛异常 %r" % (" → ".join(f.__name__ for f in seq), e))
        if len(bad) > 30:
            break
    assert not bad, "三连不变量失败（%d 条）：\n%s" % (len(bad), "\n".join(bad[:20]))


def test_after_callbacks_settle_no_stuck_form(pet):
    """动作 → 推进回调 → 必须回到稳态（抓吃帧卡死/睡眠被静默清掉这类回调后 bug）。"""
    bad = []
    seqs = [(f,) for f in ACTIONS] + list(itertools.product(ACTIONS, repeat=2))
    for seq in seqs:
        _reset(pet)
        try:
            for fn in seq:
                fn(pet)
            _settle(pet)
        except Exception as e:  # noqa: BLE001
            bad.append("%s 抛异常 %r" % (" → ".join(f.__name__ for f in seq), e))
            continue
        tag = " → ".join(f.__name__ for f in seq)
        if pet.busy:
            bad.append("%s：收尾后 busy 仍为 True（卡死）" % tag)
        if pet._sleeping:
            if pet.form not in (pet._user_form, pet._sleep_form_key() or pet.form):
                bad.append("%s：睡着但形态是 %r（既不是睡形态也不是用户形态）" % (tag, pet.form))
            continue
        own = _owner(pet)
        if own:
            bad.append("%s：收尾后仍有挂起主人 %r" % (tag, own))
        if pet.form != pet._user_form:
            bad.append("%s：收尾后形态 %r != 用户形态 %r（被吞/卡死）"
                       % (tag, pet.form, pet._user_form))
    assert not bad, "收尾稳态失败（%d 条）：\n%s" % (len(bad), "\n".join(bad[:20]))


def test_idle_not_swallow_full_form(pet):
    """v2.1.5 回归：喂食后"吃饱形态"保留期（消化窗口）内，待机不得开始/不得改形态。"""
    _reset(pet)
    pet.cfg["idle_form"] = "f3"
    pet.feed("小鱼干")
    full_form = pet.form
    assert full_form != pet._user_form, "喂食应该切到吃饱形态"
    assert pet._digest_pending() is True, "消化定时器应处于激活态"
    assert pet._idle_ready() is False, "消化窗口内 _idle_ready 必须为 False"
    pet._last_activity = 0.0
    pet._last_idle_at = 0.0
    pet.maybe_idle_behavior()          # 无交互触发条件满足，也不该开始待机
    assert pet.form == full_form, "待机把吃饱形态吞了（form=%r）" % pet.form
    assert pet._idle_form_active is False
    pet._eat_done("test")
    pet._digest_timer.stop()           # 模拟定时器到点（单发触发后本就 inactive）
    pet._digest()
    assert pet.form == pet._user_form and not pet._digest_pending()
    pet.cfg.pop("idle_form", None)


def test_feed_from_idle_display_shows_full_form(pet):
    """v2.1.6 回归（"吃饱形态被待机吞了"的真因）：

    待机形态展示期里喂食时，必须先结束待机展示（恢复用户形态）**再**按用户形态推进形态——
    否则形态推进从待机形态往后算（f3→f0），根本走不到吃饱形态；且 _idle_form_active 会残留，
    之后任何点击都把吃饱形态拉回用户形态。
    """
    _reset(pet)
    pet.cfg["idle_form"] = "f3"
    pet._start_idle("idle")                     # 待机形态展示期
    assert pet.form == "f3" and pet._idle_form_active is True
    # 严格的期望值：从**用户形态**出发、跳过 no_feed 后的第一个形态（与生产代码同源判定）
    _user_idx = pet.form_keys.index(pet._user_form)
    expect = pet.form_keys[_user_idx]
    for _step in range(1, len(pet.form_keys) + 1):
        _cand = pet.form_keys[(_user_idx + _step) % len(pet.form_keys)]
        if not pet._role_no_feed(_cand):
            expect = _cand
            break
    pet.feed("小鱼干")
    # 严格相等：不给 or 子句留活路（质量审查 M1：弱断言会让"只回退修复①"的回归溜过去）
    assert pet.form == expect, \
        "喂食没有落到用户形态的下一个可喂形态：form=%r expect=%r" % (pet.form, expect)
    assert pet._idle_form_active is False, "待机展示期旗标没清掉（之后点击会把形态拉走）"
    _full = pet.form
    pet._eat_done("test")
    pet._touch_activity()                       # 用户点一下
    assert pet.form == _full, "点击把吃饱形态拉回用户形态了（form=%r）" % pet.form
    pet._wake()
    assert pet.form == _full, "唤醒把吃饱形态拉走了"
    pet._on_voice_finished("d", "")
    assert pet.form == _full, "语音结束把吃饱形态拉走了"
    pet._digest_timer.stop()
    pet._digest()
    assert pet.form == pet._user_form
    pet.cfg.pop("idle_form", None)


def test_busy_window_does_not_strand_idle_form(pet):
    """v2.1.6 回归（质量审查 S1 场景 J）：待机展示期 + busy 重叠时，
    _idle_end 早退也不得留下"旗标清了但形态还是待机形态"的悬挂态——
    否则之后喂食会从待机形态往后推进（绕过吃饱形态），甚至永久卡在待机形态。"""
    _reset(pet)
    pet.cfg["idle_form"] = "f3"
    pet._start_idle("idle")
    assert pet.form == "f3" and pet._idle_form_active is True
    pet.busy = True                 # 模拟食物飞行中（_fly_food 的窗口）
    pet._idle_end()                 # 展示期定时器到点 → 早退分支
    pet.busy = False
    assert pet.form == pet._user_form, \
        "展示期结束后形态仍停在待机形态（旗标已清、没人再回位）：form=%r" % pet.form
    assert pet._idle_form_active is False
    _user_idx = pet.form_keys.index(pet._user_form)
    expect = pet.form_keys[_user_idx]
    for _step in range(1, len(pet.form_keys) + 1):
        _cand = pet.form_keys[(_user_idx + _step) % len(pet.form_keys)]
        if not pet._role_no_feed(_cand):
            expect = _cand
            break
    pet.feed("小鱼干")
    assert pet.form == expect, "喂食仍从待机形态推进：form=%r expect=%r" % (pet.form, expect)
    pet.cfg.pop("idle_form", None)


def test_feed_during_idle_action_sequence(pet):
    """v2.1.6（质量审查 M2）：待机**动作序列**播放中喂食，同样必须先收尾再推进。"""
    _reset(pet)
    pet.cfg["idle_form"] = "f3"
    # 待机动作必须是**已登记的行为**（idle_actions 只是引用），所以这里真建一条短行为
    # （行为名必须英文开头，validate_name 的约定）
    _b, _err = pet.behaviors.add("short_act", [{"act": "wait", "param": "", "seconds": 5}])
    assert _b, "行为创建失败：%s" % _err
    import pet_behaviors as _pb
    _pb.add_idle_action(pet.cfg, _b["id"], weight=1)   # 模块级函数：写入 cfg 的 idle_actions
    pet.apply_idle_settings(pet.cfg)
    assert pet._idle_cfg().get("idle_actions"), "待机动作没登记上"
    pet._start_idle("idle")
    assert pet._idle_active is True and pet._behavior_seq is not None
    pet.feed("小鱼干")
    assert pet._behavior_seq is None, "待机动作序列没被喂食中断"
    assert pet._idle_form_active is False and pet._idle_active is False
    assert pet.form != "f3", "喂食后仍停在待机形态"
    pet.cfg.pop("idle_form", None)
    pet.cfg["idle_actions"] = []


def test_transform_during_digest_returns_user_form(pet):
    """v2.1.7 回归（找茬 S1）：消化窗口内变身 → 变身结束必须回**用户形态**。

    此前 _transform_home 记的是当前展示形态（吃饱），而 _digest 见变身接管就跳过回位，
    变身结束时"回"到吃饱形态 → 此后 dig/tfrm/idleF 全空 = 永久卡在吃饱形态。
    """
    _reset(pet)
    pet.set_user_form("f3")                  # 选一个与"变身形态 f1"不同键的用户形态，
    pet.feed("小鱼干")                        # 否则喂到 f1 时点变身会走"提前变回"分支
    pet._eat_done("test")
    assert pet._digest_pending() and pet.form != pet._user_form
    pet._do_transform()                      # 消化窗口内变身
    assert pet._transform_home == pet._user_form, \
        "_transform_home 记成了展示形态（%r）" % pet._transform_home
    pet._digest_timer.stop()
    pet._digest()                            # 消化到点（变身接管期间跳过回位）
    pet._end_transform()                     # 变身结束
    assert pet.form == pet._user_form, "变身结束停在了 %r（应回用户形态）" % pet.form
    assert getattr(pet, "_transform_home", None) is None


def test_role_switch_keeps_user_form(pet):
    """v2.1.7 回归（找茬 S2）：睡眠/变身/消化窗口里切角色，不得把展示形态写成用户形态。"""
    _reset(pet)
    _uf = pet._user_form
    # ① 睡眠中切角色
    pet._show_sleep()
    assert pet.form != _uf
    pet.apply_role("inv1")
    assert pet._user_form == _uf, "睡眠中切角色把睡形态写成了用户形态（%r）" % pet._user_form
    pet._wake()
    assert pet.form == _uf, "醒来仍显示睡形态（form=%r）" % pet.form
    # ② 变身中切角色
    _reset(pet)
    pet._do_transform()
    assert pet.form != pet._user_form
    pet.apply_role("inv1")
    assert pet._user_form == _uf, "变身中切角色把变身形态写成了用户形态"
    assert pet.form == _uf, "变身中切角色后仍停在变身形态（form=%r）" % pet.form
    # ③ 消化窗口切角色
    _reset(pet)
    pet.feed("小鱼干")
    pet._eat_done("test")
    assert pet._digest_pending()
    pet.apply_role("inv1")
    assert pet._user_form == _uf, "消化中切角色把吃饱形态写成了用户形态"
    assert pet.form == _uf, "消化中切角色后仍停在吃饱形态（form=%r）" % pet.form


def test_feed_during_transform_basis_is_user_form(pet):
    """v2.1.7 回归（找茬 M1）：变身中喂食，推进基准必须是用户形态（不能从变身形态往后推）。"""
    _reset(pet)
    pet._do_transform()
    assert pet._transform_home is not None and pet.form != pet._user_form
    _user_idx = pet.form_keys.index(pet._user_form)
    expect = pet.form_keys[_user_idx]
    for _step in range(1, len(pet.form_keys) + 1):
        _cand = pet.form_keys[(_user_idx + _step) % len(pet.form_keys)]
        if not pet._role_no_feed(_cand):
            expect = _cand
            break
    pet.feed("小鱼干")
    assert pet.form == expect, \
        "变身中喂食的落点是 %r，应为用户形态的下一个（%r）" % (pet.form, expect)


def test_form_only_idle_ends_within_hold(pet):
    """v2.1.8（找茬 S1）**真实事件循环**回归：delay < 展示期上限时，形态待机不得被无限续期。

    旧症状：1s 检查器每 delay 秒重新触发一次 → 展示期定时器被 stop+重建 → 永不到期 →
    形态待机变成永久占位（用户形态被永久吞），实测 25s 内 IDLE_END=0。
    """
    from PySide6.QtCore import QEventLoop, QTimer
    _reset(pet)
    _fk_user = pet.form_keys[0]
    _fk_idle = pet.form_keys[-1] if len(pet.form_keys) > 1 else pet.form_keys[0]
    pet.cfg["idle_form"] = _fk_idle
    pet.cfg["idle_trigger_delay"] = 3      # 故意小于展示期上限：旧实现必然被续期
    pet.cfg["idle_form_hold"] = 2
    pet.cfg["idle_actions"] = []
    pet.apply_idle_settings(pet.cfg)
    pet._user_form = _fk_user
    pet._set_form(_fk_user, display_only=True)
    pet._last_activity = 0.0
    pet._last_idle_at = 0.0
    ends = []
    _real_end = pet._idle_end
    pet._idle_end = lambda: (ends.append(1), _real_end())[1]
    loop = QEventLoop()
    QTimer.singleShot(9000, loop.quit)     # 真跑 9 秒：3s 触发 + 2s 展示 → 至少结束一次
    loop.exec()
    assert ends, "形态待机在 9 秒内从未结束（展示期被 1s 检查无限续期 → 永久占用形态）"
    pet.cfg["idle_form"] = ""
    pet.cfg["idle_actions"] = []
    pet.cfg["idle_trigger_delay"] = 8
    pet.apply_idle_settings(pet.cfg)


def test_random_wander_action_blocked_during_full_form(pet):
    """v2.1.9 回归（用户反复反馈的"吃饱形态被待机吞了"的真因）：

    默认配置下 v2.1 待机是空操作，真正的"待机动作"是 idle_tick 里的**内置随机闲逛动作**
    （jump/zzz）。它在吃饱形态（消化窗口）里照常插播，导致"吃饱形态没保持住"。
    修法：消化窗口/变身/待机展示期间，idle_tick 不得播放随机闲逛动作、也不得入睡。
    """
    _reset(pet)
    pet.feed("小鱼干")
    pet._eat_done("test")
    assert pet._digest_pending() is True and pet.form != pet._user_form
    played = []
    _real_pa = pet.actions.play_action
    _real_pick = pet.actions._pick
    pet.actions._pick = lambda: ("jump", None)   # 强制抽到动作，验证门控
    pet.actions.play_action = lambda name, arg=None: (played.append(name), _real_pa(name, arg))[1]
    try:
        pet.actions.idle_tick()                  # 模拟 15s tick 在消化窗口内到点
        assert played == [], "消化窗口内仍插播了随机动作：%r" % played
    finally:
        pet.actions.play_action = _real_pa
        pet.actions._pick = _real_pick
    pet._digest_timer.stop()
    pet._digest()
    pet._idle_after_full_at = 0.0                # v2.2.3：等待期已过（触发 A 已消费）才恢复
    # 消化结束后（且等待期已过），随机动作应恢复可播
    pet.actions._pick = lambda: ("jump", None)
    pet.actions.play_action = lambda name, arg=None: played.append(name)
    try:
        pet.actions.idle_tick()
        assert "jump" in played, "消化结束后随机动作没恢复"
    finally:
        pet.actions.play_action = _real_pa
        pet.actions._pick = _real_pick


def test_mood_during_full_form_blocks_only_internal_mischief(pet):
    """v2.2.2 回归：吃饱形态期间——**用户点击/戳的反应必须照常**（v2.2.1 曾连这都禁，
    变成"吃饱后点了没反应"）；**只挡内部自动调皮**（smug 调度）。"""
    _reset(pet)
    pet.feed("小鱼干")
    pet._eat_done("test")
    assert pet._digest_pending() is True
    # ① 用户戳的反应照常显示
    pet._on_mood_state("puzzled")
    assert pet.anim_mode == "state", "吃饱形态期间点击毫无反应（v2.2.1 过激门控复发）"
    pet._play_idle()
    pet._mood_emote("question")
    pet._mood_bubble("咦？")
    # ② 内部调皮调度被挡
    called = []
    pet.mood.tick = lambda: called.append(1)
    pet._mood_tick()
    assert called == [], "消化窗口内内部调皮事件没被挡（会插到吃饱形态上）"
    pet._digest_timer.stop()
    pet._digest()
    pet._mood_tick()
    assert called == [1], "消化结束后调皮调度没恢复"


def test_random_action_waits_after_full_form(pet):
    """v2.2.3 回归（对照 v1.4.2 实测基线：吃饱结束→常态→安静一段时间才 zzz/跳）：
    随机跳/zzz 必须与触发 A 同一规矩——吃饱结束后 idle_delay_after_full 秒内不得插播，
    否则吃饱形态一结束、下一个 15s 节拍（可能 <1s）就把"常态"压没了。"""
    _reset(pet)
    pet.feed("小鱼干")
    pet._eat_done("test")
    pet._digest_timer.stop()
    pet._digest()                       # 吃饱结束：触发 A 挂起到 +2s
    assert pet._idle_after_full_at is not None
    played = []
    _pa = pet.actions.play_action
    _pick = pet.actions._pick
    pet.actions._pick = lambda: ("jump", None)
    pet.actions.play_action = lambda n, a=None, f=False: played.append(n)
    try:
        pet.actions.idle_tick()         # A 未到点：随机动作必须被压住（保持常态）
        assert played == [], "吃饱刚结束随机动作就跳出来了（常态被压没）"
        pet._idle_after_full_at = 0.0   # 等待期已过（触发 A 已消费）
        pet.actions.idle_tick()
        assert "jump" in played, "等待期过后随机动作没恢复"
    finally:
        pet.actions.play_action = _pa
        pet.actions._pick = _pick


def test_sleep_survives_voice_finished(pet):
    """M1 回归：睡眠中「朗读完成」不得静默醒来，也不得把形态留在睡形态且无主人。"""
    _reset(pet)
    pet._show_sleep()
    assert pet._sleeping and pet.form == "f2"
    pet._speaking_voice = True
    pet._on_voice_finished("default", "")
    assert pet._sleeping is True, "语音结束把睡着的鱼静默弄醒了"
    assert pet.form in ("f2", pet._user_form), "睡形态与标志不一致：%r" % pet.form
    pet._on_voice_dialogue_done()
    assert pet._sleeping is True, "对白结束把睡着的鱼静默弄醒了"
    pet._wake()
    assert not pet._sleeping and pet.form == pet._user_form


def test_eat_frames_not_stolen_by_idle(pet):
    """S1 回归：吃帧进行中调 _play_idle 不得顶掉吃帧（否则 busy 永久卡死）。"""
    _reset(pet)
    assert pet.has_frames, "测试角色必须带帧集，否则吃帧路径没被覆盖"
    pet.feed("小鱼干")
    assert pet.busy is True
    pet.anim_mode = "eat"
    pet._play_idle()
    assert pet.anim_mode == "eat", "吃帧被 _play_idle 顶掉了"
    pet._eat_done("test")
    assert pet.busy is False


def test_eat_watchdog_releases_busy(pet):
    """S1 兜底：即便收尾回调真的丢了，看门狗也必须把 busy 释放掉。"""
    _reset(pet)
    pet.feed("小鱼干")
    pet.anim.stop()          # 模拟回调被 stop 丢弃（on_finish 被清掉，没人再调 _eat_done）
    pet._eat_watchdog_fire()  # 看门狗兜底：到点仍 busy 就强制收尾
    assert pet.busy is False, "看门狗没释放 busy"


def test_idle_never_sticks_after_interrupt(pet):
    """待机展示期 + 任一高优先级动作 → 展示期必须结束（不变量 4）。"""
    bad = []
    for fn in ACTIONS:
        _reset(pet)
        pet.cfg["idle_form"] = "f3"  # 专用待机形态：不会被喂食循环推进到（避免假失败）
        pet._idle_form_active = True
        pet._set_form("f3", display_only=True)
        try:
            fn(pet)
        except Exception as e:  # noqa: BLE001
            bad.append("%s 抛异常 %r" % (fn.__name__, e))
        else:
            if fn in (_act_idle, _act_idle_end, _act_digest, _act_untransform):
                continue  # 这几个不是"高优先级交互"（_act_untransform 在非变身态是空操作）
            if pet._idle_form_active and pet.form == "f3" and not (
                    pet.busy or pet._sleeping or getattr(pet, "_transform_home", None) is not None):
                bad.append("%s 之后仍停在待机形态 f3（展示期没结束）" % fn.__name__)
        finally:
            pet.cfg.pop("idle_form", None)
    assert not bad, "待机打断失败：\n" + "\n".join(bad)