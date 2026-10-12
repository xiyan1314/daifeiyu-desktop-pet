# -*- coding: utf-8 -*-
"""v2.6.0（公开 CI #52）：动作链交错跑完必须把状态机带回待机（eat 例外除外）。

缺陷（已逐字复现 CI #52 的 "proc resets to idle"）：
  15s 闲逛节拍按 25% 权重挑中 jump（桌宠.py:IDLE_ACTIONS）→ pet_actions.idle_tick →
  play_action → do_jump **先置 busy=True** 再 _run_anim(520)；_run_anim 起播第一件事
  _stop_tween() 顶替在途的 sway（合成动作），并**手动执行**它的收尾 _done。此刻 busy
  已是 True → _done 有意跳过 _play_idle（桌宠.py:1515，防顶掉 _eat_done 等收尾回调）。
  随后 jump 自己的收尾走默认的 _reset_squash（它不自己设 anim_mode）→ 只清 busy/squash。
  结果：anim_mode 永久停在 "state" —— 待机帧不再按形态重绘，_idle_ready / idle_tick 的
  入睡判定（anim_mode in ("idle","form_idle")）永不成立（宠物看起来僵住）。

修法与边界（桌宠.py:_reset_squash 末尾的兜底）：
  "state" 这个模式没有主人时才回落待机 —— 表情展示的收尾定时器（_state_done 会收回）与
  在播帧动作的 on_finish（自己会收回）都算主人；吃帧（anim_mode == "eat"）是有意例外。

本文件的用例判据全部是**结构性事实**（anim_mode / 帧定时器 / 帧集名 / 收尾回调 / 调用
记账），在途动画一律用固定步进推到终态：不 sleep、不看墙钟、不依赖机器速度。
"""
import os
import sys
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import 桌宠 as main  # noqa: E402

ROLE_ID = "settle1"


def _png(path):
    from PySide6.QtGui import QColor, QImage
    img = QImage(64, 64, QImage.Format.Format_ARGB32)
    img.fill(QColor(120, 200, 255, 255))
    img.save(path)


def _install_role(win, tmp):
    """装一个单形态角色：idle 1 帧 / dance 2 帧 / eat 2 帧 + sway 合成动作。

    合成动作（procs）只有自定义角色才有（_cur_procs 对默认角色返回 {}），而本缺陷的
    被顶替者正是一次 proc（sway）。
    """
    d = os.path.join(str(tmp), "roles")
    os.makedirs(d, exist_ok=True)
    for n in ("s_base.png", "s_d1.png", "s_d2.png", "s_e1.png", "s_e2.png"):
        _png(os.path.join(d, n))
    win.role_lib._data["roles"].append({
        "id": ROLE_ID, "name": "收尾角色", "file": "s_base.png",
        "form": "single", "file_full": "", "frames": ["s_base.png"], "added": "",
        "forms": [{"name": "常态", "file": "s_base.png",
                   "animations": {"idle": ["s_base.png"],
                                  "dance": ["s_d1.png", "s_d2.png"],
                                  "eat": ["s_e1.png", "s_e2.png"]},
                   "anim_interval_ms": 80,
                   "procs": {"sway": {"kind": "sway", "amp": 0.06, "period_ms": 200}}}]})
    win.role_lib._save()
    win.apply_role(ROLE_ID)


@pytest.fixture(scope="module")
def pet(tmp_path_factory):
    """自定义角色 PetWindow（数据目录重定向到临时目录，退出时还原进程级全局）。"""
    import pet_log
    from PySide6.QtWidgets import QApplication

    tmp = tmp_path_factory.mktemp("settle")
    snap = (main.DATA_DIR, main.CONFIG_PATH, main.USAGE_PATH, main.MEMORY_PATH,
            getattr(pet_log, "_data_dir", None))
    main.DATA_DIR = str(tmp)
    main.CONFIG_PATH = str(tmp / "config.json")
    main.USAGE_PATH = str(tmp / "usage.json")
    main.MEMORY_PATH = str(tmp / "memory.json")
    pet_log.set_data_dir(str(tmp))
    QApplication.instance() or QApplication([])
    win = main.PetWindow()
    _install_role(win, tmp)
    from helpers_roles import quiet_pet_timers
    quiet_pet_timers(win)          # 停掉会自行插进状态机的周期定时器
    for _t in ("idle_timer", "walk_timer", "cpu_timer"):
        getattr(win, _t).stop()    # 15s 节拍/散步/CPU：本文件自己驱动动作链，不要随机插播
    win._say_line = lambda *a, **k: None   # 台词/配音与本缺陷的状态机无关，去掉 I/O
    try:
        yield win
    finally:
        win._stop_tween()
        win.apply_role("")
        win.role_lib.delete(ROLE_ID)
        from helpers_roles import active_timer_count, shutdown_pet
        shutdown_pet(win)
        assert active_timer_count(win) == 0, \
            "拆完还有 %d 个活跃定时器" % active_timer_count(win)
        (main.DATA_DIR, main.CONFIG_PATH, main.USAGE_PATH,
         main.MEMORY_PATH) = snap[0], snap[1], snap[2], snap[3]
        pet_log.set_data_dir(snap[4])


