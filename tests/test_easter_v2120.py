# -*- coding: utf-8 -*-
"""E1 惊喜彩蛋的钉子（v2.12.0 第 12 轮 · C 项；三审 P0 后重写）。

## 这组钉子守什么

四类触发（KINDS）必须都有可达的实现、判定必须走注入时钟、命中后的窗口必须清、
坏记录不许把用户永久静音。三审把下面三条钉成 P0，每条都有能真失败的对应用例：

  1. 派发拼 "on_" + kind → 拼出 on_late（方法却叫 on_hour），深夜永远不响且静默
     返回 None。现在查显式表 KIND_METHODS；表缺键 / 方法名错 →
     test_dispatch_table_is_complete 红。
  2. 角落拿窗口中心比屏幕边（默认窗 320 宽，贴边时中心仍离边 160px）→ 永远不可达。
     现在 near_corner 按窗口边到屏幕边判；改回中心判定 → test_near_corner_geometry 红。
  3. 深夜边界靠参数传小时，注入时钟根本没参与。现在 on_hour() 无参走 now()；
     把 time.localtime 换成 time.gmtime → test_late_clock_boundaries 红（本机 UTC+8）。

## 变异实测（全部在 %TEMP% 影子副本里跑过；红的就是下面点名的那条）

- KIND_METHODS["late"] = "on_late"           → test_dispatch_table_is_complete 红
- on_hour 里 time.localtime → time.gmtime    → test_late_clock_boundaries 等 7 条红
  （UTC+8 实测；TZ=UTC 实测只剩 test_late_reads_local_clock_even_on_utc_host 一条红，
   所以 CI 的 UTC 时区也杀得掉这个变异）
- 删掉 on_poke 命中后的 self._pokes = []      → test_poke_hit_clears_window 红
- 删掉 normalize_state 的 KINDS 过滤           → test_normalize_filters_bad_sent 红
- near_corner 改回"窗口中心到屏幕边"           → test_near_corner_geometry 红
- 删掉 _quit 清理元组里的 self.easter_timer   → test_quit_stops_easter_timer 红
- 删掉 _emit 的已发过判断                      → test_same_day_only_once +
                                                test_normalize_filters_bad_sent 红
- 删掉 _emit 的全局冷却判断                    → test_global_cooldown_blocks_other_kinds 红
- 删掉 _emit 的 enabled 判断                   → test_disabled_is_silent 红
- 删掉 _roll_day 的 sent 清空                  → test_next_day_fires_again +
                                                test_bad_state_never_mutes 红
- _as_number 不再挡 inf                        → test_bad_state_never_mutes 红

## 两条禁令

- 不写死时区偏移：一律用 time.mktime 造本地时间戳（CI 是 UTC，写 +08:00 必红）。
- 不读真桌面：角落几何只喂四元组，不实例化 Qt。
"""
import ast
import os
import sys
import time

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import pet_easter  # noqa: E402


class Clock(object):
    """可推进的注入时钟（epoch 秒）。"""

    def __init__(self, t):
        self.t = float(t)

    def __call__(self):
        return self.t

    def advance(self, sec):
        self.t += float(sec)


def _local(y, mo, d, h, mi, s=0):
    """本地时刻 → epoch。不写死时区偏移（CI 是 UTC，写死 +08:00 必红）。"""
    return time.mktime((y, mo, d, h, mi, s, 0, 0, -1))


def _local_day(ts):
    """时间戳的本地日期，用来喂 normalize_state（day 必须和 tracker 的"今天"一致）。"""
    return time.strftime("%Y-%m-%d", time.localtime(ts))


# ===================== 纯逻辑 =====================


