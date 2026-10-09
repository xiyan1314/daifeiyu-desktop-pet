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
    if getattr(win, "_digest_timer", None) is not None and win._digest_timer.isActive():
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
    pet.anim.stop()
    pet._eat_done = lambda *_a: None
    pet._eat_watchdog_fire()
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