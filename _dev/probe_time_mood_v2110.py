# -*- coding: utf-8 -*-
"""E2 时间感知情绪的**可复跑探针**（v2.11.0 · 旧第 8 轮那批 ⑧ · 用户 #194 方案 + 2026-10-16 裁决）。

为什么要有它
------------
tests/test_time_mood_v2110.py 的判据是**断言**（红/绿），但"五段到底怎么切的、1440 分钟每一分钟
落在哪儿"这件事，人读断言是读不出来的。这个探针把那张表**打印出来**：换一个人（或下一轮）
不用读代码就能核对"0900 是不是空档、0 点归谁、22:00→06:00 这一圈接没接上"。

它只读不算：不改任何文件、不读系统时钟（所有时刻都是写死的），退出码 0（内部不变量不成立才 1）。

用法
----
    python -B _dev/probe_time_mood_v2110.py            # 打印表 + 逐分钟计数 + 注入示例
    python -B _dev/probe_time_mood_v2110.py --quiet    # 只打印最后一行
"""
import datetime as dt
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import pet_time_mood as tm  # noqa: E402

DAY = dt.date(2026, 10, 16)


def _at(h, m=0, s=0, day=DAY):
    return dt.datetime(day.year, day.month, day.day, h, m, s)


def _mm(minute):
    return "%02d:%02d" % (minute // 60, minute % 60)


def _report_table():
    print("五段时段表（[start, end) 左闭右开；优先级 10=低 / 20=普通）")
    print("  %-8s %-10s %-14s %-7s %s" % ("key", "label", "窗口", "分钟数", "优先级"))
    for s in tm.slots():
        print("  %-8s %-10s %-14s %-7d %d"
              % (s.key, s.label, "%s-%s" % (_mm(s.start_min), _mm(s.end_min)),
                 s.end_min - s.start_min, s.priority))


def _report_coverage():
    """逐分钟数一遍：每个时刻落在哪段（重叠会让某段多算，留洞会让 None 变多）。"""
    counts = {}
    overlaps = []
    for minute in range(1440):
        inside = [s.key for s in tm.slots() if s.start_min <= minute < s.end_min]
        if len(inside) > 1:
            overlaps.append((minute, inside))
        bucket = tm.slot_at(_at(minute // 60, minute % 60))
        key = bucket.key if bucket is not None else None
        counts[key] = counts.get(key, 0) + 1
    print("\n1440 分钟逐分钟归属（合计必须 = 1440；重叠 %d 处）" % len(overlaps))
    for key in [s.key for s in tm.slots()] + [None]:
        print("  %-8s %4d 分钟" % (key if key else "(无)", counts.get(key, 0)))
    print("  有归属合计 %d 分钟 / 空档 %d 分钟" % (
        sum(v for k, v in counts.items() if k is not None), counts.get(None, 0)))
    return counts, overlaps


def _report_seams():
    """窗口按时间排序后，相邻两段之间的缝：留了多久的空档（跨午夜的接缝单列）。"""
    print("\n相邻两段之间的空档（0 分钟 = 严丝合缝）")
    slots = list(tm.slots())
    for a, b in zip(slots, slots[1:]):
        gap = b.start_min - a.end_min
        print("  %-8s 结束 %s  →  %-8s 开始 %s   空档 %d 分钟"
              % (a.key, _mm(a.end_min) if a.end_min < 1440 else "24:00",
                 b.key, _mm(b.start_min), gap))
    last, first = slots[-1], slots[0]
    wrapped = last.end_min - last.start_min + (first.end_min - first.start_min)
    seam = (1440 - last.end_min) + first.start_min
    print("  %-8s 结束 24:00  →  %-8s 开始 00:00   空档 %d 分钟（跨午夜：%d 分钟连成一片）"
          % (last.key, first.key, seam, wrapped))
    print("  0 点整归 %r（不归 %r）" % (tm.slot_at(_at(0, 0)).key, last.key))


def _report_boundaries():
    print("\n端点归属（判据 ④ 的读数）")
    for t in (_at(9, 29, 59), _at(9, 30), _at(23, 59, 59), _at(0, 0), _at(6, 0), _at(22, 0)):
        s = tm.slot_at(t)
        got = tm.due(t, {}, enabled=True)
        print("  %s → slot_at=%-7s due=%s"
              % (t.strftime("%H:%M:%S"), s.key if s else None,
                 "%s / %s" % (got[0], got[1]) if got else None))


def _report_dedupe():
    print("\n当天去重 / 跨天清零（state 与时钟都是注入的，所以这两步能当场演示）")
    st = {}
    first = tm.due(_at(8, 30), st, enabled=True)
    print("  第 1 天 08:30  →", first)
    st = tm.remember(st, _at(8, 30), first[0])
    print("  记账后 state   →", st)
    print("  第 1 天 08:31  →", tm.due(_at(8, 31), st, enabled=True))
    print("  第 2 天 08:31  →", tm.due(_at(8, 31, 0, dt.date(2026, 10, 17)), st, enabled=True))
    print("  enabled=False  →", tm.due(_at(8, 30), {}, enabled=False))
    print("  坏输入 now=None→", tm.due(None, {}, enabled=True))


def main(argv):
    quiet = "--quiet" in argv
    if not quiet:
        _report_table()
    counts, overlaps = _report_coverage()
    if not quiet:
        _report_seams()
        _report_boundaries()
        _report_dedupe()
    # 内部不变量（不成立就红）：重叠 0 处 / 有归属 690 分钟 / 空档 750 分钟 / 0 点归催睡
    total = counts.get(None, 0) + sum(v for k, v in counts.items() if k is not None)
    problems = []
    if overlaps:
        problems.append("有 %d 分钟被两段同时收下：%r" % (len(overlaps), overlaps[:3]))
    if total != 1440:
        problems.append("逐分钟合计 %d != 1440" % total)
    if sum(v for k, v in counts.items() if k is not None) != 690:
        problems.append("有归属分钟数 != 690")
    if tm.slot_at(_at(0, 0)) is None or tm.slot_at(_at(0, 0)).key != "sleep":
        problems.append("0 点整不归催睡")
    print("\n" + ("PROBE FAIL: " + "; ".join(problems) if problems else "PROBE OK"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
