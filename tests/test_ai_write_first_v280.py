# -*- coding: utf-8 -*-
"""v2.8.0 第 6 轮（代理 B）：pet_ai 三处「先改内存再写盘」→「先写盘成功再提交」。

覆盖：
  · set_api_key / set_ai_enabled / set_chat_rounds 的成功路径**与改前逐位等价**
    （内容与**键顺序**都一致，盘上字节也一致——用确定性 encrypt_secret 把 DPAPI 的随机性
    钉住，才可能做"逐位"比较）；
  · 失败路径：**内存不变** + 如实气泡（不复用成功话术） + 日志留痕；
  · set_ai_enabled 的第二次落盘（没 Key 把开关退回关）也必须"成功才提交"。

约定（照抄 tests/test_feedback_host_v270.py）：offscreen + 真 PetWindow + 临时数据目录；
不进模态 exec（用假 QInputDialog 直接给结论）；断言只写结构性事实（内存 / 盘上内容 / 日志行）。

    python -B -m pytest tests/test_ai_write_first_v280.py -o addopts="" -q
"""
import copy
import json
import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import 桌宠 as main  # noqa: E402
import pet_ai  # noqa: E402
import pet_log  # noqa: E402

from PySide6.QtWidgets import QApplication  # noqa: E402


def _boot_application():
    """进程里必须有**真正的 QApplication**（不是 QCoreApplication，否则 QWidget 构造即 abort）。"""
    app = QApplication.instance()
    if app is None:
        return QApplication([])
    return app


_APP = _boot_application()


def _ensure_qapplication():
    app = QApplication.instance()
    if isinstance(app, QApplication):
        return app
    pytest.fail("进程里只有 QCoreApplication（不是 QApplication），QWidget 无法构造；"
                "请单独跑本文件。", pytrace=False)


@pytest.fixture(scope="module")
def pet(tmp_path_factory):
    """真 PetWindow + 全部运行时路径指向临时目录（退出时还原进程级全局）。"""
    tmp = tmp_path_factory.mktemp("aiwrite280")
    _snap = (main.DATA_DIR, main.CONFIG_PATH, main.USAGE_PATH, main.MEMORY_PATH,
             getattr(pet_log, "_data_dir", None))
    main.DATA_DIR = str(tmp)
    main.CONFIG_PATH = str(tmp / "config.json")
    main.USAGE_PATH = str(tmp / "usage.json")
    main.MEMORY_PATH = str(tmp / "memory.json")
    pet_log.set_data_dir(str(tmp))
    _ensure_qapplication()
    win = main.PetWindow()
    from helpers_roles import quiet_pet_timers
    quiet_pet_timers(win)          # 停掉会自行弹气泡的周期定时器（否则会污染"几条气泡"）
    yield win
    from helpers_roles import active_timer_count, shutdown_pet
    shutdown_pet(win)
    QApplication.processEvents()
    (main.DATA_DIR, main.CONFIG_PATH, main.USAGE_PATH,
     main.MEMORY_PATH) = _snap[0], _snap[1], _snap[2], _snap[3]
    pet_log.set_data_dir(_snap[4])
    assert active_timer_count(win) == 0, \
        "拆完还有 %d 个活跃定时器（顺序污染源）" % active_timer_count(win)


@pytest.fixture
def cfg_back(pet):
    """用例级还原：真 PetWindow 是模块级共享的，配置必须在用例后复原并重写盘。"""
    cfg = copy.deepcopy(pet.cfg)
    yield
    pet.cfg.clear()
    pet.cfg.update(cfg)
    main.save_config(pet.cfg)


def _log_text(tmp_path=None):
    """两处日志出口都读出来（桌宠.DATA_DIR 与 conftest 隔离的 pet_log 目录）。"""
    paths = [os.path.join(str(main.DATA_DIR), "error.log")]
    if tmp_path is not None:
        paths.append(str(tmp_path / "error.log"))
    out = []
    for p in paths:
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as fh:
                out.append(fh.read())
    return "\n".join(out)


def _disk_bytes():
    with open(main.CONFIG_PATH, "rb") as fh:
        return fh.read()


def _disk_json():
    with open(main.CONFIG_PATH, encoding="utf-8-sig") as fh:
        return json.load(fh)