def test_dispatch_table_is_complete():
    """改什么会红：KIND_METHODS["late"] 写成 "on_late"（三审 P0 原样）→ hasattr 假；
    删掉任意一个键 → set 断言红（后面查表也会 KeyError）；"late" 指到 on_poke →
    handler("late").__name__ 断言红；handler 对未知 kind 改用 .get 静默 →
    最后的 KeyError 断言红。
    """
    assert set(pet_easter.KIND_METHODS) == set(pet_easter.KINDS)
    tr = pet_easter.EasterTracker(now=Clock(_local(2026, 11, 16, 14, 0)))
    for kind in pet_easter.KINDS:
        assert hasattr(tr, pet_easter.KIND_METHODS[kind]), kind
    assert tr.handler("late").__name__ == "on_hour"
    # 未知 kind 必须**抛**（不许 .get 静默返回 None）。用 pytest.raises 而不是
    # assert False —— 后者会被 test_assertion_strength 判成"恒假断言"。
    with pytest.raises(KeyError):
        tr.handler("bogus")


def test_late_clock_boundaries():
    """改什么会红：on_hour 里 time.localtime → time.gmtime（本机 UTC+8：23:00 本地 =
    15:00 UTC）→ 23:00 / 04:59 两条红；把 hour 缺省分支删掉（hour 停在 None）→
    所有正例变 None → 红；把 23:00 的 >= 改成 > → 23:00 不响红。
    """
    def hit(ts):
        return pet_easter.EasterTracker(now=Clock(ts)).on_hour()

    assert hit(_local(2026, 11, 16, 22, 59)) is None
    assert hit(_local(2026, 11, 16, 23, 0)) == "late"
    assert hit(_local(2026, 11, 17, 4, 59)) == "late"
    assert hit(_local(2026, 11, 17, 5, 0)) is None


def test_late_reads_local_clock_even_on_utc_host(monkeypatch):
    """改什么会红：on_hour 把 time.localtime 换成 time.gmtime → 本用例在 UTC 主机上也红。

    做法：只把 localtime 返回的小时钉成 23（日期/分秒不动，gmtime 保持真实），
    不写任何时区偏移。UTC 主机上真实 gmtime 小时不可能是 23（这里 ts 是 14:00），
    所以 gmtime 版本必返回 None；localtime 版本拿钉好的 23 命中。
    """
    ts = _local(2026, 11, 16, 14, 0)
    real_localtime = time.localtime

    def fake_localtime(t):
        st = real_localtime(t)
        return time.struct_time((st.tm_year, st.tm_mon, st.tm_mday, 23,
                                 st.tm_min, st.tm_sec, st.tm_wday, st.tm_yday, st.tm_isdst))

    monkeypatch.setattr(time, "localtime", fake_localtime)
    assert pet_easter.EasterTracker(now=lambda: ts).on_hour() == "late"


def test_explicit_hour_still_respected():
    """改什么会红：把 on_hour 的 hour 参数吞掉（永远用时钟）→ 14:00 传 23 不响 → 红。"""
    tr = pet_easter.EasterTracker(now=Clock(_local(2026, 11, 16, 14, 0)))
    assert tr.on_hour(23) == "late"
    tr2 = pet_easter.EasterTracker(now=Clock(_local(2026, 11, 16, 23, 10)))
    assert tr2.on_hour(22) is None


def test_normalize_filters_bad_sent():
    """改什么会红：删掉 normalize_state 里的 KINDS 过滤（直接 list(sent)）→
    st["sent"] == ["late", "bogus", 3] 红；把 out["day"] = day 换成 pass →
    st["day"] 断言红（后面的 tracker 也会把同一个 day 当成换天，late 又能响）。
    """
    ts = _local(2026, 11, 16, 23, 10)
    day = _local_day(ts)
    raw = {"day": day, "sent": ["late", "bogus", 3], "last": 0}
    st = pet_easter.normalize_state(raw)
    assert st["day"] == day
    assert st["sent"] == ["late"]

    tr = pet_easter.EasterTracker(now=lambda: ts, state=raw)
    assert tr.on_hour() is None, "同一天 + late 已发过 → 必须静音（day 丢了才会误判换天）"
    tr2 = pet_easter.EasterTracker(
        now=lambda: ts, state={"day": day, "sent": ["bogus", 3], "last": 0})
    assert tr2.on_hour() == "late", "坏 sent 不许把用户静音"


