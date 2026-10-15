# -*- coding: utf-8 -*-
"""v2.7.0 反馈批次（代理 B）：**非对话框那一半**的"有反馈"回归。

领地：`桌宠.py` · `pet_balance.py` · `pet_resources.py`（**不碰 pet_dialogs.py** —— 对话框侧
由代理 A 覆盖，两边共用的接口在这里钉住）。

覆盖：
  B1 主窗三个回调的 **(ok, msg)** 契约 —— apply_ai_settings / apply_bubble_style / apply_physics
     （含"值未变"这条以前绝对静默的路径、异常路径、非 dict 路径，以及对话框侧通道
     pet_dialogs._call 的**透传**——A 靠它决定"关不关窗"）
  B2 五处"入口打不开静默"里属于本代理的四处：行为 / 待机 / 闹钟（桌宠.py）· 账本（pet_balance.py）
  B3 声音素材库索引里白名单外的条目被丢弃时必须留痕（限流，不刷屏）

约定（照抄 tests/test_dialogs_more_v24.py，不另起炉灶）：
  · offscreen + 真 PetWindow + 临时数据目录；**不 exec() 模态**（offscreen 下 modal() 的
    exec() 会挂死测试进程），统一把 pet_dialogs.modal / _warn 换成记录器；
  · 断言只写**结构性事实**（返回值 / 磁盘内容 / 日志行 / 记到的调用），不 sleep、不看时序
    （铁律 3：不依赖机器速度）；
  · 每条修复都配"注释掉就红"的变异点，写在用例 docstring 的「变异」一行里。

    python -B -m pytest tests/test_feedback_host_v270.py -o addopts="" -q
"""
import json
import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import 桌宠 as main  # noqa: E402
import pet_ai  # noqa: E402
import pet_config  # noqa: E402
import pet_dialogs  # noqa: E402
import pet_io  # noqa: E402
import pet_log  # noqa: E402
import pet_resources  # noqa: E402

from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402


# ---------------- 起步：必须是真 QApplication ----------------

def _boot_application():
    """进程里必须有**真正的 QApplication**（不是 QCoreApplication）。

    实测坑（见 tests/test_dialogs_more_v24.py 的长注释）：某个模块的 fixture 先建了
    QCoreApplication 的话，QApplication.instance() 会把那个（truthy 的）对象还回来，
    随后 new PetWindow() 造 QWidget 时 Qt **直接 abort 整进程**（无 traceback）。
    所以导入期就把它建出来（导入期一定早于任何用例执行）。
    """
    app = QApplication.instance()
    if app is None:
        return QApplication([])
    return app


_APP = _boot_application()


def _ensure_qapplication():
    app = QApplication.instance()
    if isinstance(app, QApplication):
        return app
    pytest.fail("进程里只有 QCoreApplication（不是 QApplication），QWidget 无法构造，"
                "Qt 会直接 abort。请单独跑本文件，或与 tests/test_dialogs_more_v24.py 同序。",
                pytrace=False)


# ---------------- 隔离：真 PetWindow + 临时数据目录 ----------------

@pytest.fixture(scope="module")
def pet(tmp_path_factory):
    """真 PetWindow + 全部运行时路径指向临时目录（退出时还原进程级全局）。"""
    tmp = tmp_path_factory.mktemp("fbhost270")
    _snap = (main.DATA_DIR, main.CONFIG_PATH, main.USAGE_PATH, main.MEMORY_PATH,
             getattr(pet_log, "_data_dir", None))
    main.DATA_DIR = str(tmp)
    main.CONFIG_PATH = str(tmp / "config.json")
    main.USAGE_PATH = str(tmp / "usage.json")
    main.MEMORY_PATH = str(tmp / "memory.json")
    pet_log.set_data_dir(str(tmp))
    _ensure_qapplication()
    win = main.PetWindow()
    # v2.7.0 第 5 轮（代理 B）：**停掉会自行弹气泡的周期定时器**（心情/待机/闹钟/余额…）。
    # 不停的话，"这次动作弹了几条气泡"会被环境里恰好到点的定时器污染（口径同
    # tests/test_ui_wire_cache_v241.py 的 quiet_pet_timers）——那是"用例不自隔离"，不是产品行为。
    from helpers_roles import quiet_pet_timers
    quiet_pet_timers(win)
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
    """用例级还原：真 PetWindow 是模块级共享的，配置 / 气泡样式必须在用例后复原。"""
    import copy
    cfg = copy.deepcopy(pet.cfg)
    style = dict(main.BUBBLE_STYLE)
    yield
    pet.cfg.clear()
    pet.cfg.update(cfg)
    main.save_config(pet.cfg)
    main.BUBBLE_STYLE.clear()
    main.BUBBLE_STYLE.update(style)
    pet.bubble.update()


