# -*- coding: utf-8 -*-
"""E2 时间感知情绪（v2.11.0 · 旧第 8 轮那批的第 ⑧ 项）：pet_time_mood 的七条判据 + 五组结构钉子（6 条用例）。

来路：用户 #194 提交的两份附件方案里的 UX E2，用户 2026-10-16 裁决并入 v2.11.0
（_dev/REMAINING.md §十三 第 ⑧ 行；作业单 _dev/task_r11_v2110_round.md W4-c）。
原方案一条判据都没写 —— 本文件就是它的判据。

这个文件不建窗口、不读系统时钟、不碰磁盘：被测模块 0 个 Qt import，时刻与记账都是入参，
所以「一天 1440 分钟穷举」在毫秒级跑完（判据 ⑤）。

七条判据（编号与作业单一致），每条都写了「拿掉哪行会红」
----------------------------------------------------------
① 五段各自命中且文案非空 ....... test_five_slots_are_reachable_with_non_empty_text
② 同一天重复调用只出一次 ....... test_second_call_on_the_same_day_is_silent
③ 跨天清零后又出 ............... test_next_day_fires_again
④ 端点归属 ..................... test_endpoints_belong_to_exactly_one_block
⑤ 1440 分钟穷举 ............... test_every_minute_lands_in_at_most_one_slot
⑥ enabled=False → 永远 None ... test_disabled_is_silent_at_every_minute
⑦ 坏输入不抛、返回 None ....... test_bad_inputs_yield_none_without_raising

五组结构钉子（判据之外，防「判据还在、被测的东西已经变形」）
------------------------------------------------------------
· 五段 = 方案原文的五个窗口，端点值逐个点名 ....... test_slot_table_is_the_five_windows_from_the_plan
· 低优先只给早安 / 催睡 + 压不压的规则 ........... test_priority_is_low_exactly_for_morning_and_sleep
                                                  test_may_interrupt_lets_normal_slots_replace_but_not_low_ones
· 台词来源四条路径（默认 / 注入 / 删光 / 坏值）... test_pick_line_is_deterministic_and_overrides_win
· remember 纯函数、不改入参 ...................... test_remember_returns_a_new_copy_and_never_mutates
· 模块 0 个 Qt import、不取系统时钟、不碰文件 ..... test_module_stays_qt_free_and_clock_free
"""
import ast
import datetime as dt
import io

import pytest

import pet_time_mood as tm

DAY = dt.date(2026, 10, 16)


def _at(h, m=0, s=0, day=DAY):
    """某天 h:m:s → datetime（本文件的时刻一律这么造：显式、可读、不碰系统时钟）。"""
    return dt.datetime(day.year, day.month, day.day, h, m, s)


# 五段的代表时刻：都取在时段中间，**故意不取端点**（端点归判据 ④）
SAMPLE = {
    "sleep": _at(3, 0),
    "morning": _at(8, 30),
    "lunch": _at(12, 30),
    "coffee": _at(14, 30),
    "rest": _at(23, 0),
}


# ======================== 判据 ① ========================

def test_five_slots_are_reachable_with_non_empty_text():
    """五段各自命中，且文案非空。

    能真失败：
    · 把 SLOTS 里任一段的 start_min / end_min 改错（morning 480 → 481、lunch 720 → 700 之类的
      一千零一种走法）→ 8:30 / 12:30 那次返回 None，这条立刻红（并点名是哪一段）；
    · 把任一段的 lines 清成空元组 → pick_line 走「删光了不念」返回 ""，due 返回 None → 红；
    · 把 pick_line 末尾的 return pool[...] 改成 return "" → 文案空 → 红。
    """
    assert len(tm.slots()) == 5, "五段是方案原文的窗口数，不是随便几个"
    for s in tm.slots():
        rep = SAMPLE[s.key]
        got = tm.due(rep, {}, enabled=True)
        assert got is not None, "%s 在 %s 没命中" % (s.key, rep.strftime("%H:%M"))
        key, text = got
        assert key == s.key, "命中错了段：%r != %r" % (key, s.key)
        assert isinstance(text, str) and text.strip(), "%s 的文案是空的 / 只有空白" % s.key
        assert text in s.lines, "%s 的文案不在默认池里：%r" % (s.key, text)
    # state=None 必须等价于「什么都没发过」：首次运行就是这个值，不许因此整天不弹
    got = tm.due(SAMPLE["lunch"], None, enabled=True)
    assert got is not None and got[0] == "lunch"


