# -*- coding: utf-8 -*-
"""E1 惊喜彩蛋的钉子（v2.12.0 第 12 轮 · C 项）。

## 为什么需要这组钉子

四类彩蛋最容易出的三个错都不是"不响"，而是**响太多**：
连戳命中后不清窗口（第 8 下之后每一下都响）、跨天不清 sent（第二天不响）、
冷却只按类记（换个类立刻再响一条）。三条都写成"能真失败"的断言。

## 每条能真失败在哪

- 把 on_poke 里命中后的 self._pokes = [] 删掉 → test_poke_fires_once_per_burst 红（第 8 下又响）；
- 把 _roll_day 的 sent 清空删掉 → test_same_day_second_time_silent 红（第二天仍不响）；
- 把 _emit 里的 cooldown 判断删掉 → test_global_cooldown_blocks_other_kinds 红；
- 把 enabled 判断删掉 → test_disabled_is_silent 红；
- 把 on_hour 的 >= 改成 > → test_late_hour_boundary 红（23:00 不响）；
- 把 normalize_state 的 isinstance 守卫删掉 → test_bad_state_is_empty 红（脏值永久静音）。
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import pet_easter  # noqa: E402


class Clock(object):
    def __init__(self, t):
        self.t = float(t)

    def __call__(self):
        return self.t

    def advance(self, sec):
        self.t += float(sec)


def _local(y, mo, d, h, mi, s=0):
    """本地时刻 → epoch。不写死时区偏移（CI 是 UTC，写死 +08:00 必红）。"""
    return time.mktime((y, mo, d, h, mi, s, 0, 0, -1))


def test_poke_fires_once_per_burst():
    c = Clock(_local(2026, 11, 16, 14, 0))
    tr = pet_easter.EasterTracker(now=c)
    hits = [tr.on_poke() for _ in range(6)]
    assert hits == [None] * 6           # 第 7 次才响
    assert tr.on_poke() == "poke"
    assert tr.on_poke() is None         # 窗口已清空：第 8 下不重复


def test_poke_window_expiry():
    c = Clock(_local(2026, 11, 16, 14, 0))
    tr = pet_easter.EasterTracker(now=c, opts={"poke_window": 4.0})
    for _ in range(6):
        assert tr.on_poke() is None
        c.advance(1.0)                   # 每下隔 1s，6 下共 6s > 4s 窗口
    assert tr.on_poke() is None          # 窗口外的旧戳已过期，这次只算第 1 下


def test_feed_fires_once():
    c = Clock(_local(2026, 11, 16, 14, 0))
    tr = pet_easter.EasterTracker(now=c)
    assert tr.on_feed() is None
    assert tr.on_feed() is None
    assert tr.on_feed() == "feed"
    assert tr.on_feed() is None


def test_same_day_second_time_silent():
    c = Clock(_local(2026, 11, 16, 14, 0))
    tr = pet_easter.EasterTracker(now=c)
    assert tr.on_hour(23) == "late"
    c.advance(3600 * 3)                  # 同一天，冷却早过
    assert tr.on_hour(23) is None        # 同一类一天只一次


def test_next_day_fires_again():
    c = Clock(_local(2026, 11, 16, 23, 30))
    tr = pet_easter.EasterTracker(now=c)
    assert tr.on_hour(23) == "late"
    c.t = _local(2026, 11, 17, 23, 30)   # 次日
    assert tr.on_hour(23) == "late"


def test_global_cooldown_blocks_other_kinds():
    c = Clock(_local(2026, 11, 16, 14, 0))
    tr = pet_easter.EasterTracker(now=c)
    assert tr.on_hour(23) == "late"
    c.advance(60)                        # 1 分钟后，换一类
    assert tr.on_corner(99) is None      # 全局冷却 30 分钟仍在窗口内
    c.advance(1800 - 60 + 1)
    assert tr.on_corner(99) == "corner"


def test_disabled_is_silent():
    c = Clock(_local(2026, 11, 16, 14, 0))
    tr = pet_easter.EasterTracker(now=c, enabled=False)
    assert tr.on_hour(23) is None
    assert tr.on_corner(99) is None
    for _ in range(9):
        assert tr.on_poke() is None
    assert tr.to_cfg()["sent"] == []     # 关掉 = 一个字节都不写状态


def test_late_hour_boundary():
    tr = pet_easter.EasterTracker(now=lambda: _local(2026, 11, 16, 22, 59))
    assert tr.on_hour(22) is None        # 22:59 不响
    tr2 = pet_easter.EasterTracker(now=lambda: _local(2026, 11, 16, 23, 0))
    assert tr2.on_hour(23) == "late"     # 23:00 响
    tr3 = pet_easter.EasterTracker(now=lambda: _local(2026, 11, 17, 4, 59))
    assert tr3.on_hour(4) == "late"      # 凌晨 4:59 仍算深夜
    tr4 = pet_easter.EasterTracker(now=lambda: _local(2026, 11, 17, 5, 0))
    assert tr4.on_hour(5) is None        # 5:00 出界


def test_corner_requires_dwell():
    c = Clock(_local(2026, 11, 16, 14, 0))
    tr = pet_easter.EasterTracker(now=c)
    assert tr.on_corner(7.9) is None
    assert tr.on_corner(8.0) == "corner"


def test_bad_state_is_empty():
    for bad in (None, "x", 1, [], {"day": 1, "sent": "oops", "last": "nan"}):
        st = pet_easter.normalize_state(bad)
        assert st["sent"] == [] and st["last"] == 0.0
    # 脏记录不许把用户永久静音：归一之后当天仍能响
    tr = pet_easter.EasterTracker(now=lambda: _local(2026, 11, 16, 23, 10),
                                  state={"day": "x", "sent": ["late"], "last": "oops"})
    assert tr.on_hour(23) == "late"


# ===================== 接线（v2.12.0 第 12 轮 · E1 四处钩子） =====================
#
# 纯逻辑绿了不等于功能存在：钩子没接，用户侧一个彩蛋都不会出现。下面几条钉住接线本身。
# 能真失败：删掉任意一处 _easter_check(...) 调用 -> 对应断言红。


def _src(name):
    return open(os.path.join(HERE, name), encoding="utf-8").read()


def test_hooks_are_wired_in_window():
    src = _src("桌宠.py")
    assert '_easter_check("poke")' in src, "点击钩子没接"
    assert '_easter_check("feed")' in src, "喂食钩子没接"
    assert '_easter_check("corner"' in src, "角落钩子没接"
    assert "_easter_corner_sample" in src


def test_late_hook_is_wired_in_idle_tick():
    src = _src("pet_actions.py")
    assert '_easter("late")' in src, "深夜钩子没接（idle_tick 里那句）"


def test_corner_timer_respects_switch():
    src = _src("桌宠.py")
    i = src.index("self.easter_timer = QTimer(self)")
    seg = src[i:i + 700]
    assert 'self.cfg.get("easter_eggs", True)' in seg, "采样定时器必须受开关控制（关掉不该还在跑）"
    assert "easter_timer.start(2000)" in seg
    assert "self.easter_timer" in src, "退出时必须停掉（cleanup 那行）"


def test_trigger_persists_to_cfg():
    src = _src("桌宠.py")
    i = src.index("def _easter_save")
    seg = src[i:i + 400]
    assert 'self.cfg["easter_sent"]' in seg, "触发后必须落盘（否则重启就重响）"
    assert "save_config" in seg


def test_trigger_is_silent_when_off():
    src = _src("桌宠.py")
    i = src.index("def _easter_tracker")
    seg = src[i:i + 700]
    assert 'self.cfg.get("easter_eggs", True)' in seg
    assert "enabled=enabled" in seg
