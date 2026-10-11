# -*- coding: utf-8 -*-
"""第三轮找茬（v2.4.3）代理 A 修复回归：P1-1 / P2-2 / P2-3 / P3-1 / P3-2 / P3-3 / P3-4 + 注解口径。

每条都配了"能真失败"的机制（本轮统一用 _dev/mutate_check.py 再验一遍：把修复那几行拿掉，
本文件的用例必须变红）：

  P1-1  BalanceService._worker 的 emit 裸露在 try 之外 → test_worker_* 一组：emit 打在
        已销毁对象上 / _request_balance 抛 / 退出中，守卫状态都必须收尾、异常都不许外抛；
        test_control_naked_worker_really_leaks 是控制组（修复前的写法必须真的泄漏）；
  A-1   v2.4.4：守卫从布尔换成**请求代次**（本文件同一组用例已按新口径改写）——worker 只
        emit（带代次），槽消费后才放行；同一时刻只允许一个在途请求（第二次点击排队），
        旧代的迟到结果丢弃且**零副作用**（不弹气泡/不放音/不撒钱）+ 一条日志；
  P2-2  pet_widgets 8 处 QFont 硬编码字体名 → 字体族列表断言 + AST"不许再出现硬编码族名"；
  P2-3  requirements.txt 的 requests/PyInstaller 缺上界 → 上界断言 + 越界必须被拒；
  P3-1  pet_chat.last_updated 无时区 → 必须带 ±HHMM 且能被 strptime("%z") 解析；
  P3-2  CI 不锁 pytest → ci.yml 必须与 lock 同版本，且安装行不许出现裸 pytest；
  P3-3  pet_export 依赖 zipfile 私有属性 _compresslevel → "换压缩级别必须换产出字节"
        反证它仍被消费（属性被改名/改语义 → 两个级别会写出相同字节 → 红）；
  P3-4  pet_io._almost_utf8 极小文件退化 → 文档说明 + 边界行为（纯西文小文件仍被拒）；
  口径   README（中/英）的类型注解表格必须与 AST 实测数字一致，防止再写成"全仓完成"。
"""
import ast
import datetime
import json
import os
import re
import sys
import types

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pet_balance  # noqa: E402
import pet_chat  # noqa: E402
import pet_export  # noqa: E402
import pet_io  # noqa: E402
import pet_widgets  # noqa: E402
from PySide6.QtGui import QFont  # noqa: E402
# v2.4.3（兼容审查 M3）：依赖区间口径的单一来源（不再在本文件手写包名清单）
from helpers_deps_bounds import (lock_text, parse_version, satisfies,  # noqa: E402
                                specs as req_specs, requirements_text)

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ANNOTATED_MODULES = ("pet_tools.py", "pet_lines.py", "pet_io.py", "pet_book.py")


def _read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


# ===================== P1-1 / A-1：balance worker 与请求代次 =====================
# v2.4.4（A-1）把"在途守卫"从一个**布尔**换成**请求代次**：worker 只负责把结果（带代次）
# emit 出去，自己那一代**留着**；由**槽**消费后才放行。只有结果没交出去（退出中 / emit 抛）
# 时才由 worker 自己收尾。所以下面这一组的收口判据是"槽跑完"，不是"worker 返回"——
# 信号替身因此模拟 Qt 的队列连接：emit 只入队，deliver() = 事件循环轮到槽。

class _Signal(object):
    """最小信号替身：记录 emit 实参，并把它**排队**交给槽（模拟跨线程队列连接）。

    boom 非 None 时模拟"打到已删除的 C++ 对象"：emit 抛异常且**不投递**（接收者没了就
    收不到，与 Qt 一致）。
    """

    def __init__(self, boom=None):
        self.calls = []
        self.boom = boom
        self.slot = None
        self.queue = []

    def connect(self, slot):
        self.slot = slot

    def emit(self, *args):
        self.calls.append(args)
        if self.boom is not None:
            raise self.boom
        self.queue.append(args)

    def deliver(self):
        """把排队的 emit 逐条交给槽（= 主线程事件循环轮到它们）。"""
        while self.queue:
            args = self.queue.pop(0)
            if self.slot is not None:
                self.slot(*args)


class _Signals(object):
    def __init__(self, updated_boom=None, err_boom=None):
        self.balance_updated = _Signal(updated_boom)
        self.balance_err = _Signal(err_boom)

    def wire(self, svc):
        """按生产口径接槽（桌宠.py：signals.balance_updated.connect(self.balance.on_updated)）。"""
        self.balance_updated.connect(svc.on_updated)
        self.balance_err.connect(svc.on_err)
        return self

    def deliver(self):
        self.balance_updated.deliver()
        self.balance_err.deliver()


class _TimerSpy(object):
    """QTimer 替身：记录 singleShot(ms, ctx, fn)；fire() = 让"补发排队的手动查询"到点。

    真 QTimer 既需要 QApplication，又要求 receiver 是 QObject，而本文件的 pet 是替身对象。
    """

    def __init__(self):
        self.shots = []

    def singleShot(self, ms, ctx, fn):
        self.shots.append((ms, ctx, fn))

    def fire(self):
        shots, self.shots = list(self.shots), []
        for _ms, _ctx, fn in shots:
            fn()
        return len(shots)


class _Pet(object):
    """BalanceService 用到的全部状态（语义与 PetWindow 一致）。

    v2.4.4（A-1）：在途守卫 = **请求代次**（_balance_active_gen，None = 空闲）；
    _manual_pending 只对"当前那一代"有效。has_closing=False 用来模拟 _closing 被改名。
    """

    def __init__(self, closing=False, active_gen=None, manual=False, has_closing=True):
        if has_closing:
            self._closing = closing
        self._balance_gen = int(active_gen or 0)
        self._balance_active_gen = active_gen
        self._manual_pending = manual
        self._pending_manual = False
        self._currency = "CNY"
        self._usage = 0.0
        self._shown_balance = None
        self._balance_anim = None
        self.bubbles = []
        self.money = 0
        self.badges = 0

    def show_bubble(self, text):
        self.bubbles.append(text)

    def _fx_celebrate(self):
        self.money += 1

    def _update_badge(self):
        self.badges += 1


def _service(pet, signals, logs, sounds=None):
    """BalanceService + 按生产口径接好的两个槽；sounds 记录 play_sound 调用。"""
    sounds = [] if sounds is None else sounds
    svc = pet_balance.BalanceService(
        pet, signals, lambda: {"api_key": "k"}, lambda: None,
        sounds.append, lambda *a: None, logs.append, lambda: None)
    signals.wire(svc)
    return svc


def _deleted_cpp():
    return RuntimeError("wrapped C/C++ object of type PetWindow has been deleted")


def _inflight(pet, gen=1, manual=False):
    """把 pet 摆成"第 gen 代已由 refresh() 发出去"的样子（worker 由用例直接驱动）。"""
    pet._balance_gen = pet._balance_active_gen = gen
    pet._manual_pending = manual
    return gen