# ======================== 判据 ② ========================

def test_second_call_on_the_same_day_is_silent():
    """同一天同一段只出一次；同一段不许把别的段一起压掉（跨时段要能触发新 slot）。

    能真失败：
    · 把 due 里 `if last == now.date().isoformat(): return None` 这行删掉 → 第二次照样出 → 红；
    · 把 _last_fired 写成不按 key 取值（例如读 state.get("date")）→ 同一天第二段出不来 → 红；
    · 把 remember 写成 return state（不写新值）→ 第 3 条断言（已记账后必须静默）红。
    """
    first = tm.due(SAMPLE["coffee"], {}, enabled=True)
    assert first is not None
    state = tm.remember({}, SAMPLE["coffee"], first[0])
    assert state == {"coffee": "2026-10-16"}, state
    # 同一段里连问 5 次，一次都不许再出
    assert [tm.due(SAMPLE["coffee"], state, enabled=True) for _ in range(5)] == [None] * 5
    # 14:59:59 仍在同一段（左闭右开）：照样静默
    assert tm.due(_at(14, 59, 59), state, enabled=True) is None
    # 但同一段的记账不许影响别的段（跨时段要能触发新 slot）
    other = tm.due(SAMPLE["lunch"], state, enabled=True)
    assert other is not None and other[0] == "lunch"


# ======================== 判据 ③ ========================

def test_next_day_fires_again():
    """跨天自动清零：昨天的记账不许挡住今天，今天的记账也不许挡住明天。

    能真失败：把 _last_fired 改成「只要 state 里 keys 非空就算今天已发」（不看日期）→
    第二天那次 due 变 None → 红；把 remember 的日期写成常量 → 第三天的断言红。
    """
    s1 = tm.remember({}, _at(8, 30), "morning")
    assert s1 == {"morning": "2026-10-16"}
    assert tm.due(_at(8, 31), s1, enabled=True) is None, "今天已发却还出"
    day2 = _at(8, 30, 0, dt.date(2026, 10, 17))
    assert tm.due(day2, s1, enabled=True) is not None, "跨天没清零"
    s2 = tm.remember(s1, day2, "morning")
    assert s2 == {"morning": "2026-10-17"}, s2
    assert tm.due(_at(8, 31, 0, dt.date(2026, 10, 17)), s2, enabled=True) is None
    assert tm.due(_at(8, 31, 0, dt.date(2026, 10, 18)), s2, enabled=True) is not None
    # 跨年那一夜也必须翻篇（字符串比较的话 "2027-01-01" > "2026-12-31" 才对；
    # 如果谁把日期比成"大小"而不是"相等"，这里会红）
    s3 = tm.remember({}, _at(23, 30, 0, dt.date(2026, 12, 31)), "rest")
    assert tm.due(_at(23, 45, 0, dt.date(2026, 12, 31)), s3, enabled=True) is None
    assert tm.due(_at(23, 45, 0, dt.date(2027, 1, 1)), s3, enabled=True) is not None


# ======================== 判据 ④ ========================