def test_poke_hit_clears_window():
    """改什么会红：删掉 on_poke 命中后的 self._pokes = [] → 下面的 _pokes == [] 红。
    注意：命中后同一天再戳 6 下本来就都返回 None —— 第 8 下先被 _emit 的每日闸挡，
    所以那 6 下**不能**单独当清窗的判据（实测：删掉清窗它们仍然全是 None）。
    """
    c = Clock(_local(2026, 11, 16, 14, 0))
    tr = pet_easter.EasterTracker(now=c)
    for _ in range(6):
        assert tr.on_poke() is None
    assert tr.on_poke() == "poke"
    assert tr._pokes == [], "命中后必须清窗（否则窗口里还留着 7 个旧戳）"
    for _ in range(6):
        assert tr.on_poke() is None


def test_poke_window_expiry():
    """改什么会红：删掉 on_poke 里的窗口过滤（self._pokes = [...]）→ 6 次隔 1s 全留下，
    第 7 下立刻响 → 最后一条 None 红。
    """
    c = Clock(_local(2026, 11, 16, 14, 0))
    tr = pet_easter.EasterTracker(now=c, opts={"poke_window": 4.0})
    for _ in range(6):
        assert tr.on_poke() is None
        c.advance(1.0)                   # 每下隔 1s，6 下共 6s > 4s 窗口
    assert tr.on_poke() is None          # 窗口外的旧戳已过期，这次只算第 1 下


def test_feed_hit_clears_window():
    """改什么会红：删掉 on_feed 命中后的 self._feeds = [] → 下面的 _feeds == [] 红。
    同 poke：第 4 下仍 None 是每日闸挡的，不是清窗的证据。
    """
    c = Clock(_local(2026, 11, 16, 14, 0))
    tr = pet_easter.EasterTracker(now=c)
    assert tr.on_feed() is None
    assert tr.on_feed() is None
    assert tr.on_feed() == "feed"
    assert tr._feeds == [], "命中后必须清窗"
    assert tr.on_feed() is None


def test_same_day_only_once():
    """改什么会红：删掉 _emit 里的 if kind in self.state["sent"] → 23:30（全局冷却已过）
    再响 late → 红。advance 少于 1800 会被冷却先挡，测不到每日闸，所以必须 1801。
    """
    c = Clock(_local(2026, 11, 16, 23, 0))
    tr = pet_easter.EasterTracker(now=c)
    assert tr.on_hour() == "late"
    c.advance(1801)                      # 23:30，同一天，30 分钟冷却已过
    assert tr.on_hour() is None          # 同一类一天只一次


def test_next_day_fires_again():
    """改什么会红：删掉 _emit 里的 _roll_day(now) 调用 → 次日仍 None → 红；
    _roll_day 不清 sent（删掉 "sent": []）→ 次日仍 None → 红。
    """
    c = Clock(_local(2026, 11, 16, 23, 30))
    tr = pet_easter.EasterTracker(now=c)
    assert tr.on_hour() == "late"
    c.t = _local(2026, 11, 17, 23, 30)   # 次日
    assert tr.on_hour() == "late"


def test_global_cooldown_blocks_other_kinds():
    """改什么会红：删掉 _emit 里的 cooldown 判断 → 60s 后 corner 立刻响 → 红。"""
    c = Clock(_local(2026, 11, 16, 23, 0))
    tr = pet_easter.EasterTracker(now=c)
    assert tr.on_hour() == "late"
    c.advance(60)                        # 1 分钟后，换一类
    assert tr.on_corner(99) is None      # 全局冷却 30 分钟仍在窗口内
    c.advance(1800 - 60 + 1)             # 总 1801s，23:30
    assert tr.on_corner(99) == "corner"


def test_disabled_is_silent():
    """改什么会红：删掉 _emit 的 if not self.enabled → 23:10 的 on_hour 响 → 红；
    把 enabled 写死 True → 同。
    """
    c = Clock(_local(2026, 11, 16, 23, 10))
    tr = pet_easter.EasterTracker(now=c, enabled=False)
    assert tr.on_hour() is None
    assert tr.on_corner(99) is None
    for _ in range(9):
        assert tr.on_poke() is None
    st = tr.to_cfg()
    assert st["sent"] == [] and st["last"] == 0.0   # 关掉 = 一个字节都不写状态


