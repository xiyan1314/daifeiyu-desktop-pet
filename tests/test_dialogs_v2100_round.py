# -*- coding: utf-8 -*-
"""v2.12.0（P6）对话框侧验收：E1 试听在途状态行 · E2 无服务要有交代 · E3 键盘路径 ·
F1「动作」页签 · C-15 进行态文案 · C-25 失败写回发起窗口。

本文件只覆盖 **pet_dialogs.py** 这一块的改动（E2 的"加强式改写那条既有用例"按任务书
落在 tests/test_dialogs_more_v24.py:1412-1419，本文件只补它没覆盖的那一半）。

写法沿用 tests/test_dialogs_more_v24.py 的隔离套路（不另起炉灶）：
  · offscreen + 真 PetWindow + 临时数据目录；
  · **不 exec() 模态**：_warn/_info/_confirm 一律换成记录器（offscreen 下 exec() 会挂死）；
  · 落盘以"重新读文件"为准，不看内存 dict。
"""
import json
import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import 桌宠 as main  # noqa: E402
import pet_dialogs  # noqa: E402

from PySide6.QtCore import QCoreApplication, QEvent, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QAbstractItemView, QAbstractScrollArea, QApplication, QDialog, QLabel, QLineEdit,
    QPushButton, QWidget)

from helpers_dialog_fit_v250 import dialog_factories  # noqa: E402


def _boot_application():
    """导入期就建好 QApplication（理由与 test_dialogs_more_v24.py 一字不差）。"""
    app = QApplication.instance()
    if app is None:
        return QApplication([])
    return app


_APP = _boot_application()


def _ensure_qapplication():
    app = QApplication.instance()
    if isinstance(app, QApplication):
        return app
    pytest.fail("进程里只有 QCoreApplication（不是 QApplication），QWidget 无法构造。",
                pytrace=False)


def _shutdown_pet(win):
    """拆真 PetWindow：先停全部 QTimer，再 hide/close/deleteLater（同既有套路）。"""
    try:
        win._closing = True
    except Exception:
        pass
    try:
        win.voice.stop()
    except Exception:
        pass
    for _t in win.findChildren(QTimer):
        try:
            _t.stop()
        except Exception:
            pass
    try:
        win.hide()
        win.close()
        win.deleteLater()
    except Exception:
        pass


@pytest.fixture(scope="module")
def pet(tmp_path_factory):
    import pet_log
    tmp = tmp_path_factory.mktemp("dlg_v2100")
    _snap = (main.DATA_DIR, main.CONFIG_PATH, main.USAGE_PATH, main.MEMORY_PATH,
             getattr(pet_log, "_data_dir", None))
    main.DATA_DIR = str(tmp)
    main.CONFIG_PATH = str(tmp / "config.json")
    main.USAGE_PATH = str(tmp / "usage.json")
    main.MEMORY_PATH = str(tmp / "memory.json")
    pet_log.set_data_dir(str(tmp))
    _ensure_qapplication()
    win = main.PetWindow()
    from helpers_roles import install_three_form_role
    install_three_form_role(win, tmp)
    yield win
    _shutdown_pet(win)
    QApplication.processEvents()
    (main.DATA_DIR, main.CONFIG_PATH, main.USAGE_PATH, main.MEMORY_PATH) = _snap[:4]
    pet_log.set_data_dir(_snap[4])


@pytest.fixture
def ui(monkeypatch):
    """模态三件套 → 记录器（offscreen 下 exec() 会挂死测试进程）。"""
    seen = {"warn": [], "info": [], "confirm": True}

    def _rec(bucket):
        def _f(_parent, title, text):
            bucket.append((title, text))
        return _f

    monkeypatch.setattr(pet_dialogs, "_warn", _rec(seen["warn"]))
    monkeypatch.setattr(pet_dialogs, "_info", _rec(seen["info"]))
    monkeypatch.setattr(pet_dialogs, "_confirm", lambda _p, _t, _x: seen["confirm"])
    return seen


def _send(widget, key, mods=Qt.KeyboardModifier.NoModifier):
    """把一次按键真发给控件（走 Qt 的分发路径，不是直接调槽）。"""
    QApplication.sendEvent(widget, QKeyEvent(QEvent.Type.KeyPress, key, mods))
    QApplication.processEvents()


def _focus_chain(dlg):
    """对话框的 Tab 链（从 dlg 自己出发，绕一圈回到自己为止）。"""
    out = []
    w = dlg
    for _ in range(500):
        w = w.nextInFocusChain()
        if w is None or w is dlg:
            break
        out.append(w)
    return out


def _row_buttons(dlg):
    """底排按钮行（stick_buttons 记下的 _btn_row）里的按钮，按行内从左到右。"""
    row = getattr(dlg, "_btn_row", None)
    out = []
    if row is None:
        return out
    for i in range(row.count()):
        w = row.itemAt(i).widget()
        if isinstance(w, QPushButton):
            out.append(w)
    return out


def _tab_focusable(w):
    """这个控件会不会进 Tab 链（用例侧口径，与断言要守的东西一致）。"""
    return bool(w.isEnabled() and (w.focusPolicy() & Qt.FocusPolicy.TabFocus))


def _drain_deferred():
    """处理 DeferredDelete（deleteLater 的真正回收点）。"""
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QApplication.processEvents()