def test_endpoints_belong_to_exactly_one_block():
    """端点归属：左闭右开 + 分钟粒度，每个接缝的两侧逐秒点名一遍。

    能真失败：把 slot_at 的 `s.start_min <= minute < s.end_min` 任一侧改成 <=（含右端点）→
    09:30:00 / 06:00:00 / 15:00:00 那几行红；把判定改成看 now.second → 09:29:59 那行红；
    把 rest 的 end_min 从 1440 改小 → 23:59:59 那行红（0 点那条属于 sleep，另一侧会红）。
    """
    cases = [
        # (时刻, 应归属)
        (_at(0, 0, 0), "sleep"),          # ★ 00:00 整归催睡，不归「该休息」
        (_at(5, 59, 59), "sleep"),        # 催睡段最后一秒
        (_at(6, 0, 0), None),             # 06:00 起是空档
        (_at(7, 59, 59), None),
        (_at(8, 0, 0), "morning"),        # 早安起点（含）
        (_at(9, 29, 59), "morning"),      # ★ 09:29:59 还归早安
        (_at(9, 30, 0), None),            # ★ 09:30:00 整已经出界
        (_at(11, 59, 59), None),
        (_at(12, 0, 0), "lunch"),
        (_at(12, 59, 59), "lunch"),
        (_at(13, 0, 0), None),
        (_at(13, 59, 59), None),
        (_at(14, 0, 0), "coffee"),
        (_at(14, 59, 59), "coffee"),
        (_at(15, 0, 0), None),
        (_at(21, 59, 59), None),
        (_at(22, 0, 0), "rest"),          # 该休息起点（含）
        (_at(23, 59, 59), "rest"),        # ★ 当天最后一秒
    ]
    for t, want in cases:
        s = tm.slot_at(t)
        got = None if s is None else s.key
        assert got == want, "%s 归 %r，应为 %r" % (t.strftime("%H:%M:%S"), got, want)
        # 同一个读数必须与 due 那条路一致：两处各写一份判断就会漂移
        d = tm.due(t, {}, enabled=True)
        assert (d[0] if d is not None else None) == want, "%s 的 due 与 slot_at 不一致" % t
    # 秒不进界：09:30:00.999999 仍然是「无」（判定按分钟，秒与微秒不参与）
    assert tm.slot_at(dt.datetime(2026, 10, 16, 9, 30, 0, 999999)) is None
    # 但 09:29:59.999999 仍是早安（同一分钟内，秒不分段）
    last = tm.slot_at(dt.datetime(2026, 10, 16, 9, 29, 59, 999999))
    assert last is not None and last.key == "morning"


# ======================== 判据 ⑤ ========================