def _settle(win):
    """收敛到"用户形态 + 待机帧动画在跑 + 无临时展示/无在途动画"的干净前置。"""
    win._closing = False
    win.busy = False
    win._petting = False
    win._sleeping = False
    win._sleep_home = None
    win._cancel_transform()
    win._stop_idle_hold()
    win._idle_active = False
    win._idle_form_active = False
    win._idle_after_full_at = None
    if getattr(win, "_digest_timer", None) is not None:
        win._digest_timer.stop()
    win._state_timer.stop()
    # 待机展示（触发 B）会让位：0 是产品自带的"关闭无交互触发"取值，本文件只测状态机收尾
    win.cfg["idle_trigger_delay"] = 0
    win._user_form = win.form_keys[0]
    if win.form != win._user_form:
        win._set_form(win._user_form, display_only=True)
    win._stop_tween()
    win.anim_mode = ""
    win._play_idle()
    assert win.anim_mode == "idle" and win.anim._timer.isActive(), "前置状态没收敛"


def _spy_idle(win):
    """给 _play_idle 装调用记账（包一层后转发真实现，不改行为）→ 返回调用列表。"""
    real = getattr(win, "_idle_real", None) or win._play_idle
    win._idle_real = real
    calls = []

    def spy(*a, **k):
        calls.append(1)
        return real(*a, **k)

    win._play_idle = spy
    return calls