class _FakeInputDialog(object):
    """替代 pet_ai.QInputDialog：不进 exec()（offscreen 下会挂死），直接给结论。"""

    InputMode = None

    def __init__(self, text="", accepted=True, intval=0):
        self._text = text
        self._accepted = accepted
        self._int = intval

    def setWindowTitle(self, *_a):
        pass

    def setLabelText(self, *_a):
        pass

    def setTextEchoMode(self, *_a):
        pass

    def setTextValue(self, *_a):
        # talk() 会先 setTextValue("") 预填；有意**不**覆盖构造时给的"用户输入"
        pass

    def setInputMode(self, *_a):
        pass

    def setIntRange(self, *_a):
        pass

    def setIntValue(self, v):
        # 有意**不**覆盖：产品代码会先 setIntValue(当前值) 再 exec()，覆盖了就等于
        # "用户输入"被预填值吃掉（intval 是构造时给的"用户最终按下的值"）。
        pass

    def intValue(self):
        return self._int

    def windowFlags(self):
        from PySide6.QtCore import Qt as _Qt
        return _Qt.WindowType.Widget

    def setWindowFlags(self, *_a):
        pass

    def show(self):
        pass

    def raise_(self):
        pass

    def activateWindow(self):
        pass

    def setFocus(self):
        pass

    def textValue(self):
        return self._text

    def exec(self):
        from PySide6.QtWidgets import QDialog as _Q
        return _Q.DialogCode.Accepted if self._accepted else _Q.DialogCode.Rejected


def _install_fake_input(monkeypatch, **kw):
    """换成**既可直接调用、又带 InputMode 枚举**的工厂（pet_ai 里两种写法都有）。"""
    from PySide6.QtWidgets import QInputDialog as _Real

    class _F(_FakeInputDialog):
        pass

    class _Factory(object):
        InputMode = _Real.InputMode

        def __call__(self, *_a, **_k):
            return _F(**kw)

    monkeypatch.setattr(pet_ai, "QInputDialog", _Factory())
    return _F


# ================= 成功路径：与改前逐位等价 =================

def test_set_api_key_成功路径与改前逐位等价(pet, cfg_back, monkeypatch):
    """成功时：内存内容 / **键顺序** / 盘上字节都与"改前的写法"完全一致。

    做法：把 encrypt_secret 换成确定性实现（DPAPI 每次密文都不同，不钉住就没法比字节），
    先跑产品路径取字节，再照改前的写法（原地改 cfg + save）算控制组字节，两者必须相同。
    变异：把 set_api_key 改成"先 cfg.update 再 save"（或多提交一个键）→ 字节/键顺序对不上，红。
    """
    monkeypatch.setattr(main, "encrypt_secret", lambda s: ("enc:" + s) if s else "")
    pet.cfg["api_key"] = "sk-旧值"
    pet.cfg["ai_reply_len"] = 20
    pet.cfg["chat_memory_rounds"] = 3
    assert main.save_config(pet.cfg) is None
    keys_before = list(pet.cfg.keys())
    start = dict(pet.cfg)

    bubbles = []
    monkeypatch.setattr(pet, "show_bubble", lambda t: bubbles.append(t))
    _install_fake_input(monkeypatch, text="sk-新值")
    pet.ai.set_api_key()
    assert bubbles and "记住啦" in bubbles[-1], bubbles
    assert pet.cfg["api_key"] == "sk-新值", "成功路径没提交进内存"
    assert list(pet.cfg.keys()) == keys_before, \
        "成功路径挪动了键顺序：%r → %r" % (keys_before, list(pet.cfg.keys()))
    product_bytes = _disk_bytes()

    # 回到同一个起点，按**改前**的写法算控制组（原地改 + 保存）
    pet.cfg.clear()
    pet.cfg.update(start)
    assert main.save_config(pet.cfg) is None
    assert _disk_bytes() != product_bytes, "用例前提：控制组必须从旧值重新写一遍"
    ctrl = dict(start)
    ctrl["api_key"] = "sk-新值"
    assert main.save_config(ctrl) is None
    assert _disk_bytes() == product_bytes, "成功路径与改前不逐位等价（盘上字节不同）"
    assert _disk_json()["api_key"] == "enc:sk-新值", _disk_json()


def test_set_chat_rounds_成功路径落盘且内存同步(pet, cfg_back, monkeypatch):
    """反向控制组：真改了值 → 盘上是新值、内存是新值、气泡是成功话术。"""
    bubbles = []
    monkeypatch.setattr(pet, "show_bubble", lambda t: bubbles.append(t))
    _install_fake_input(monkeypatch, intval=7)
    pet.ai.set_chat_rounds()
    assert _disk_json()["chat_memory_rounds"] == 7, _disk_json()
    assert pet.cfg["chat_memory_rounds"] == 7
    assert bubbles and "记住最近 7 轮" in bubbles[-1], bubbles


# ================= 失败路径：内存不变 + 如实气泡 + 留痕 =================