def test_worker_hands_the_result_to_the_slot_which_releases_the_generation():
    """成功路径：worker 只把 (代次, 余额) 交给槽；**槽跑完**守卫才放行（A-1 的核心时序）。

    能真失败：把 worker 改回"emit 后无条件复位守卫"（= v2.4.3 的口径）→ 第三条断言红；
    漏掉 emit 里的代次 → 第一条断言红。
    """
    pet, logs = _Pet(), []
    signals = _Signals()
    svc = _service(pet, signals, logs)
    svc._request_balance = lambda key: (True, (1.5, "CNY", 0.25))
    _inflight(pet)
    svc._worker("k", 1)
    assert signals.balance_updated.calls == [(1, 1.5, "CNY", 0.25)], signals.balance_updated.calls
    assert signals.balance_err.calls == []
    assert pet._balance_active_gen == 1,         "结果还没被槽消费就放行了守卫（旧口径的提前复位 → 窗口里再点一次会起第二个并发线程）"
    signals.deliver()
    assert pet._balance_active_gen is None, "槽消费后必须放行守卫"
    assert pet._shown_balance == 1.5 and pet.badges == 1


def test_worker_emits_err_and_the_slot_releases_the_generation():
    """HTTP 失败：错误同样带代次交给槽；手动查询弹一次提示，守卫由槽放行。"""
    pet, logs = _Pet(), []
    signals = _Signals()
    svc = _service(pet, signals, logs)
    svc._request_balance = lambda key: (False, "timeout")
    _inflight(pet, manual=True)
    svc._worker("k", 1)
    assert signals.balance_err.calls == [(1,)], signals.balance_err.calls
    assert signals.balance_updated.calls == []
    assert any("timeout" in m for m in logs)
    assert pet._balance_active_gen == 1, "错误结果没交给槽就放行了守卫"
    signals.deliver()
    assert pet._balance_active_gen is None
    assert pet.bubbles == ["余额查不到……API Key 对吗？"]


def test_worker_survives_request_exception_and_the_slot_still_releases():
    """_request_balance 之后的某行在 try 外抛时，守卫此前会永真卡死。"""
    pet, logs = _Pet(), []
    signals = _Signals()
    svc = _service(pet, signals, logs)

    def boom(key):
        raise ValueError("worker 内部的意外异常")

    svc._request_balance = boom
    _inflight(pet)
    svc._worker("k", 1)                  # 修复前：异常直接冲出 daemon 线程
    assert signals.balance_err.calls == [(1,)], "异常路径必须补发 balance_err"
    assert any("crashed" in m for m in logs)
    signals.deliver()
    assert pet._balance_active_gen is None, "异常路径泄漏了在途守卫（查询会被永久挡住）"


def test_worker_retires_its_generation_when_emit_hits_a_deleted_object():
    """PetWindow 已销毁时 emit 会抛 RuntimeError——不许冲出 worker，且这一代要自己收尾。

    没交出去 = 永远没有槽来消费它，不收尾就是 P1-1 那条守卫泄漏。
    """
    pet, logs = _Pet(), []
    signals = _Signals(updated_boom=_deleted_cpp())
    svc = _service(pet, signals, logs)
    svc._request_balance = lambda key: (True, (2.0, "CNY", 0.0))
    _inflight(pet)
    svc._worker("k", 1)                  # 修复前：RuntimeError 从 daemon 线程冒出
    assert pet._balance_active_gen is None, "结果没交出去还不收尾：守卫会永久挂着"
    assert any("balance emit balance_updated failed" in m for m in logs)


def test_worker_survives_both_signals_raising():
    """两个信号都打在已销毁对象上（退出时序竞态）：worker 仍不许抛，守卫仍收尾。"""
    pet, logs = _Pet(), []
    signals = _Signals(updated_boom=_deleted_cpp(), err_boom=_deleted_cpp())
    svc = _service(pet, signals, logs)
    svc._request_balance = lambda key: (False, "boom")
    _inflight(pet)
    svc._worker("k", 1)
    svc._worker("k", 1)                  # 幂等：再来一次也不许抛
    assert pet._balance_active_gen is None


def test_worker_does_not_emit_while_closing():
    """退出中（_closing=True）：emit 端此前不判，会把信号打到正在销毁的窗口上。"""
    pet, logs = _Pet(closing=True), []
    signals = _Signals()
    svc = _service(pet, signals, logs)
    svc._request_balance = lambda key: (True, (3.0, "CNY", 0.0))
    _inflight(pet)
    svc._worker("k", 1)
    assert signals.balance_updated.calls == [], "退出中不该再 emit 余额结果"
    assert pet._balance_active_gen is None, "退出中不收尾：窗口没退干净就永久卡住"

    pet2, signals2 = _Pet(closing=True), _Signals()
    svc2 = _service(pet2, signals2, [])
    svc2._request_balance = lambda key: (False, "boom")
    _inflight(pet2)
    svc2._worker("k", 1)
    assert signals2.balance_err.calls == [], "退出中不该再 emit 错误"


def test_refresh_resets_guard_when_thread_start_fails(monkeypatch):
    """refresh() 自己也要兜住 start() 的异常（复审 M1，A-1 口径）。

    Windows 线程/句柄耗尽、解释器关闭期，threading.Thread.start() 真会抛
    RuntimeError("can't start new thread")。此前那两行（置标志 + start）不在 try 里：
    标志恒真 → 此后 refresh 一个线程都起不来、只置 _pending_manual=True → 症状与 P1-1
    的守卫泄漏**一模一样**（点"查询余额"毫无反应），而泄漏点在 worker 之外，worker 兜不住。
    现在异常路径把这一代交回 balance_err（槽消费它即放行；真交不出去才自己收尾）。

    能真失败：把 refresh() 里的 try/except 拿掉 → 异常冲出 refresh（调用方是 Qt 槽，
    只会被吞掉），前四条断言全红。
    """
    pet, logs = _Pet(), []
    signals = _Signals()
    svc = _service(pet, signals, logs)

    class _DeadThread(object):
        def __init__(self, *a, **k):
            pass

        def start(self):
            raise RuntimeError("can't start new thread")

    monkeypatch.setattr(pet_balance.threading, "Thread", _DeadThread)
    svc.refresh(manual=True)                    # 不许抛
    assert pet._balance_active_gen == 1, "启动失败的那一代没登记（后面无从收尾）"
    assert [c[0] for c in signals.balance_err.calls] == [1],         "启动失败要补发 balance_err（带代次）：%r" % (signals.balance_err.calls,)
    assert any("thread start failed" in m for m in logs), logs
    signals.deliver()
    assert pet._balance_active_gen is None, "start() 抛了却没放行（此后一次都起不来）"
    # 反例对照：start() 正常时照旧走原路径（别把守卫改成永远复位）
    monkeypatch.undo()
    started = []

    class _GoodThread(object):
        def __init__(self, target=None, args=(), **k):
            started.append((target, args))

        def start(self):
            started.append("start")

    monkeypatch.setattr(pet_balance.threading, "Thread", _GoodThread)
    svc.refresh(manual=False)
    assert pet._balance_active_gen == pet._balance_gen == 2 and started[-1] == "start", started