def _fit_dialogs():
    """(名字, 造窗口的可调用) —— pet_dialogs 里**全部** _FitDialog 子类，顺序照 v2.5.0 那份清单。

    清单**不在这里另抄一份**：直接取 tests/helpers_dialog_fit_v250.py 的 dialog_factories()
    （那份 docstring 自己写着"新对话框必须同时登记三处，漏一个不会红"——再抄一份只会更漏），
    这里只把非 _FitDialog 的条目（3 个面板 / 内联框 / "ResourceManagerDialog(tab2)"）滤掉。
    以后新加的 _FitDialog 子类只要登记进那份清单，就自动进本文件这两条全量用例。
    """
    out = []
    for name, make in dialog_factories():
        cls = getattr(pet_dialogs, name, None)
        if isinstance(cls, type) and issubclass(cls, pet_dialogs._FitDialog):
            out.append((name, make))
    return tuple(out)


_FIT_DIALOGS = _fit_dialogs()
_FIT_DIALOG_IDS = [n for n, _ in _FIT_DIALOGS]


def _stub_modal_paths(monkeypatch):
    """把"会开第二个窗口/会等人按键"的两条路换成记录器（offscreen 下 exec() 会**挂死**
    整条 pytest，不是红）。返回文件对话框的调用记录。

    - QFileDialog：主按钮里有"导入角色…"/"安装…"/"导出 CSV…"这类真开文件框的；
    - modal()：角色导入向导那一步是 modal(RoleImportDialog) = exec()。
    换掉它们，用例才能在"空格误点主按钮"时**红得出来**（而不是把 pytest 挂住），
    顺带把"有没有点开文件框"变成一条断言。
    """
    calls = []

    class _FD(object):
        @staticmethod
        def getOpenFileName(*_a, **_k):
            calls.append("getOpenFileName")
            return ("", "")

        @staticmethod
        def getOpenFileNames(*_a, **_k):
            calls.append("getOpenFileNames")
            return ([], "")

        @staticmethod
        def getSaveFileName(*_a, **_k):
            calls.append("getSaveFileName")
            return ("", "")

        @staticmethod
        def getExistingDirectory(*_a, **_k):
            calls.append("getExistingDirectory")
            return ""

    monkeypatch.setattr(pet_dialogs, "QFileDialog", _FD)
    monkeypatch.setattr(pet_dialogs, "modal", lambda _dlg: QDialog.DialogCode.Rejected)
    # 安全网：万一哪条路退回裸 exec()，offscreen 下模态 exec 会挂死整条 pytest
    monkeypatch.setattr(QDialog, "exec", lambda _self: QDialog.DialogCode.Rejected)
    return calls


# ============================================================
# E1：公共「试听：在途 → 结果」状态行，三处复用
# ============================================================

def test_E1_三处状态行是同一个实现(pet, ui):
    """三处复用**同一份**实现（不是各写一遍）：朗读页 / 角色绑定页 / 事件音效页。"""
    dlg = pet_dialogs.VoiceDialog(pet)
    try:
        assert isinstance(dlg._play_line, pet_dialogs._StatusLine)
        assert isinstance(dlg._preview_line, pet_dialogs._StatusLine)
        assert isinstance(dlg._row_status("feed"), pet_dialogs._StatusLine)
        # 三处绑的是三个**不同**的已有控件：各写一句，只有对应的那个标签变
        for lb in (dlg._play_label, dlg._preview_hint, dlg._row_labels["feed"]):
            lb.setText("")
        dlg._play_line.set("A")
        dlg._preview_line.set("B")
        dlg._row_status("feed").set("C")
        assert (dlg._play_label.text(), dlg._preview_hint.text(),
                dlg._row_labels["feed"].text()) == ("A", "B", "C"), \
            "三处状态行没有各写各的控件：%r" % (
                (dlg._play_label.text(), dlg._preview_hint.text(),
                 dlg._row_labels["feed"].text()),)
    finally:
        dlg.hide()


def test_E1_绑定页试听有在途且结论写回这一页_不覆盖bind_hint(pet, ui, monkeypatch):
    """角色绑定页试听：在途 → 结果都写**本页**状态行；健康提示 _bind_hint 一个字不改。

    能真失败：把 _preview_line.pending() 去掉（回到 B 的"点了界面毫无变化"）→ 第一条红；
    把结论写回 _play_label（改回旧行为）→ 第二条红；用 _bind_hint 当状态行 → 第三条红。
    """
    import pet_voice
    pet.cfg["voice"] = pet_voice.normalize_voice(None)
    main.save_config(pet.cfg)
    dlg = pet_dialogs.VoiceDialog(pet)
    dlg.show()
    try:
        hint_before = dlg._bind_hint.text()
        dlg._preview_hint.setText("")
        monkeypatch.setattr(pet.voice, "preview_asset", lambda vs, **k: (True, ""))
        dlg._preview("some_asset")
        assert "试听中" in dlg._preview_hint.text(), dlg._preview_hint.text()
        assert dlg._voice_waiting is True, "没有进入等结果状态，后面的结论写不进来"
        assert dlg._pending_line is dlg._preview_line, "结论没有归属到发起它的这一页"

        # 合成失败（异步事件）→ 写进绑定页，而不是朗读页
        dlg._play_label.setText("（朗读页原来的内容）")
        pet_dialogs._route_voice_event(pet.voice, "error", "参考音不见了（素材被删？）")
        QApplication.processEvents()
        assert "❌" in dlg._preview_hint.text() and "参考音不见了" in dlg._preview_hint.text(), \
            dlg._preview_hint.text()
        assert dlg._play_label.text() == "（朗读页原来的内容）", \
            "结论写错了地方（写进了用户没在看的那一页）：%r" % dlg._play_label.text()
        assert dlg._voice_waiting is False

        # 健康提示（空库/故障态）不许被试听状态冲掉
        assert dlg._bind_hint.text() == hint_before, \
            "_bind_hint 的健康提示被试听结果覆盖了：%r" % dlg._bind_hint.text()
    finally:
        dlg.hide()


