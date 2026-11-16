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


def _tree(name):
    return ast.parse(_src(name))


def _methods(tree):
    return {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}


def _const_str(node, value=None):
    """node 是字符串常量（给了 value 时还要求字面量相等）。"""
    return (isinstance(node, ast.Constant) and isinstance(node.value, str)
            and (value is None or node.value == value))


def _calls(node):
    return [n for n in ast.walk(node) if isinstance(n, ast.Call)]


# ⚠ 2026-11-16（第 13 轮 · 遗留-13）：下面五条**全部换成 AST**。此前读源码字符串，
# 把调用注释掉照样绿（独立验收 X1 实测：_easter_check("poke") 改成注释 → rc=0）。
# 注释天然不进语法树，所以 AST 判据对"注释可满足"这一类免疫。


def test_hooks_are_wired_in_window():
    """改什么会红：把任意一处 _easter_check("poke"/"feed"/"corner") 调用**注释掉**
    （字还在注释里）→ 对应集合缺项 → 红；删掉 _easter_corner_sample 方法定义 → 红。

    v2.12.0 旧版读源码字符串，注释掉仍然绿（遗留-13 的原始 bug）。
    """
    tree = _tree("桌宠.py")
    wired = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not (isinstance(fn, ast.Attribute) and fn.attr == "_easter_check"):
            continue
        if node.args and _const_str(node.args[0]):
            wired.add(node.args[0].value)
    assert {"poke", "feed", "corner"} <= wired, "彩蛋钩子没接：缺 %r" % (
        {"poke", "feed", "corner"} - wired,)
    assert "_easter_corner_sample" in _methods(tree), "角落采样方法没定义"


def test_late_hook_is_wired_in_idle_tick():
    """改什么会红：把 idle_tick 里那句 _easter("late") 注释掉/删掉 → 红；
    把它挪出 idle_tick（挂到别处）→ 红（本条只认 idle_tick 函数体里的调用）。
    """
    tree = _tree("pet_actions.py")
    fn = _methods(tree).get("idle_tick")
    assert fn is not None, "pet_actions.py 里找不到 idle_tick"
    hits = [c for c in _calls(fn)
            if isinstance(c.func, ast.Name) and c.func.id == "_easter"
            and c.args and _const_str(c.args[0], "late")]
    assert hits, "深夜钩子没接（idle_tick 里那句 _easter(\"late\")）"


def test_corner_timer_respects_switch():
    """改什么会红：删掉 start(2000) 外层的 cfg 开关 if → 红；
    把开关判断挪到别处、start 无条件执行 → 红。
    """
    tree = _tree("桌宠.py")

    def _is_eggs_read(test):
        return any(isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                   and c.func.attr == "get" and c.args and _const_str(c.args[0], "easter_eggs")
                   for c in _calls(test))

    ok = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If) or not _is_eggs_read(node.test):
            continue
        for stmt in node.body:
            for call in _calls(stmt):
                if (isinstance(call.func, ast.Attribute) and call.func.attr == "start"
                        and call.args and isinstance(call.args[0], ast.Constant)
                        and call.args[0].value == 2000):
                    ok.append(call.lineno)
    assert ok, "采样定时器的 start(2000) 必须放在 cfg 的 easter_eggs 开关里"


def test_trigger_persists_to_cfg():
    """改什么会红：把 _easter_save 里 self.cfg["easter_sent"] = … 注释掉 → 红；
    删掉 save_config(self.cfg) 调用 → 红。
    """
    fn = _methods(_tree("桌宠.py")).get("_easter_save")
    assert fn is not None, "桌宠.py 里找不到 _easter_save"
    wrote = False
    for node in ast.walk(fn):
        if not isinstance(node, ast.Assign):
            continue
        for tgt in node.targets:
            if not isinstance(tgt, ast.Subscript):
                continue
            key = tgt.slice
            if not isinstance(key, ast.Constant) and hasattr(key, "value"):
                key = key.value  # Python 3.8 的 ast.Index 包装（3.10 下不会走到）
            if (isinstance(tgt.value, ast.Attribute) and tgt.value.attr == "cfg"
                    and isinstance(key, ast.Constant) and key.value == "easter_sent"):
                wrote = True
    assert wrote, "触发后必须落盘 self.cfg[\"easter_sent\"]（否则重启就重响）"
    assert any(isinstance(c.func, ast.Name) and c.func.id == "save_config"
               for c in _calls(fn)), "写了 cfg 却没调 save_config"


def test_trigger_is_silent_when_off():
    """改什么会红：把 enabled=enabled 改成 enabled=True（关掉开关也照响）→ 红；
    删掉 cfg 里 easter_eggs 的读取（enabled 变常量）→ 红。
    """
    fn = _methods(_tree("桌宠.py")).get("_easter_tracker")
    assert fn is not None, "桌宠.py 里找不到 _easter_tracker"
    reads_switch = any(isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                       and c.func.attr == "get" and c.args and _const_str(c.args[0], "easter_eggs")
                       for c in _calls(fn))
    assert reads_switch, "_easter_tracker 必须现读 cfg 的 easter_eggs 开关"
    passes_enabled = False
    for call in _calls(fn):
        if not (isinstance(call.func, ast.Attribute) and call.func.attr == "EasterTracker"):
            continue
        for kw in call.keywords:
            if kw.arg == "enabled" and isinstance(kw.value, ast.Name) and kw.value.id == "enabled":
                passes_enabled = True
    assert passes_enabled, "EasterTracker 必须收到 enabled=<开关变量>，不许写死 True"


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
