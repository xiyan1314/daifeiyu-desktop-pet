# -*- coding: utf-8 -*-
"""v2.8.0 第 6 轮（代理 B）：pet_balance.add_manual_record 的两处"点了没反应"。

对应 _dev/audit_feedback_v270.md §5 的 S20 / P3-3（菜单「✏️ 记一笔…」）：
  · 对话框构建/弹出失败：此前**只写日志** —— 用户点了菜单毫无反应（与 open_ledger 同一类问题）；
  · 金额 <= 0（含清空后点确定）：此前**静默丢弃** —— 用户以为记上了，账本里却没有。

口径与 open_ledger 一致：日志 + 宠物气泡（**不 import** pet_dialogs 的私有助手），
气泡是"一次用户动作一句反馈"里那一句，不抢焦点、不弹模态。

这里用**替身 pet / 替身账本**直接驱动 BalanceService.add_manual_record：判据是结构性事实
（收到了哪个调用、气泡里有哪句话、日志里有哪一行），不依赖机器速度、不需要真窗口。

    python -B -m pytest tests/test_balance_feedback_v280.py -o addopts="" -q
"""
import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pet_balance    # noqa: E402
import pet_log        # noqa: E402

from PySide6.QtWidgets import QDialog  # noqa: E402


class _FakePet(object):
    """只提供 add_manual_record 用到的那两件事（气泡 + 账本变更通知）。"""

    def __init__(self, bubble_boom=False):
        self.bubbles = []
        self.ledger_pings = 0
        self._boom = bubble_boom

    def show_bubble(self, text):
        if self._boom:
            raise RuntimeError("气泡本身也炸了（模拟）")
        self.bubbles.append(text)

    def on_ledger_changed(self):
        self.ledger_pings += 1


class _FakeBook(object):
    """账本替身：把"有没有真记账"变成可断言的结构性事实。"""

    def __init__(self):
        self.calls = []

    def add_manual(self, amount, note):
        self.calls.append((amount, note))


def _service(pet, book, logs):
    return pet_balance.BalanceService(
        pet, None, lambda: {}, lambda: book, lambda kind: None,
        lambda cfg: None, lambda msg: logs.append(msg), lambda: None)


class _FakeDialog(object):
    """假「记一笔」对话框：不进 exec()，直接给出 values()/result()。"""

    def __init__(self, values, accepted=True, boom=False):
        self._values = values
        self._accepted = accepted
        if boom:
            raise RuntimeError("假对话框构建失败（模拟）")

    def values(self):
        return self._values

    def result(self):
        return QDialog.DialogCode.Accepted if self._accepted else QDialog.DialogCode.Rejected


def _install_dialog(monkeypatch, values=None, accepted=True, boom=False):
    def _factory(_pet, _amount, _note):
        return _FakeDialog(values if values is not None else (0.0, ""),
                           accepted=accepted, boom=boom)
    monkeypatch.setattr(pet_balance.pet_dialogs, "AmountNoteDialog", _factory)
    monkeypatch.setattr(pet_balance.pet_dialogs, "modal", lambda _dlg: None)
    # 安全网：万一哪条路退回裸 exec()，offscreen 下模态 exec 会**挂死整条 pytest**
    monkeypatch.setattr(QDialog, "exec", lambda _self: QDialog.DialogCode.Rejected)


def test_对话框构建失败_有可见提示与日志(monkeypatch, tmp_path):
    """构建/弹出失败 → 气泡（用户看得见）+ 日志（可查），绝不静默。

    改前：except 里只有 self._log —— 用户点了菜单毫无反应。
    变异：删掉 except 里的 pet.show_bubble(...) 那两行（退回"只写日志"）→ 第一条断言红。
    """
    pet_log.set_data_dir(str(tmp_path))
    pet, book, logs = _FakePet(), _FakeBook(), []
    svc = _service(pet, book, logs)
    _install_dialog(monkeypatch, boom=True)

    svc.add_manual_record(12.0, "午饭")           # 不许抛

    assert pet.bubbles and "打不开" in pet.bubbles[-1], pet.bubbles
    assert "记一笔" in pet.bubbles[-1], pet.bubbles
    assert "模拟" in pet.bubbles[-1], "原因没给出来：%r" % (pet.bubbles[-1],)
    assert any("add_manual_record failed" in m for m in logs), logs
    assert book.calls == [], "对话框没建起来却记了账：%r" % (book.calls,)


def test_金额不大于零_给提示且绝不记账(monkeypatch):
    """金额 0 / 空 → 明说"没有记"，且**一次 add_manual 都不能发生**。

    改前：if amount and amount > 0 的 else 分支不存在 —— 静默丢弃（用户以为记上了）。
    变异：删掉那条 else 分支 → 第一条断言红（bubbles 为空）。
    """
    for values in ((0.0, ""), (None, ""), (-3.0, "退钱")):
        pet, book, logs = _FakePet(), _FakeBook(), []
        svc = _service(pet, book, logs)
        _install_dialog(monkeypatch, values=values)

        svc.add_manual_record()

        assert pet.bubbles, "金额 %r 被静默丢弃了（一条提示都没有）" % (values,)
        assert "没有记" in pet.bubbles[-1], pet.bubbles
        assert "大于 0" in pet.bubbles[-1], pet.bubbles
        assert book.calls == [], "金额 %r 竟然记账了：%r" % (values, book.calls)
        assert pet.ledger_pings == 0, "没记账却通知了账本变更"


def test_正常记账的回执与联动没被改坏(monkeypatch):
    """反向控制组：金额正常时照旧记账 + 通知账本 + 「记好啦：N 元」回执。"""
    pet, book, logs = _FakePet(), _FakeBook(), []
    svc = _service(pet, book, logs)
    _install_dialog(monkeypatch, values=(12.5, "午饭"))

    svc.add_manual_record()

    assert book.calls == [(12.5, "午饭")], book.calls
    assert pet.ledger_pings == 1, "记账了却没通知账本刷新"
    assert pet.bubbles and "记好啦：12.50 元" in pet.bubbles[-1], pet.bubbles
    assert logs == [], "正常路径不该写失败日志：%r" % (logs,)


def test_取消对话框_一个字都不动也不打扰(monkeypatch):
    """用户点取消：不记账、不提示（这不是失败，是"我不想记了"）。"""
    pet, book, logs = _FakePet(), _FakeBook(), []
    svc = _service(pet, book, logs)
    _install_dialog(monkeypatch, values=(99.0, "取消前填的"), accepted=False)

    svc.add_manual_record()

    assert book.calls == [] and pet.ledger_pings == 0
    assert pet.bubbles == [], "取消也弹提示（默认零打扰）：%r" % (pet.bubbles,)
    assert logs == [], logs


def test_气泡自己也炸时_只留日志不抛(monkeypatch, tmp_path):
    """兜底：连 show_bubble 都炸时不许把异常抛回调用方（菜单回调里抛 = 用户看到别的怪象）。

    变异：删掉 except 里那层嵌套 try/except（只留 self._log 之后的 show_bubble）→ 本用例红。
    """
    pet_log.set_data_dir(str(tmp_path))
    pet, book, logs = _FakePet(bubble_boom=True), _FakeBook(), []
    svc = _service(pet, book, logs)
    _install_dialog(monkeypatch, boom=True)

    svc.add_manual_record(1.0, "x")               # 不许抛

    assert any("add_manual_record notify failed" in m for m in logs), logs
