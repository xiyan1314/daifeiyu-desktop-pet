# -*- coding: utf-8 -*-
"""v2.13.0（体积与暴露面）菜单结构的钉子：一级菜单恰好 9 项，功能只搬家不丢失。

每条能真失败在哪：
- 顶层加一条 / 改名 / 调顺序 -> test_top_level_is_exactly_nine 红（精确等于 9）；
- 四个开关搬回顶层或漏搬 -> test_moved_toggles 红；
- 搬过去但 toggled 接错方法 / 初始勾选写死 -> test_moved_toggles 红；
- 余额行被删或又回顶层 -> test_balance_line 红；
- 「更多」里少一条或点了不触发 -> test_more_menu 红；
- 资源管理入口出现两次（D3 回归）-> test_resource_manager_appears_once 红。

不读真桌面：复用 test_menu_preview_v2120 的 offscreen 假桌宠。
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtWidgets import QMenu  # noqa: E402

import pet_menu  # noqa: E402
from test_menu_preview_v2120 import _MenuPet  # noqa: E402

TOP_LEVEL = ["💭 和它说话", "🍖 喂食", "🐟 角色", "💰 记账",
             "📦 资源管理…", "⚙️ 设置…", "🎭 动作", "ℹ️ 更多", "⏹ 退出"]


def _open(pet):
    cap = {}

    class _Cap(QMenu):
        def exec(self, *_a, **_k):  # noqa: A003
            cap["top"] = list(self.actions())
            for act in self.actions():
                if act.menu() is not None:
                    cap[act.text()] = act.menu()
            return None

    pet._new_menu = lambda: _Cap(pet)
    pet_menu.MenuBuilder(pet, lambda cfg: None, lambda: False).open(QPoint(5, 5))
    return cap


def _texts(actions):
    return [a.text() for a in actions if a.text()]


def _find(actions, text):
    for a in actions:
        if a.text() == text:
            return a
    raise AssertionError("菜单里没有 %r（现有：%r）" % (text, _texts(actions)))


def test_top_level_is_exactly_nine():
    top = _texts(_open(_MenuPet())["top"])
    assert top == TOP_LEVEL, "顶层不是 9 条公开口径：\n实际 %r\n应 %r" % (top, TOP_LEVEL)


def test_moved_toggles_live_in_settings_and_keep_their_wiring():
    pet = _MenuPet()
    calls = []
    pet._set_always_on_top = lambda on: calls.append(("topmost", bool(on)))
    pet._set_sound = lambda on: calls.append(("sound", bool(on)))
    pet.ai.set_ai_enabled = lambda on: calls.append(("ai", bool(on)))
    pet._set_physics = lambda on: calls.append(("physics", bool(on)))
    cap = _open(pet)
    top = _texts(cap["top"])
    settings = cap["⚙️ 设置…"].actions()
    labels = _texts(settings)
    for label in ("📌 窗口置顶", "🔊 音效", "🤖 AI对话", "🌀 甩抛物理"):
        assert label in labels, "设置里没有 %r（现有：%r）" % (label, labels)
        assert label not in top, "%r 又回到顶层了" % (label,)
    assert _find(settings, "📌 窗口置顶").isChecked() is True
    assert _find(settings, "🔊 音效").isChecked() is True
    assert _find(settings, "🤖 AI对话").isChecked() is False
    assert _find(settings, "🌀 甩抛物理").isChecked() is False
    # 四个开关**全部**要 trigger：只测两个的话，删掉另两条 connect 仍然绿
    # （v2.13.0 三审实测：删 :164 / :177 的 toggled.connect → 旧版本 6 passed）。
    _find(settings, "📌 窗口置顶").trigger()
    _find(settings, "🔊 音效").trigger()
    _find(settings, "🤖 AI对话").trigger()
    _find(settings, "🌀 甩抛物理").trigger()
    assert calls == [("topmost", False), ("sound", False), ("ai", True), ("physics", True)], calls


def test_balance_line_moved_into_ledger_menu():
    pet = _MenuPet()
    pet._shown_balance = 12.34
    pet._usage = 5.0
    cap = _open(pet)
    first = cap["💰 记账"].actions()[0]
    assert "余额" in first.text() and "12.34" in first.text(), first.text()
    assert first.isEnabled() is False, "余额信息行必须只读"
    assert not any("余额" in t or "今日已用" in t for t in _texts(cap["top"]))


def test_more_menu_holds_companion_entries_and_they_still_fire():
    pet = _MenuPet()
    fired = []
    pet.mood.blush = lambda: fired.append("blush")
    pet.weather.fetch = lambda: fired.append("weather")
    pet._set_city = lambda *a: fired.append("city")
    pet.actions.show_system_status = lambda: fired.append("status")
    pet._about = lambda *a: fired.append("about")
    cap = _open(pet)
    acts = cap["ℹ️ 更多"].actions()
    labels = _texts(acts)
    expected = ["❤️ 夸夸她", "☀️ 今日天气", "📍 天气城市…", "🖥️ 系统状态", "ℹ️ 关于"]
    for label in expected:
        assert label in labels, "「更多」里没有 %r（现有：%r）" % (label, labels)
        assert label not in _texts(cap["top"]), "%r 又回到顶层了" % (label,)
    for label in expected:
        _find(acts, label).trigger()
    assert fired == ["blush", "weather", "city", "status", "about"], fired


def test_resource_manager_appears_once():
    def walk(actions):
        for a in actions:
            yield a
            if a.menu() is not None:
                for sub in walk(a.menu().actions()):
                    yield sub

    hits = [a.text() for a in walk(_open(_MenuPet())["top"]) if "资源管理" in a.text()]
    assert hits == ["📦 资源管理…"], hits


def test_settings_menu_kept_all_old_entries():
    settings = _texts(_open(_MenuPet())["⚙️ 设置…"].actions())
    assert len(settings) >= 30, "设置只剩 %d 条（搬家丢功能）：%r" % (len(settings), settings)
    # 点名清单要足够长：只钉 8 条时，删掉「⏰ 闹钟…」仍绿（三审实测）。
    for label in ("📌 窗口置顶", "🔊 音效", "🤖 AI对话", "🌀 甩抛物理",
                  "🖱️ 跟随鼠标", "🚶 散步", "🎨 气泡样式…", "🖱️ 透明区穿透",
                  "🖥️ 全屏时自动隐藏", "🔔 系统通知", "💾 备份数据…", "♻️ 从备份恢复…",
                  "⏰ 时段问候", "🎁 惊喜彩蛋", "👀 菜单悬停预览", "🌊 减少动效",
                  "🔲 高对比度", "🎞️ 帧数上限…", "🌀 物理参数…", "🎤 语音设置…",
                  "🧩 行为设置…", "😴 待机设置…", "⏰ 闹钟…", "🎵 音效设置",
                  "💬 自定义台词…", "🚀 开机自启", "🤖 AI设置…", "🧠 对话记忆…",
                  "🧹 清理日志…", "🧩 插件管理…"):
        assert label in settings, "设置里丢了 %r" % (label,)