@pytest.fixture
def ui(monkeypatch):
    """模态提示 → 记录器（offscreen 下 modal() 的 exec() 会挂死测试进程）。

    与 tests/test_dialogs_more_v24.py:142-159 同一套路：断言"提示了中文原因"，
    而不是"真弹了框"。
    """
    seen = {"warn": [], "info": []}
    monkeypatch.setattr(pet_dialogs, "_warn",
                        lambda _p, title, text: seen["warn"].append((title, text)))
    monkeypatch.setattr(pet_dialogs, "_info",
                        lambda _p, title, text: seen["info"].append((title, text)))
    return seen


@pytest.fixture
def fake_modal(monkeypatch):
    """pet_dialogs.modal → 记录器：记下"哪个对话框被打开"，随即 reject（不进 exec）。"""
    opened = []

    def _fake(dlg):
        opened.append(type(dlg).__name__)
        dlg.show()
        dlg.reject()
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(pet_dialogs, "modal", _fake)
    # 安全网：入口哪天走回裸 .exec()，offscreen 下模态 exec 会**挂死整条 pytest**（不是红，
    # 是永远卡住）。这里把 QDialog.exec 也换成立即 reject——于是"没走 modal()"会干净地红，
    # 而不是把 CI 挂住（变异验证时必须保证这一点）。
    monkeypatch.setattr(QDialog, "exec", lambda _self: QDialog.DialogCode.Rejected)
    return opened


def _log_text(tmp_path=None):
    """把两处日志出口都读出来，断言才不会看错地方（实测：确实分两处）。

      · 桌宠.DATA_DIR/error.log —— 桌宠._log_error 与 pet_balance 的 _log 都**显式**传
        data_dir=DATA_DIR（pet_log 自己的 data_dir 管不着它们）；
      · pet_log 的 data_dir/error.log —— conftest 的 _isolate_log_dir 指向本用例 tmp_path，
        pet_dialogs._dialog_failed 这类不带 data_dir 的调用落这里。
    """
    paths = [os.path.join(str(main.DATA_DIR), "error.log")]
    if tmp_path is not None:
        paths.append(str(tmp_path / "error.log"))
    out = []
    for p in paths:
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as fh:
                out.append(fh.read())
    return "\n".join(out)


# ================= B1：主窗回调的 (ok, msg) 契约 =================

def test_apply_physics_no_change_is_not_silent(pet, cfg_back, monkeypatch):
    """物理参数"值没变"必须返回 (True, "没有改动")，而不是像改前那样静默 return。

    变异：把 apply_physics 里 `return True, "物理参数没有改动"` 还原成裸 `return`
    → 本用例解包即红（cannot unpack non-sequence NoneType）。
    """
    bubbles = []
    monkeypatch.setattr(pet, "show_bubble", lambda t: bubbles.append(t))
    pet.cfg["physics"] = pet_config.normalize_physics(pet.cfg.get("physics"))
    main.save_config(pet.cfg)
    before = dict(pet.cfg["physics"])

    ok, msg = pet.apply_physics(dict(before))          # 一个字都没改
    assert ok is True, "没改值被当成了失败：%r" % (msg,)
    assert "改动" in msg or "没变" in msg, "值未变没有给出可读结论：%r" % (msg,)
    assert main.load_config()["physics"] == before, "没改值却动了盘"

    # 控制组：真改了值 → 仍然 (True, ...) 且落盘（既有行为不许被这次改动弄坏）
    changed = dict(before)
    changed["gravity"] = float(before.get("gravity") or 1.0) * 0.5 + 0.05
    want = pet_config.normalize_physics(changed)
    assert want["gravity"] != before.get("gravity"), "用例前提不成立（归一化后没变化）"
    ok2, msg2 = pet.apply_physics(changed)
    assert ok2 is True, (ok2, msg2)
    assert main.load_config()["physics"]["gravity"] == want["gravity"], "改了的物理参数没落盘"
    assert bubbles, "值真的变了却没有气泡（既有可见反馈被改掉了）"


def test_apply_physics_failure_returns_false_and_logs(pet, cfg_back, tmp_path, monkeypatch):
    """落盘/归一化抛异常 → (False, 中文原因) + error.log 有线索，且**不得向外抛**。

    变异：删掉 apply_physics 里的 try/except → 本用例在调用处直接炸红。
    """
    def _boom(_ph):
        raise RuntimeError("physics-boom")

    monkeypatch.setattr(pet_config, "normalize_physics", _boom)
    ok, msg = pet.apply_physics({"gravity": 1.0})
    assert ok is False and "physics-boom" in msg, (ok, msg)
    txt = _log_text(tmp_path)
    assert "apply_physics" in txt and "physics-boom" in txt, \
        "失败既没上报也没留痕：%r" % (txt,)