def test_E1_绑定页试听成功后结论落在本页(pet, ui, monkeypatch):
    """成功路径同样写本页（finished 事件）；且之后归位，下一次朗读仍写朗读页。"""
    import pet_voice
    pet.cfg["voice"] = pet_voice.normalize_voice(None)
    main.save_config(pet.cfg)
    dlg = pet_dialogs.VoiceDialog(pet)
    dlg.show()
    try:
        monkeypatch.setattr(pet.voice, "preview_asset", lambda vs, **k: (True, ""))
        dlg._preview("some_asset")
        pet_dialogs._route_voice_event(pet.voice, "started", "")
        QApplication.processEvents()
        assert "正在播放" in dlg._preview_hint.text(), dlg._preview_hint.text()
        pet_dialogs._route_voice_event(pet.voice, "finished", "")
        QApplication.processEvents()
        assert dlg._preview_hint.text().startswith("✅"), dlg._preview_hint.text()
        assert dlg._pending_line is dlg._play_line, "落定后没有归位"
    finally:
        dlg.hide()


def test_E1_绑定页无服务与失败都要有交代(pet, ui, monkeypatch):
    """服务不可用 / 服务拒绝入队：绑定页都要给一句人话（不许静默 return）。"""
    dlg = pet_dialogs.VoiceDialog(pet)
    dlg.show()
    try:
        monkeypatch.setattr(dlg, "_svc", None)
        dlg._preview_hint.setText("")
        dlg._preview("some_asset")
        assert "不可用" in dlg._preview_hint.text(), dlg._preview_hint.text()

        monkeypatch.setattr(dlg, "_svc", pet.voice)
        monkeypatch.setattr(pet.voice, "preview_asset",
                            lambda vs, **k: (False, "声音素材不存在（先在资源管理导入）"))
        ui["warn"].clear()
        dlg._preview_hint.setText("")
        dlg._preview("ghost")
        assert "❌" in dlg._preview_hint.text() and "素材不存在" in dlg._preview_hint.text(), \
            dlg._preview_hint.text()
        assert ui["warn"] and ui["warn"][-1][0] == "试听失败", ui["warn"]
        assert dlg._voice_waiting is False
    finally:
        dlg.hide()


def test_E1_事件音效页试听走在途再走结果(pet, ui, monkeypatch, tmp_path):
    """事件音效页试听：状态位先'试听中'、成功给结果、失败回到原义（不把状态位弄脏）。"""
    import wave

    def _wav(path, seconds=0.1):
        rate = 8000
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(b"\x00\x00" * max(1, int(rate * seconds)))
        return str(path)

    src = _wav(tmp_path / "clip_v2100.wav")
    key = "poke"
    assert pet.voice.set_clip(key, src)[0] is True
    dlg = pet_dialogs.VoiceDialog(pet)
    dlg.show()
    try:
        seen_mid = []
        monkeypatch.setattr(pet, "preview_audio",
                            lambda p: seen_mid.append(dlg._row_labels[key].text()) or True,
                            raising=False)
        dlg._test(key)
        assert seen_mid == ["⏳ 试听中…"], \
            "试听期间状态位没有进入在途（用户分不清'没点上'和'正在合成'）：%r" % (seen_mid,)
        assert "已配" in dlg._row_labels[key].text(), dlg._row_labels[key].text()

        ui["warn"].clear()
        monkeypatch.setattr(pet, "preview_audio", lambda p: False, raising=False)
        dlg._test(key)
        assert dlg._row_labels[key].text() == "✓ 已配", \
            "试听失败后状态位没回到原义：%r" % dlg._row_labels[key].text()
        assert ui["warn"] and "损坏" in ui["warn"][-1][1], ui["warn"]

        ui["warn"].clear()
        pet.voice.set_clip(key, None)
        dlg._test(key)
        assert dlg._row_labels[key].text() == "✓ 已配", "没片段那次不许改状态位"
        assert ui["warn"] and "还没配片段" in ui["warn"][-1][1], ui["warn"]
    finally:
        dlg.hide()
        pet.voice.set_clip(key, None)


# ============================================================
# C-15：用户可见文案必须是**进行态**且自洽
# ============================================================

def test_C15_朗读与整段都是进行态且不自相矛盾(pet, ui, monkeypatch):
    """'已开始朗读：正在合成…'是完成态+进行态拼在一起 —— 改成'已排上队：正在合成…'。

    能真失败：把这句改回'✅ 已开始朗读：正在合成…' → 最后两条断言红。
    """
    dlg = pet_dialogs.VoiceDialog(pet)
    dlg.show()
    try:
        dlg._line_combo.clear()
        dlg._line_combo.addItem("假台词", "ghost_line")
        dlg._dlg_combo.clear()
        dlg._dlg_combo.addItem("假对白", "ghost_dlg")
        monkeypatch.setattr(pet.voice, "speak_line", lambda lid, **k: (True, ""))
        monkeypatch.setattr(pet.voice, "speak_dialogue", lambda did, **k: (True, ""))
        dlg._speak_line()
        text = dlg._play_label.text()
        assert text.startswith("✅") and "正在合成" in text, text
        assert "已排上队" in text, "入队成功的说法不是进行态：%r" % text
        assert "已开始朗读" not in text, "完成态措辞回来了（'已开始朗读'与'正在合成'打架）：%r" % text
        dlg._speak_dialogue()
        text2 = dlg._play_label.text()
        assert "已排上队" in text2 and "正在合成" in text2, text2
        assert "已开始按顺序朗读" not in text2, text2
    finally:
        dlg.hide()


