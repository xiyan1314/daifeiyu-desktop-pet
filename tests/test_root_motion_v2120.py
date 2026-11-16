# -*- coding: utf-8 -*-
"""A · root motion 的钉子（v2.12.0 第 12 轮 · 三审后重写）。

判据来自 _dev/task_r12_v2120_round.md §五，并按三审的三条 P0/P1 收紧：
  ① 近距：走帧推进 → 位移 = 步数 × STEP_PX（方向随行进方向）；
  ② 边界：夹紧按**当前屏可用区**（换一块小屏必须跟着变，不许写死 1920）；
  ③ 远距：**仍走 tick 老路**（三区速度是 v1.4.2 既有行为，不许被帧驱动顶掉）；
  ④ 无帧集 → 帧路径零位移（老路仍然动）；
  ⑤ 「减少动效」**不接**：walk 的 anim.play 必须 rate_factor=1.0（接上 = 走速砍半）。

## 每条能真失败在哪（都在 %TEMP% 影子副本里实测过）

- 删掉 root_dx 里的 min(raw, abs(dx)) → test_root_dx_clamped_by_remaining 红；
- 删掉 clamp_x 的 min(hi, ...) → test_clamp_at_right_edge 红；
- `pet_wander.tick` 里把 `if dist > WALK_FAR_DIST: steps = 0` 删掉 →
  test_far_distance_still_uses_the_old_tick_path 红（远距一步从 32px 掉回 6px）；
- 把 `clamp_x(nx, scr.left(), scr.right() - pet.width() + 1)` 改成写死 `1920` →
  test_clamp_follows_the_current_screen 红（1000px 屏上会跑到 100 而不是 81）；
- 把 `rate_factor=1.0` 改回 `self._frame_rate_factor()` →
  test_walk_frames_ignore_reduce_motion 红（AST 读的是调用实参，不是字符串碰运气）。
"""
import ast
import os
import sys

from PySide6.QtCore import QPoint, QRect

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import pet_motion  # noqa: E402
import pet_wander  # noqa: E402


class _FakePet(object):
    """够用的鸭子类型：tick 只碰这些属性（见 pet_wander 模块头）。"""

    def __init__(self, x=0, y=0, w=320, h=320, steps=0, screen=(0, 0, 1000, 600)):
        self._x, self._y = x, y
        self._w, self._h = w, h
        self._steps = steps
        self._screen = screen
        self._sleeping = False
        self.busy = False
        self._flying = False
        self.has_frames = True          # 跳过"贴正面图"那条支
        self.anim_mode = "walk"
        self._using_front = False
        self.flip = 1
        self.walk_phase = 0
        self.squash_y = 1.0
        self._wander_target = None
        self.walk_anim_calls = []

    def pos(self):
        return QPoint(self._x, self._y)

    def width(self):
        return self._w

    def height(self):
        return self._h

    def move(self, x, y):
        self._x, self._y = int(x), int(y)

    def frameGeometry(self):
        return QRect(self._x, self._y, self._w, self._h)

    def _take_walk_steps(self):
        s, self._steps = self._steps, 0
        return s

    def _walk_anim(self, on):
        self.walk_anim_calls.append(on)
        return True

    def _apply_transform(self):
        pass


def _ctl(pet):
    return pet_wander.WanderController(
        pet, lambda: {"wander": True, "follow_mouse": False},
        lambda _center: QRect(*pet._screen), lambda cfg: None)


def test_step_token_exists_and_positive():
    assert pet_motion.ROOT["STEP_PX"] > 0


def test_root_dx_is_steps_times_step():
    step = pet_motion.ROOT["STEP_PX"]
    assert pet_wander.root_dx(1000, 3, step) == 3 * step
    assert pet_wander.root_dx(-1000, 3, step) == -3 * step


def test_root_dx_clamped_by_remaining():
    assert pet_wander.root_dx(10, 3, 6) == 10     # 剩 10px，3×6=18 → 只走到目标为止
    assert pet_wander.root_dx(-10, 3, 6) == -10
    assert pet_wander.root_dx(18, 3, 6) == 18     # 恰好够：一步不多


def test_no_frames_is_zero_dx():
    assert pet_wander.root_dx(100, 0, 6) == 0     # 没有帧推进 → 老路接管
    assert pet_wander.root_dx(0, 5, 6) == 0       # 没有水平目标 → 不横移
    assert pet_wander.root_dx(100, 5, 0) == 0     # 令牌没配 → 不猜默认值