def test_apply_ai_settings_roundtrip_and_failure(pet, cfg_back, tmp_path, monkeypatch):
    """AI 设置：成功 → (True, msg) 且落盘；回调抛异常 → (False, 原因) 且**盘上不变**。

    变异：① 把 apply_ai_settings 还原成裸 `self.ai.apply_settings(data)`（无返回值）→
    成功路径解包红；② 删掉 try/except → 异常路径直接炸红。
    """
    ok, msg = pet.apply_ai_settings({"ai_model": "deepseek-chat", "ai_reply_len": 21})
    assert ok is True and isinstance(msg, str) and msg.strip(), (ok, msg)
    assert main.load_config()["ai_reply_len"] == 21, "成功的 AI 设置没有落盘"

    def _boom(_data):
        raise RuntimeError("ai-save-boom")

    monkeypatch.setattr(pet.ai, "apply_settings", _boom)
    ok2, msg2 = pet.apply_ai_settings({"ai_reply_len": 33})
    assert ok2 is False and "ai-save-boom" in msg2, (ok2, msg2)
    assert main.load_config()["ai_reply_len"] == 21, "失败路径却改了盘（正是 P1-1 的假象）"
    assert "apply_ai_settings" in _log_text(tmp_path), "失败没有留痕"


def test_apply_bubble_style_roundtrip_and_failure(pet, cfg_back, tmp_path, monkeypatch):
    """气泡样式：成功 → (True, msg) 且 BUBBLE_STYLE / 磁盘都更新；落盘抛异常 → (False, 原因)。

    变异：① 删掉 return（回到无返回值的 apply_bubble_style）→ 解包红；
    ② 删掉 try/except → 异常路径炸红；③ 把 BUBBLE_STYLE.update(st) 挪到 save_config
    之前 → 失败路径会留下半截样式，最后那条断言红。
    """
    style = {"bg": "#112233", "fg": "#445566", "border": "#778899",
             "font_size": 13, "radius": 18}
    ok, msg = pet.apply_bubble_style(dict(style))
    assert ok is True and msg.strip(), (ok, msg)
    assert main.BUBBLE_STYLE["bg"] == "#112233" and main.BUBBLE_STYLE["font_size"] == 13, \
        "成功却没生效：%r" % (dict(main.BUBBLE_STYLE),)
    disk = main.load_config()["bubble_style"]
    assert disk["bg"] == "#112233" and disk["font_size"] == 13, "样式没落盘"

    def _boom(_cfg):
        raise RuntimeError("style-disk-boom")

    monkeypatch.setattr(main, "save_config", _boom)
    ok2, msg2 = pet.apply_bubble_style({"bg": "#000000"})
    assert ok2 is False and "style-disk-boom" in msg2, (ok2, msg2)
    assert main.BUBBLE_STYLE["bg"] == "#112233", "失败留下了半截样式（内存已改、盘上没改）"
    assert "apply_bubble_style" in _log_text(tmp_path), "失败没有留痕"


@pytest.mark.parametrize("name", ["apply_ai_settings", "apply_bubble_style", "apply_physics"])
@pytest.mark.parametrize("bad", [None, [], "x", 3])
def test_apply_callbacks_reject_non_dict_with_false(pet, cfg_back, name, bad):
    """非 dict 入参：三个回调都必须给 (False, 中文原因)，不能像改前那样静默 return。

    变异：把任一处 `if not isinstance(...): return False, "..."` 还原成裸 `return` → 红。
    """
    res = getattr(pet, name)(bad)
    assert isinstance(res, tuple) and len(res) == 2, \
        "%s(%r) 的返回值不是 (ok, msg)：%r" % (name, bad, res)
    ok, msg = res
    assert ok is False and isinstance(msg, str) and msg.strip(), (name, bad, res)


def test_dialog_channel_passes_tuple_through(pet, cfg_back):
    """契约的**消费端**：对话框只能经 pet_dialogs._call 拿到结论，必须原样透传 (ok, msg)。

    变异：把任一 apply_* 的返回改成裸 True/False（不是二元组）→ 本用例红。
    这条同时是 A 的接口约定（_dev/task_v270_round.md 代理 A · A3/A6）的可执行版本。
    """
    for name, arg in (("apply_ai_settings", {"ai_reply_len": 20}),
                      ("apply_bubble_style", {"bg": "#ffffff"}),
                      ("apply_physics", {})):
        res = pet_dialogs._call(pet, name, arg)
        assert isinstance(res, tuple) and len(res) == 2, (name, res)
        ok, msg = res
        assert ok is True and isinstance(msg, str), (name, res)