def _drive_to_end(anim, steps=4):
    """把在途 QVariantAnimation 按固定步进推到终态（finished 同拍同步发出）。

    步数固定 → 与机器速度无关（与 _verify_v13.py 的确定性驱动同一思路）。
    """
    from PySide6.QtCore import QAbstractAnimation, QVariantAnimation
    assert isinstance(anim, QVariantAnimation), "在途动画不是 QVariantAnimation：%r" % (anim,)
    dur = int(anim.duration())
    assert dur > 0
    for i in range(steps + 1):
        anim.setCurrentTime(dur * i // steps)
    assert anim.state() == QAbstractAnimation.State.Stopped, "动画没被推到终态"


def _frame_steps(anim):
    """帧动作播完还差几步：play 起播即计 1 帧 → loops×帧数-1（结构性步数）。"""
    return max(0, anim._loops * len(anim._frames or []) - 1)


def test_jump_inserted_during_proc_settles_back_to_idle(pet):
    """CI #52 的交错逐字复刻：sway 在途时插播 jump → 跑完必须回 idle。

    能真失败（修前必红）：sway 的收尾 _done 看到 busy=True 有意跳过 _play_idle
    （桌宠.py:1515），jump 自己的默认收尾 _reset_squash 只清 busy/squash、不碰 anim_mode
    → 断言 anim_mode == "idle" 红（拿到的是 'state'），待机帧动画再也不会被重新起播。
    """
    _settle(pet)
    pet.actions.play_action("sway")
    sway = pet._tween_anim
    assert pet.anim_mode == "state" and sway is not None, "前置：合成动作没起播"
    pet.actions.do_jump()                      # 闲逛节拍 25% 权重挑中的 jump
    assert pet.busy is True and pet._tween_anim is not sway, "前置：jump 没顶替掉在途 sway"
    _drive_to_end(pet._tween_anim)
    assert pet.busy is False, "jump 收尾没释放 busy"
    assert pet.anim_mode == "idle", \
        "交错跑完 anim_mode 停在 %r（待机不再恢复）" % pet.anim_mode
    assert pet.anim._name == "idle" and pet.anim._timer.isActive(), "待机帧动画没在跑"
    assert pet._tween_anim is None and pet._tween_finish_cb is None, "动画槽没清干净"
    assert abs(pet.squash_x - 1.0) < 1e-6 and abs(pet.squash_y - 1.0) < 1e-6


def test_proc_finish_during_eat_keeps_eat(pet):
    """_done 的 eat 例外不许拿掉：吃帧在途时合成动作收尾不得回落待机。

    能真失败：把桌宠.py:1515 的 anim_mode != "eat" 去掉 → _play_idle 会 anim.stop()
    顶掉待回调的 _eat_done（busy 永久卡死），本断言红。
    """
    _settle(pet)
    pet.actions.play_action("sway")
    tween = pet._tween_anim
    assert tween is not None
    pet.anim_mode = "eat"                      # 吃帧在途（吃帧动画的收尾由 _eat_done 负责）
    calls = _spy_idle(pet)
    _drive_to_end(tween)                       # 合成动作自然播完 → _done
    assert pet.anim_mode == "eat", "合成动作收尾把吃帧顶掉了（anim_mode=%r）" % pet.anim_mode
    assert calls == [], "吃帧在途时回了待机：%d 次" % len(calls)


def test_tween_reset_during_eat_keeps_eat(pet):
    """eat 例外不许拿掉（第二条路径）：_reset_squash 的回落判据必须把 eat 排除在外。

    生产上吃帧在途时帧回调也是主人（on_finish != None），两道判据都挡住回落；所以这里把
    状态机直接摆到"吃帧态 + 帧回调已清"（帧定时器停），让**模式判据**成为唯一防线。
    能真失败：把 anim_mode == "state" 放宽成"eat 也算可回落态"（或无条件 _play_idle）
    → 吃帧被顶掉（生产上会 anim.stop() 丢弃 _eat_done → busy 永久卡死）、断言红。
    """
    _settle(pet)
    pet.anim_mode = "eat"                      # 吃帧态（_eat_done 尚未跑）
    pet.anim.stop()                            # 帧回调已清：收尾链只剩"模式"这一道判据
    assert pet.anim._on_finish is None and not pet.busy and pet.anim_mode == "eat"
    calls = _spy_idle(pet)
    pet._reset_squash()                        # 在途 tween 的默认收尾（jump 这类不给自己收尾回调的动作走这条）
    assert pet.anim_mode == "eat", "收尾把吃帧顶掉了（anim_mode=%r）" % pet.anim_mode
    assert calls == [], "吃帧在途时回了待机：%d 次" % len(calls)


def test_eat_chain_preempting_proc_settles_to_idle(pet):
    """真实吃帧链（feed 的顺序：先置 busy 再起播吃帧）→ 吃完必须回 idle。

    能真失败：吃帧起播前回待机会把待回调的 _eat_done 顶掉（busy 永久卡死）；
    收尾链断了则步进数对不上。两条判据都是结构事实。
    """
    _settle(pet)
    calls = _spy_idle(pet)
    pet.actions.play_action("sway")
    assert pet._tween_anim is not None, "前置：合成动作没起播"
    pet.busy = True                            # feed 的顺序：先置 busy（在途收尾因此让位）
    pet._play_eat()                            # feed 的 120ms 错峰调的就是它
    assert pet.anim_mode == "eat" and pet.anim._name == "eat" and pet.anim._timer.isActive()
    assert pet._tween_anim is None, "吃帧起播没顶掉在途合成动作"
    assert calls == [], "吃帧起播前回了待机（会顶掉 _eat_done）：%d 次" % len(calls)
    need = _frame_steps(pet.anim)
    steps = 0
    while pet.anim_mode == "eat" and steps < need:
        pet.anim._advance()
        steps += 1
    assert steps == need, "吃帧步进数对不上（%d/%d）：收尾链断了" % (steps, need)
    assert not pet.busy and pet.anim_mode == "idle" and pet.anim._timer.isActive()
    assert len(calls) == 1, "吃帧收尾该回一次待机，实际 %d 次" % len(calls)


def test_chain_keeps_owner_then_settles_to_idle(pet):
    """被顶替之后紧接着又来一个动作：拥有者还在时不许提前回 idle，链走完必须回 idle。

    链：sway 在途 → jump 插播（顶掉 sway）→ 表情展示接管 "state" → 展示期间又跳一次 →
    表情到期收尾。三段判据：① 交互在途时一次 _play_idle 都不许有；② 表情展示（自带收尾
    定时器）才是 "state" 的主人，期间 jump 的收尾不许抢走它；③ 链走完回 idle。
    """
    _settle(pet)
    calls = _spy_idle(pet)
    pet.actions.play_action("sway")            # 动作 1：合成动作在途
    n0 = len(calls)
    pet.actions.do_jump()                      # 动作 2：busy 插播（顶掉动作 1）
    assert len(calls) == n0, "交互在途时回了待机（会把在途收尾回调顶掉）"
    pet._show_state("laugh", 60000)            # 动作 3：表情展示（长时长：不会自己到期）
    assert pet.busy is False, "jump 的收尾没跑（_show_state 的 _stop_tween 应顶掉它）"
    assert pet.anim_mode == "state" and pet._state_timer.isActive(), "表情展示没接管 'state'"
    assert not pet.anim._timer.isActive(), "表情是静态展示，帧定时器不该在跑"
    n_face = len(calls)
    pet.actions.do_jump()                      # 动作 4：表情展示期间又跳一次
    jump2 = pet._tween_anim
    assert jump2 is not None
    _drive_to_end(jump2)
    assert pet.anim_mode == "state" and pet._state_timer.isActive(), \
        "第二个 jump 的收尾把表情展示顶掉了（提前回 idle）"
    assert len(calls) == n_face, "表情展示期间回了待机 %d 次" % (len(calls) - n_face)
    pet._state_timer.stop()
    pet._state_done()                          # 表情到期（产品自己的收尾）
    assert pet.anim_mode == "idle" and pet.anim._timer.isActive(), "链走完没回待机"


def test_frame_action_owner_is_not_truncated_by_a_tween_finish(pet):
    """在播帧动作（自定义命名动作 / 戳戳帧）是 "state" 的另一个合法主人，tween 收尾不许腰斩它。

    能真失败：把 _reset_squash 兜底判据里的 anim._on_finish is None 去掉 → jump 收尾会把
    在播的 dance 帧动作顶掉（anim.play("idle") 内部 stop()），帧集名/记账断言红。
    """
    _settle(pet)
    calls = _spy_idle(pet)
    pet.actions.play_action("dance")           # 帧动作：loops=1，收尾 on_finish=_play_idle
    assert pet.anim_mode == "state" and pet.anim._name == "dance" and pet.anim._timer.isActive()
    assert pet.anim._on_finish is not None, "前置：帧动作没有待触发的收尾回调"
    pet.actions.do_jump()                      # 帧动作期间插播 jump
    assert pet._tween_anim is not None
    _drive_to_end(pet._tween_anim)
    assert pet.anim_mode == "state", "帧动作还在播，tween 收尾却回待机了"
    assert pet.anim._name == "dance" and pet.anim._timer.isActive(), "帧动作被腰斩了"
    assert calls == [], "tween 收尾把在播帧动作顶掉了：%d 次" % len(calls)
    need = _frame_steps(pet.anim)
    steps = 0
    while pet.anim._timer.isActive() and steps < need:
        pet.anim._advance()
        steps += 1
    assert steps == need, "帧动作步进数对不上（%d/%d）" % (steps, need)
    assert pet.anim_mode == "idle" and pet.anim._timer.isActive()
    assert len(calls) == 1, "帧动作收尾该回一次待机，实际 %d 次" % len(calls)


def test_idle_gates_usable_after_interleave(pet):
    """交错的真实后果：anim_mode 卡在 'state' → 待机/入睡判定永久不成立（宠物僵住）。

    能真失败：修前 anim_mode 停在 "state" → _idle_ready() 为假、idle_tick 的入睡判定
    （anim_mode in ("idle","form_idle")）永不成立 → 两条断言都红。
    """
    _settle(pet)
    pet.actions.play_action("sway")
    pet.actions.do_jump()
    _drive_to_end(pet._tween_anim)
    assert pet._idle_ready() is True, "待机入口被 anim_mode=%r 挡住" % pet.anim_mode
    pet._last_activity = time.monotonic() - (pet.actions._sleep_after + 5.0)
    pet.actions.idle_tick()
    assert pet._sleeping is True, "交错之后睡不着（anim_mode=%r）" % pet.anim_mode
    pet._wake()
    assert pet.anim_mode == "idle" and pet.anim._timer.isActive()