def test_set_api_key_写失败_内存不变且不说记住了(pet, cfg_back, tmp_path, monkeypatch):
    """写盘失败：Key **不提交进内存**、盘上不动、气泡给原因、error.log 有记录。

    改前是"先 cfg['api_key'] = key 再 save"——失败后本次会话已经在用新 Key（用户却读到
    "没能保存"）。变异：把 `new = dict(cfg)` 改回 `new = cfg`（= 原地改）→ 第二条断言红。
    """
    pet.cfg["api_key"] = "sk-旧值"
    assert main.save_config(pet.cfg) is None
    disk_before = _disk_bytes()

    bubbles = []
    monkeypatch.setattr(pet, "show_bubble", lambda t: bubbles.append(t))
    monkeypatch.setattr(pet.ai, "_save_cfg", lambda _cfg: "磁盘只读（注入）")
    _install_fake_input(monkeypatch, text="sk-新值")
    pet.ai.set_api_key()

    assert bubbles and "磁盘只读（注入）" in bubbles[-1], bubbles
    assert "记住啦" not in bubbles[-1], "写失败仍回「记住啦！」：%r" % (bubbles[-1],)
    assert pet.cfg["api_key"] == "sk-旧值", "写失败却把新 Key 提交进内存了"
    assert _disk_bytes() == disk_before, "写失败却动了盘"
    assert "set_api_key save failed" in _log_text(tmp_path), "写失败没有留痕"


def test_set_ai_enabled_写失败_内存不变且不假装生效(pet, cfg_back, tmp_path, monkeypatch):
    """开关写盘失败：内存里的 ai_enabled 不变 + 气泡给原因 + 日志留痕。

    变异：把 `cfg.update(new)` 提前到 `if err` 之前 → 第二条断言红。
    """
    pet.cfg["ai_enabled"] = False
    assert main.save_config(pet.cfg) is None

    bubbles = []
    monkeypatch.setattr(pet, "show_bubble", lambda t: bubbles.append(t))
    monkeypatch.setattr(pet.ai, "_save_cfg", lambda _cfg: "磁盘只读（注入）")
    pet.ai.set_ai_enabled(True)

    assert bubbles and "磁盘只读（注入）" in bubbles[-1], bubbles
    assert pet.cfg["ai_enabled"] is False, "写失败却把开关状态改了"
    assert _disk_json().get("ai_enabled", False) in (False, None) or \
        not _disk_json().get("ai_enabled"), "写失败却动了盘"
    assert "set_ai_enabled save failed" in _log_text(tmp_path), "写失败没有留痕"


def test_set_ai_enabled_无Key回退落盘失败_内存保持已提交值(pet, cfg_back, tmp_path, monkeypatch):
    """第一次落盘成功、第二次（没 Key 把开关退回关）失败 → 内存保持**已提交**的 True。

    改前：第二次无论成败都把内存改成 False（盘上却是 True）——同一件事两个真相。
    变异：把 `if not _bad2:` 去掉（无条件 cfg.update(new2)）→ 第二条断言红。
    """
    pet.cfg["api_key"] = ""
    pet.cfg["ai_enabled"] = False
    assert main.save_config(pet.cfg) is None
    monkeypatch.setattr(pet.ai, "set_api_key", lambda: None)   # 不弹输入框 = 用户没填 Key

    calls = []

    def save(cfg):
        calls.append(dict(cfg))
        return None if len(calls) == 1 else "磁盘只读（注入）"

    bubbles = []
    monkeypatch.setattr(pet, "show_bubble", lambda t: bubbles.append(t))
    monkeypatch.setattr(pet.ai, "_save_cfg", save)
    pet.ai.set_ai_enabled(True)

    assert len(calls) == 2, "第二次落盘（把开关退回关）没有被调用：%r" % (calls,)
    assert calls[0]["ai_enabled"] is True and calls[1]["ai_enabled"] is False, calls
    assert pet.cfg["ai_enabled"] is True, \
        "第二次写盘失败了，内存却提交了没写进去的值（盘与内存两个真相）"
    assert bubbles and "磁盘只读（注入）" in bubbles[-1], bubbles
    assert "rollback save failed" in _log_text(tmp_path), "第二次失败没有留痕"


def test_set_chat_rounds_写失败_内存不变且不报成功(pet, cfg_back, tmp_path, monkeypatch):
    """对话记忆写失败：内存里的轮数不变、盘上不动、不出现成功话术、日志留痕。

    变异：把 `new = dict(cfg)` 改回原地改 → 第三条断言红。
    """
    pet.cfg["chat_memory_rounds"] = 4
    assert main.save_config(pet.cfg) is None
    disk_before = _disk_bytes()

    bubbles = []
    monkeypatch.setattr(pet, "show_bubble", lambda t: bubbles.append(t))
    monkeypatch.setattr(pet.ai, "_save_cfg", lambda _cfg: "磁盘只读（注入）")
    _install_fake_input(monkeypatch, intval=9)
    pet.ai.set_chat_rounds()

    assert bubbles and "磁盘只读（注入）" in bubbles[-1], bubbles
    assert "记住最近" not in bubbles[-1] and "不带记忆" not in bubbles[-1], bubbles
    assert pet.cfg["chat_memory_rounds"] == 4, "写失败却改了内存里的轮数"
    assert _disk_bytes() == disk_before, "写失败却动了盘"
    assert "set_chat_rounds save failed" in _log_text(tmp_path), "写失败没有留痕"

