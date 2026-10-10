# -*- coding: utf-8 -*-
"""S1（v2.4 审查）：账本「跨天归档 ‖ 并发记账」竞态——内存态读-改-写没有锁。

复现口径（与审查报告一致）：
  worker 线程 today_usage()（走 _ensure_today 的跨天归档分支）
  ‖ 主线程 add_manual(1.0, 唯一 note)
旧实现只锁"写盘"（_write_json），不锁内存态：A 取走旧 records 引用 → B 记一笔
（落进新列表）→ A 重绑 self._ledger["records"] = [] 把 B 那笔整个丢掉——归档与
ledger 都查不到，随后落盘 = 永久丢账。

本文件用**确定性交错**（钩住"归档写盘"那一刻）而不是靠睡眠碰运气：
  1 test_cross_day_race_keeps_every_record        新实现：交错 N 轮，一条不丢
  2 test_serial_control_keeps_every_record        串行对照 N 轮（证明 1 不是"碰巧没并发"）
  3 test_harness_catches_unlocked_implementation  反例：把锁变异掉（with → if True）后
    同一条交错必须真的丢账——证明 1 不是恒真护栏。
"""
import importlib.util
import json
import os
import sys
import threading
import time

import pytest

import pet_book

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
YESTERDAY_NOTE = "昨日账"
RACE_NOTE = "并发新账"

# 交错窗口：钩子让归档停在"已取走旧 records、还没重绑"的位置，给并发的 add_manual
# 足够时间插进来。旧实现里主线程 1~3ms 就能记完这笔（实测余量 >20 倍）。
WINDOW = 0.05
# 反例用例的窗口给得更宽（只跑 1 轮，不怕慢），保证"旧实现必丢"不依赖机器快慢。
WINDOW_SAFE = 0.4


def _disk_notes(tmp_path):
    """磁盘上（ledger ∪ archive）的全部 note —— 只查内存态不足以证明"没丢"。"""
    notes = []
    led = json.loads((tmp_path / "ledger.json").read_text(encoding="utf-8"))
    notes += [r.get("note") for r in led.get("records") or []]
    arc_path = tmp_path / "ledger_archive.json"
    if arc_path.exists():
        arc = json.loads(arc_path.read_text(encoding="utf-8"))
        for day in (arc.get("days") or {}).values():
            notes += [r.get("note") for r in day.get("records") or []]
    return notes


def _interleave(book_mod, tmp_path, window=WINDOW):
    """一次确定性的「跨天归档 ‖ 记账」交错。

    返回 (book, hooked：钩子是否被触发, blocked：主线程是否被锁挡住)。
    """
    b = book_mod.Book(str(tmp_path))
    b.add_manual(5.0, YESTERDAY_NOTE)
    # 内存里把日界拨回昨天（磁盘不动）→ 下一次 _ensure_today 必走跨天归档分支
    b._ledger["date"] = book_mod._date_shift(book_mod._today(), -1)
    real = book_mod._write_json
    box = {"fired": False, "blocked": False}
    go = threading.Event()

    def hooked(path, data):
        if not box["fired"] and str(path) == b._archive_path:
            box["fired"] = True
            go.set()            # 放主线程去记账
            time.sleep(window)  # 停在"旧 records 已取走、还没重绑"的窗口里
        return real(path, data)

    book_mod._write_json = hooked
    t = threading.Thread(target=b.today_usage)   # worker 侧真实调用点（pet_tools/_build_ai_context 同款）
    t.start()
    try:
        assert go.wait(5), "归档写盘钩子没被触发（跨天分支没走到？）"
        t0 = time.monotonic()
        b.add_manual(1.0, RACE_NOTE)             # 主线程记账
        box["blocked"] = (time.monotonic() - t0) > window * 0.5
    finally:
        book_mod._write_json = real
        t.join(10)
    assert not t.is_alive(), "worker 线程没收尾"
    return b, box["fired"], box["blocked"]