# ============================================================
# E2 的同族补充：没选条目 / 无服务都不许静默
# （"加强式改写那条既有用例"按任务书在 tests/test_dialogs_more_v24.py）
# ============================================================

def test_E2_regen_no_selection_also_speaks(pet, ui):
    """没选台词点「重新生成」也不许静默（同函数第二处静默 return）。"""
    dlg = pet_dialogs.VoiceDialog(pet)
    dlg.show()
    try:
        dlg._line_combo.clear()
        dlg._play_label.setText("（原位）")
        dlg._regen_line()
        assert dlg._play_label.text() != "（原位）", "点了没反应（静默 return）"
        assert "还没有选中台词" in dlg._play_label.text(), dlg._play_label.text()
    finally:
        dlg.hide()


# ============================================================
# E3：对话框侧的键盘路径（Tab / Enter·Space / Esc）
# ============================================================

@pytest.mark.parametrize("name", ("VoiceDialog", "ResourceManagerDialog", "LinesDialog",
                                  "IdleDialog", "AmountNoteDialog"))
def test_E3_底排按钮行落在Tab链最后_主按钮在行内第一(pet, ui, name):
    """Tab 顺序（E3）：这条**不用排，只要钉住** —— 实测 Qt 按创建顺序串出来的链本来就把
    底排按钮行放在最后，行内按左→右。

    为什么"不用排"也值得一条用例：这条不变量是**构造顺序**换来的（内容先建、按钮行最后
    stick_buttons 挂上去）。谁哪天在按钮行之后又往对话框上挂控件，链尾就不是按钮了 ——
    Tab 要穿过一堆控件才够得到保存/取消。本用例就是那次改动的红灯。
    （本轮试过在基类里再排一次链：实测零行为收益，反而在 showEvent 里走
    nextInFocusChain() 让整进程崩在 0xC0000374，代码已撤掉——见本轮回报。）

    能真失败：把某个对话框的 stick_buttons(...) 挪到内容之前，或在其后再挂一个可聚焦
    控件 → 该对话框的 pos 不再等于链尾那一段，本用例红。
    """
    dlg = {"VoiceDialog": lambda: pet_dialogs.VoiceDialog(pet),
           "ResourceManagerDialog": lambda: pet_dialogs.ResourceManagerDialog(pet),
           "LinesDialog": lambda: pet_dialogs.LinesDialog(pet),
           "IdleDialog": lambda: pet_dialogs.IdleDialog(pet),
           "AmountNoteDialog": lambda: pet_dialogs.AmountNoteDialog(pet)}[name]()
    dlg.show()
    QApplication.processEvents()
    try:
        row = [b for b in _row_buttons(dlg) if _tab_focusable(b)]
        if not row:
            pytest.skip("%s 没有底排按钮行" % name)
        chain = _focus_chain(dlg)
        assert len(chain) == len(set(chain)), "Tab 链有环/重复项：%r" % (chain,)
        pos = [chain.index(b) for b in row if b in chain]
        assert len(pos) == len(row), "%s：有底排按钮根本没进 Tab 链" % name
        assert pos == list(range(len(chain) - len(row), len(chain))), \
            "%s：底排按钮行没有排在 Tab 链最后（位置 %r / 链长 %d）" % (name, pos, len(chain))
        # 主按钮在按钮行里排第一（Tab 先到它）
        primary = dlg.primary_button()
        if primary in row:
            assert row[0] is primary, "%s：主按钮没排在按钮行第一位" % name
    finally:
        dlg.close()


@pytest.mark.parametrize("name,make", _FIT_DIALOGS, ids=_FIT_DIALOG_IDS)
def test_E3_底排按钮行落在Tab链最后_全量(pet, ui, name, make):
    """把上面那条不变量**扩到全部** _FitDialog 子类（质量审 Y-2）——15 个，一个不漏。

    上面那条只钉了 5 个窗口，而 pet_dialogs.py 里那段注释与发布说明写的是**无条件**的
    「谁往按钮行后面再加控件就会红」—— 措辞比覆盖面宽，正是本仓最恨的那一类。这条把它
    变成真的：15 个窗口逐个构造、逐个数链。

    口径与上面那条**只差一处**：这里量的是**整条底排**（含当前被禁用的按钮），上面那条量的是
    "底排里可 Tab 的那些"。为什么非得改这一处：插件的底排有 8 个按钮，其中 5 个
    （安装/更新/回滚/卸载/启用禁用）在没选中行时是禁用的、被那层过滤器滤掉，于是
    "可 Tab 的按钮位置" = [61, 66, 67] 而"链尾那一段" = [65, 66, 67] —— 会**冤枉**它；
    而整条底排实测就是 60..67 连续收在链尾。旧口径扩不到全量，不是因为它更严，
    而是因为它量的对象不对（把"底排里有禁用按钮"误读成"有人在按钮行后面加了控件"）。

    能真失败：在任意一个窗口里，往 stick_buttons(...) 之后再挂一个可聚焦控件（或把
    stick_buttons 挪到内容之前）→ 那个窗口的位置数组不再等于链尾那一段，本用例红。
    """
    dlg = make(pet)
    dlg.show()
    QApplication.processEvents()
    try:
        all_btns = list(_row_buttons(dlg))
        assert all_btns, "%s：没有底排按钮行" % name
        chain = _focus_chain(dlg)
        assert len(chain) == len(set(chain)), "%s：Tab 链有环/重复项：%r" % (name, chain)
        pos = [chain.index(b) for b in all_btns if b in chain]
        assert len(pos) == len(all_btns), "%s：有底排按钮根本没进 Tab 链" % name
        assert pos == list(range(len(chain) - len(all_btns), len(chain))), \
            "%s：整条底排没有排在 Tab 链最后（位置 %r / 链长 %d）" % (name, pos, len(chain))
    finally:
        dlg.close()


