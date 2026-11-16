# -*- coding: utf-8 -*-
"""E1 惊喜彩蛋（v2.12.0 第 12 轮 · C 项）—— 纯逻辑、零 Qt、时钟与计数可注入。

四类触发（默认值写在 DEFAULTS，产品码不许再散落字面量）：
  1. 连戳：poke_window 秒内被戳 poke_n 次（默认 7 次 / 4s）；
  2. 连喂：feed_window 秒内被喂 feed_n 次（默认 3 次 / 60s）；
  3. 时段：本地时间落在 [late_start,24) ∪ [0,late_end)（默认 23 点后 / 5 点前）；
  4. 角落：窗口贴住屏幕角连续 corner_sec 秒（默认 8s），贴角判定见 near_corner。

派发只认显式表 KIND_METHODS（kind → 方法名），**不许再拼 "on_" + kind**：
v2.12.0 三审 P0 里就是拼出来的 "on_late"，而方法叫 on_hour —— 夜间这一类永远不响、
且静默返回 None 不留痕。表里缺键 / 方法名写错现在是响亮的 KeyError/AttributeError。

统一约束（每条都有钉子，见 tests/test_easter_v2120.py）：
  · 每类每天最多一次（easter_sent 落盘；坏值一律回空表，不让脏记录永久静音）；
  · 全局冷却 30 分钟（任意一类触发后，30 分钟内别类也不响）；
  · easter_eggs 默认开，关掉即全部静默（返回 None，一个字节都不写状态）；
  · v1 不做屏幕震动：本模块只回答"该不该出彩蛋"，出什么由调用方决定（台词 / 表情）。

为什么单独一个模块：四类里三类要"时间窗内的历史"（连戳/连喂/角落停留）。这些状态
活在 Qt 窗口里会和 UI 生命周期绑死（重开窗口就清零，测试还得起窗口）。把时钟与计数
做成参数，pytest 里直接喂时间，不 sleep、不起 GUI。
"""
import time

# 四类彩蛋的代号（对外只认这四个字符串）
KINDS = ("poke", "feed", "late", "corner")

# 显式派发表：产品侧只按它取方法，不拼 "on_" + kind（拼出来是 on_late，方法却叫 on_hour）。
# KINDS 与这张表必须一一对应；缺键/写错方法名 = 产品侧报错，不再静默返回 None。
KIND_METHODS = {
    "poke": "on_poke",
    "feed": "on_feed",
    "late": "on_hour",
    "corner": "on_corner",
}

# 贴角判定半径（像素）：窗口边到屏幕边 ≤ 它才算"在角上"。
CORNER_RADIUS_PX = 24

# 默认阈值。改默认值 = 改产品行为，必须同步 README 与钉子。
DEFAULTS = {
    "poke_n": 7,
    "poke_window": 4.0,
    "feed_n": 3,
    "feed_window": 60.0,
    "late_start": 23,
    "late_end": 5,
    "corner_sec": 8.0,
    "cooldown_sec": 1800.0,
}