def test_closing_flag_renamed_does_not_silently_drop_results():
    """L①：`_closing` 读不到（属性**不存在**）不该被当成"在退出"而永久丢弃结果。

    能真失败：把 _closing() 退回 `bool(self.pet._closing)`（属性不存在 → AttributeError →
    兜底 True）→ 第一条断言红（emit 被丢掉且一行日志都没有）。
    """
    pet, logs = _Pet(active_gen=1, has_closing=False), []
    signals = _Signals()
    svc = _service(pet, signals, logs)
    svc._request_balance = lambda key: (True, (1.0, "CNY", 0.0))
    svc._worker("k", 1)
    assert signals.balance_updated.calls == [(1, 1.0, "CNY", 0.0)],         "属性改名后余额结果被静默丢弃了（_closing 兜底方向反了）"
    assert signals.balance_updated.queue == [(1, 1.0, "CNY", 0.0)],         "结果没被交给槽（emit 端把它当成了'在退出'）"
    assert pet._balance_active_gen == 1, "结果已交给槽：这一代该留着等槽消费"


def test_worker_treats_unreadable_closing_flag_as_closing():
    """pet 已被销毁（取属性就抛）时按"在退出"处理：不发、不抛、守卫照样收尾。"""
    class _Gone(object):
        """pet 已被销毁的替身：连 _closing 都读不出来（属性访问直接抛）。"""

        def __init__(self):
            self._balance_gen = 1
            self._balance_active_gen = 1
            self._manual_pending = False

        @property
        def _closing(self):
            raise _deleted_cpp()

    pet, logs = _Gone(), []
    signals = _Signals()
    svc = _service(pet, signals, logs)
    svc._request_balance = lambda key: (True, (1.0, "CNY", 0.0))
    svc._worker("k", 1)
    assert signals.balance_updated.calls == []
    assert pet._balance_active_gen is None


def test_refresh_is_not_wedged_after_an_emit_failure(monkeypatch):
    """端到端：emit 炸过之后，守卫必须已放行——下一次 refresh 还得能真发请求。

    v2.4.3 的口径里守卫只在槽里复位，emit 一炸槽永远不跑 → 之后所有轮询/手动查询都被
    "在途"挡住（用户点"查询余额"毫无反应）。v2.4.4（A-1）：没交给槽的结果由 worker 自己
    收尾，交给槽的才等槽消费。
    """
    class _InlineThread(object):
        """把 BalanceService 起的线程改成同步执行（本用例只关心状态机）。"""

        def __init__(self, target=None, args=(), daemon=None, **kw):
            self._target, self._args = target, args

        def start(self):
            self._target(*self._args)

    monkeypatch.setattr(pet_balance, "threading", types.SimpleNamespace(Thread=_InlineThread))
    calls = []
    pet = _Pet()
    signals = _Signals(updated_boom=_deleted_cpp())
    svc = _service(pet, signals, [])
    svc._request_balance = lambda key: (calls.append(key) or (True, (1.0, "CNY", 0.0)))

    svc.refresh(manual=True)
    assert len(calls) == 1
    assert pet._balance_active_gen is None, "emit 失败后守卫没放行：后续查询全被挡住"
    svc.refresh(manual=True)
    assert len(calls) == 2, "第二次 refresh 被永真的在途守卫挡住了"


def test_control_naked_worker_really_leaks():
    """控制组：修复前的写法（emit 裸露、无 finally）必须真的泄漏守卫/抛异常。

    这条保证上面几条断言不是空转——真把 try/finally 拿掉，行为就是这个样子。
    """
    pet = _Pet(active_gen=1)
    signals = _Signals(updated_boom=_deleted_cpp())

    def naked_worker(key):               # v2.4.2 的写法
        ok, payload = True, (1.0, "CNY", 0.0)
        if ok:
            signals.balance_updated.emit(*payload)

    with pytest.raises(RuntimeError):
        naked_worker("k")
    assert pet._balance_active_gen == 1, "控制组失效：这就不是修复前那条路径了"


# ===================== A-1（v2.4.4）：同一时刻只有一个在途请求 / 旧代无副作用 =====================

def _mk_service(monkeypatch, pet=None, sounds=None, **sig_kw):
    """接好槽的 BalanceService + 记录副作用的 pet/sounds（QTimer 换成可手动到点的替身）。"""
    timer = _TimerSpy()
    monkeypatch.setattr(pet_balance, "QTimer", timer)
    pet = _Pet() if pet is None else pet
    logs = []
    sounds = [] if sounds is None else sounds
    signals = _Signals(**sig_kw)
    svc = _service(pet, signals, logs, sounds)
    return pet, signals, svc, timer, logs, sounds


def test_second_click_queues_instead_of_starting_a_second_thread(monkeypatch):
    """核心判据：结果已 emit、槽还没轮到跑时再点一次「查询余额」→ **排队**，不许起第二个线程。

    能真失败：把在途判据退回布尔 + worker 的 finally 提前复位（= v2.4.3 的口径）→
    started 变成 2（审查探针实测的两个并发线程）→ 第二条断言红。
    """
    started = []

    class _RecorderThread(object):
        """同步执行 + 登记：用例自己控制"谁在什么时候跑"。"""

        def __init__(self, target=None, args=(), daemon=None, **kw):
            self._target, self._args = target, args

        def start(self):
            started.append(self._args)
            self._target(*self._args)

    monkeypatch.setattr(pet_balance, "threading",
                        types.SimpleNamespace(Thread=_RecorderThread))
    pet, signals, svc, timer, logs, _sounds = _mk_service(monkeypatch)
    svc._request_balance = lambda key: (True, (5.0, "CNY", 0.0))

    svc.refresh(manual=False)                       # ① 自动轮询：第 1 代
    assert len(started) == 1 and pet._balance_active_gen == 1
    assert signals.balance_updated.queue, "第 1 代的结果应当已排队等槽"

    svc.refresh(manual=True)                        # ② 结果还在队列里时用户点了「查询余额」
    assert len(started) == 1, ("在途/待消费窗口里起了第二个并发线程：%r"
                               "（v2.4.3 口径会真的并发两个）" % (started,))
    assert pet._pending_manual is True, "手动查询没排队：落地后没人补发它"

    signals.deliver()                               # ③ 第 1 代落地 → 补发排队的手动查询
    assert timer.shots, "排队的手动查询没有被补发（应当排一个 QTimer.singleShot）"
    assert timer.fire() == 1
    assert len(started) == 2, "补发没起第 2 代：%r" % (started,)
    assert pet._balance_active_gen == 2 and pet._manual_pending is True

    signals.deliver()                               # ④ 第 2 代（手动）落地
    assert pet._balance_active_gen is None
    assert len(started) == 2, "手动查询落地后又起了第 3 个线程：%r" % (started,)