def test_corner_requires_dwell():
    """改什么会红：on_corner 的 dwell < corner_sec 改成 <= → 8.0 不响 → 红；
    把阈值写死 7.0 → 7.9 响 → 红。
    """
    c = Clock(_local(2026, 11, 16, 14, 0))
    tr = pet_easter.EasterTracker(now=c)
    assert tr.on_corner(7.9) is None
    assert tr.on_corner(8.0) == "corner"


def test_bad_state_never_mutes():
    """改什么会红：删掉 normalize_state 的 raw dict 守卫 → "x".get 抛 AttributeError；
    删掉 day 的 isinstance(str) 守卫 → st["day"] 变成 1 → 红；
    删掉 sent 的 list/tuple 守卫 → {"late": True} 迭代出 "late" 被保留 → 当天的 late 被静音；
    删掉 _as_number 的 inf/nan 守卫 → st["last"] 断言红（inf 还会让冷却永久生效）。
    """
    for bad in (None, "x", 1, [], {"day": 1, "sent": "oops", "last": "nan"}):
        st = pet_easter.normalize_state(bad)
        assert isinstance(st["day"], str)
        assert st["sent"] == []
        assert st["last"] == 0.0

    st = pet_easter.normalize_state({"day": "2026-01-01", "sent": {"late": True}, "last": 0})
    assert st["sent"] == []
    assert pet_easter.normalize_state(
        {"day": "x", "sent": [], "last": float("inf")})["last"] == 0.0
    assert pet_easter.normalize_state(
        {"day": "x", "sent": [], "last": float("nan")})["last"] == 0.0

    ts = _local(2026, 11, 16, 23, 10)
    tr = pet_easter.EasterTracker(
        now=lambda: ts,
        state={"day": "2000-01-01", "sent": ["late"], "last": float("inf")})
    assert tr.on_hour() == "late", "last=inf 必须洗干净，旧 day 换天 → 今天仍能响"
    tr2 = pet_easter.EasterTracker(
        now=lambda: ts,
        state={"day": _local_day(ts), "sent": {"late": True}, "last": 0})
    assert tr2.on_hour() == "late", "sent 是 dict 属于坏值，不许静音"


def test_near_corner_geometry():
    """改什么会红：改回"窗口中心到屏幕边" → 左上 320×320 窗为假（中心离边 160px）；
    <= 改 < → 24px 边界为假；radius 写死 48 → 30px 边距也为真；只看横向 →
    (0,140,320,460) 为真；只看纵向 → (340,0,660,320) 为真；去掉 abs → -100px 远离为真。
    """
    screen = (0, 0, 1000, 600)
    assert pet_easter.CORNER_RADIUS_PX == 24

    # 贴齐左上 / 右下 / 探出 5px / 恰好 24px 边距：都算贴角
    assert pet_easter.near_corner((0, 0, 320, 320), screen) is True
    assert pet_easter.near_corner((680, 280, 1000, 600), screen) is True
    assert pet_easter.near_corner((-5, -5, 315, 315), screen) is True
    assert pet_easter.near_corner((24, 24, 344, 344), screen) is True

    # 居中 / 边距 30px（> 24）/ 边距 25px：都不算
    assert pet_easter.near_corner((340, 140, 660, 460), screen) is False
    assert pet_easter.near_corner((30, 30, 350, 350), screen) is False
    assert pet_easter.near_corner((25, 25, 345, 345), screen) is False
    assert pet_easter.near_corner((25, 25, 345, 345), screen, radius=25) is True

    # 单边贴边不够：横向/纵向两个方向都得近
    assert pet_easter.near_corner((0, 140, 320, 460), screen) is False
    assert pet_easter.near_corner((340, 0, 660, 320), screen) is False

    # 远离屏幕 100px 不算（探出 5px 才算，见上）
    assert pet_easter.near_corner((-100, -100, 220, 220), screen) is False

    # 多显示器：屏幕原点不是 0 也要按对应边算
    screen2 = (1920, 0, 3840, 1080)
    assert pet_easter.near_corner((1920, 0, 2240, 320), screen2) is True
    assert pet_easter.near_corner((2260, 140, 2580, 460), screen2) is False