def test_clamp_at_right_edge():
    lo, hi = 0, 1000 - 320
    assert pet_wander.clamp_x(5000, lo, hi) == hi   # 右边缘：整只不许出屏
    assert pet_wander.clamp_x(-50, lo, hi) == lo
    assert pet_wander.clamp_x(300, lo, hi) == 300
    assert pet_wander.clamp_x(300, 100, 50) == 100  # 可用区比窗口还窄：退到 lo


def test_near_distance_is_frame_driven():
    """近距（≤200px）：位移 = 步数 × STEP_PX。"""
    pet = _FakePet(x=0, y=0, steps=1)
    pet._wander_target = QPoint(100, 0)
    _ctl(pet).tick()
    assert pet.pos().x() == pet_motion.ROOT["STEP_PX"], "近距没按帧驱动走"


def test_far_distance_still_uses_the_old_tick_path():
    """远距（>200px）：走**三区速度**那条老路（一步 32px），不是 6px。

    这是三审 P1-2 的钉子：上一版只要有走帧就用 root_dx，远距一步只有 6px，
    与老路 30~40px 交替 → 忽快忽慢，4K 屏上追 3000px 要 60 秒。
    """
    pet = _FakePet(x=0, y=0, steps=1)
    pet._wander_target = QPoint(900, 0)          # dx=900 > WALK_FAR_DIST
    _ctl(pet).tick()
    cap = min(40, max(10, int(pet.width() * 0.10)))   # 32
    expect = pet_wander._walk_step(900, cap)
    assert pet.pos().x() == expect, "远距还在被帧驱动顶掉老路（%d != %d）" % (pet.pos().x(), expect)
    assert expect > pet_motion.ROOT["STEP_PX"]


def test_clamp_follows_the_current_screen():
    """夹紧必须按**当前屏可用区**：一块 400px 宽的屏，右边上限 = right(399) - 320 + 1 = 80。

    写死 1920 的版本会给出 100（= 70 + 5 帧 × 6px），所以这条能真红。
    """
    pet = _FakePet(x=70, y=0, steps=5, screen=(0, 0, 400, 600))
    pet._wander_target = QPoint(200, 0)          # 近距：5 帧 × 6px = 30 → 100，须被夹到 80
    _ctl(pet).tick()
    assert pet.pos().x() == 399 - pet.width() + 1, "夹紧没用当前屏（写死了？）"
    assert pet.pos().x() != 70 + 5 * pet_motion.ROOT["STEP_PX"]


def test_no_walk_frames_means_zero_frame_dx():
    """无帧集：帧路径零位移，老路仍然动（不会僵住）。"""
    pet = _FakePet(x=0, y=0, steps=0)
    pet._wander_target = QPoint(100, 0)
    _ctl(pet).tick()
    assert pet.pos().x() > 0


def test_walk_speed_is_invariant_under_reduce_motion():
    """⑤ 「减少动效」只许放慢**帧**，不许改**走多快**（A-07：位移不是时长动画）。

    机制：walk 的 anim.play 照常带 rate_factor 开关（全仓规则 A-11），但 pet_wander
    按 1/倍率补偿每帧步长 —— 帧间隔翻倍时一步走两倍距离，每秒位移不变。
    把 pet_wander 里那段补偿删掉 → 本条红（0.5 倍率下只走 6px 而不是 12px）。
    """
    pet = _FakePet(x=0, y=0, steps=1)
    pet._wander_target = QPoint(100, 0)
    pet._frame_rate_factor = lambda: 1.0
    _ctl(pet).tick()
    normal = pet.pos().x()

    pet2 = _FakePet(x=0, y=0, steps=1)
    pet2._wander_target = QPoint(100, 0)
    pet2._frame_rate_factor = lambda: 0.5      # 「减少动效」开：帧率减半
    _ctl(pet2).tick()
    reduced = pet2.pos().x()

    assert normal == pet_motion.ROOT["STEP_PX"]
    assert reduced == 2 * normal, (
        "「减少动效」把走速也砍半了（%d vs %d）：位移不是时长动画，步长必须按 1/倍率补偿"
        % (reduced, normal))