def test_manual_landing_gives_exactly_one_set_of_side_effects(monkeypatch):
    """手动查询落地：恰好一次气泡 + 一次金币音 + 一次撒钱（A-1：不是两份）。"""
    pet, signals, svc, _timer, _logs, sounds = _mk_service(monkeypatch)
    svc._request_balance = lambda key: (True, (8.0, "CNY", 1.0))
    _inflight(pet, gen=1, manual=True)
    svc._worker("k", 1)
    signals.deliver()
    assert len(pet.bubbles) == 1 and "余额 ¥8.00" in pet.bubbles[0], pet.bubbles
    assert sounds == ["coin"], "金币音不是一次：%r" % (sounds,)
    assert pet.money == 1, "撒钱不是一次：%d" % pet.money


def test_stale_generation_result_is_dropped_without_side_effects(monkeypatch):
    """旧代迟到结果：丢弃 + 记一条日志；**不许**弹气泡/放金币音/撒钱，也不许碰新一代的标记。

    能真失败：把 _consume 的代次判断拿掉（槽照收旧代）→ 副作用立刻出现（气泡/音效/撒钱
    各一份）且日志里没有"丢弃旧代结果" → 两条断言同时红。
    """
    pet, signals, svc, _timer, logs, sounds = _mk_service(monkeypatch)
    _inflight(pet, gen=2, manual=True)          # 当前在途：第 2 代（用户刚点的手动查询）
    svc.on_updated(1, 8.0, "CNY", 1.0)          # 第 1 代的迟到结果
    assert pet.bubbles == [] and sounds == [] and pet.money == 0,         "旧代结果产生了副作用：气泡 %r / 音效 %r / 撒钱 %d" % (pet.bubbles, sounds, pet.money)
    assert pet._balance_active_gen == 2, "旧代把新一代的在途状态抹掉了"
    assert pet._manual_pending is True, "旧代把新一代的手动标记消费掉了"
    assert any("丢弃旧代结果" in m for m in logs), "旧代结果被静默丢弃（不许静默）：%r" % (logs,)
    # 对照组：正确的那一代照常落地（证明上面的"没有副作用"不是全局静音）
    svc.on_updated(2, 8.0, "CNY", 1.0)
    assert len(pet.bubbles) == 1 and sounds == ["coin"] and pet.money == 1


def test_stale_generation_error_is_dropped_too(monkeypatch):
    """旧代的错误同样丢弃 + 记日志：新一代的手动查询不该被旧错误顶上气泡。"""
    pet, signals, svc, _timer, logs, _sounds = _mk_service(monkeypatch)
    _inflight(pet, gen=2, manual=True)
    svc.on_err(1)
    assert pet.bubbles == [], "旧代错误弹了气泡：%r" % (pet.bubbles,)
    assert pet._balance_active_gen == 2 and pet._manual_pending is True
    assert any("丢弃旧代结果" in m for m in logs), logs
    svc.on_err(2)
    assert pet.bubbles == ["余额查不到……API Key 对吗？"]


# ------------- v2.4.4 复审（兼容审查 L1/L2）：槽端退出收尾 · _retire 顺序 · refresh 防御读 -------------

def test_retire_clears_the_manual_flag_before_releasing_the_generation(monkeypatch):
    """L1（兼容审查）：_retire 里"清手动标记"必须排在"放行代次"**之前**。

    反过来的话主线程只要在这两条语句之间抢到 GIL 并跑 refresh(manual=True)，新开的那一代
    就会拿到 manual=False：结果照常落地，却**不再弹气泡/放金币音/撒钱**（与 _retire 自己
    "旧代不许动新代状态"的注释矛盾）。这里用 property 探针在赋值那一刻重入 refresh，把那个
    窗口**确定性**地摆出来（不用真并发）。

    能真失败：两条语句调换回去 → 第一条断言红（新代的手动标记被上一代抹掉）。
    """
    started = []

    class _RecorderThread(object):
        def __init__(self, target=None, args=(), **kw):
            started.append(args)

        def start(self):
            started.append("start")

    monkeypatch.setattr(pet_balance, "threading", types.SimpleNamespace(Thread=_RecorderThread))
    box = {}

    class _ReentrantPet(_Pet):
        """放行代次（置 None）的那一刻重入 refresh = 主线程在这两条语句之间抢到 GIL。"""

        @property
        def _balance_active_gen(self):
            return self._active_gen

        @_balance_active_gen.setter
        def _balance_active_gen(self, value):
            self._active_gen = value
            if value is None and box.get("svc") is not None and not box.get("done"):
                box["done"] = True
                box["svc"].refresh(manual=True)

    pet = _ReentrantPet(active_gen=1, manual=True)
    svc = _service(pet, _Signals(), [])
    box["svc"] = svc
    svc._retire(1, "测试：worker 交不出去")
    assert pet._manual_pending is True, \
        "上一代收尾把新代的手动标记抹掉了（结果落地不再弹气泡/放金币音/撒钱）"
    assert pet._balance_active_gen == 2, \
        "窗口里那次 refresh 没起第 2 代：%r" % (pet._balance_active_gen,)
    assert started and started[-1] == "start", started


def test_slot_closing_early_return_retires_the_generation(monkeypatch):
    """L1（兼容审查）：槽端"退出中"早退也必须收尾。

    emit 已经交出去（worker 那边守卫留着等槽消费），槽跑到时窗口已在退出 → 早退 return，
    那一代就永久挂在非 None 上。生产上进程正在退出、无感；但探针/夹具会把 `_closing` 改回
    False 继续用同一个窗口（_dev/probe_ui_freeze.py / tests/test_full_form_frames_v24.py），
    之后就撞上"点查询余额毫无反应"。_retire 自带 `== gen` 守卫，旧代不会误伤新代。

    能真失败：早退分支不收尾 → 两条断言红。
    """
    pet, logs = _Pet(closing=True, active_gen=1), []
    signals = _Signals()
    svc = _service(pet, signals, logs)
    svc.on_updated(1, 1.0, "CNY", 0.0)          # 已 emit 的那一代，槽跑到时窗口在退出
    assert signals.balance_updated.calls == [], "退出中不该响应在途结果"
    assert pet._balance_active_gen is None, \
        "退出中早退没收尾：这一代永远挂着（窗口被复用后查询全被挡住）"
    pet2, logs2 = _Pet(closing=True, active_gen=3), []
    svc2 = _service(pet2, _Signals(), logs2)
    svc2.on_err(3)
    assert pet2._balance_active_gen is None, "退出中早退没收尾（错误路径）：这一代永远挂着"
    # 反例对照：窗口被复用（_closing 改回 False）后，下一次查询必须还能真发出去
    started = []

    class _RecorderThread(object):
        def __init__(self, target=None, args=(), **kw):
            started.append(args)

        def start(self):
            started.append("start")

    monkeypatch.setattr(pet_balance, "threading", types.SimpleNamespace(Thread=_RecorderThread))
    pet._closing = False
    svc.refresh(manual=True)
    assert started and started[-1] == "start" and pet._balance_active_gen == 2, \
        "收尾漏了：窗口复用后查询被永真的在途守卫挡住：%r" % (started,)