def test_E3_回车与空格都触发主按钮(pet, ui):
    """Enter / Space 都落到**同一个**主按钮上，且各只点一次。"""
    dlg = pet_dialogs.VoiceDialog(pet)
    dlg.show()
    QApplication.processEvents()
    try:
        primary = dlg.primary_button()
        assert primary is not None and primary.text() == "保存", \
            "主按钮不是「保存」：%r" % (primary and primary.text(),)
        hits = []
        primary.clicked.connect(lambda: hits.append(1))
        dlg.setFocus()
        QApplication.processEvents()
        _send(dlg, Qt.Key.Key_Return)
        assert hits == [1], "回车没有（或不止一次）触发主按钮：%r" % (hits,)
        _send(dlg, Qt.Key.Key_Space)
        assert hits == [1, 1], "空格没有（或不止一次）触发主按钮：%r" % (hits,)
    finally:
        dlg.close()


def test_E3_输入框里的空格不许被主按钮抢走(pet, ui):
    """焦点在 QLineEdit 上时，空格是**字符**，不是主按钮的快捷键。

    能真失败：把 _space_is_free 去掉（无条件抢空格）→ 本用例红。
    """
    dlg = pet_dialogs.VoiceDialog(pet)
    dlg.show()
    QApplication.processEvents()
    try:
        primary = dlg.primary_button()
        hits = []
        primary.clicked.connect(lambda: hits.append(1))
        ed = QLineEdit()
        dlg._content_body.layout().addWidget(ed)
        ed.setFocus()
        QApplication.processEvents()
        assert dlg.focusWidget() is ed
        _send(ed, Qt.Key.Key_Space)
        assert hits == [], "输入框里的空格被主按钮抢走了（会打不出空格）"
    finally:
        dlg.close()


def test_E3_没有主按钮的窗口回车空格不做事(pet, ui, monkeypatch):
    """取不到主按钮时（控件都不可用）：Enter/Space 不许偷偷关窗。"""
    dlg = pet_dialogs.VoiceDialog(pet)
    dlg.show()
    QApplication.processEvents()
    try:
        monkeypatch.setattr(dlg, "primary_button", lambda: None)
        dlg.setFocus()
        _send(dlg, Qt.Key.Key_Return)
        _send(dlg, Qt.Key.Key_Space)
        assert dlg.isVisible(), "没有主按钮却把窗口关掉了"
    finally:
        dlg.close()


def test_E3_Esc关窗(pet, ui):
    """Esc → reject（关窗）。各对话框自己的 reject（未保存先问一次）照旧生效。"""
    for mk in (lambda: pet_dialogs.VoiceDialog(pet),
               lambda: pet_dialogs.ResourceManagerDialog(pet),
               lambda: pet_dialogs.PhysicsDialog(pet)):
        dlg = mk()
        dlg.show()
        QApplication.processEvents()
        try:
            dlg.setFocus()
            _send(dlg, Qt.Key.Key_Escape)
            assert dlg.isVisible() is False, "%s：Esc 没有关窗" % type(dlg).__name__
            assert int(dlg.result()) == 0, "%s：Esc 走的是 accept" % type(dlg).__name__
        finally:
            dlg.close()


# ============================================================
# Z-1（质量审 必1）：**开窗默认焦点就在滚动区**上 —— 空格不许把窗口确定掉
# ============================================================

@pytest.mark.parametrize("name,make", _FIT_DIALOGS, ids=_FIT_DIALOG_IDS)
def test_Z1_开窗后直接按空格不许点主按钮(pet, ui, monkeypatch, name, make):
    """**不改焦点**，开窗直接按空格 → 窗口不许关、主按钮不许被点。

    这一格是本轮 E3 漏掉的：内容区套了 scroll_content() 之后，Qt 把**开窗默认焦点**给了
    那个 QScrollArea（实测 15 个 _FitDialog 子类，开窗后 focusWidget() 全是 QScrollArea），
    而滚动区当时不在 _SPACE_OWNERS 里 —— "开窗 → 空格"于是整条落到主按钮上。
    后果最重的是「记一笔」：它的「确定」带 setDefault(True)，一点就是 accept()，
    调用方（pet_balance.add_manual_record）接着读 result()==Accepted **直接落库一笔默认
    ¥1.00**（端到端那一条见下面 test_Z1_空格不会替用户记一笔）。

    能真失败：把 _SPACE_OWNERS 换回修复前那条（不含 QAbstractScrollArea）→ 15 个全红；
    把"焦点确实是滚动区"那条反面断言去掉，用例就会变成空转（哪天焦点不在滚动区了也照绿）。
    """
    fd_calls = _stub_modal_paths(monkeypatch)
    dlg = make(pet)
    dlg.show()
    QApplication.processEvents()
    try:
        fw = dlg.focusWidget()
        assert isinstance(fw, QAbstractScrollArea), (
            "%s：这条用例守的是「开窗默认焦点就在滚动区」这一格，现在焦点是 %r —— "
            "要么 Qt 的初始焦点规则变了，要么这个窗口自己改过焦点，先重读 Z-1 再改这里。"
            % (name, type(fw).__name__ if fw is not None else None))
        primary = dlg.primary_button()
        assert primary is not None, "%s：取不到主按钮，这条用例会空转" % name
        hits = []
        primary.clicked.connect(lambda: hits.append(1))
        _send(fw, Qt.Key.Key_Space)          # 发到**焦点控件**上，走 Qt 的真分发路径
        assert hits == [], \
            "%s：焦点在滚动区上，空格还是把主按钮「%s」点了（Z-1 回归）" % (name, primary.text())
        assert fd_calls == [], "%s：空格点开了文件对话框：%r" % (name, fd_calls)
        assert dlg.isVisible(), "%s：按一下空格窗口就关掉了" % name
        assert int(dlg.result()) == 0, \
            "%s：按一下空格窗口就被确定掉了（result=%d）" % (name, int(dlg.result()))
    finally:
        dlg.close()


