# -*- coding: utf-8 -*-
"""
跟随 / 散步（P1-4 / v1.4.2 三区速度档）：目标生成 + 换屏目标作废 + 步进几何。

独立模块：不 import 桌宠.py；依赖 pet 的鸭子类型接口
（busy/has_frames/item/sprites/form/pos/width/move/flip/walk_phase/squash_y/
_apply_transform/walk_timer/_walk_interval/_wander_target/_was_walking/_wake/菜单 act）。

v2.11.0（第 11 轮 W2）：**走路播帧**的唯一开关点是这里的 tick —— 真的移动时
`pet._walk_anim(True)`（切 walk 帧集），停下的那三支 `pet._walk_anim(False)`（回 idle）。
只做"切帧集"，**位移与 squash 起伏一个字都没改**（U-16 未裁决：位移不算动效，见
pet_motion.effective_duration 的「已知边界」）；无帧集角色那边 `_walk_anim` 自己返回
False，于是仍然走**静态图 + squash** 这条老路（不报错、也不停住不动）。
⚠ 睡眠 / busy / 飞行 三支在切换**之前**就 return —— 所以这三支必须**先**停走帧
（`pet._walk_anim(False)`），否则散步途中睡着/忙起来/被甩飞时走帧还在原地循环。
「不许在这三种状态下切到走帧」由早退结构保证，不是靠调用方自觉。

v2.5.0（A1/A2）：服务构造搬进 pet_services.ServiceRegistry；本模块（该子系统）补全类型注解。
"""
import random
from typing import Any, Callable

from PySide6.QtCore import QPoint
from PySide6.QtGui import QCursor

# 跟随/散步行走参数（v1.4.2 降速档：温柔滑行，保证用户能追上点住）
WALK_INTERVAL_MS = 120   # 行走 tick 间隔
WALK_EASE = 0.10         # 每 tick 走剩余距离的比例（缓动）
WALK_STEP_MIN = 1        # 每轴最小步进（px）
WALK_STEP_MAX = 6        # 每轴最大步进（px，峰值约 50px/s）
WALK_FAR_DIST = 200      # 远距阈值：超过走快追档
WALK_NEAR_CAP = 8        # 近距每 tick 上限


def _walk_step(d: int, cap: int | None = None) -> int:
    """行走步进（模块级纯函数，供验证脚本直接断言）：
    每轴走剩余距离 WALK_EASE，夹紧在 [WALK_STEP_MIN, cap]。

    cap 默认 WALK_STEP_MAX（6px）；主程序按窗口宽度自适应（大屏/大角色不龟速），
    由 WanderController.tick 传入，封顶 40px。
    """
    if d == 0:
        return 0
    cap = int(cap) if cap else WALK_STEP_MAX
    return min(cap, max(WALK_STEP_MIN, int(abs(d) * WALK_EASE)))