def test_refresh_reads_the_guard_flags_defensively(monkeypatch):
    """L2（兼容审查）：refresh() 对新守卫属性也要走 getattr（与 _consume/_retire 同口径）。

    refresh 由 Qt 槽调用（菜单 / 补发定时器），裸取属性时"替身 pet / 属性改名"会抛
    AttributeError —— 槽里抛出去就是"点查询余额毫无反应"。

    能真失败：把两处 getattr 退回裸取 → 抛 AttributeError，第一条断言前就红。
    """
    class _Bare(object):
        """最小 pet：**没有**代次属性（模拟替身 / 属性改名）。"""

    pet = _Bare()
    svc = _service(pet, _Signals(), [])
    started = []

    class _RecorderThread(object):
        def __init__(self, target=None, args=(), **kw):
            started.append(args)

        def start(self):
            started.append("start")

    monkeypatch.setattr(pet_balance, "threading", types.SimpleNamespace(Thread=_RecorderThread))
    svc.refresh(manual=True)                    # 修复前：AttributeError（Qt 槽里就是"点了没反应"）
    assert started and started[-1] == "start", started
    assert pet._balance_gen == 1, "没有 _balance_gen 时应当从 0 起算：%r" % (pet._balance_gen,)
    assert pet._balance_active_gen == 1 and pet._manual_pending is True, \
        "守卫没登记：%r/%r" % (pet._balance_active_gen, pet._manual_pending)


def test_auto_poll_landing_has_no_manual_side_effects(monkeypatch):
    """自动轮询落地**不许**有手动反馈（气泡 / 金币音 / 撒钱）。

    v2.4.4（质量审查 M3）：这条行为面此前**一条用例都没有**——把 on_updated 里的
    `if manual:` 改成恒真（等价于每 5 分钟自动轮询都弹气泡 + 放金币音 + 撒钱）时，
    定向用例集 65 例全绿（NOT CAUGHT）。

    能真失败：同上的 `if True:` 变异 → 前三条断言同时红（见 M-V4）。
    """
    pet, signals, svc, _timer, _logs, sounds = _mk_service(monkeypatch)
    svc._request_balance = lambda key: (True, (8.0, "CNY", 1.0))
    _inflight(pet, gen=1, manual=False)
    svc._worker("k", 1)
    signals.deliver()
    assert pet.bubbles == [], "自动轮询弹了气泡：%r" % (pet.bubbles,)
    assert sounds == [], "自动轮询放了金币音：%r" % (sounds,)
    assert pet.money == 0, "自动轮询撒了钱：%d" % pet.money
    # 反例对照：余额本身必须照常落地（别把"没有手动反馈"做成"什么都不做"）
    assert pet._shown_balance == 8.0 and pet.badges == 1,         "自动轮询的余额没落地：shown=%r badges=%d" % (pet._shown_balance, pet.badges)
    assert pet._balance_active_gen is None, "槽消费后没有放行守卫"


def test_retire_only_touches_its_own_generation():
    """L3（质量审查）：_retire 只许动**自己那一代**——旧代收尾不许抹掉新一代的在途/手动标记。

    能真失败：把 _retire 的 `if getattr(pet, "_balance_active_gen", None) == gen:` 改成
    `if True:` → 第一条断言红（第 2 代被第 1 代的收尾误伤，见 M-V7）。
    """
    pet, logs = _Pet(active_gen=2, manual=True), []
    svc = _service(pet, _Signals(), logs)
    svc._retire(1, "旧代收尾")                       # 第 1 代早已不是当前那一代
    assert pet._balance_active_gen == 2, "旧代的收尾把新一代的在途状态抹掉了"
    assert pet._manual_pending is True, "旧代的收尾把新一代的手动标记抹掉了"
    svc._retire(2, "自己那一代")                     # 反例对照：自己那一代照常收尾
    assert pet._balance_active_gen is None and pet._manual_pending is False,         "自己那一代没收尾：%r/%r" % (pet._balance_active_gen, pet._manual_pending)


# ===================== P2-2：QFont 回退链 =====================

def _hardcoded_qfont_families(src):
    """源码里 QFont 直接用**字符串字面量族名**的地方 → [(行号, 族名)]。

    只看第一个位置参数是字符串常量的调用：QFont(list(UI_FONT_FAMILIES)) 这类不算。
    """
    out = []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
        if name != "QFont" or not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            out.append((node.lineno, first.value))
    return out


def _ui_font_calls(src):
    n = 0
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            if name == "ui_font":
                n += 1
    return n


def test_hardcoded_qfont_checker_can_fail():
    """控制组：硬编码检测器必须能认出坏样本（否则下面那条断言是空转）。"""
    bad = 'from PySide6.QtGui import QFont\nf = QFont("Microsoft YaHei", 9)\n'
    assert _hardcoded_qfont_families(bad) == [(2, "Microsoft YaHei")]
    good = 'from PySide6.QtGui import QFont\nf = QFont(list(UI_FONT_FAMILIES), 9)\n'
    assert _hardcoded_qfont_families(good) == []


def test_widgets_never_hardcode_a_font_family():
    src = _read("pet_widgets.py")
    hard = _hardcoded_qfont_families(src)
    assert hard == [], ("pet_widgets.py 仍有硬编码字体名（非中文 Windows 上会变方块）：%r" % (hard,))
    assert _ui_font_calls(src) >= 8, "8 处字体构造都应走 ui_font 助手"


def test_ui_font_uses_the_fallback_chain():
    fams = list(pet_widgets.UI_FONT_FAMILIES)
    assert len(fams) >= 3, "回退链太短：一个族不可用时没有后备"
    assert fams[0] == "Microsoft YaHei"
    assert "SimSun" in fams and "Arial Unicode MS" in fams
    f = pet_widgets.ui_font(9, QFont.Weight.Bold)
    assert list(f.families()) == fams, "QFont 没拿到整条族列表（Qt6 才支持列表重载）"
    assert f.pointSize() == 9
    assert f.weight() == QFont.Weight.Bold
    plain = pet_widgets.ui_font(12)
    assert plain.pointSize() == 12 and plain.weight() == QFont.Weight.Normal


# ---- v2.4.3（兼容审查 M1）：QSS 也是字体名的一部分，守卫必须覆盖全仓而不只是 pet_widgets ----

def _shipped_py_sources():
    """仓库根下的产品 .py（静态检查与发布流程读的就是这些）。"""
    out = {}
    for name in sorted(os.listdir(HERE)):
        if name.endswith(".py"):
            out[name] = _read(name)
    return out


def _font_family_declarations(text):
    """文本里所有 font-family 声明 → [(行号, 值)]（.py 里的 QSS 常量与独立 .qss 都适用）。"""
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        m = re.search(r"font-family\s*:\s*([^;}\n]+)", line)
        if m:
            out.append((i, m.group(1).strip()))
    return out