def test_every_minute_lands_in_at_most_one_slot():
    """1440 分钟穷举：每个时刻恰好落在一段或「无」，且没有任何一分钟被两段同时收下。

    能真失败：
    · 把任意一段的窗口改宽成与邻段重叠（morning 480-580）→ `len(inside) <= 1` 那条红；
    · 把窗口整体挪动（sleep 0 → 60）→ 分钟计数表里 sleep/None 的数目变 → 红；
    · 让 due 顺手改 state（写成 state[key] = ...）→ `assert state == {}` 红（纯函数契约）；
    · 把 rest 的 end_min 从 1440 改小 → 「22:00→06:00 那一圈」留洞 → 红。
    """
    state = {}   # 故意复用同一个字典：due 是纯函数，跑完必须还是空的
    hits = {}
    for minute in range(1440):
        t = _at(minute // 60, minute % 60)
        # ① 用**表本身**数一遍「有几段收了这一分钟」——这条才看得见重叠
        inside = [s.key for s in tm.slots() if s.start_min <= minute < s.end_min]
        assert len(inside) <= 1, "第 %d 分钟被 %r 同时归进几段（重叠）" % (minute, inside)
        s = tm.slot_at(t)
        d = tm.due(t, state, enabled=True)
        # ② slot_at 与 due 必须给出同一个答案
        assert (d[0] if d is not None else None) == (s.key if s is not None else None), t
        if d is not None:
            assert d[1].strip() != "", "第 %d 分钟出了条空气泡" % minute
        bucket = s.key if s is not None else None
        hits[bucket] = hits.get(bucket, 0) + 1
    assert state == {}, "due 改了 state（纯函数契约被破坏）：%r" % (state,)
    # ③ 「相邻不留洞」的那一对：22:00 → 06:00 跨午夜首尾相接，一分钟都不能掉。
    #    **故意放在计数表前面**：留洞时先得到"哪几分钟掉进洞里"这句诊断，而不是一张直方图差异
    #    （同在一条用例里，先跑到哪句就先看见哪句）。
    rest, sleep = tm.slot("rest"), tm.slot("sleep")
    assert rest is not None and sleep is not None
    assert (rest.end_min, sleep.start_min) == (1440, 0), \
        "跨午夜那两段没接上（0 点会掉进洞里）：%r" % ((rest.end_min, sleep.start_min),)
    wrapped = list(range(rest.start_min, 1440)) + list(range(0, sleep.end_min))
    holes = [m for m in wrapped
             if not any(s.start_min <= m < s.end_min for s in tm.slots())]
    assert holes == [], "22:00→06:00 这一圈留了 %d 个洞：%r" % (len(holes), holes[:5])
    # ④ 逐段数目：360 + 90 + 60 + 60 + 120 = 690 分钟有归属，其余 750 分钟无归属
    assert hits == {None: 750, "sleep": 360, "morning": 90, "lunch": 60,
                    "coffee": 60, "rest": 120}, hits
    assert sum(v for k, v in hits.items() if k is not None) == 690


# ======================== 判据 ⑥ ========================

def test_disabled_is_silent_at_every_minute():
    """默认关闭：enabled=False（以及任何不是 True 的值）永远 None —— 一天 1440 分钟逐分钟验。

    能真失败：把 due 的 `if enabled is not True: return None` 改成 `if not enabled`（于是字符串
    "false" 也被当成打开）→ 下面那句 "true" 的断言红；整行删掉 → 1440 分钟那一圈红；
    把默认值改成 True（`enabled=True`）→ 不传 enabled 的那句红。
    """
    for minute in range(1440):
        assert tm.due(_at(minute // 60, minute % 60), {}, enabled=False) is None, minute
    # 缺省入参（不传 enabled）也必须静默：老用户升级后不许突然多出气泡
    assert tm.due(SAMPLE["morning"], {}) is None
    # 只认 True：配置里读出来的字符串 / 1 / 空值一律不算打开
    for bad in (0, 1, "", "true", "on", "1", None, [], {}, 1.0):
        assert tm.due(SAMPLE["morning"], {}, enabled=bad) is None, repr(bad)
    # 反证（防空转）：同一个时刻 enabled=True 就出；否则上面那一大批断言"全 None"可能只是因为
    # 这个时刻本来就无归属（那就什么都验不到）
    assert tm.due(SAMPLE["morning"], {}, enabled=True) is not None


# ======================== 判据 ⑦ ========================

def test_bad_inputs_yield_none_without_raising():
    """坏输入不抛、返回 None，且**不猜**（猜错的两个方向都比"这次不弹"更糟）。

    能真失败：把 due 里 `if not isinstance(now, datetime)` 那段（slot_at 的）删掉 → 传字符串时
    AttributeError 冒出来 → 红；把 `if last is None: return None` 删掉 → state 是坏类型时它
    会当成"今天什么都没发"并出气泡 → 红。
    """
    good = SAMPLE["morning"]
    assert tm.due(good, {}, enabled=True) is not None, "反证：好输入必须会出（否则本条空转）"
    bad_nows = (None, "2026-10-16 08:30", 20261016, 3.14, dt.date(2026, 10, 16),
                dt.time(8, 30), [], {})
    for now in bad_nows:
        assert tm.due(now, {}, enabled=True) is None, repr(now)
        assert tm.slot_at(now) is None, repr(now)
    bad_states = ("oops", 42, 3.14, ["morning"], ("morning",), {"morning"})
    for st in bad_states:
        assert tm.due(good, st, enabled=True) is None, repr(st)
    # 反证：同一时刻换成合法 state 就出
    assert tm.due(good, {"sleep": "2026-10-15"}, enabled=True) is not None
    # 单个值坏掉 ≠ state 坏掉：只坏这一格时按「没发过」处理（口径 4 的另一侧，明确写死）
    assert tm.due(good, {"morning": 20261016}, enabled=True) is not None
    assert tm.due(good, {"morning": None}, enabled=True) is not None


# ==================== 结构钉子（判据之外） ====================

def test_slot_table_is_the_five_windows_from_the_plan():
    """五段 = 方案原文的五个窗口，端点值逐个点名；表不可变（它是唯一真源）。

    能真失败：把任一段的窗口改动一个数字（例如 rest 1320 → 1300、morning 570 → 560）→ 红；
    去掉 dataclass 的 frozen=True → 赋值那行不再抛 → 红。
    """
    want = [("sleep", 0, 360), ("morning", 480, 570), ("lunch", 720, 780),
            ("coffee", 840, 900), ("rest", 1320, 1440)]
    assert [(s.key, s.start_min, s.end_min) for s in tm.slots()] == want
    assert isinstance(tm.slots(), tuple), "时段表必须是元组（可变表就没法当判据用）"
    with pytest.raises((AttributeError, TypeError)):
        tm.slots()[0].start_min = 1   # type: ignore[misc]  # frozen 表的自证
    # 每段的默认台词池：非空、3 句、两两不同（同一段里说两遍同一句像卡带）
    for s in tm.slots():
        assert len(s.lines) == 3 and len(set(s.lines)) == 3, (s.key, s.lines)
        assert all(isinstance(x, str) and x.strip() for x in s.lines), s.key


def test_priority_is_low_exactly_for_morning_and_sleep():
    """「不刷屏」的第一半：只有早安 / 催睡是低优先，其余普通；不认识的 key 没有优先级。

    能真失败：把 lunch 的 priority 改成 PRIORITY_LOW（或把 morning 改成 NORMAL）→ 集合不等 → 红。
    """
    low = set(k for k in SAMPLE if tm.priority_of(k) == tm.PRIORITY_LOW)
    assert low == {"morning", "sleep"}, low
    for k in ("lunch", "coffee", "rest"):
        assert tm.priority_of(k) == tm.PRIORITY_NORMAL, k
    assert tm.priority_of("nope") is None
    assert tm.priority_of(None) is None
    assert tm.PRIORITY_LOW < tm.PRIORITY_NORMAL, "优先级是「数字大的更能压」，大小关系不许反"


def test_may_interrupt_lets_normal_slots_replace_but_not_low_ones():
    """「不刷屏」的第二半：低优先不压在途气泡；普通优先允许覆盖；没有在途气泡时谁都该发。

    能真失败：把 may_interrupt 的 `return p > PRIORITY_LOW or not bubble_in_flight` 写成
    `return True` → 早安那两条红；写成 `return not bubble_in_flight` → 午餐/咖啡/该休息
    那三条红；把 p is None 分支删掉 → 不认识的 key 会抛 TypeError → 红。
    """
    assert tm.may_interrupt("morning", True) is False
    assert tm.may_interrupt("sleep", True) is False
    assert tm.may_interrupt("lunch", True) is True
    assert tm.may_interrupt("coffee", True) is True
    assert tm.may_interrupt("rest", True) is True
    assert tm.may_interrupt("morning", False) is True
    assert tm.may_interrupt("sleep", False) is True
    assert tm.may_interrupt("nope", False) is False


def test_pick_line_is_deterministic_and_overrides_win():
    """台词来源四条路径：默认池 / 注入池 / 删光不念 / 坏值回落；同一段同一天总是同一句。

    能真失败：把 pick_line 的 `if not pool: return pool[0]` 顺序改坏（删光时回落内置）→ "删光"那条红；
    把 overrides 分支删掉 → 注入那条红；把 "坏类型回落内置" 改成"坏类型当删光" → 回落那条红；
    把下标里的日期序数换成 random → 同一天两句不同 → 红（大概率先红）。
    """
    s = tm.slot("morning")
    a = tm.pick_line("morning", _at(8, 30))
    b = tm.pick_line("morning", _at(9, 29))          # 同一天、同一段的另一分钟
    assert a == b and a in s.lines, (a, b)
    assert tm.pick_line("morning", _at(8, 30), {"morning": ["自定义一句"]}) == "自定义一句"
    assert tm.pick_line("morning", _at(8, 30), {"morning": []}) == ""            # 删光 → 不念
    assert tm.pick_line("morning", _at(8, 30), {"morning": ["  ", ""]}) == ""    # 只剩空白 → 不念
    assert tm.pick_line("morning", _at(8, 30), {"morning": 42}) in s.lines       # 坏值 → 回落
    assert tm.pick_line("morning", _at(8, 30), "oops") in s.lines                # 整个 overrides 坏 → 回落
    assert tm.pick_line("nope", _at(8, 30)) == ""                                # 不认识的 key
    assert tm.pick_line("morning", None) in s.lines                              # 坏时钟 → 第一句、不抛
    # 换一天允许（不保证）换一句：只钉「永远来自池子」，不钉具体是哪句
    assert tm.pick_line("morning", _at(8, 30, 0, dt.date(2026, 10, 17))) in s.lines
    # due 这条路也要跟着走：注入的池子删光 → 这一句不弹（不是弹个空气泡）
    assert tm.due(_at(8, 30), {}, enabled=True, overrides={"morning": []}) is None
    got = tm.due(_at(8, 30), {}, enabled=True, overrides={"morning": ["只此一句"]})
    assert got == ("morning", "只此一句"), got


def test_remember_returns_a_new_copy_and_never_mutates():
    """记账是纯函数：返回新副本、入参一个字节都不改；坏输入不抛。

    能真失败：把 remember 改成 out = state（就地）→ 入参被改 → 红；把 `if isinstance(now, datetime)`
    删掉 → 传 None 时 AttributeError → 红；把 out 的初值写成 {} 而不是入参副本 → 第一条红。
    """
    src = {"morning": "2026-10-15"}
    out = tm.remember(src, _at(12, 30), "lunch")
    assert out == {"morning": "2026-10-15", "lunch": "2026-10-16"}, out
    assert src == {"morning": "2026-10-15"}, src
    assert out is not src
    # 坏 state / 坏 now：不抛。坏 state 只能重建成新表（没人能说出它昨天发过什么）
    assert tm.remember("oops", _at(12, 30), "lunch") == {"lunch": "2026-10-16"}
    assert tm.remember(None, _at(12, 30), "lunch") == {"lunch": "2026-10-16"}
    assert tm.remember({"lunch": "2026-10-16"}, None, "lunch") == {"lunch": "2026-10-16"}


def test_module_stays_qt_free_and_clock_free():
    """结构钉子：0 个 Qt import、不取系统时钟、不碰文件 —— 这是「能注入、能穷举」的前提。

    能真失败：加一行 `from PySide6.QtCore import QTimer` → 第一条红；在 due 里加一句
    `now = datetime.now()` → 第二条红；加一句 open(...) 写盘 → 第三条红。
    （任务书 §四.3「新建对象数回基线」在这个包上是**更强**的形态：一个 Qt 对象都不建。）
    """
    src = io.open(tm.__file__, encoding="utf-8").read()
    tree = ast.parse(src)
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            mods.add((node.module or "").split(".")[0])
    assert not (mods & {"PySide6", "shiboken6"}), "本模块必须 0 个 Qt import：%r" % (mods,)
    # 只许标准库里的这三个（也就等于「不新增第三方依赖」这条硬约束）
    assert mods == {"datetime", "collections", "dataclasses"}, mods
    calls = [ast.unparse(n.func) for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
    clock = [c for c in calls
             if c.endswith((".now", ".today", ".utcnow", ".localtime", ".time", ".mktime"))]
    assert clock == [], "本模块不许自己取时钟（now 必须由调用方注入）：%r" % (clock,)
    plain = [ast.unparse(n.func) for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
    assert "open" not in plain, "纯逻辑模块不许碰文件和磁盘：%r" % (plain,)