# ===================== 接线（v2.12.0 第 12 轮 · E1 四处钩子） =====================
#
# 纯逻辑绿了不等于功能存在：钩子没接，用户侧一个彩蛋都不会出现。下面几条钉住接线本身。
# 每条都能真失败：删掉对应调用/赋值/开关判断 -> 点名的那条红。


def _src(name):
    return open(os.path.join(HERE, name), encoding="utf-8").read()


def test_hooks_are_wired_in_window():
    """改什么会红：删掉 桌宠.py 里任意一处 _easter_check(...) 调用（poke 已实测）
    → 对应断言红；删掉 _easter_corner_sample 方法 → 最后一条红。
    """
    src = _src("桌宠.py")
    assert '_easter_check("poke")' in src, "点击钩子没接"
    assert '_easter_check("feed")' in src, "喂食钩子没接"
    assert '_easter_check("corner"' in src, "角落钩子没接"
    assert "def _easter_corner_sample(self):" in src, "角落采样方法没定义"


def test_late_hook_is_wired_in_idle_tick():
    """改什么会红：删掉 pet_actions.py 的 idle_tick 里 _easter("late") → 红。"""
    src = _src("pet_actions.py")
    assert '_easter("late")' in src, "深夜钩子没接（idle_tick 里那句）"


def test_corner_timer_respects_switch():
    """改什么会红：删掉起定时器前的 cfg 开关判断 → 关掉也照跑；删掉 start(2000) → 红。"""
    src = _src("桌宠.py")
    i = src.index("self.easter_timer = QTimer(self)")
    j = src.index("self._idle_check_timer", i)
    seg = src[i:j]
    assert 'self.cfg.get("easter_eggs", True)' in seg, "采样定时器必须受开关控制"
    assert "easter_timer.start(2000)" in seg


def test_trigger_persists_to_cfg():
    """改什么会红：删掉 _easter_save 里 self.cfg["easter_sent"] 赋值 → 红；
    删掉 save_config 调用 → 红。
    """
    src = _src("桌宠.py")
    i = src.index("def _easter_save")
    seg = src[i:i + 400]
    assert 'self.cfg["easter_sent"]' in seg, "触发后必须落盘（否则重启就重响）"
    assert "save_config" in seg


def test_trigger_is_silent_when_off():
    """改什么会红：把 _easter_tracker 里的 enabled=enabled 改成 enabled=True → 红；
    删掉 cfg 开关读取 → 红。
    """
    src = _src("桌宠.py")
    i = src.index("def _easter_tracker")
    seg = src[i:i + 700]
    assert 'self.cfg.get("easter_eggs", True)' in seg
    assert "enabled=enabled" in seg


def test_quit_stops_easter_timer():
    """改什么会红：从 _quit 的清理元组删掉 self.easter_timer 这一项 → 红。

    这条替代旧的 assert "self.easter_timer" in src：旧断言只要文件里出现这串字就真，
    注释里有一份也算，永远不可能失败。现在要求它真的是 for 循环元组的一个元素。
    """
    tree = ast.parse(_src("桌宠.py"))
    quit_fns = [n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "_quit"]
    assert quit_fns, "桌宠.py 里找不到 _quit"
    quit_fn = quit_fns[0]
    stopped = []
    for node in ast.walk(quit_fn):
        if isinstance(node, ast.For) and isinstance(node.iter, (ast.Tuple, ast.List)):
            for elt in node.iter.elts:
                if (isinstance(elt, ast.Attribute)
                        and isinstance(elt.value, ast.Name)
                        and elt.value.id == "self"):
                    stopped.append(elt.attr)
    assert "easter_timer" in stopped, "退出清理元组没停 self.easter_timer"