def test_future_schema_readonly_mode_is_not_reported_as_success(pet, cfg_back, monkeypatch):
    """兼容模式（配置来自更高版本）下 save_config **一个字节都没写** → 不许对外报"成功"。

    变异：把 桌宠.save_config 里那条 `return "当前配置来自更高版本…"` 改回裸 `return`
    → 本用例红（AI 设置会显示"已更新"，实际没落盘）。
    """
    monkeypatch.setattr(main, "_FUTURE_CFG", True)
    monkeypatch.setattr(main, "_FUTURE_CFG_LOGGED", True)   # 免得刷日志
    res = main.save_config(pet.cfg)
    assert res and "兼容模式" in str(res), "只读兼容模式下 save_config 仍报成功：%r" % (res,)
    ok, msg = pet.apply_ai_settings({"ai_reply_len": 27})
    assert ok is False and "兼容模式" in msg, (ok, msg)


# ===== S17：空 Key 输入 + AI 开关/记忆轮数的写盘失败（都不许"假装修好"） =====

class _FakeInputDialog(object):
    """替代 pet_ai.QInputDialog：不进 exec()（offscreen 下会挂死进程），直接给结论。"""

    InputMode = None    # 构造后由 _install 填真枚举

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

    def setInputMode(self, *_a):
        pass

    def setIntRange(self, *_a):
        pass

    def setIntValue(self, v):
        self._int = v

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
    """把 pet_ai.QInputDialog 换成一个**既可直接调用、又带 InputMode 枚举**的工厂。

    为什么要是工厂而不是 lambda：pet_ai 里既写 `QInputDialog(pet)@@BT@@，也写
    @@BT@@QInputDialog.InputMode.IntInput@@BT@@ —— 换成裸函数会让后者 AttributeError。
    """
    from PySide6.QtWidgets import QInputDialog as _Real

    class _F(_FakeInputDialog):
        pass

    class _Factory(object):
        InputMode = _Real.InputMode

        def __call__(self, *_a, **_k):
            return _F(**kw)

    monkeypatch.setattr(pet_ai, "QInputDialog", _Factory())
    return _F


def test_set_api_key_empty_input_is_not_silent(pet, cfg_back, monkeypatch):
    """S17：空 Key 点确定 → **必须有一句反馈**（改前完全静默），且**不动已有 Key**、不说"记住了"。

    变异：删掉 `if not key:` 那个分支 → 本用例红（bubbles 为空 = 改前状态）。
    """
    import json as _json
    pet.cfg["api_key"] = "sk-原有值"
    main.save_config(pet.cfg)
    before = _json.loads(open(main.CONFIG_PATH, encoding="utf-8").read()).get("api_key")
    assert before, "用例前提不成立：已有 Key 没有落盘"

    bubbles = []
    monkeypatch.setattr(pet, "show_bubble", lambda t: bubbles.append(t))
    _install_fake_input(monkeypatch, text="   ")      # 全是空格 = 空输入
    pet.ai.set_api_key()

    assert len(bubbles) == 1, "空 Key 点确定的反馈条数应为 1（改前是 0）：%r" % (bubbles,)
    assert "记住啦" not in bubbles[0], "空输入却回了「记住啦」"
    assert ("没有输入" in bubbles[0]) or ("什么都没改" in bubbles[0]), bubbles
    after = _json.loads(open(main.CONFIG_PATH, encoding="utf-8").read()).get("api_key")
    assert after == before, "空输入把已有 Key 改了（数据风险）"
    assert pet.cfg["api_key"] == "sk-原有值", "空输入改了内存里的 Key"


def test_set_api_key_write_failure_does_not_claim_success(pet, cfg_back, monkeypatch):
    """Key 写盘失败 → **不许回「记住啦！」**（那是"保存成功"假象）。

    变异：删掉 `if err:` 分支 → 本用例红。
    """
    bubbles = []
    monkeypatch.setattr(pet, "show_bubble", lambda t: bubbles.append(t))
    monkeypatch.setattr(pet.ai, "_save_cfg", lambda _cfg: "磁盘只读（注入）")
    _install_fake_input(monkeypatch, text="sk-new-key")
    pet.ai.set_api_key()
    assert bubbles, "写失败却没有任何提示"
    assert "记住啦" not in bubbles[-1], "写失败仍回「记住啦！」：%r" % (bubbles[-1],)
    assert "磁盘只读（注入）" in bubbles[-1], bubbles