class _LedgerSpy(object):
    """账本替身：把"到底有没有真记账"变成可数的结构事实。"""

    def __init__(self):
        self.calls = []

    def add_manual(self, amount, note):
        self.calls.append((amount, note))


def test_Z1_空格不会替用户记一笔(pet, ui, monkeypatch):
    """Z-1 的那笔"凭空的钱"：**端到端**跑 pet_balance.add_manual_record 那条链。

    口径：真 AmountNoteDialog + 真 BalanceService，只把 modal() 换成"show 一次"
    （offscreen 下 exec() 会挂死测试进程；换掉的正是"等人按键"那一步，按键本身照发）。
    空格落在**开窗默认焦点**（滚动区）上时：
      · 主按钮「确定」一次都没被点 → result() 不是 Accepted；
      · 账本 add_manual 一次都没发生 —— 默认金额 1.00 就是那笔凭空的钱。

    能真失败：把 _SPACE_OWNERS 换回修复前那条 → 第一条断言之前 result() 就已经是
    Accepted，账本里会多一笔 (1.0, "")。
    """
    import pet_balance
    book = _LedgerSpy()
    seen = {}

    def _fake_modal(dlg):
        seen["dlg"] = dlg
        dlg.show()
        QApplication.processEvents()
        fw = dlg.focusWidget()
        seen["focus"] = fw
        pb = dlg.primary_button()
        assert pb is not None and pb.text() == "确定", \
            "「记一笔」的主按钮变了：%r" % (pb and pb.text(),)
        hits = []
        pb.clicked.connect(lambda: hits.append(1))
        _send(fw if fw is not None else dlg, Qt.Key.Key_Space)   # ← 用户打开窗口后直接按空格
        seen["hits"] = hits

    monkeypatch.setattr(pet_dialogs, "modal", _fake_modal)
    monkeypatch.setattr(QDialog, "exec", lambda _self: QDialog.DialogCode.Rejected)  # 挂死安全网
    svc = pet_balance.BalanceService(pet, None, lambda: pet.cfg, lambda: book,
                                     lambda _kind: None, lambda _cfg: None,
                                     lambda _msg: None, lambda: None)
    svc.add_manual_record(None, "")
    dlg = seen["dlg"]
    try:
        assert isinstance(seen["focus"], QAbstractScrollArea), \
            "开窗默认焦点不在滚动区（%r）—— 这条用例要守的就是那一格" % (
                type(seen["focus"]).__name__ if seen["focus"] is not None else None,)
        assert seen["hits"] == [], "空格把「确定」点了"
        assert int(dlg.result()) != 1, "空格把窗口确定掉了"
        assert book.calls == [], \
            "空格替用户记了一笔：%r（默认金额 1.00）" % (book.calls,)
    finally:
        dlg.close()


# ============================================================
# F1：资源管理第 4 页签「动作」（纯视图）
# ============================================================

def _install_action_role(pet, tmp_path, rid="act_role_v2100"):
    """装一个带**自定义帧动作 + 合成动作**的角色（走库自己的归一化，不塞半成品）。

    幂等：先用同一个 id 装过一次的话先删掉 —— pet fixture 是模块级的，直接 append 会造出
    **两条同 id 的角色**，角色库 update() 只替换第一条，第二条会让"删了还在"变成假象。
    """
    import shutil
    pet.role_lib._data["roles"] = [r for r in pet.role_lib._data["roles"] if r["id"] != rid]
    roles_dir = pet.role_lib._dir
    for n in ("act_a.png", "act_b.png"):
        shutil.copy(os.path.join(roles_dir, "inv_a.png"), os.path.join(roles_dir, n))
    forms = [{"name": "常态", "file": "act_a.png",
              "animations": {"idle": ["act_a.png"], "wave": ["act_a.png", "act_b.png"]},
              "procs": {"breathe": {"kind": "breathe", "amp": 0.05, "period_ms": 1200}}}]
    raw = {"id": rid, "name": "动作角色", "file": "act_a.png", "form": "single",
           "file_full": "", "frames": ["act_a.png"], "added": "", "forms": forms}
    norm = pet.role_lib._normalize_role(raw) or raw
    pet.role_lib._data["roles"].append(norm)
    pet.role_lib._save()
    return rid


def _read_roles_json():
    with open(os.path.join(main.DATA_DIR, "roles.json"), encoding="utf-8") as f:
        return json.load(f)


def _find_action_item(panel, rid, name):
    for i in range(panel._tree.topLevelItemCount()):
        top = panel._tree.topLevelItem(i)
        for j in range(top.childCount()):
            form_node = top.child(j)
            for k in range(form_node.childCount()):
                leaf = form_node.child(k)
                data = leaf.data(0, Qt.ItemDataRole.UserRole)
                if isinstance(data, tuple) and data[0] == rid and data[2] == name:
                    return leaf
    return None


def test_F1_第四页签存在且登记在ResourceManagerDialog里(pet, ui):
    dlg = pet_dialogs.ResourceManagerDialog(pet)
    try:
        titles = [dlg._tabs.tabText(i) for i in range(dlg._tabs.count())]
        assert titles == ["角色", "音效", "声音素材", "动作"], titles
        assert dlg._tabs.widget(3) is dlg._action_panel
        # initial_tab=3 直接落在动作页（以前 min(2, …) 会把 3 夹回声音素材）
        dlg2 = pet_dialogs.ResourceManagerDialog(pet, 3)
        try:
            assert dlg2._tabs.currentIndex() == 3
        finally:
            dlg2.close()
    finally:
        dlg.close()


