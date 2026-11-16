# -*- coding: utf-8 -*-
"""A · root motion 的钉子（v2.12.0 第 12 轮）。

判据来自 _dev/task_r12_v2120_round.md §五：
  ① 走帧推进 → 位移 = 步数 × STEP_PX（方向随行进方向）；
  ② 右边缘处继续推进 → x 不超过可用区上限（整只不出屏）；
  ③ 无帧集 → 走帧路径零位移（老路仍然动）；
  ④ root motion 不读「减少动效」开关（接上 → 必红）。

## 每条能真失败在哪

- 删掉 root_dx 里的 min(raw, abs(dx)) → test_root_dx_is_steps_times_step 之外的
  test_root_dx_clamped_by_remaining 红（角色会冲过目标点左右甩）；
- 删掉 clamp_x 的 min(hi, ...) → test_clamp_at_right_edge 红（整只出屏）；
- 删掉 root_dx 的 if not steps → test_no_frames_is_zero_dx 红；
- 删掉 _walk_anim 里的 self._walk_root_on = True → test_walk_anim_turns_root_on 红；
- 在 root 分支里读 _reduce_motion / _frame_rate_factor → test_root_motion_ignores_reduce_motion 红。
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import pet_motion  # noqa: E402
import pet_wander  # noqa: E402


def _fn_body(path, name):
    src = open(path, encoding="utf-8").read()
    i = src.index("def %s(" % name)
    j = src.index("\n    def ", i + 1)
    return src[i:j]


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
    lo, hi = 0, 1920 - 256
    assert pet_wander.clamp_x(5000, lo, hi) == hi   # 右边缘：整只不许出屏
    assert pet_wander.clamp_x(-50, lo, hi) == lo
    assert pet_wander.clamp_x(300, lo, hi) == 300
    assert pet_wander.clamp_x(300, 100, 50) == 100  # 可用区比窗口还窄：退到 lo


def test_walk_anim_turns_root_on():
    body = _fn_body(os.path.join(HERE, "桌宠.py"), "_walk_anim")
    assert "self._walk_root_on = True" in body
    assert "self._walk_root_on = False" in body    # 停下 / 无帧集必须关掉


def test_tick_uses_root_dx():
    body = _fn_body(os.path.join(HERE, "pet_wander.py"), "tick")
    assert "root_dx(dx, steps" in body
    assert "_take_walk_steps" in body
    assert "clamp_x(" in body


def test_root_motion_ignores_reduce_motion():
    """④ root motion 是位移，不是时长动画 → 不许接「减少动效」。"""
    src = open(os.path.join(HERE, "pet_wander.py"), encoding="utf-8").read()
    for bad in ("_reduce_motion", "_frame_rate_factor", "FRAME_REDUCED"):
        assert bad not in src, bad + " 不许出现在飘逸逻辑里（root motion 不接开关）"
    assert "ROOT[" in src                          # 令牌必须经 pet_motion 读，不许写字面量 6