def test_ai_toggle_and_chat_rounds_report_write_failure(pet, cfg_back, monkeypatch):
    """AI 开关 / 对话记忆轮数写盘失败 → 同样不许回"已生效"。

    变异：删掉 `set_ai_enabled` 或 `set_chat_rounds` 里任一 `if err:` 分支 → 对应断言红。
    """
    bubbles = []
    monkeypatch.setattr(pet, "show_bubble", lambda t: bubbles.append(t))
    monkeypatch.setattr(pet.ai, "_save_cfg", lambda _cfg: "磁盘只读（注入）")

    pet.ai.set_ai_enabled(False)
    assert bubbles and "磁盘只读（注入）" in bubbles[-1], \
        "AI 开关写失败却没有任何提示：%r" % (bubbles,)

    bubbles[:] = []
    _install_fake_input(monkeypatch, intval=5)
    pet.ai.set_chat_rounds()
    assert bubbles and "磁盘只读（注入）" in bubbles[-1], \
        "对话记忆写失败却没有任何提示：%r" % (bubbles,)
    assert "记住最近" not in bubbles[-1] and "不带记忆" not in bubbles[-1], bubbles


# ===== B1 闭环②：**不抛异常的真实写失败**（atomic_write_json 返回错误串）必须一路可见 =====

def test_write_failure_chain_reaches_dialog_and_keeps_it_open(pet, ui, cfg_back, tmp_path, monkeypatch):
    """真实写失败（**不抛异常**，只返回错误串）→ 服务层/主窗/对话框三层都看得见。

    这条补的是"假装修好"的最后一环：改前 `pet_config.write_config` 无论成败都
    `return None`，磁盘满/只读/被占用时用户仍旧只看到窗口关闭。
    链路：pet_io.atomic_write_json →(err) pet_config.write_config →(err) 桌宠.save_config
          →(err) AIService.apply_settings →(False,msg) → 桌宠.apply_ai_settings →(False,msg)
          → 对话框 _save_failed（不关窗 + 状态行/警告框）

    变异：把 `pet_config.write_config` 的 `return err` 改回 `return None`
    （或把 桌宠.save_config 的 return 去掉）→ 本用例红（三层全变"成功"）。
    """
    monkeypatch.setattr(pet_io, "atomic_write_json", lambda *a, **k: "磁盘只读（注入）")

    ok, msg = pet.ai.apply_settings({"ai_reply_len": 26})
    assert ok is False and "磁盘只读（注入）" in msg, (ok, msg)
    ok2, msg2 = pet.apply_ai_settings({"ai_reply_len": 26})
    assert ok2 is False and "磁盘只读（注入）" in msg2, (ok2, msg2)

    dlg = pet_dialogs.AISettingsDialog(pet)
    dlg.show()
    try:
        dlg._save()
        assert dlg.result() != QDialog.DialogCode.Accepted, \
            "真实写失败时窗口仍然关掉了 = 用户看到的就是「保存成功」假象"
        visible = [t for _ti, t in ui["warn"]] + [dlg._save_hint.text()]
        assert any("磁盘只读（注入）" in t for t in visible), \
            "写失败的原因没有对用户可见：%r" % (visible,)
    finally:
        dlg.hide()
    assert "save_config failed" in _log_text(tmp_path) and "磁盘只读（注入）" in _log_text(tmp_path), \
        "写失败没有留痕：%r" % (_log_text(tmp_path),)


def test_write_failure_reaches_physics_and_bubble_style(pet, cfg_back, monkeypatch):
    """同一类写失败在 物理参数 / 气泡样式 两个回调上也要变成 (False, 原因)，且不留半截状态。

    变异：删掉任一 `if err:` 分支 → 对应断言红（会回到"关窗 + 成功"）。
    """
    monkeypatch.setattr(pet_io, "atomic_write_json", lambda *a, **k: "磁盘只读（注入）")
    before_style = dict(main.BUBBLE_STYLE)

    ok, msg = pet.apply_physics({"gravity": 0.77})
    assert ok is False and "磁盘只读（注入）" in msg, (ok, msg)

    ok2, msg2 = pet.apply_bubble_style({"bg": "#0a0b0c", "font_size": 15})
    assert ok2 is False and "磁盘只读（注入）" in msg2, (ok2, msg2)
    assert dict(main.BUBBLE_STYLE) == before_style, \
        "写失败却已经把新样式应用到内存（失败留半截）：%r" % (dict(main.BUBBLE_STYLE),)


# ===== B1 闭环：pet_ai.AIService.apply_settings 也返回 (ok, msg) 且不再自己弹气泡 =====

