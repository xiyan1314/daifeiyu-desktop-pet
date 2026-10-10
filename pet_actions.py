# -*- coding: utf-8 -*-
"""
动作点播 / 闲逛 tick / 系统状态（P3-2 加权动作目录点播共用）。

独立模块：不 import 桌宠.py；pick_idle_action / 睡眠阈值由构造注入。
"""
import random
import time

import psutil
from PySide6.QtCore import QEasingCurve, QPoint


_MB = 1048576.0


class ActionService:
    """动作点播（jump/emote）+ 闲逛 tick + 系统状态 / CPU 采样。"""

    def __init__(self, pet, cfg_getter, idle_picker, sleep_after):
        self.pet = pet
        self._cfg = cfg_getter
        self._pick = idle_picker
        self._sleep_after = sleep_after

    def do_jump(self):
        pet = self.pet
        if pet.busy:
            return
        pet.busy = True
        start = pet.pos()
        h = int(60 * pet.scale)
        pet._run_anim(520, lambda v: pet.move(start + QPoint(0, -int(h * v))),
                      keyframes=[(0.5, 1.0)], end=0.0, easing=QEasingCurve.Type.InOutQuad)
        pet._show_emote("heart")
        # v2.1：跳跃台词取台词库"开心"类别；v2.1.2 修复（M-2）：**库可用时不回落内置常量**
        # （否则用户删掉的台词会"复活"）；池子为空就这次不喊。
        _say = getattr(pet, "_say_line", pet.show_bubble)
        _happy = pet.lines_pools.get("happy") or []
        if _happy:
            _say(random.choice(_happy))

    def play_action(self, name, arg=None, force=False):
        """P3-2：按名称点播动作（闲逛加权随机与右键「动作」菜单共用同一实现）。

        与 idle_tick 同款门控：busy/摸摸头/跟随/散步中不播；睡眠中先醒来再表演。
        v2.2：force=True 跳过"跟随/散步"门控（右键动作菜单、语音 talk_action 是**用户显式
        点播**，开着跟随时点了就该表演，而不是静默没反应——此前三个入口都因此"只说不做"）。
        分派优先级：内建分支（jump/emote）→ 帧集动作（内建 + v2.0.1 自定义命名帧动作，
        播一次回待机）→ v2.0.1 程序化合成动作（呼吸/摇摆/点头）。"""
        pet = self.pet
        if name == "none":
            return
        if pet.busy or pet._petting or ((self._cfg().get("follow_mouse") or self._cfg().get("wander"))
                                        and not force):
            return
        if pet._sleeping:
            pet._wake()
        if name == "jump":
            self.do_jump()
        elif name == "emote":
            pet._show_emote(arg or "note")
        elif name in (pet.anim._sets or {}):
            # v2.0.1：自定义命名帧动作——播放一次后回待机。
            # 先停合成动作（防振荡叠加/播到一半被 proc 收尾截断）
            _stop = getattr(pet, "_stop_tween", None)
            if _stop is not None:
                _stop()
            # 帧间隔：forms[i].anim_interval_ms 优先；缺省与戳戳帧同口径（EAT_FRAME_MS）
            interval = pet._cur_form_anim().get("interval_ms") or pet.EAT_FRAME_MS
            pet.anim_mode = "state"
            pet._state_timer.stop()
            pet.anim.play(name, interval, loops=1, on_finish=pet._play_idle)
        else:
            procs = pet._cur_procs()
            if name in procs:
                # v2.0.1：程序化合成动作（呼吸/摇摆/点头）
                pet._play_proc(name, procs[name])

    def idle_tick(self):
        pet = self.pet
        cfg = self._cfg()
        if pet.busy or pet._petting:
            return  # 摸摸头期间不跳不发 zzz（S3 修复）
        if pet._sleeping:
            return
        # v2.0.2：待机行为（默认关闭；PetWindow 内部判断时机与去重，未配置=无操作）
        _maybe_idle = getattr(pet, "maybe_idle_behavior", None)
        if _maybe_idle is not None:
            _maybe_idle()
        # v2.1.9：吃饱形态（消化窗口）/变身/待机展示期间**不入睡**，也不插播随机闲逛动作。
        # v2.2.3（用户反馈"吃饱结束→直接待机，常态被压没了"）：随机跳/zzz 按自己的 15s 节拍走，
        # 吃饱形态一结束下一个节拍（可能 <1s）就跳出来——它也必须**等吃饱结束后
        # idle_delay_after_full 秒**（与触发 A 同一规矩）。_idle_after_full_at 就是触发 A
        # 挂起的到点时刻：到点前一律安静，到点后（触发 A 已消费=None）才允许随机动作。
        _after_full_at = getattr(pet, "_idle_after_full_at", None)
        _high_priority_display = (
            getattr(pet, "_digest_pending", lambda: False)()
            or (_after_full_at is not None and time.monotonic() < _after_full_at)
            or getattr(pet, "_transform_home", None) is not None
            or bool(getattr(pet, "_idle_form_active", False)))
        if _high_priority_display:
            return
        if pet.anim_mode in ("idle", "form_idle") and (time.monotonic() - pet._last_activity) > self._sleep_after:
            pet._show_sleep()
            pet.show_bubble(random.choice(["呼……呼……", "zzZ……睡得好香~", "睡着了……别吵~"]))
            return
        if cfg.get("follow_mouse") or cfg.get("wander"):
            # v2.1.7（L2）：跟随鼠标/散步时只跳过"随机闲逛动作"，
            # 待机系统与入睡判定照常（此前整条 tick 提前 return → 开着跟随就永不待机、永不自动入睡）
            return
        # v2.0.2：行为序列播放中不插播闲逛动作（防随机 jump/emote 与行为步骤互踩）
        if getattr(pet, "_behavior_seq", None) is not None:
            return
        # P3-2：加权动作目录替代 0.35/0.65 魔法数（可扩展、可点播，共用 play_action）
        name, arg = self._pick()
        if name == "none":
            return
        self.play_action(name, arg)
        if name == "emote" and arg == "zzz":
            # v2.1：走日常台词出口（气泡 + 可选配音朗读）
            # v2.1.2 修复（S-1）：用户可能把这两类台词全删掉 → 池子为空时
            # random.choice([]) 会抛 IndexError，QTimer 槽里未捕获异常会弹模态错误框（每轮复发）
            _say = getattr(pet, "_say_line", pet.show_bubble)
            _pool = pet.lines_pools.get("idle", []) + pet.lines_pools.get("greedy", [])
            if _pool:
                _say(random.choice(_pool))

    def cpu_tick(self):
        pet = self.pet
        try:
            cpu = psutil.cpu_percent(interval=None)
            pet._last_cpu = cpu
            if cpu > 90:
                pet._show_emote("exclaim")
                pet.show_bubble("CPU %.0f%% 啦！我要被烤熟了！" % cpu)
        except Exception:
            pass  # 有意忽略：采样失败下个周期再试（6s 周期高频，不刷日志）

    def show_system_status(self):
        pet = self.pet
        try:
            cpu = pet._last_cpu  # 复用定时器缓存，避免阻塞 GUI 线程
            mem = psutil.virtual_memory().percent
            self_rss = psutil.Process().memory_info().rss / _MB
            pet.show_bubble("CPU %.0f%% · 内存 %.0f%% · 本宠 %.0fMB" % (cpu, mem, self_rss))
        except Exception:
            pet.show_bubble("系统状态读不到啦……")