# ================= talk()：自动开开关（同族第 4 处） =================

def _prep_talk(pet, monkeypatch, msg="你好呀"):
    """把"和它说话"摆成确定性的样子：有 Key（不弹 Key 框）、取走 ask、装一个**真 QAction** 当

    AI 菜单项（菜单是**首次打开时才建**的，刚造出来的 PetWindow 上 `_ai_act` 还是 None；
    产品代码只对它用 setChecked / isChecked / blockSignals，真 QAction 是忠实的替身）。
    顺便把 toggled 接一个记录器：程序化同步勾选**不许**再触发一次 set_ai_enabled（那会多写一次
    盘，没 Key 时还会再弹一次输入框）。
    """
    from PySide6.QtGui import QAction
    pet.cfg["ai_enabled"] = False
    pet.cfg["api_key"] = "sk-测试"
    assert main.save_config(pet.cfg) is None
    act = QAction(pet)
    act.setCheckable(True)
    monkeypatch.setattr(pet, "_ai_act", act, raising=False)
    emitted = []
    act.toggled.connect(lambda on: emitted.append(on))
    sent = []
    monkeypatch.setattr(pet.chat, "ask", lambda m: sent.append(m))
    _install_fake_input(monkeypatch, text=msg)
    return act, sent, emitted


def test_talk_自动开开关_写失败_内存不变且如实告知但对话照常(pet, cfg_back, tmp_path, monkeypatch):
    """talk() 的自动开开关：**先写盘、成功才提交**；失败时内存不变、盘不变、有如实反馈，
    而且**对话照常发起**（用户目的是说话，不该被一次落盘失败掐掉）；勾选回读 cfg。

    改前：先改内存、丢弃 _save_cfg 的返回值 —— 内存 True、菜单已勾选、盘上没这个键、
    零气泡零日志，重启又变回关。
    变异：把 `new = dict(cfg)` 改回 `new = cfg`（= 原地改）→ 第一条断言红。
    """
    act, sent, emitted = _prep_talk(pet, monkeypatch)
    disk_before = _disk_bytes()
    bubbles = []
    monkeypatch.setattr(pet, "show_bubble", lambda t: bubbles.append(t))
    monkeypatch.setattr(pet.ai, "_save_cfg", lambda _cfg: "磁盘只读（注入）")

    pet.ai.talk()

    assert pet.cfg["ai_enabled"] is False, "写失败却把开关提交进内存了"
    assert _disk_bytes() == disk_before, "写失败却动了盘"
    assert bubbles and "磁盘只读（注入）" in bubbles[-1], bubbles
    assert "记住啦" not in bubbles[-1], "失败路径复用了成功话术：%r" % (bubbles[-1],)
    assert "照常" in bubbles[-1], "没告诉用户这次对话照常：%r" % (bubbles[-1],)
    assert sent == ["你好呀"], "落盘失败把对话也掐掉了：%r" % (sent,)
    assert act.isChecked() is False, "勾选与 cfg 不一致（界面必须 = cfg）"
    assert "talk auto-enable save failed" in _log_text(tmp_path), "写失败没有留痕"
    assert emitted == [], \
        "程序化同步勾选 emit 了 toggled（会再走一次 set_ai_enabled：多写一次盘，没 Key 时还会再弹一次输入框）"


def test_talk_自动开开关_成功路径落盘且勾选跟上(pet, cfg_back, monkeypatch):
    """反向控制组：写盘成功 → 内存/磁盘都是 True、勾选跟上、没有失败话术、对话照常。"""
    act, sent, emitted = _prep_talk(pet, monkeypatch)
    log_before = _log_text()          # 日志文件是模块共享的：只判"这次有没有新增失败行"

    pet.ai.talk()

    assert sent == ["你好呀"], sent
    assert pet.cfg["ai_enabled"] is True, "成功路径没提交进内存"
    assert _disk_json().get("ai_enabled") is True, "成功路径没落盘"
    assert act.isChecked() is True, "成功后菜单勾选没跟上 cfg"
    assert emitted == [], \
        "程序化同步勾选 emit 了 toggled（会再走一次 set_ai_enabled：多写一次盘，没 Key 时还会再弹一次输入框）"
    assert "talk auto-enable save failed" not in _log_text()[len(log_before):], \
        "成功路径写了失败日志：%r" % (_log_text()[len(log_before):],)