def test_ai_service_apply_settings_returns_tuple_and_does_not_bubble(pet, cfg_back, monkeypatch):
    """`AIService.apply_settings` 成功 → (True, msg)，落盘，且**自己弹气泡 = 0 次**。

    改前：返回 None（成功也 None）**且自己弹气泡** —— 调用方看不出成败，同一次保存还会
    和对话框的回执凑成两条气泡（"一次用户动作一句反馈"）。

    变异：① 成功路径改回裸 `return` → 解包红；② 把 `self.pet.show_bubble(...)`
    加回方法里 → 本用例最后那条 bubbles 断言红。
    """
    bubbles = []
    monkeypatch.setattr(pet, "show_bubble", lambda t: bubbles.append(t))
    res = pet.ai.apply_settings({"ai_reply_len": 22, "ai_model": "deepseek-chat"})
    assert isinstance(res, tuple) and len(res) == 2, "返回值不是 (ok, msg)：%r" % (res,)
    ok, msg = res
    assert ok is True and msg.strip(), res
    assert main.load_config()["ai_reply_len"] == 22, "服务层成功却没落盘"
    assert bubbles == [], "服务层自己弹了气泡（应由对话框按 msg 弹一次）：%r" % (bubbles,)


def test_ai_service_apply_settings_disk_failure_returns_false(pet, cfg_back, tmp_path, monkeypatch):
    """真落盘失败（`_save_cfg` 抛异常）→ (False, 可读原因) + error.log，且**不弹气泡**。

    变异：① 删掉 apply_settings 的 try/except（或把 except 收窄）→ 本用例在调用处炸红；
    ② 恢复"失败也弹气泡"的写法 → bubbles 断言红。
    """
    bubbles = []
    monkeypatch.setattr(pet, "show_bubble", lambda t: bubbles.append(t))

    def _boom(_cfg):
        raise RuntimeError("ai-disk-boom")

    monkeypatch.setattr(pet.ai, "_save_cfg", _boom)
    ok, msg = pet.ai.apply_settings({"ai_reply_len": 33})
    assert ok is False and "ai-disk-boom" in msg, (ok, msg)
    assert bubbles == [], "失败路径弹了气泡（一次动作一句反馈，失败由对话框给）：%r" % (bubbles,)
    assert "ai apply_settings" in _log_text(tmp_path) and "ai-disk-boom" in _log_text(tmp_path), \
        "服务层失败没有留痕：%r" % (_log_text(tmp_path),)


def test_ai_service_apply_settings_save_error_string_is_failure(pet, cfg_back, tmp_path, monkeypatch):
    """落盘回调**不抛异常、返回错误串**（pet_io / pet_config 的口径）同样算失败。

    变异：删掉 `if err is False or (isinstance(err, str) ...)` 那段 → 本用例红（会被当成成功）。
    """
    monkeypatch.setattr(pet, "_save_cfg", None, raising=False)   # 占位，避免误用
    monkeypatch.setattr(pet.ai, "_save_cfg", lambda _cfg: "磁盘只读")
    ok, msg = pet.ai.apply_settings({"ai_reply_len": 44})
    assert ok is False and "磁盘只读" in msg, (ok, msg)
    assert "磁盘只读" in _log_text(tmp_path), "错误串没有留痕"


def test_ai_service_apply_settings_non_dict(pet, cfg_back):
    """非 dict 入参 → (False, 中文原因)，不能像改前那样静默 return。"""
    res = pet.ai.apply_settings(None)
    assert isinstance(res, tuple) and len(res) == 2 and res[0] is False, res
    assert isinstance(res[1], str) and res[1].strip(), res


def test_host_passes_ai_service_result_through(pet, cfg_back, monkeypatch):
    """主窗必须**原样透传**服务层结论：失败不丢原因、成功不换文案。

    变异：把 apply_ai_settings 改回"忽略内部返回值、无条件 return True" → 前半段红。
    """
    monkeypatch.setattr(pet.ai, "apply_settings",
                        lambda data: (False, "AI 设置没能保存：磁盘只读"))
    ok, msg = pet.apply_ai_settings({"ai_reply_len": 25})
    assert ok is False and "磁盘只读" in msg, "主窗把服务层的失败吞掉了：%r" % ((ok, msg),)

    monkeypatch.setattr(pet.ai, "apply_settings", lambda data: (True, "AI 设置已更新~"))
    ok2, msg2 = pet.apply_ai_settings({"ai_reply_len": 25})
    assert ok2 is True and msg2 == "AI 设置已更新~", "主窗换掉了服务层的文案：%r" % ((ok2, msg2),)