def test_cross_day_race_keeps_every_record(tmp_path):
    """交错 N 轮：内存态 + 磁盘上都必须看到"昨日账 + 并发新账"，一条不丢。"""
    rounds = 30
    for i in range(rounds):
        d = tmp_path / ("r%02d" % i)
        d.mkdir()
        b, fired, _blocked = _interleave(pet_book, d)
        assert fired
        mem = sorted(r["note"] for r in b.all_records())
        assert mem == sorted([YESTERDAY_NOTE, RACE_NOTE]), "第 %d 轮内存态丢账：%r" % (i, mem)
        assert abs(b.total_amount() - 6.0) < 1e-9
        disk = sorted(n for n in _disk_notes(d) if n)
        assert disk == sorted([YESTERDAY_NOTE, RACE_NOTE]), "第 %d 轮磁盘丢账：%r" % (i, disk)


def test_race_is_actually_serialized_by_the_lock(tmp_path):
    """新实现的直接证据：归档期间主线程的记账被同一把锁挡住（旧实现里它立刻返回）。

    没有这条，上一条即使在"完全没并发"的机器上也会绿。
    """
    b, fired, blocked = _interleave(pet_book, tmp_path)
    assert fired
    assert blocked, "记账没有被锁挡住：归档与 append 之间仍有裸窗口"
    # 锁在归档结束后必须已释放（count 0 才是真释放，不是泄漏）
    assert pet_book._BOOK_WRITE_LOCK.acquire(timeout=2), "锁没释放"
    pet_book._BOOK_WRITE_LOCK.release()


def test_serial_control_keeps_every_record(tmp_path):
    """串行对照：同样 N 轮、同样两次记账，不并发 → 一条不丢（说明口径本身守恒）。"""
    rounds = 50
    for i in range(rounds):
        d = tmp_path / ("s%02d" % i)
        d.mkdir()
        b = pet_book.Book(str(d))
        b.add_manual(5.0, YESTERDAY_NOTE)
        b._ledger["date"] = pet_book._date_shift(pet_book._today(), -1)
        b.today_usage()                 # 先归档（串行）
        b.add_manual(1.0, RACE_NOTE)    # 再记账
        assert sorted(r["note"] for r in b.all_records()) == sorted([YESTERDAY_NOTE, RACE_NOTE])
        assert sorted(n for n in _disk_notes(d) if n) == sorted([YESTERDAY_NOTE, RACE_NOTE])


def _load_unlocked_mutant(tmp_path):
    """把 pet_book.py 的 _BOOK_WRITE_LOCK 临界区变异成无锁（with → if True）。

    在临时目录里以独立模块名加载——不改仓库文件、不影响已导入的 pet_book。
    这就是"旧实现"的等价物：内存态读-改-写重新变成裸的。
    """
    src = open(os.path.join(ROOT, "pet_book.py"), encoding="utf-8").read()
    mut = src.replace("\n        with _BOOK_WRITE_LOCK:\n",
                      "\n        if True:  # MUTANT: 无锁\n")
    assert mut != src, "变异没命中任何临界区——S1 的锁还在吗？"
    d = tmp_path / "mutant"
    d.mkdir()
    f = d / "pet_book_unlocked.py"
    f.write_text(mut, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("pet_book_unlocked", str(f))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["pet_book_unlocked"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_harness_catches_unlocked_implementation(tmp_path):
    """反例（能真失败）：去掉那把锁 → 同一条交错必须丢账。

    这条绿 = 上面两条不是恒真护栏：它们抓的正是审查报告里的真实丢数据路径。
    """
    mod = _load_unlocked_mutant(tmp_path)
    d = tmp_path / "race"
    d.mkdir()
    b, fired, blocked = _interleave(mod, d, window=WINDOW_SAFE)
    assert fired
    assert not blocked, "变异体里主线程仍被挡住？那变异没生效"
    mem = sorted(r["note"] for r in b.all_records())
    disk = sorted(n for n in _disk_notes(d) if n)
    assert mem != sorted([YESTERDAY_NOTE, RACE_NOTE]) or disk != sorted([YESTERDAY_NOTE, RACE_NOTE]), (
        "无锁变体居然没丢账——这条反例失去意义：mem=%r disk=%r" % (mem, disk))