def _unfallback_font_declarations(text, token=None):
    """**单族**（没有逗号回退）的 font-family 声明 → [(行号, 值)]。

    token = "由单一来源注入"的占位符：它在源码里就该是单值，替换后才是整条链。
    """
    if token is None:
        token = pet_dialogs_qss_token()
    out = []
    for lineno, value in _font_family_declarations(text):
        if token and token in value:
            continue
        names = [p for p in value.split(",") if p.strip()]
        if len(names) < 2:
            out.append((lineno, value))
    return out


def pet_dialogs_qss_token():
    """对话框 QSS 的族占位符（从产品源码里取，避免测试另写一份字面量）。"""
    return "".join(re.findall(r'DIALOG_QSS_FONT_TOKEN = "([^"]+)"',
                              _read("pet_dialogs.py"))) or "__UI_FONT_FAMILIES__"


def _font_chain_comment(src):
    """UI_FONT_FAMILIES 上方的机理注释块（从"字体回退链"标题到常量定义）。"""
    start = src.find("字体回退链")
    end = src.find("UI_FONT_FAMILIES = ")
    return src[start:end] if 0 <= start < end else ""


def _unhedged_font_claims(text):
    """把"必现缺陷"式的绝对说法挑出来（复审 M4：措辞要用"可能"）。"""
    return [p for p in ("就回退到默认无衬线", "显示成", "会显示成方块") if p in text]


def test_font_fallback_mechanism_comment_is_hedged():
    """机理描述必须是"多一层候选 + 显式兜底（Qt 自身仍会做字体链接）"，用"可能"不用"不会"。

    审查实测（复审 M4）：候选族全不存在时 Qt 回退到 Tahoma 且 exactMatch()==False，
    但 inFontUcs4(0x4E2D)==True、advance("中") 仍是正常宽度 → **只要机器上还有任意一份
    CJK 字体就不会变方块**，新增链的成员也全是有 CJK 的族。旧注释把回退链写成了
    "修掉中文变方块这个必现缺陷"，属于把防御性加固说成缺陷修复。

    能真失败：把旧那句写回（"Qt 找不到该族就回退到默认无衬线 → 中文…显示成方块"）
    → "字体链接"缺失 + _unhedged_font_claims 非空 → 红。
    """
    text = _font_chain_comment(_read("pet_widgets.py"))
    assert text, "没找到 UI_FONT_FAMILIES 上方的机理注释块"
    assert "字体链接" in text, "注释没写 Qt 自身的字体链接（这才是中文不变方块的真正原因）"
    assert "可能" in text, "措辞要用'可能'，不能写成绝对断言"
    assert "多一层候选" in text or "显式兜底" in text, "没写清这是'多一层候选 + 显式兜底'"
    bad = _unhedged_font_claims(text)
    assert bad == [], "又把回退链写成了必现缺陷修复（命中绝对说法 %r）" % (bad,)
    # 控制组：旧那句必须被认出来（否则上面那条是空转）
    old = ("# 卸载中文字体的环境里，Qt 找不到该族就回退到默认无衬线 → 中文气泡与余额徽章显示成\n"
           "# **方块**（豆腐块）。")
    assert _unhedged_font_claims(old), "检测器认不出旧说法"
    assert "字体链接" not in old


def test_font_family_checker_can_fail():
    """控制组：单族声明必须被认出来（否则下面那条断言是空转）。"""
    bad = 'QDialog {\n    font-family: "Microsoft YaHei";\n}'
    assert _unfallback_font_declarations(bad) == [(2, '"Microsoft YaHei"')]
    good = 'QDialog { font-family: "Microsoft YaHei", "SimSun"; }'
    assert _unfallback_font_declarations(good) == []
    tok = "QDialog { font-family: __UI_FONT_FAMILIES__; }"
    assert _unfallback_font_declarations(tok) == []
    assert _font_family_declarations('QLabel { color: #fff; }') == []


def test_no_shipped_source_hardcodes_a_single_font_family():
    """**全仓**（不只 pet_widgets）：QSS 的 font-family 不许单族，QFont 不许吃字符串字面量。

    能真失败：把 DIALOG_QSS 改回 font-family: "Microsoft YaHei";（或把占位符换成字面量）
    → 红；把任一处 QFont("Microsoft YaHei", …) 写回 → 红。审查实测：此前这条守卫只读
    pet_widgets.py，pet_dialogs 里那 24 处 setStyleSheet 用的 QSS 谁也管不着。
    """
    offenders = {}
    for name, src in _shipped_py_sources().items():
        hard = _hardcoded_qfont_families(src)
        single = _unfallback_font_declarations(src)
        if hard or single:
            offenders[name] = {"QFont 字面量": hard, "单族 font-family": single}
    assert offenders == {}, "仍有硬编码/无回退的字体声明：%r" % (offenders,)


def test_dialog_qss_uses_the_single_source_fallback_chain():
    """对话框 QSS 的族列表必须**由 pet_widgets.UI_FONT_FAMILIES 拼出**（不是两处各写一份）。

    能真失败：把 DIALOG_FONT_FAMILY 换成字面量 "Microsoft YaHei"（两处会漂移）→ 红；
    把 QSS 末尾的 .replace(...) 拿掉（占位符残留、链根本没进 QSS）→ 红。
    """
    import pet_dialogs
    fams = list(pet_widgets.UI_FONT_FAMILIES)
    qss = pet_dialogs.DIALOG_QSS
    assert pet_dialogs.DIALOG_QSS_FONT_TOKEN not in qss, "QSS 里的族占位符没被替换掉"
    assert pet_dialogs._qss_font_family(fams) == pet_dialogs.DIALOG_FONT_FAMILY, \
        "DIALOG_FONT_FAMILY 不是由 UI_FONT_FAMILIES 拼出来的"
    assert len(fams) >= 3 and pet_dialogs.DIALOG_FONT_FAMILY.count(",") >= 2, \
        "QSS 的族列表太短：%r" % (pet_dialogs.DIALOG_FONT_FAMILY,)
    for fam in fams:
        assert fam in qss, "回退链成员 %r 没进 QSS（两处口径漂移了）" % fam
    # 反向：换一条链，QSS 必须跟着换（否则说明 QSS 是另写死的一份）
    assert pet_dialogs._qss_font_family(("A", "B")) == "A, B"
    assert pet_dialogs._qss_font_family(("Microsoft YaHei",)) == '"Microsoft YaHei"'
    # 含空格的族名要带引号，否则 QSS 解析器只认第一个词
    assert pet_dialogs._qss_font_family(("SimSun",)) == "SimSun"


# ===================== P2-3：依赖上界（口径在 helpers_deps_bounds 单一来源） =====================
# v2.4.3（兼容审查 M3）：本文件此前自己写了一份"要检查的包名"元组，与
# test_deps_bounds_v24.py 的 NEED_BOUNDS 各写一份——新增依赖要改两处，漏一处就永远
# 不红（pytest 就是这么漏的）。现在解析与"必须有上界"的规则都来自
# tests/helpers_deps_bounds.py（那里的口径是"requirements.txt 里每个包都要有上界"），
# 本文件只钉 requests / PyInstaller 这两个**具体上界的数值**。