def test_F1_清单是只读的且列出角色形态动作(pet, ui, tmp_path):
    """列 = 角色 → 形态 → 动作（帧 N 张 / 合成 类型·幅度·周期）；树本身不许就地编辑。"""
    rid = _install_action_role(pet, tmp_path)
    dlg = pet_dialogs.ResourceManagerDialog(pet, 3)
    dlg.show()
    QApplication.processEvents()
    panel = dlg._action_panel
    try:
        assert panel._tree.editTriggers() == QAbstractItemView.EditTrigger.NoEditTriggers, \
            "纯视图却允许就地编辑"
        wave = _find_action_item(panel, rid, "wave")
        assert wave is not None, "自定义帧动作没出现在清单里"
        assert wave.text(1) == "帧" and wave.text(2) == "帧 2 张", (wave.text(1), wave.text(2))
        breathe = _find_action_item(panel, rid, "breathe")
        assert breathe is not None, "合成动作没出现在清单里"
        assert breathe.text(1) == "合成", breathe.text(1)
        assert "breathe" in breathe.text(2) and "0.05" in breathe.text(2) \
            and "1200" in breathe.text(2), breathe.text(2)
        # 内建动作不进清单（口径与 RoleLibrary.custom_actions 一致）
        assert _find_action_item(panel, rid, "idle") is None, "内建动作混进了自定义动作清单"
        # 默认角色那一行必须说明"它为什么没有动作"
        texts = [panel._tree.topLevelItem(i).text(0)
                 for i in range(panel._tree.topLevelItemCount())]
        assert any("默认角色" in t for t in texts), texts
    finally:
        dlg.close()


def test_F1_删除动作立即写回roles_json(pet, ui, tmp_path):
    """删除 = 只解除引用（帧文件不删）+ 立即落盘（纯视图没有暂存区，所以有二次确认）。"""
    rid = _install_action_role(pet, tmp_path)
    dlg = pet_dialogs.ResourceManagerDialog(pet, 3)
    dlg.show()
    QApplication.processEvents()
    panel = dlg._action_panel
    try:
        wave = _find_action_item(panel, rid, "wave")
        panel._tree.setCurrentItem(wave)
        ui["confirm"] = False
        panel._delete_action()
        assert _find_action_item(panel, rid, "wave") is not None, "取消了却把动作删了"

        ui["confirm"] = True
        panel._tree.setCurrentItem(wave)
        panel._delete_action()
        assert _find_action_item(panel, rid, "wave") is None, "删完清单里还在"
        disk = _read_roles_json()
        role = [r for r in disk["roles"] if r["id"] == rid][0]
        anims = (role["forms"][0].get("animations") or {})
        assert "wave" not in anims, "没有落盘：%r" % (anims,)
        assert anims.get("idle"), "只该删被选中的那一条，内建 idle 不能被牵连"
        assert (role["forms"][0].get("procs") or {}).get("breathe"), "不该动合成动作"
        assert os.path.isfile(os.path.join(pet.role_lib._dir, "act_a.png")), \
            "帧文件被删了（口径是「只解除引用」）"
        # 对照：同一形态的合成动作还在（按类型只删对应那条）
        assert _find_action_item(panel, rid, "breathe") is not None
    finally:
        dlg.close()


def test_F1_没选中与角色不存在都给状态行交代(pet, ui, tmp_path):
    """纯视图里的"没选中/找不到"不是错误：写状态行说清楚（不弹框、不静默）。"""
    dlg = pet_dialogs.ResourceManagerDialog(pet, 3)
    dlg.show()
    QApplication.processEvents()
    panel = dlg._action_panel
    try:
        panel._hint.setText("")
        panel._tree.setCurrentItem(None)
        panel._delete_action()
        assert "选中一条动作" in panel._hint.text(), panel._hint.text()
        panel._hint.setText("")
        panel._locate_role()
        assert "选中一条动作" in panel._hint.text(), panel._hint.text()
        # 选到"角色行"（不是动作叶子）同样给交代
        panel._hint.setText("")
        panel._tree.setCurrentItem(panel._tree.topLevelItem(0))
        panel._delete_action()
        assert "选中一条动作" in panel._hint.text(), panel._hint.text()
    finally:
        dlg.close()


def test_F1_定位到所属角色切页签并选中(pet, ui, tmp_path):
    """「定位到所属角色」= 切到「角色」页签 + 选中它（窗口内定位，不新开窗口）。

    找不到角色那一支由**面板**写状态行（质量审 Y-3：此前只断言了容器的返回值，
    把写状态行那两行删掉也全绿 —— 现在断言的是用户真能看见的那句话）。
    """
    rid = _install_action_role(pet, tmp_path)
    dlg = pet_dialogs.ResourceManagerDialog(pet, 3)
    dlg.show()
    QApplication.processEvents()
    panel = dlg._action_panel
    try:
        before = len(QApplication.topLevelWidgets())
        leaf = _find_action_item(panel, rid, "breathe")
        panel._tree.setCurrentItem(leaf)
        panel._locate_role()
        assert dlg._tabs.currentIndex() == 0, "没有切到角色页签"
        cur = dlg._role_panel._list.currentItem()
        assert cur is not None and cur.data(Qt.ItemDataRole.UserRole) == rid, \
            "角色页签没有选中这条动作所属的角色：%r" % (cur and cur.text(),)
        assert len(QApplication.topLevelWidgets()) == before, "定位开了新窗口"
        # 找不到的角色 → **面板那侧**写状态行交代，不静默（容器只负责返回 False）
        panel._tree.setCurrentItem(leaf)
        dlg._role_panel._list.clear()      # 角色被删过 / 清单还没刷新 —— 就是那种时机差
        panel._hint.setText("")
        panel._locate_role()
        assert "找不到角色" in panel._hint.text(), \
            "角色找不到时状态行一声不吭（静默 return）：%r" % panel._hint.text()
        assert dlg._locate_role("ghost_role") is False, \
            "容器侧的定位在角色不存在时应当返回 False"
    finally:
        dlg.close()