class WanderController:
    """跟随 / 散步控制器：三区速度、目标生成、换屏目标作废（P1-4）。"""

    def __init__(self, pet: Any, cfg_getter: Callable[[], dict],
                 screen_geo: Callable[[Any], Any], save_cfg: Callable[[dict], None]) -> None:
        self.pet = pet
        self._cfg = cfg_getter
        self._screen_geo = screen_geo
        self._save_cfg = save_cfg

    def set_target(self, target: Any) -> None:
        self.pet._wander_target = target

    def restart(self) -> None:
        """跟随/散步开关或拖动结束后重启行走定时器；全关时复位朝向与贴图。"""
        pet = self.pet
        cfg = self._cfg()
        if cfg.get("follow_mouse") or cfg.get("wander"):
            pet.walk_timer.start(pet._walk_interval)
        else:
            pet.walk_timer.stop()
            pet._walk_anim(False)  # v2.11.0（W2）：全关 = 停下回 idle（无帧集角色是空操作）
            if not pet.has_frames and not pet._using_front:
                pet.item.setPixmap(pet.sprites[pet.form]["front"])
                pet._using_front = True
            pet.flip = 1
            pet.squash_y = 1.0
            pet._apply_transform()

    def on_drag_end(self) -> None:
        """拖拽松手：被暂停的行走按原状态恢复。"""
        if self.pet._was_walking:
            self.pet.walk_timer.start(self.pet._walk_interval)

    def set_follow(self, on: Any) -> None:
        cfg = self._cfg()
        cfg["follow_mouse"] = bool(on)
        if on:
            self.pet._wake()  # 睡着时开跟随：先醒过来再走（M4）
            cfg["wander"] = False
            if self.pet._wander_act:
                self.pet._wander_act.setChecked(False)
        self._save_cfg(cfg)
        self.restart()

    def set_wander(self, on: Any) -> None:
        cfg = self._cfg()
        cfg["wander"] = bool(on)
        if on:
            self.pet._wake()  # 睡着时开散步：先醒过来再走（M4）
            cfg["follow_mouse"] = False
            self.pet._wander_target = None
            if self.pet._follow_act:
                self.pet._follow_act.setChecked(False)
        self._save_cfg(cfg)
        self.restart()

    def tick(self) -> None:
        pet = self.pet
        if getattr(pet, "_sleeping", False):
            pet._walk_anim(False)   # v2.11.0（W2 尾巴）：睡着 = 停走帧（否则走帧在睡眠里继续循环）
            return  # v2.2（质量审查）：睡着不再满屏漂移（v2.1.7 起跟随/散步中允许入睡，但没停 walk_timer）
        if pet.busy:
            pet._walk_anim(False)   # v2.11.0（W2 尾巴）：busy（喂食飞盘/吃帧）停走帧，别原地迈腿
            return  # 喂食/吃帧期间暂停行走，避免「边吃边漂」（M3）
        if getattr(pet, "_flying", False):
            pet._walk_anim(False)   # v2.11.0（W2 尾巴）：甩抛飞行中停走帧（空中不许迈腿）
            return  # P1-手感：甩抛飞行中暂停行走，落地静止后恢复
        # v2.11.0（W2）：walk 也要排除——有走路帧但没有 idle 帧集的角色（自定义角色只配了
        # walk）正在播走路帧时，这里贴 side 静态图会把走帧盖掉（走起来像滑冰）。
        if not pet.has_frames and pet._using_front and pet.anim_mode not in ("state", "sleep", "walk"):
            pet.item.setPixmap(pet.sprites[pet.form]["side"])
            pet._using_front = False
        cfg = self._cfg()
        target = None
        if cfg.get("follow_mouse"):
            target = QCursor.pos()
            # 距光标 60px 内停住伴飞：不追到光标正下方，给用户留出点击空间
            cx, cy = pet.frameGeometry().center().x(), pet.frameGeometry().center().y()
            if abs(target.x() - cx) < 60 and abs(target.y() - cy) < 60:
                pet._walk_anim(False)   # v2.11.0（W2）：伴飞停住 = 停下回 idle
                # 伴飞静止时复位正面贴图（静止显侧身很怪）
                if not pet.has_frames and not pet._using_front:
                    pet.item.setPixmap(pet.sprites[pet.form]["front"])
                    pet._using_front = True
                    pet._apply_transform()
                return
        elif cfg.get("wander"):
            scr = self._screen_geo(pet.frameGeometry().center())
            if scr is None:
                return  # 无屏（headless 极端场景）：本 tick 不漫游
            # P1-4：换屏后旧目标可能落在上一块屏——目标不在当前屏就重新生成，
            # 避免被拖到副屏后还执着走回第一屏
            if (pet._wander_target is None or self._reached(pet._wander_target)
                    or not scr.contains(pet._wander_target)):
                xmin = scr.left() + 20
                xmax = max(xmin, scr.right() - pet.width() - 20)
                ymin = scr.top() + 20
                ymax = max(ymin, scr.bottom() - pet.height() - 20)
                pet._wander_target = QPoint(random.randint(xmin, xmax), random.randint(ymin, ymax))
            target = pet._wander_target
        if target is None:
            pet._walk_anim(False)   # v2.11.0（W2）：没有目标（全关/无屏）= 停下回 idle
            return
        cur = pet.pos()
        dx = target.x() - cur.x()
        dy = target.y() - cur.y()
        if abs(dx) < 3 and abs(dy) < 3:
            pet._walk_anim(False)   # v2.11.0（W2）：到点了 = 停下回 idle
            return
        # 三区速度（v1.4.2）：远距（>200px）快追防 4K 大屏龟速；
        # 近距缓行（8px 上限，温柔不吓人）；60px 内跟随模式已伴飞停下
        dist = max(abs(dx), abs(dy))
        if dist > WALK_FAR_DIST:
            cap = min(40, max(10, int(pet.width() * 0.10)))
        else:
            cap = WALK_NEAR_CAP
        step_x = _walk_step(dx, cap)
        step_y = _walk_step(dy, cap)
        nx = cur.x() + (min(step_x, abs(dx)) if dx > 0 else -min(step_x, abs(dx)))
        ny = cur.y() + (min(step_y, abs(dy)) if dy > 0 else -min(step_y, abs(dy)))
        pet.move(nx, ny)
        if dx != 0:
            pet.flip = 1 if dx < 0 else -1
        pet.walk_phase = (pet.walk_phase + 1) % 2
        pet.squash_y = 0.95 if pet.walk_phase == 0 else 1.0
        pet._apply_transform()
        # v2.11.0（W2）：**真的要移动**才切走帧（上面所有早退分支都还没走到这里）。
        # 无帧集角色在这里拿回 False → 继续静态图 + squash（硬要求的安全兜底）。
        pet._walk_anim(True)

    def _reached(self, target: Any) -> bool:
        p = self.pet.pos()
        return abs(p.x() - target.x()) < 8 and abs(p.y() - target.y()) < 8
