# -*- coding: utf-8 -*-
"""M4（v2.4 审查）：_slot_recover 把 anim_mode 直置 "idle" 却不重启帧定时器 → 画面冻住。

复现：_show_state("laugh", 长时长) 内部 anim.stop() + anim_mode="state" →
_slot_recover()（form 本来就是用户形态 → 不走 _set_form）→ 旧实现把 anim_mode 置回
"idle"，而帧定时器仍是停的：下一次 _play_idle() 看到 anim_mode == "idle" 整段跳过 →
画面停在表情那一帧，要等一次表情/吃帧/切形态才自愈。

护栏：恢复后**立即**按当前形态重新起播（anim_mode 置空 + 走统一的待机重绘入口），
并且画面真的在变（两个不同时刻的 pixmap cacheKey 不同、且来自待机帧集）。
"""
import os
import sys
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import 桌宠 as main  # noqa: E402


@pytest.fixture(scope="module")
def pet(tmp_path_factory):
    """默认角色的 PetWindow（数据目录重定向到临时目录，退出时还原进程级全局）。"""
    import pet_log
    from PySide6.QtWidgets import QApplication

    tmp = tmp_path_factory.mktemp("slotrec")
    snap = (main.DATA_DIR, main.CONFIG_PATH, main.USAGE_PATH, main.MEMORY_PATH,
            getattr(pet_log, "_data_dir", None))
    main.DATA_DIR = str(tmp)
    main.CONFIG_PATH = str(tmp / "config.json")
    main.USAGE_PATH = str(tmp / "usage.json")
    main.MEMORY_PATH = str(tmp / "memory.json")
    pet_log.set_data_dir(str(tmp))
    QApplication.instance() or QApplication([])
    win = main.PetWindow()
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


def _settle(win):
    """收敛到"用户形态 + 待机帧动画在跑"的干净状态。"""
    win._closing = False
    win.busy = False
    win._sleeping = False
    win._petting = False
    win._cancel_transform()
    win._stop_idle_hold()
    win._idle_active = False
    win._idle_form_active = False
    if getattr(win, "_digest_timer", None) is not None:
        win._digest_timer.stop()
    win._state_timer.stop()
    win._user_form = win.form_keys[0]
    if win.form != win._user_form:
        win._set_form(win._user_form, display_only=True)
    win.anim_mode = ""
    win._play_idle()
    assert win.anim_mode == "idle" and win.anim._timer.isActive(), "前置状态没收敛"


def _sample_keys(win, seconds=0.6):
    """泵事件循环，采集一串时刻的画面 cacheKey（画面有没有在变）。"""
    from PySide6.QtWidgets import QApplication

    keys = []
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.02)
        p = win.item.pixmap()
        keys.append(p.cacheKey() if (p is not None and not p.isNull()) else 0)
    return keys


def test_slot_recover_restarts_idle_frame_timer(pet):
    """槽异常恢复后：帧定时器在跑 + 画面在变（两个时刻 cacheKey 不同）。"""
    _settle(pet)
    idle_keys = {p.cacheKey() for p in (pet.anim._sets.get("idle") or [])}
    assert len(idle_keys) > 1, "待机帧集少于 2 帧，这条用例无法判定"
    pet._show_state("laugh", 60000)      # 长时长：_state_timer 不会自己收尾
    assert pet.anim_mode == "state", "前置：表情态"
    assert not pet.anim._timer.isActive(), "前置：表情态已经停掉帧定时器"
    frozen = pet.item.pixmap().cacheKey()
    assert frozen not in idle_keys, "前置：画面停在表情图上"

    pet._slot_recover("simulated_failure")   # form 本来就是用户形态 → 不走 _set_form
    assert pet.form == pet._user_form
    assert pet.anim_mode == "idle"
    assert pet.anim._timer.isActive(), "恢复后帧定时器没在跑 → 画面冻住"
    keys = _sample_keys(pet, 0.6)
    assert len(set(keys)) > 1, "两个不同时刻画面完全相同（cacheKey=%r）" % (set(keys),)
    assert set(keys) & idle_keys, "在动的不是待机帧集：%r" % (set(keys) - idle_keys,)
    pet._state_timer.stop()


def test_old_style_recover_keeps_the_picture_frozen(pet):
    """反例：旧写法（只把 anim_mode 置 "idle"）在同一场景下帧定时器**不会**起来。

    这条绿 = 主用例不是恒真断言：它抓的正是"anim_mode 谎报 idle"这个差异。
    """
    _settle(pet)
    pet._show_state("laugh", 60000)
    assert not pet.anim._timer.isActive()
    pet.busy = False
    pet._cancel_transform()
    pet._stop_idle_hold()
    pet._idle_active = False
    pet._idle_form_active = False
    pet.anim_mode = "idle"      # ← 旧实现的那一行（帧定时器并没有跟着起来）
    pet._play_idle()            # 槽异常之后的第一次待机 tick
    assert not pet.anim._timer.isActive(), "旧写法竟然自己起来了？那这条反例失去意义"
    keys = _sample_keys(pet, 0.4)
    assert len(set(keys)) == 1, "旧写法画面竟然在变：%r" % (set(keys),)
    pet._state_timer.stop()


def test_slot_recover_is_idempotent_and_leaves_no_owner(pet):
    """幂等收尾：连收两次不炸、不留形态主人（不 busy/不睡/无待机展示期）。"""
    _settle(pet)
    pet._show_state("laugh", 60000)
    pet._slot_recover("simulated_failure")
    pet._slot_recover("simulated_failure")
    assert pet.form == pet._user_form
    assert not pet.busy and not pet._sleeping and not pet._petting
    assert getattr(pet, "_transform_home", None) is None
    assert pet._idle_hold_timer is None and not pet._idle_form_active
    assert pet.anim_mode == "idle" and pet.anim._timer.isActive()
    pet._state_timer.stop()