def test_F1_新页签的对象数回基线(pet, ui):
    """任务书四-2：任何"新窗口/新控件"都要有**对象数回基线**的断言。

    实测口径：开一个资源管理窗口 → 关掉 → 处理 DeferredDelete → 应用里的控件总数
    必须回到打开之前。前一半（开窗后必须变多）是反向对照：计数没动说明这条判据空转。
    """
    QApplication.processEvents()
    _drain_deferred()
    base = len(QApplication.allWidgets())
    dlg = pet_dialogs.ResourceManagerDialog(pet, 3)
    dlg.show()
    QApplication.processEvents()
    opened = len(QApplication.allWidgets())
    assert opened > base, "开窗后控件数没变，计数判据是空转：%d → %d" % (base, opened)
    dlg.hide()
    dlg.close()
    dlg.deleteLater()
    _drain_deferred()
    after = len(QApplication.allWidgets())
    assert after == base, "资源管理窗口留下了未回收的控件：%d → %d" % (base, after)


def test_F1_角色库不可用不崩且说清楚(pet, ui, monkeypatch):
    """角色库拿不到：清单空、状态行说明，两个按钮点了给交代（不抛）。"""
    dlg = pet_dialogs.ResourceManagerDialog(pet, 3)
    dlg.show()
    QApplication.processEvents()
    panel = dlg._action_panel
    try:
        monkeypatch.setattr(panel, "_lib", None)
        panel._refresh()
        assert panel._tree.topLevelItemCount() == 1, \
            "库里没有角色时应当只剩「默认角色」那一行：%d" % panel._tree.topLevelItemCount()
        panel._hint.setText("")
        panel._tree.setCurrentItem(panel._tree.topLevelItem(0).child(0))
        panel._delete_action()
        assert panel._hint.text(), "选中非动作行却没有任何交代"
    finally:
        dlg.close()


# ============================================================
# C-25：**本轮裁决 = 收窄措辞，不扩路由**（钉住现状，免得发布说明被当成实现）
# ============================================================

def test_C25_从台词设置发起朗读的异步结论不写台词窗口(pet, ui, monkeypatch):
    """C-25 现状（协调者本轮裁决：**不**把路由扩到"发起朗读的那个窗口"，改收窄措辞）。

    这里把"现状"钉成机器判据：从「台词设置 → 对白编排 → 朗读对白」发起时，异步结论
    只进**语音设置**窗（_route_voice_event 只认 dlg._svc is svc 的 VoiceDialog）；
    台词窗口既没有在途提示、也不会被写脏。发布说明里那句"写进你正在看的那个窗口"
    必须按这个口径收窄（建议措辞见本轮回报），而不是照现状放宽。
    """
    dlg = pet_dialogs.LinesDialog(pet)
    dlg.show()
    try:
        assert not hasattr(dlg, "_voice_waiting"), \
            "台词窗口接上了语音事件路由 —— 那说明本轮裁决被改成了「扩路由」"
        monkeypatch.setattr(pet, "speak_dialogue", lambda did: (True, ""), raising=False)
        dlg._editing_dlg = "ghost_dlg"
        dlg._notes.setText("（原位）")
        dlg._speak_dialogue()
        assert dlg._notes.text() == "（原位）", \
            "本轮不扩路由：台词窗口不该有在途提示：%r" % dlg._notes.text()
        pet_dialogs._route_voice_event(pet.voice, "error", "参考音不见了（素材被删？）")
        pet_dialogs._route_voice_event(pet.voice, "finished", "")
        QApplication.processEvents()
        assert dlg._notes.text() == "（原位）", dlg._notes.text()
    finally:
        dlg.close()


# ============================================================
# D4（兄弟串）：对话框侧的旧词「音频片段」退役 → 统一叫「音效片段」
# ============================================================

def test_D4_对话框侧旧词音频片段已退役(pet, ui):
    """D4：词表统一后，对话框侧不许再有「音频片段」（= 音效库；参考音库叫「声音素材」）。

    ⚠ 那条按钮「管理声音素材…（导入/试听/删除）」**本来就是对的**（它去 tab2），不在退役范围。
    能真失败：把任意一处改回「音频片段」→ 第一条红；把标签改回旧词 → 第二条红。
    """
    import io
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = io.open(os.path.join(root, "pet_dialogs.py"), encoding="utf-8").read()
    assert "音频片段" not in src, "旧词「音频片段」还在 pet_dialogs.py 里（该叫「音效片段」）"
    dlg = pet_dialogs.ResourceManagerDialog(pet, 1)
    try:
        texts = [w.text() for w in dlg._tabs.widget(1).findChildren(QLabel)]
        assert any("音效片段" in t for t in texts), \
            "音效页签的说明标签没改成「音效片段」：%r" % (texts[:6],)
        # 对照：参考音那一路的用词不受影响（按钮名本来就是对的）
        assert "声音素材" in dlg._tabs.tabText(2)
    finally:
        dlg.close()