# ===== B1 契约的"消费端"集成用例（跨领地：真对话框 + 真 PetWindow，只换回调） =====

def test_dialog_keeps_window_open_when_host_reports_failure(pet, ui, monkeypatch):
    """**失败时调用方真能不关窗** —— 返回 (ok, msg) 却没人用，等于没改。

    真实路径：真 `AISettingsDialog` + 真 PetWindow，只把回调换成"返回失败"。
    断言用户可见结果（窗口没关 + 原因看得见），不是"日志里有一行"。

    变异（**不在 A 的文件里写一个字节**，用运行时替换 Driver 复刻老行为）：
    `_save` 换回"丢弃返回值 + 无条件 accept()" → 本用例红（窗口关掉了）。
    """
    dlg = pet_dialogs.AISettingsDialog(pet)
    monkeypatch.setattr(pet, "apply_ai_settings",
                        lambda data: (False, "AI 设置没能保存：磁盘只读"))
    dlg.show()
    try:
        dlg._save()
        assert dlg.result() != QDialog.DialogCode.Accepted, \
            "回调报了失败，窗口却关掉了 —— 用户看到的就是「保存成功」假象"
        visible = [t for _ti, t in ui["warn"]] + [dlg._save_hint.text()]
        assert any("磁盘只读" in t for t in visible), \
            "失败原因没有对用户可见（状态行/警告框都没有）：%r" % (visible,)
    finally:
        dlg.hide()

    # 控制组：回调成功 → 关窗 + 成功气泡（不该因为这次改动就变成"永远不关窗"）
    bubbles = []
    monkeypatch.setattr(pet, "apply_ai_settings", lambda data: (True, "AI 设置已更新~"))
    monkeypatch.setattr(pet, "show_bubble", lambda t: bubbles.append(t))
    dlg2 = pet_dialogs.AISettingsDialog(pet)
    dlg2.show()
    try:
        dlg2._save()
        assert dlg2.result() == QDialog.DialogCode.Accepted, "成功路径反而不关窗了"
    finally:
        dlg2.hide()
    assert bubbles and "AI 设置" in bubbles[-1], "成功路径没有回执：%r" % (bubbles,)


def test_physics_dialog_shows_no_change_message(pet, ui, monkeypatch):
    """物理参数"值没变"这条以前是**绝对静默**（主窗裸 return + 对话框无条件 accept）。

    现在主窗返回 (True, "没有改动")，对话框据此给回执 —— 端到端断言"用户看得到一句话"。

    变异（运行时替换，不动 A 的文件）：把 `PhysicsDialog._save` 换回"无条件 accept()"
    （= 值未变时零回执）→ 本用例红。
    """
    bubbles = []
    monkeypatch.setattr(pet, "show_bubble", lambda t: bubbles.append(t))
    monkeypatch.setattr(pet, "apply_physics", lambda data: (True, "物理参数没有改动"))
    dlg = pet_dialogs.PhysicsDialog(pet)
    dlg.show()
    try:
        dlg._save()
        assert dlg.result() == QDialog.DialogCode.Accepted, "值没变时窗口应当照常关闭"
    finally:
        dlg.hide()
    assert bubbles and "没有改动" in bubbles[-1], \
        "值没变仍然没有任何回执（= 改前的「点保存什么都不知道」）：%r" % (bubbles,)


# ================= B2：入口打不开不许静默 =================

def test_host_entries_open_through_modal(pet, fake_modal):
    """行为 / 待机 / 闹钟三个菜单入口必须走 pet_dialogs.modal（置顶 + raise + 抢焦点）。

    改前是裸 XDialog(...).exec()：缺 WindowStaysOnTopHint / raise_ / activateWindow /
    setFocus，受 Windows 前台锁影响（pet_dialogs.modal 的 docstring 明说这是必要步骤）。

    变异：把任一入口还原成裸 .exec() → fake_modal 收不到该对话框 → 红。
    """
    pet._open_behavior_dialog()
    pet._open_idle_dialog()
    pet._open_alarm_dialog()
    assert fake_modal == ["BehaviorDialog", "IdleDialog", "AlarmDialog"], \
        "入口没有走 modal()：%r" % (fake_modal,)