def test_requests_and_pyinstaller_have_upper_bounds():
    specs = req_specs(requirements_text())
    for name in ("requests", "PyInstaller"):
        key = name.lower()
        assert key in specs, "requirements.txt 没有声明 %s" % name
        bounds = dict(specs[key])
        assert "<" in bounds, "%s 没有上界（全新环境可能装到未验证的大版本）" % name
        assert ">=" in bounds, "%s 的下界被弄丢了" % name
    assert parse_version(dict(specs["requests"])["<"]) == (3,)
    assert parse_version(dict(specs["pyinstaller"])["<"]) == (7,)


def test_lock_versions_fit_inside_the_new_bounds():
    specs = req_specs(requirements_text())
    lock = req_specs(lock_text())
    for name in ("requests", "PyInstaller"):
        key = name.lower()
        assert key in lock, "lock 里没有 %s 的实测版本" % name
        pinned = [v for op, v in lock[key] if op == "=="]
        assert pinned, "lock 里 %s 不是精确锁定" % name
        assert satisfies(pinned[0], specs[key]), \
            "lock 的 %s==%s 落在 requirements.txt 区间之外" % (name, pinned[0])


def test_bound_checker_rejects_out_of_range_versions():
    """控制组：上界必须真的能拒——越界版本被判过关的话上面两条形同虚设。"""
    specs = req_specs(requirements_text())
    assert not satisfies("3.0.0", specs["requests"])
    assert not satisfies("2.27", specs["requests"])
    assert not satisfies("7.0", specs["pyinstaller"])
    assert not satisfies("5.9", specs["pyinstaller"])
    assert satisfies("2.34.2", specs["requests"])
    assert satisfies("6.22.2", specs["pyinstaller"])


# ===================== P3-2：CI 锁 pytest =====================

_BARE_PYTEST = re.compile(r"(?<![\w=])pytest(?!\s*==)")


def test_ci_pins_pytest_to_the_lock_version():
    ci = _read(os.path.join(".github", "workflows", "ci.yml"))
    lock = _read("requirements-lock.txt")
    m = re.search(r"^pytest==([0-9][0-9A-Za-z.\-]*)$", lock, re.M)
    assert m, "requirements-lock.txt 里没有锁定 pytest"
    want = "pytest==%s" % m.group(1)
    assert want in ci, "CI 没把 pytest 锁到 lock 的版本（%s）" % want
    installs = [ln for ln in ci.splitlines() if "pip install" in ln]
    assert installs, "没找到 CI 的 pip install 行"
    for ln in installs:
        assert not _BARE_PYTEST.search(ln), "CI 安装行里还有未锁版本的 pytest：%r" % ln


def test_bare_pytest_detector_can_fail():
    assert _BARE_PYTEST.search("pip install Pillow==12.1.1 pytest")
    assert not _BARE_PYTEST.search("pip install Pillow==12.1.1 pytest==9.1.1")


# ===================== P3-1：last_updated 时区 =====================

def test_last_updated_carries_timezone_offset(tmp_path):
    path = str(tmp_path / "memory.json")
    lt = pet_chat.write_long_term(path, {"preferences": ["香菜"]}, max_entries=3)
    stamp = lt["last_updated"]
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{4}$", stamp), \
        "last_updated 没有时区偏移：%r" % (stamp,)
    dt = datetime.datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S%z")
    assert dt.utcoffset() is not None
    assert stamp in _read_text(path), "落盘的 last_updated 与返回值不一致"


def _read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


# ===================== P3-3：zipfile 私有属性仍被消费 =====================

def _big_plan(tmp_path):
    """一个能过 validate_bundle 的 plan：**唯一**的条目就是跨片写的大素材。

    为什么只留一条：小条目走 stdlib 的 zf.write()（它自己会设私有属性），会把"大条目
    有没有设 _compresslevel"的差异盖住——那样本用例会变成空转（第一版就是这样，
    _dev/mutate_check.py 的 M-A10 变异没被抓到，见回报）。整包字节比较必须只被
    大条目的压缩结果影响。
    """
    roles = tmp_path / "roles"
    roles.mkdir(exist_ok=True)
    big = roles / "f00.png"
    big.write_bytes(b"abcdefghij" * 40000)          # 400KB 可压缩内容（级别差异看得见）
    assert os.path.getsize(str(big)) > pet_export._BIG_ENTRY_MIN_BYTES
    manifest = {"format": pet_export.BUNDLE_FORMAT, "version": pet_export.BUNDLE_VERSION,
                "role": {"id": "r3a", "name": "第三轮 A", "file": "f00.png",
                         "form": "single", "file_full": "", "frames": ["f00.png"],
                         "added": "", "forms": [{"name": "常态", "file": "f00.png",
                                                 "front": "f00.png",
                                                 "animations": {"idle": ["f00.png"]}}]},
                "behaviors": [], "config": {}, "excluded": [], "alarms": []}
    return {"manifest": manifest, "entries": [("roles/f00.png", str(big))]}


def _write_with_level(tmp_path, plan, level, name):
    """按片驱动写出一个包；返回 (整包字节, _big_begin 调用次数)。"""
    out = str(tmp_path / name)
    w = pet_export.BundleWriter(plan, out, compresslevel=level)
    stats = {"big": 0}
    real_begin = w._big_begin

    def spy(arc, src):
        stats["big"] += 1
        return real_begin(arc, src)

    w._big_begin = spy
    guard = 0
    while not w.done:
        w.step(budget_ms=0.5)
        guard += 1
        assert guard < 200, "分片驱动没有收敛（测试自身兜底）"
    ok, err = w.finish()
    assert ok, err
    with open(out, "rb") as f:
        return f.read(), stats["big"]


def test_zipinfo_compresslevel_is_still_consumed(tmp_path):
    """私有属性 _compresslevel 必须仍被 CPython 消费：换级别 → 产出字节必须不同。

    能真失败：删掉 pet_export._big_begin 里的 "zinfo._compresslevel = ..."（或未来某个
    Python 版本不再读它），zinfo 就退回默认级别（None → zlib 6），1 与 9 两个级别写出
    完全相同的字节 → 本用例红（这正是报告 P3-3 担心的静默失效）。
    """
    plan = _big_plan(tmp_path)
    b1, big1 = _write_with_level(tmp_path, plan, 1, "lvl1.zip")
    b9, big9 = _write_with_level(tmp_path, plan, 9, "lvl9.zip")
    assert big1 >= 1 and big9 >= 1, "大条目没走 _big_begin：这条用例没验证到私有属性那条路径"
    assert b1 != b9, "压缩级别没有生效：zipfile 私有属性 _compresslevel 已不再被消费"
    assert len(b1) != len(b9)
    # 双保险：直接看**大条目**的压缩尺寸（整包字节里还混着 manifest 等固定内容）
    import zipfile
    with zipfile.ZipFile(str(tmp_path / "lvl1.zip")) as z1, \
            zipfile.ZipFile(str(tmp_path / "lvl9.zip")) as z9:
        assert z1.getinfo("roles/f00.png").compress_size != \
            z9.getinfo("roles/f00.png").compress_size, \
            "大条目的压缩尺寸不随级别变：_compresslevel 没被消费"