def _as_number(value, default=0.0):
    """严格取数：只接受 int/float（bool 不算），NaN/Inf 与非数值一律给 default。

    刻意**不用 try/except**：静默 except 在本仓是受审对象（每一条都要登记理由），
    而"类型判断"本来就该写成判断，不该写成"抛了再说"。
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    v = float(value)
    if v != v or v in (float("inf"), float("-inf")):
        return default
    return v


def near_corner(rect, screen, radius=None):
    """窗口是否贴在屏幕的某个角上。纯几何：不读 Qt、不读真桌面。

    rect / screen 都是 (left, top, right, bottom)。判定用**窗口边到屏幕边**的间距：
    横向取「窗口左边到屏幕左边」与「窗口右边到屏幕右边」的较小者，纵向同理；
    两个方向都 ≤ radius 才算贴角（等价于窗口某个角贴近屏幕对应角）。

    · 中心判定是错的：默认窗口 320×320，贴齐屏幕左边时中心仍离边 160px，
      拿中心比 24px 会让「角落」这一类永远不可达（v2.12.0 三审 P0 #2）。
    · 用绝对值：窗口探出屏幕 5px 和差 5px 一样算贴近；探出 100px 就不算。
    · radius 缺省走 CORNER_RADIUS_PX；传非法值按缺省处理，负半径 = 不命中。
    """
    if radius is None:
        radius = CORNER_RADIUS_PX
    if not isinstance(rect, (tuple, list)) or len(rect) != 4:
        return False
    if not isinstance(screen, (tuple, list)) or len(screen) != 4:
        return False
    rl, rt, rr, rb = rect
    sl, st, sr, sb = screen
    coords = []
    for value in (rl, rt, rr, rb, sl, st, sr, sb):
        n = _as_number(value, None)
        if n is None:
            return False
        coords.append(n)
    rl, rt, rr, rb, sl, st, sr, sb = coords
    r = _as_number(radius, CORNER_RADIUS_PX)
    if r < 0:
        return False
    dx = min(abs(rl - sl), abs(rr - sr))
    dy = min(abs(rt - st), abs(rb - sb))
    return dx <= r and dy <= r


def normalize_state(raw):
    """把 easter_sent 的任意输入归一成 {"day": str, "sent": list, "last": float}。

    坏值（None / "x" / 1 / [] / 缺键 / 类型错）一律回空表：
    宁可多响一次彩蛋，也不让一条脏记录把这个人永久静音。
    """
    out = {"day": "", "sent": [], "last": 0.0}
    if not isinstance(raw, dict):
        return out
    day = raw.get("day")
    if isinstance(day, str):
        out["day"] = day
    sent = raw.get("sent")
    if isinstance(sent, (list, tuple)):
        out["sent"] = [k for k in sent if k in KINDS]
    out["last"] = _as_number(raw.get("last"), 0.0)
    return out


def _day_of(ts):
    """本地日期。用本地时间而不是 UTC：彩蛋的"每天一次"跟用户作息走。"""
    return time.strftime("%Y-%m-%d", time.localtime(ts))


class EasterTracker(object):
    """四类触发的状态机。所有时间都走注入的 now()，不读别的东西。"""

    def __init__(self, now=time.time, state=None, enabled=True, opts=None):
        self._now = now
        self.enabled = bool(enabled)
        self.state = normalize_state(state)
        self.opts = dict(DEFAULTS)
        if isinstance(opts, dict):
            for k, v in opts.items():
                if k in self.opts:
                    self.opts[k] = v
        self._pokes = []
        self._feeds = []

    # ---- 状态读写（调用方负责把 to_cfg() 塞回 cfg["easter_sent"]） ----
    def to_cfg(self):
        return {"day": self.state["day"], "sent": list(self.state["sent"]),
                "last": float(self.state["last"])}

    def handler(self, kind):
        """返回 kind 对应的触发方法（绑定方法）；未知 kind 抛 KeyError，不静默。

        产品侧 _easter_check 查的是同一张 KIND_METHODS。缺键、拼错方法名都要变成
        响亮的异常（由调用方记 error.log），不许再出现三审 P0 的 "on_late" 静默 None。
        """
        return getattr(self, KIND_METHODS[kind])

    def _roll_day(self, now):
        day = _day_of(now)
        if self.state.get("day") != day:
            # 换天只清"今天发过哪些"，不动冷却锚点（跨零点刚发过的那条仍要挡半小时）
            self.state = {"day": day, "sent": [], "last": self.state.get("last") or 0.0}
            self._pokes = []
            self._feeds = []

    def _emit(self, kind):
        """唯一出口：开关 / 每日一次 / 全局冷却 三道闸都过了才返回 kind。"""
        if not self.enabled or kind not in KINDS:
            return None
        now = self._now()
        self._roll_day(now)
        if kind in self.state["sent"]:
            return None
        cooldown = _as_number(self.opts.get("cooldown_sec"), 0.0)
        if cooldown > 0 and (now - float(self.state.get("last") or 0.0)) < cooldown:
            return None
        self.state["sent"].append(kind)
        self.state["last"] = now
        return kind

    # ---- 四类触发 ----
    def on_poke(self):
        """连戳：窗口内第 poke_n 次才算；命中后清空窗口（不然第 8 下一次、第 9 下再一次）。"""
        now = self._now()
        self._roll_day(now)
        win = float(self.opts["poke_window"])
        self._pokes = [t for t in self._pokes if now - t <= win]
        self._pokes.append(now)
        if len(self._pokes) < int(self.opts["poke_n"]):
            return None
        self._pokes = []
        return self._emit("poke")

    def on_feed(self):
        now = self._now()
        self._roll_day(now)
        win = float(self.opts["feed_window"])
        self._feeds = [t for t in self._feeds if now - t <= win]
        self._feeds.append(now)
        if len(self._feeds) < int(self.opts["feed_n"]):
            return None
        self._feeds = []
        return self._emit("feed")

    def on_hour(self, hour=None):
        """时段：本地小时落在 [late_start, late_end)（跨零点）即命中。

        边界**含左不含右**：22:59 不响 / 23:00 响；凌晨 04:59 响 / 05:00 不响。
        hour 缺省时必须走**注入时钟**的本地小时（time.localtime(self._now())），
        产品侧就是无参调用。CI 在 UTC 跑，钉子用 time.mktime 造本地时间戳，不写死
        +08:00；把这里的 localtime 换成 gmtime，23:00 的用例会红（UTC+8 实测；
        UTC 主机由 test_late_reads_local_clock_even_on_utc_host 兜底）。
        """
        if hour is None:
            hour = time.localtime(self._now()).tm_hour
        _h = _as_number(hour, -1.0)
        if _h < 0:
            return None
        h = int(_h) % 24
        start = int(self.opts["late_start"]) % 24
        end = int(self.opts["late_end"]) % 24
        if start == end:
            return None
        if start < end:
            hit = start <= h < end
        else:
            hit = h >= start or h < end
        return self._emit("late") if hit else None

    def on_corner(self, dwell_sec):
        """角落：连续停留秒数到阈值才触发；离开时调用方传 0（本模块不记位置）。"""
        dwell = _as_number(dwell_sec, -1.0)
        if dwell < 0:
            return None
        if dwell < float(self.opts["corner_sec"]):
            return None
        return self._emit("corner")