@pytest.mark.parametrize("klass,method,label", [
    ("BehaviorDialog", "_open_behavior_dialog", "行为设置"),
    ("IdleDialog", "_open_idle_dialog", "待机设置"),
    ("AlarmDialog", "_open_alarm_dialog", "闹钟"),
])
def test_host_entry_failure_is_visible(pet, ui, tmp_path, monkeypatch, klass, method, label):
    """入口打不开：日志 + 一句中文（改前只有 error.log → 用户"点了没反应"），且不得向外抛。

    变异：把入口里的 `pet_dialogs._dialog_failed(self, "<名>", e)` 还原成
    `_log_error("...: %r" % (e,))` → ui["warn"] 为空 → 红。
    """
    def _boom(*_a, **_k):
        raise RuntimeError("no-open-boom")

    monkeypatch.setattr(pet_dialogs, klass, _boom)
    ui["warn"].clear()
    getattr(pet, method)()          # 不得抛出
    assert ui["warn"], "入口打不开却没有任何用户可见提示"
    title, text = ui["warn"][-1]
    assert label in title or label in text, (title, text)
    assert "打不开" in text and "no-open-boom" in text, (title, text)
    assert "no-open-boom" in _log_text(tmp_path), "入口失败没有留痕"


def test_balance_open_ledger_failure_shows_bubble(pet, tmp_path, monkeypatch):
    """账本入口打不开：日志 + 宠物气泡（口径同 _dialog_failed，但不 import 那个私有助手）。

    变异：删掉 show_bubble 那一句（回到只 self._log）→ bubbles 为空 → 红。
    """
    def _boom(*_a, **_k):
        raise RuntimeError("ledger-boom")

    monkeypatch.setattr(pet_dialogs, "LedgerDialog", _boom)
    bubbles = []
    monkeypatch.setattr(pet, "show_bubble", lambda t: bubbles.append(t))
    pet.balance.open_ledger()       # 不得抛出
    assert bubbles, "账本打不开却没有任何用户可见提示"
    assert "账本" in bubbles[-1] and "ledger-boom" in bubbles[-1], bubbles
    assert "ledger dialog failed" in _log_text(tmp_path), "入口失败没有留痕"


def test_balance_open_ledger_ok_path_unchanged(pet, monkeypatch):
    """控制组：账本正常打开时**不许**弹气泡（只在失败时提示，避免每次开面板都刷一句）。"""
    opened = []

    def _fake_modal(dlg):
        opened.append(type(dlg).__name__)
        dlg.show()
        dlg.reject()
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(pet_dialogs, "modal", _fake_modal)
    bubbles = []
    monkeypatch.setattr(pet, "show_bubble", lambda t: bubbles.append(t))
    pet.balance.open_ledger()
    assert opened == ["LedgerDialog"], opened
    assert bubbles == [], "正常打开也弹了提示：%r" % (bubbles,)


# ================= B3：声音素材库里白名单外的条目 =================

def test_voice_asset_dropped_ext_is_logged_once(tmp_path):
    """索引里白名单外的条目（.m4a）被丢弃时必须留痕，且库状态可解释、不误伤 wav、不动文件。

    变异：把 pet_resources._load 里的 log_throttled 调用删回纯 continue
    → 日志里没有任何线索 → 本用例红（= 改前状态）。
    """
    data = tmp_path / "data"
    (data / "voice_ref").mkdir(parents=True)
    (data / "voice_ref" / "a1.m4a").write_bytes(b"\x00" * 32)
    (data / "voice_assets.json").write_text(json.dumps({"assets": [
        {"id": "a1", "name": "手机录音", "file": "a1.m4a", "ext": ".m4a", "added": "2026-01-01"},
        {"id": "a2", "name": "正常参考音", "file": "a2.wav", "ext": ".wav", "added": "2026-01-01"},
    ]}, ensure_ascii=False), encoding="utf-8")

    pet_log._THROTTLE_SEEN.clear()     # 限流表是进程级的：用例内先清，断言才算得准
    lib = pet_resources.VoiceAssetLibrary(str(data))
    assert [a["id"] for a in lib.assets()] == ["a2"], \
        "白名单外条目没被丢弃 / 误伤了 wav：%r" % (lib.assets(),)
    assert (data / "voice_ref" / "a1.m4a").is_file(), \
        "丢弃索引项不该删用户文件（那是数据丢失，不是反馈问题）"

    log = data / "error.log"
    txt = log.read_text(encoding="utf-8") if log.is_file() else ""
    assert "1 条" in txt and ".m4a" in txt and "白名单" in txt, \
        "丢弃没有可解释的日志：%r" % (txt,)
    assert "手机录音" in txt, "日志没有点名是哪一条（用户无法判断少了什么）"

    # 限流：同一数据目录 60s 窗口内再建一次库，不许再刷一条（口径 = pet_log.log_throttled）
    pet_resources.VoiceAssetLibrary(str(data))
    again = log.read_text(encoding="utf-8")
    assert again.count("不在白名单") == 1, \
        "同一条丢弃被重复记录（限流没生效）：%r" % (again,)