def test_zipinfo_still_has_the_private_attribute():
    """依赖存在性前置断言：属性被改名时给出直白原因（而不是只在字节比较里变红）。"""
    import zipfile
    zi = zipfile.ZipInfo("x")
    assert hasattr(zi, "_compresslevel"), "CPython 的 ZipInfo 已经没有 _compresslevel 了"
    assert zi._compresslevel is None, "默认值变了：产出字节口径要重新对拍"


# ===================== P3-4：_almost_utf8 极小文件退化 =====================

def test_tiny_western_file_is_not_almost_utf8():
    """<200 字节时段数上限退化为 1，但判据二仍须把纯西文小文件挡住。"""
    raw = b"caf\xe9 price 12.00"
    assert len(raw) < 200
    assert pet_io._almost_utf8(raw) is False, "纯西文小文件被误判成坏 UTF-8（会按 GBK 读成乱码）"
    tiny_cn = "中文测试".encode("utf-8")[:-1]        # 截断尾巴：1 个损坏段 + 3 个完好汉字
    assert len(tiny_cn) < 200
    assert pet_io._almost_utf8(tiny_cn) is True, "极小文件里的坏 UTF-8 中文应仍能被救回"


def test_almost_utf8_documents_the_small_file_degradation():
    doc = pet_io._almost_utf8.__doc__ or ""
    assert "退化" in doc, "极小文件退化这条已知取舍必须有文档说明（报告 P3-4）"
    src = _read("pet_io.py")
    assert "极小文件会退化" in src, "常量区的退化说明丢了"


# ===================== 口径：README 注解表格必须与实测一致 =====================

def _annotation_counts(name):
    """(带返回注解的函数数, 函数总数)。"""
    tree = ast.parse(_read(name))
    tot = ret = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            tot += 1
            ret += 1 if node.returns is not None else 0
    return ret, tot


def _readme_rows(text):
    """README 注解表格 → {模块名: (已注解, 总数)}。

    v2.4.3（质量审查 M1）：两类行都解析——
      · ✅/⚠️ 行：`| `mod.py` | ✅ 39/39 | …` → (39, 39)；
      · ❌ 行：同一格里并排多个模块，`` `桌宠.py`（253 函数）/ `pet_dialogs.py`（251） ``
        → (0, N)（英文 README 是 `(253 funcs)`，中英括号都要认）。
    此前只认 ✅/⚠️ 且只对 ANNOTATED_MODULES 取，`桌宠.py`（248 函数）那一行**没有任何
    用例看着**：实测把 248 改成 999，两条 README 用例都过。
    """
    out = {}
    for name in ANNOTATED_MODULES:
        m = re.search(r"\|\s*`%s`\s*\|\s*(?:✅|⚠️)\s*(\d+)/(\d+)" % re.escape(name), text)
        if m:
            out[name] = (int(m.group(1)), int(m.group(2)))
    for line in text.splitlines():
        if not line.lstrip().startswith("|") or "❌" not in line:
            continue
        for mod, num in re.findall(r"`([A-Za-z0-9_.\u4e00-\u9fff\-]+\.py)`\s*[（(]\s*(\d+)",
                                   line):
            out.setdefault(mod, (0, int(num)))
    return out


def test_readme_annotation_scope_matches_the_code():
    """README 里的 注解数/函数数 必须是 AST 实测值（防表格过期 / 又写成"全仓完成"）。

    v2.4.3（质量审查 M1）：❌ 行里点名的大文件同样要被 AST 核对（此前那行无人守）。
    """
    for readme in ("README.md", "README.en.md"):
        rows = _readme_rows(_read(readme))
        assert set(rows) >= set(ANNOTATED_MODULES), \
            "%s 的注解表格缺模块：%r" % (readme, sorted(set(ANNOTATED_MODULES) - set(rows)))
        # 口径澄清的核心就是这三个大文件：必须在表里被点名（且数字要被核对）
        for big in ("桌宠.py", "pet_dialogs.py"):
            assert big in rows, ("%s 的表格没有点名 %s 的函数总数（大文件口径无人守）"
                                 % (readme, big))
        for name, (claimed_ret, claimed_tot) in rows.items():
            got = _annotation_counts(name)
            assert (claimed_ret, claimed_tot) == got, \
                "%s 里 %s 写成 %d/%d，实际是 %d/%d" % (readme, name, claimed_ret, claimed_tot,
                                                        got[0], got[1])


def test_readme_says_the_big_files_are_not_done():
    zh = _read("README.md")
    assert "类型注解口径" in zh
    assert "单独立项" in zh and "桌宠.py" in zh and "pet_dialogs.py" in zh
    assert "82/82" in zh, "必须点名澄清 v2.4.1 那句 82/82 的口径，否则还会被误读"
    en = _read("README.en.md")
    assert "Type-annotation scope" in en and "82/82" in en and "pet_dialogs.py" in en


def test_module_docstrings_state_the_annotation_scope():
    """口径也要写在代码里：读 pet_io / pet_chat 头注释的人不该被"82/82"误导。"""
    for mod in (pet_io, pet_chat):
        doc = mod.__doc__ or ""
        assert "类型注解口径" in doc, "%s 的模块注释没写注解口径" % mod.__name__
        assert "单独立项" in doc, "%s 的注释没说清大文件是单独立项" % mod.__name__
        assert "82" in doc, "%s 的注释没点名澄清 82/82 那句口径" % mod.__name__


def test_readme_row_parser_can_fail():
    """控制组：表格解析器认不出被改坏的表格（否则上面的断言是空转）。"""
    good = "| `pet_tools.py` | ✅ 39/39 | x |"
    assert _readme_rows(good) == {"pet_tools.py": (39, 39)}
    assert _readme_rows("| pet_tools.py | 39/39 |") == {}
    # v2.4.3（M1）：❌ 行里的 "(N 函数)" 也要解析，中英两种括号都要认
    zh = "| `桌宠.py`（253 函数）/ `pet_dialogs.py`（251） | ❌ 0 | x |"
    assert _readme_rows(zh) == {"桌宠.py": (0, 253), "pet_dialogs.py": (0, 251)}
    en = "| `桌宠.py` (253 funcs) / `pet_dialogs.py` (251) | ❌ 0 | x |"
    assert _readme_rows(en) == {"桌宠.py": (0, 253), "pet_dialogs.py": (0, 251)}
    # 没写数字的行不许瞎猜（"❌ 0" 那格本身不是函数总数）
    assert _readme_rows("| `pet_chat.py` / `pet_balance.py` | ❌ 0 | x |") == {}
    # ✅ 行不能把 ❌ 行的数字吸进来，反之亦然
    assert _readme_rows(good + chr(10) + zh) == {"pet_tools.py": (39, 39),
                                                 "桌宠.py": (0, 253),
                                                 "pet_dialogs.py": (0, 251)}
