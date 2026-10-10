# -*- coding: utf-8 -*-
"""pet_mood.Mood 状态机回归（戳链/食物超时/调皮节流）。"""
import time

import pytest
# N4（v2.4.1）：**必须是 QApplication**，不能是 QCoreApplication——其它模块用
# "QApplication.instance() or QApplication([])" 复用进程里已有的 app，而这个 truthy 的
# QCoreApplication 会被当成"已有 app"收下，之后任何模块建 QWidget 都会 Qt fatal 崩进程
# （退出码 0xC0000409、无 traceback，表现为"单跑绿、全量崩"）。
from PySide6.QtWidgets import QApplication

import pet_mood


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _make_mood():
    m = pet_mood.Mood()
    m.prime_mischief()
    return m


def test_poke_chain(qapp):
    m = _make_mood()
    states, emotes = [], []
    m.state.connect(states.append)
    m.emote.connect(emotes.append)
    m.poke()
    m.poke()
    m.poke()
    assert states == ["puzzled", "angry", "hiss"]
    assert emotes == ["question", "anger", "anger"]


def test_poke_reset_after_threshold(qapp, monkeypatch):
    m = _make_mood()
    states = []
    m.state.connect(states.append)
    m.poke()
    monkeypatch.setattr(time, "monotonic", lambda: 10 ** 15)  # 远大于当前单调时钟
    m.poke()
    assert states == ["puzzled", "puzzled"]  # 重新从 1 开始


def test_food_withhold(qapp):
    m = _make_mood()
    states = []
    m.state.connect(states.append)
    m.food_shown()
    assert states == ["drool"]
    m._withhold()
    assert states[-1] == "cry"
    m.fed()  # 不抛


def test_mischief_primed(qapp, monkeypatch):
    m = _make_mood()
    states = []
    m.state.connect(states.append)
    m.tick()
    assert states == []  # prime 后首次 tick 不触发
    monkeypatch.setattr(time, "monotonic", lambda: 10 ** 15)
    m.tick()
    assert states == ["smug"]

